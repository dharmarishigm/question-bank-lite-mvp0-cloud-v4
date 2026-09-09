"""Authenticated examination platform layered on the existing question bank."""
from __future__ import annotations

import hashlib, json, os, re, secrets, sqlite3, time
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import BackgroundTasks, APIRouter, Cookie, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ValidationError

router = APIRouter(prefix="/api")
SESSION_SECONDS = 12 * 60 * 60
_ADMIN_LOGIN_FAILURES: dict[str, list[float]] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, google_sub TEXT NOT NULL UNIQUE, email TEXT NOT NULL,
 email_verified INTEGER NOT NULL DEFAULT 0, display_name TEXT NOT NULL DEFAULT '', given_name TEXT NOT NULL DEFAULT '',
 family_name TEXT NOT NULL DEFAULT '', profile_picture TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'STUDENT',
 status TEXT NOT NULL DEFAULT 'ACTIVE', created_at REAL NOT NULL, updated_at REAL NOT NULL, last_login_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE TABLE IF NOT EXISTS app_sessions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL,
 csrf_token TEXT NOT NULL, expires_at REAL NOT NULL, created_at REAL NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS oauth_states (state_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS exams (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', exam_type TEXT NOT NULL DEFAULT '',
 subject TEXT NOT NULL DEFAULT '', level TEXT NOT NULL DEFAULT '', instructions TEXT NOT NULL DEFAULT '', duration_minutes INTEGER NOT NULL DEFAULT 30,
 total_marks REAL NOT NULL DEFAULT 0, negative_marking REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'DRAFT',
 registration_start_at REAL, registration_end_at REAL, exam_start_at REAL, exam_end_at REAL, max_attempts INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, FOREIGN KEY(created_by) REFERENCES users(id));
CREATE INDEX IF NOT EXISTS idx_exams_status ON exams(status);
CREATE TABLE IF NOT EXISTS exam_questions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER NOT NULL, question_id INTEGER NOT NULL, display_order INTEGER NOT NULL,
 marks REAL NOT NULL DEFAULT 1, negative_marks REAL NOT NULL DEFAULT 0, section_name TEXT NOT NULL DEFAULT '', required INTEGER NOT NULL DEFAULT 1,
 created_at REAL NOT NULL, UNIQUE(exam_id, question_id), FOREIGN KEY(exam_id) REFERENCES exams(id), FOREIGN KEY(question_id) REFERENCES questions(id));
CREATE INDEX IF NOT EXISTS idx_exam_questions_exam ON exam_questions(exam_id);
CREATE TABLE IF NOT EXISTS exam_blueprints (
 id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER, name TEXT NOT NULL, blueprint_json TEXT NOT NULL,
 created_by INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 FOREIGN KEY(exam_id) REFERENCES exams(id), FOREIGN KEY(created_by) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS exam_generation_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER, blueprint_id INTEGER NOT NULL, requested_questions INTEGER NOT NULL,
 selected_questions INTEGER NOT NULL DEFAULT 0, shortage_count INTEGER NOT NULL DEFAULT 0, fallback_count INTEGER NOT NULL DEFAULT 0,
 selection_seed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL,
 created_by INTEGER NOT NULL, created_at REAL NOT NULL,
 FOREIGN KEY(exam_id) REFERENCES exams(id), FOREIGN KEY(blueprint_id) REFERENCES exam_blueprints(id), FOREIGN KEY(created_by) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS exam_enrollments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER NOT NULL, user_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'ENROLLED',
 registered_at REAL NOT NULL, cancelled_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE(exam_id,user_id),
 FOREIGN KEY(exam_id) REFERENCES exams(id), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE INDEX IF NOT EXISTS idx_enrollments_user ON exam_enrollments(user_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_exam ON exam_enrollments(exam_id);
CREATE TABLE IF NOT EXISTS exam_sessions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER NOT NULL, user_id INTEGER NOT NULL, registration_id INTEGER NOT NULL,
 attempt_number INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'IN_PROGRESS', started_at REAL NOT NULL, submitted_at REAL,
 expires_at REAL NOT NULL, duration_minutes INTEGER NOT NULL, score REAL, max_score REAL, percentage REAL,
 correct_count INTEGER, incorrect_count INTEGER, unanswered_count INTEGER, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 UNIQUE(exam_id,user_id,attempt_number), FOREIGN KEY(exam_id) REFERENCES exams(id), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE INDEX IF NOT EXISTS idx_exam_sessions_user ON exam_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_exam ON exam_sessions(exam_id);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_status ON exam_sessions(status);
CREATE TABLE IF NOT EXISTS exam_answers (
 id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, question_id INTEGER NOT NULL, selected_answer TEXT NOT NULL DEFAULT '',
 answer_payload_json TEXT NOT NULL DEFAULT '{}', is_answered INTEGER NOT NULL DEFAULT 0, is_correct INTEGER, marks_awarded REAL,
 answered_at REAL, updated_at REAL NOT NULL, UNIQUE(session_id,question_id), FOREIGN KEY(session_id) REFERENCES exam_sessions(id));
CREATE INDEX IF NOT EXISTS idx_exam_answers_session ON exam_answers(session_id);
"""

def db():
    from app import connect
    return connect()

def init_platform():
    with closing(db()) as conn:
        conn.executescript(SCHEMA); conn.commit()
    from exam_conduct import init_exam_conduct
    init_exam_conduct()
    from tutor_agent import init_tutor
    init_tutor()
    from mobile_api import init_mobile
    init_mobile()
    from registration_identity import init_identities
    init_identities()

def _hash(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()
def _admins(): return {x.strip().lower() for x in os.getenv('ADMIN_EMAILS','').split(',') if x.strip()}
def _public_user(row):
    return {**{k: row[k] for k in ('id','email','display_name','given_name','family_name','profile_picture','role','status')},'email_verified':bool(row['email_verified'])}

def _local_request(request: Request) -> bool:
    host=(request.client.host if request.client else '').split('%')[0]
    local_hosts={'127.0.0.1','::1','localhost'}
    if os.getenv('APP_ENV')=='test': local_hosts.add('testclient')
    base=os.getenv('APP_BASE_URL','http://127.0.0.1:8000').lower()
    return host in local_hosts and ('localhost' in base or '127.0.0.1' in base or '[::1]' in base)

def _bootstrap_available(request: Request) -> bool:
    if not _local_request(request): return False
    with closing(db()) as conn:
        return conn.execute('SELECT COUNT(*) n FROM users').fetchone()['n']==0

def _create_login(identity: dict, response: Response):
    sub, email = str(identity.get('sub','')), str(identity.get('email','')).strip().lower()
    if not sub or not email or not identity.get('email_verified'): raise HTTPException(401,'Verified Google identity required')
    now=time.time(); role='ADMIN' if email in _admins() else 'STUDENT'
    with closing(db()) as conn:
        from registration_identity import reserve_email,reserve_phone,phone_key
        reserve_email(conn,email)
        row=conn.execute('SELECT * FROM users WHERE google_sub=?',(sub,)).fetchone()
        if not row:
            existing=conn.execute("SELECT * FROM users WHERE lower(trim(email))=? ORDER BY email_verified DESC,id LIMIT 1",(email,)).fetchone()
            if existing:
                if not existing['google_sub'].startswith(('bootstrap:','registration:')):
                    raise HTTPException(409,'This email already belongs to an account. Sign in using the original Google account.')
                conn.execute('UPDATE users SET google_sub=? WHERE id=?',(sub,existing['id']))
                row=conn.execute('SELECT * FROM users WHERE id=?',(existing['id'],)).fetchone()
        if row and row['email'].strip().lower()!=email and conn.execute('SELECT 1 FROM users WHERE lower(trim(email))=? AND id<>?',(email,row['id'])).fetchone():
            raise HTTPException(409,'This email is already registered to another account.')
        if row:
            next_role = 'ADMIN' if email in _admins() else row['role']
            conn.execute('UPDATE users SET email=?,email_verified=1,display_name=?,given_name=?,family_name=?,profile_picture=?,role=?,last_login_at=?,updated_at=? WHERE id=?',
              (email,identity.get('name',''),identity.get('given_name',''),identity.get('family_name',''),identity.get('picture',''),next_role,now,now,row['id']))
            uid=row['id']
        else:
            cur=conn.execute('INSERT INTO users(google_sub,email,email_verified,display_name,given_name,family_name,profile_picture,role,status,created_at,updated_at,last_login_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
              (sub,email,1,identity.get('name',''),identity.get('given_name',''),identity.get('family_name',''),identity.get('picture',''),role,'ACTIVE',now,now,now)); uid=cur.lastrowid
        pending=conn.execute("SELECT * FROM pending_exam_registrations WHERE lower(registered_email)=? AND status='PENDING'",(email,)).fetchall() if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pending_exam_registrations'").fetchone() else []
        for registration in pending:
            conn.execute("INSERT INTO exam_enrollments(exam_id,user_id,status,registered_at,created_at,updated_at,registered_email,registration_source,created_by,full_name_snapshot,registration_link_id) VALUES(?,?,'ENROLLED',?,?,?,?,?,?,?,?) ON CONFLICT(exam_id,user_id) DO NOTHING",(registration['exam_id'],uid,now,now,now,email,registration['registration_source'],registration['created_by'],registration['full_name'],registration['registration_link_id']))
            if registration['full_name']:
                try:reserve_phone(conn,registration['phone_number'],email)
                except HTTPException:
                    # Preserve the account and its history; conflicting legacy profile data is not copied.
                    continue
                conn.execute("UPDATE users SET display_name=?,date_of_birth=?,phone_number=?,school_name=?,profile_completed=1,updated_at=? WHERE id=?",(registration['full_name'],registration['date_of_birth'],registration['phone_number'],registration['school_name'],now,uid))
            conn.execute("UPDATE pending_exam_registrations SET status='LINKED',updated_at=? WHERE id=?",(now,registration['id']))
        raw,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(24)
        conn.execute('INSERT INTO app_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)',(_hash(raw),uid,csrf,now+SESSION_SECONDS,now)); conn.commit()
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='exam_audit_log'").fetchone():conn.execute("INSERT INTO exam_audit_log(user_id,event_type,metadata_json,created_at) VALUES(?,'USER_LOGIN','{}',?)",(uid,now));conn.commit()
        user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    response.set_cookie('qb_session',raw,max_age=SESSION_SECONDS,httponly=True,samesite='lax',secure=os.getenv('APP_BASE_URL','').startswith('https://'))
    response.set_cookie('qb_csrf',csrf,max_age=SESSION_SECONDS,httponly=False,samesite='lax',secure=os.getenv('APP_BASE_URL','').startswith('https://'))
    return _public_user(user)

def current_user(qb_session: str|None=Cookie(None)):
    if not qb_session: raise HTTPException(401,'Authentication required')
    with closing(db()) as conn:
        row=conn.execute('SELECT u.* FROM app_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?',(_hash(qb_session),time.time())).fetchone()
    if not row or row['status']!='ACTIVE': raise HTTPException(401,'Session expired')
    return row

def require_admin(user=None):
    user=user or current_user()
    if user['role']!='ADMIN': raise HTTPException(403,'Administrator access required')
    return user

def _auth(request: Request, csrf: bool=False):
    user=current_user(request.cookies.get('qb_session'))
    if csrf:
        sent=request.headers.get('x-csrf-token',''); cookie=request.cookies.get('qb_csrf','')
        raw=request.cookies.get('qb_session','')
        with closing(db()) as conn:
            session=conn.execute('SELECT csrf_token FROM app_sessions WHERE token_hash=? AND expires_at>?',(_hash(raw),time.time())).fetchone()
        expected=session['csrf_token'] if session else ''
        if not sent or not cookie or not expected or not secrets.compare_digest(sent,cookie) or not secrets.compare_digest(sent,expected): raise HTTPException(403,'Invalid CSRF token')
    return user

@router.get('/auth/config')
def auth_config(request:Request):
    local_email=os.getenv('ADMIN_LOCAL_EMAIL','').strip().lower()
    # Authentication configuration is intentionally neutral. Administrator
    # identity remains server-side and is resolved only after authentication.
    return {'client_id':os.getenv('GOOGLE_CLIENT_ID',''),'mock':os.getenv('AUTH_MODE')=='mock' and os.getenv('APP_ENV') in {'test','development'},'bootstrap_available':_bootstrap_available(request),'local_admin':bool(local_email and os.getenv('ADMIN_LOCAL_PASSWORD'))}
@router.get('/auth/me')
def auth_me(request:Request): return _public_user(_auth(request))
@router.post('/auth/google')
async def auth_google(request:Request,response:Response):
    token=(await request.json()).get('credential','')
    try:
        from google.auth.transport import requests as grequests
        from google.oauth2 import id_token
        identity=id_token.verify_oauth2_token(token,grequests.Request(),os.getenv('GOOGLE_CLIENT_ID'))
    except Exception as exc: raise HTTPException(401,'Google authentication failed') from exc
    return _create_login(identity,response)
@router.post('/auth/mock')
async def auth_mock(request:Request,response:Response):
    if os.getenv('AUTH_MODE')!='mock' or os.getenv('APP_ENV') not in {'test','development'}: raise HTTPException(404)
    data=await request.json(); email=str(data.get('email','student@example.test')).lower()
    return _create_login({'sub':'mock:'+email,'email':email,'email_verified':True,'name':data.get('name','Test User')},response)
@router.post('/auth/bootstrap-admin')
async def bootstrap_admin(request:Request,response:Response):
    if not _local_request(request): raise HTTPException(403,'Initial administrator registration is available only on this machine')
    data=await request.json();email=str(data.get('email','')).strip().lower();name=str(data.get('name','')).strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): raise HTTPException(422,'Enter a valid administrator email')
    if not name or len(name)>120: raise HTTPException(422,'Enter an administrator name')
    now=time.time();sub='bootstrap:'+secrets.token_urlsafe(18)
    with closing(db()) as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM users LIMIT 1').fetchone(): raise HTTPException(409,'Initial administrator has already been registered')
            conn.execute('INSERT INTO users(google_sub,email,email_verified,display_name,role,status,created_at,updated_at,last_login_at) VALUES(?,?,?,?,?,?,?,?,?)',(sub,email,1,name,'ADMIN','ACTIVE',now,now,now));conn.commit()
        except Exception:
            conn.rollback();raise
    return _create_login({'sub':sub,'email':email,'email_verified':True,'name':name},response)

@router.post('/auth/admin-login')
async def admin_login(request:Request,response:Response):
    data=await request.json();email=str(data.get('email','')).strip().lower();password=str(data.get('password',''));now=time.time();host=request.client.host if request.client else 'unknown'
    failures=[stamp for stamp in _ADMIN_LOGIN_FAILURES.get(host,[]) if stamp>now-300];_ADMIN_LOGIN_FAILURES[host]=failures
    if len(failures)>=5:raise HTTPException(429,'Too many failed sign-in attempts. Try again later.')
    expected_email=os.getenv('ADMIN_LOCAL_EMAIL','').strip().lower();expected_password=os.getenv('ADMIN_LOCAL_PASSWORD','')
    if not expected_email or not expected_password or not secrets.compare_digest(email,expected_email) or not secrets.compare_digest(password,expected_password):failures.append(now);raise HTTPException(401,'Invalid administrator credentials')
    with closing(db()) as conn:
        user=conn.execute("SELECT * FROM users WHERE lower(email)=? AND role='ADMIN' AND status='ACTIVE'",(email,)).fetchone()
        if not user:raise HTTPException(403,'Configured administrator account was not found')
        raw,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(24);conn.execute('INSERT INTO app_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)',(_hash(raw),user['id'],csrf,now+SESSION_SECONDS,now));conn.execute('UPDATE users SET last_login_at=?,updated_at=? WHERE id=?',(now,now,user['id']));conn.commit()
    _ADMIN_LOGIN_FAILURES.pop(host,None);secure=os.getenv('APP_BASE_URL','').startswith('https://');response.set_cookie('qb_session',raw,max_age=SESSION_SECONDS,httponly=True,samesite='lax',secure=secure);response.set_cookie('qb_csrf',csrf,max_age=SESSION_SECONDS,httponly=False,samesite='lax',secure=secure);return _public_user(user)

@router.post('/auth/student-registration-login')
async def student_registration_login(request:Request,response:Response):
    data=await request.json();email=str(data.get('email','')).strip().lower();dob=str(data.get('date_of_birth','')).strip();phone=re.sub(r'\D','',str(data.get('phone_number','')));now=time.time()
    with closing(db()) as conn:
        from registration_identity import reserve_email,reserve_phone,phone_key
        reserve_email(conn,email)
        pending=conn.execute("SELECT * FROM pending_exam_registrations WHERE lower(registered_email)=? AND status IN ('PENDING','LINKED') ORDER BY id DESC",(email,)).fetchall()
        match=next((r for r in pending if r['date_of_birth']==dob and re.sub(r'\D','',r['phone_number'])==phone),None)
        if not match:raise HTTPException(401,'Registration details do not match. Use the email, date of birth and phone entered during registration.')
        user=conn.execute("SELECT * FROM users WHERE lower(email)=?",(email,)).fetchone()
        if user and user['role']!='STUDENT':raise HTTPException(403,'This email belongs to a staff account')
        if not user:
            reserve_phone(conn,match['phone_number'],email)
            cur=conn.execute("INSERT INTO users(google_sub,email,email_verified,display_name,role,status,created_at,updated_at,last_login_at,date_of_birth,phone_number,school_name,profile_completed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",(f"registration:{secrets.token_urlsafe(18)}",email,0,match['full_name'],'STUDENT','ACTIVE',now,now,now,match['date_of_birth'],match['phone_number'],match['school_name']));uid=cur.lastrowid
        else:
            if phone_key(user['phone_number'])!=phone_key(match['phone_number']):reserve_phone(conn,match['phone_number'],email)
            uid=user['id'];conn.execute("UPDATE users SET display_name=?,date_of_birth=?,phone_number=?,school_name=?,profile_completed=1,last_login_at=?,updated_at=? WHERE id=?",(match['full_name'],match['date_of_birth'],match['phone_number'],match['school_name'],now,now,uid))
        for registration in pending:
            if registration['status']=='PENDING' and registration['date_of_birth']==dob and re.sub(r'\D','',registration['phone_number'])==phone:
                conn.execute("INSERT INTO exam_enrollments(exam_id,user_id,status,registered_at,created_at,updated_at,registered_email,registration_source,created_by,full_name_snapshot,registration_link_id) VALUES(?,?,'ENROLLED',?,?,?,?,?,?,?,?) ON CONFLICT(exam_id,user_id) DO UPDATE SET status='ENROLLED',updated_at=excluded.updated_at",(registration['exam_id'],uid,now,now,now,email,registration['registration_source'],registration['created_by'],registration['full_name'],registration['registration_link_id']));conn.execute("UPDATE pending_exam_registrations SET status='LINKED',updated_at=? WHERE id=?",(now,registration['id']))
        raw,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(24);conn.execute('INSERT INTO app_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)',(_hash(raw),uid,csrf,now+SESSION_SECONDS,now));conn.commit();user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    secure=os.getenv('APP_BASE_URL','').startswith('https://');response.set_cookie('qb_session',raw,max_age=SESSION_SECONDS,httponly=True,samesite='lax',secure=secure);response.set_cookie('qb_csrf',csrf,max_age=SESSION_SECONDS,httponly=False,samesite='lax',secure=secure);return _public_user(user)
@router.post('/auth/logout')
def logout(request:Request,response:Response):
    _auth(request,True)
    raw=request.cookies.get('qb_session','')
    with closing(db()) as conn: conn.execute('DELETE FROM app_sessions WHERE token_hash=?',(_hash(raw),));conn.commit()
    response.delete_cookie('qb_session');response.delete_cookie('qb_csrf');return {'ok':True}

class ExamIn(BaseModel):
    name:str=Field(min_length=1,max_length=200); description:str='';exam_type:str='';subject:str='';level:str='';instructions:str=''
    duration_minutes:int=Field(default=30,ge=1,le=1440);negative_marking:float=0;status:str='DRAFT';max_attempts:int=Field(default=1,ge=1,le=20)
    registration_start_at:float|None=None;registration_end_at:float|None=None;exam_start_at:float|None=None;exam_end_at:float|None=None
    proctor_required:bool=False;result_release_mode:str='IMMEDIATE'
    allow_retake:bool=False;allow_self_registration:bool=True;allow_registration_link:bool=True
    question_ids:list[int]=Field(default_factory=list)

from exam_generation_service import ExamBlueprint, availability as blueprint_availability, combined as combine_filters, generate as generate_blueprint, load_candidates, matches as question_matches

def validate_exam_blueprint(payload) -> ExamBlueprint:
    try:return ExamBlueprint.model_validate(payload)
    except ValidationError as exc:raise HTTPException(422,exc.errors(include_url=False)) from exc

@router.post('/admin/exam-blueprints/availability')
async def check_exam_blueprint(request:Request):
    require_admin(_auth(request,True));blueprint=validate_exam_blueprint(await request.json())
    with closing(db()) as conn:return blueprint_availability(conn,blueprint)

@router.post('/admin/exam-blueprints/preview')
async def preview_exam_blueprint(request:Request):
    require_admin(_auth(request,True));blueprint=validate_exam_blueprint(await request.json())
    with closing(db()) as conn:
        try:return generate_blueprint(conn,blueprint)
        except ValueError as exc:raise HTTPException(409,str(exc))

class BlueprintApproval(BaseModel):
    blueprint: ExamBlueprint
    question_ids: list[int] = Field(min_length=1, max_length=200)
    selection_rule_ids: dict[int,str] = Field(default_factory=dict)
    status: str = 'DRAFT'

class BlueprintReplacement(BaseModel):
    blueprint: ExamBlueprint
    rule_id: str
    exclude_question_ids: list[int] = Field(default_factory=list)

@router.post('/admin/exam-blueprints/replacement')
async def replace_blueprint_question(request:Request):
    require_admin(_auth(request,True))
    try:data=BlueprintReplacement.model_validate(await request.json())
    except ValidationError as exc:raise HTTPException(422,exc.errors(include_url=False)) from exc
    rule=next((r for r in data.blueprint.rules if r.id==data.rule_id),None)
    if not rule:raise HTTPException(404,'Blueprint rule not found')
    replacement=data.blueprint.model_copy(update={'total_questions':1,'rules':[rule.model_copy(update={'count':1})],'exclude_question_ids':data.exclude_question_ids})
    with closing(db()) as conn:
        try:return generate_blueprint(conn,replacement)['questions'][0]
        except (ValueError,IndexError) as exc:raise HTTPException(409,str(exc) or 'No matching replacement is available')

@router.post('/admin/exam-blueprints/approve')
async def approve_exam_blueprint(request:Request):
    user=require_admin(_auth(request,True))
    try:data=BlueprintApproval.model_validate(await request.json())
    except ValidationError as exc:raise HTTPException(422,exc.errors(include_url=False)) from exc
    bp=data.blueprint;now=time.time()
    if len(data.question_ids)!=bp.total_questions or len(set(data.question_ids))!=len(data.question_ids):raise HTTPException(422,'Selected question count must equal the blueprint total and contain no duplicates')
    if data.status not in {'DRAFT','PUBLISHED'}:raise HTTPException(422,'Status must be DRAFT or PUBLISHED')
    with closing(db()) as conn:
        generated=generate_blueprint(conn,bp);pool={q['id']:q for q in load_candidates(conn,bp)};rule_map={r.id:r for r in bp.rules};counts={r.id:0 for r in bp.rules}
        selection_rules=data.selection_rule_ids or {q['id']:q['rule_id'] for q in generated['questions']}
        for qid in data.question_ids:
            rule_id=selection_rules.get(qid);rule=rule_map.get(rule_id or '')
            effective=combine_filters(bp.global_filters,rule.filters) if rule else None
            valid=bool(rule and qid in pool and (question_matches(pool[qid],effective) or (bp.allow_controlled_fallback and (question_matches(pool[qid],effective,'subtopic') or question_matches(pool[qid],effective,'topic')))))
            if not valid:
                raise HTTPException(409,f'Question {qid} does not satisfy its blueprint rule')
            counts[rule_id]+=1
        if any(counts[r.id]!=r.count for r in bp.rules):raise HTTPException(409,'Selected questions no longer satisfy the blueprint quotas')
        if bp.exam_id:
            exam=conn.execute('SELECT * FROM exams WHERE id=?',(bp.exam_id,)).fetchone()
            if not exam:raise HTTPException(404,'Saved exam template not found')
            if exam['status']!='DRAFT' or conn.execute('SELECT 1 FROM exam_sessions WHERE exam_id=?',(bp.exam_id,)).fetchone():raise HTTPException(409,'Only an unused draft exam template can receive a generated question paper')
            eid=bp.exam_id;conn.execute('DELETE FROM exam_questions WHERE exam_id=?',(eid,));conn.execute('UPDATE exams SET name=?,description=?,exam_type=?,subject=?,level=?,duration_minutes=?,status=?,updated_at=? WHERE id=?',(bp.exam_name,bp.prompt,bp.exam_type,bp.global_filters.subject or '',bp.global_filters.grade or '',bp.duration_minutes,data.status,now,eid))
        else:
            cur=conn.execute('INSERT INTO exams(name,description,exam_type,subject,level,instructions,duration_minutes,negative_marking,status,max_attempts,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(bp.exam_name,bp.prompt,bp.exam_type,bp.global_filters.subject or '',bp.global_filters.grade or '','',bp.duration_minutes,0,data.status,1,user['id'],now,now));eid=cur.lastrowid
        questions={qid:pool[qid] for qid in data.question_ids}
        for order,qid in enumerate(data.question_ids,1):
            try:marks=max(.01,float(questions[qid].get('marks') or 1))
            except (TypeError,ValueError):marks=1
            conn.execute('INSERT INTO exam_questions(exam_id,question_id,display_order,marks,negative_marks,created_at) VALUES(?,?,?,?,0,?)',(eid,qid,order,marks,now))
        conn.execute('UPDATE exams SET total_marks=(SELECT COALESCE(SUM(marks),0) FROM exam_questions WHERE exam_id=?) WHERE id=?',(eid,eid))
        raw=bp.model_dump_json();bcur=conn.execute('INSERT INTO exam_blueprints(exam_id,name,blueprint_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)',(eid,bp.exam_name,raw,user['id'],now,now));bid=bcur.lastrowid
        summary=generated['summary'];rcur=conn.execute('INSERT INTO exam_generation_runs(exam_id,blueprint_id,requested_questions,selected_questions,shortage_count,fallback_count,selection_seed,status,request_json,result_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(eid,bid,bp.total_questions,len(data.question_ids),0,summary['fallback_matches'],bp.random_seed,'GENERATED',raw,json.dumps(summary),user['id'],now));run_id=rcur.lastrowid
        if data.status=='PUBLISHED':
            from exam_conduct import publish_version
            publish_version(conn,eid,user['id'])
            conn.execute("UPDATE exam_generation_runs SET status='PUBLISHED' WHERE id=?",(run_id,))
        conn.commit()
    return {'id':eid,'blueprint_id':bid,'generation_run_id':run_id,'status':data.status}

@router.get('/admin/question-metadata/facets')
def question_metadata_facets(request:Request,grade:str='',subject:str='',chapter:str='',topic:str=''):
    require_admin(_auth(request));conditions=["statement<>''"];params=[]
    for field,value in (("subject",subject),("chapter",chapter),("topic",topic)):
        if value:conditions.append(f"lower({field})=lower(?)");params.append(value)
    if grade:
        canonical=grade.strip().lower().replace('class ','grade ')
        alias=canonical.replace('grade ','class ')
        conditions.append("(lower(exam || ' ' || tags || ' ' || generation_metadata) LIKE ? OR lower(exam || ' ' || tags || ' ' || generation_metadata) LIKE ?)")
        params.extend((f"%{canonical}%",f"%{alias}%"))
    where=' AND '.join(conditions);result={}
    with closing(db()) as conn:
        for field,key in (("subject","subjects"),("chapter","chapters"),("topic","topics"),("subtopic","subtopics"),("difficulty","difficulties"),("qtype","question_types"),("source_type","source_types"),("verification_status","verification_statuses")):
            result[key]=[{'value':r['value'],'count':r['count']} for r in conn.execute(f"SELECT {field} value,COUNT(*) count FROM questions WHERE {where} AND {field}<>'' GROUP BY {field} ORDER BY count DESC,{field}",tuple(params)).fetchall()]
    return result

def _exam(row, count=0):
    return {**dict(row),'question_count':count}

@router.get('/public/exams')
def public_exams():
    """Return only non-sensitive metadata for assessments open to learners."""
    with closing(db()) as conn:
        rows=conn.execute("""SELECT e.id,e.name,e.description,e.exam_type,e.subject,e.level,
          e.duration_minutes,e.proctor_required,e.allow_self_registration,COUNT(eq.id) question_count
          FROM exams e LEFT JOIN exam_questions eq ON eq.exam_id=e.id
          WHERE e.status='OPEN' GROUP BY e.id ORDER BY e.updated_at DESC LIMIT 12""").fetchall()
    return [{**dict(row),'proctor_required':bool(row['proctor_required']),'allow_self_registration':bool(row['allow_self_registration'])} for row in rows]

@router.post('/public/exams/{exam_id}/register')
async def public_exam_registration(exam_id:int,request:Request,response:Response):
    if os.getenv('APP_ENV')!='test':
        raise HTTPException(401,'Continue with Google to verify your Gmail identity before enrollment')
    data=await request.json();first=str(data.get('first_name','')).strip();last=str(data.get('last_name','')).strip();dob=str(data.get('date_of_birth','')).strip();email=str(data.get('email','')).strip().lower();now=time.time()
    if not first or not last or len(first)>80 or len(last)>80:raise HTTPException(422,'Enter the student first and last name')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',dob):raise HTTPException(422,'Enter a valid date of birth')
    if not re.fullmatch(r'[^\s@]+@gmail\.com',email):raise HTTPException(422,'Enter a valid Gmail address')
    with closing(db()) as conn:
        from registration_identity import reserve_email
        reserve_email(conn,email)
        exam=conn.execute("SELECT * FROM exams WHERE id=? AND status='OPEN' AND allow_self_registration=1",(exam_id,)).fetchone()
        if not exam:raise HTTPException(404,'This exam is not available for public registration')
        if (exam['registration_start_at'] and now<exam['registration_start_at']) or (exam['registration_end_at'] and now>exam['registration_end_at']):raise HTTPException(403,'Registration window is closed')
        user=conn.execute('SELECT * FROM users WHERE lower(email)=?',(email,)).fetchone()
        if user and user['role']!='STUDENT':raise HTTPException(403,'This email belongs to a staff account')
        if user and user['date_of_birth'] and user['date_of_birth']!=dob:raise HTTPException(401,'Registration details do not match the existing student account')
        name=f'{first} {last}'.strip()
        if not user:
            cur=conn.execute("INSERT INTO users(google_sub,email,email_verified,display_name,given_name,family_name,role,status,created_at,updated_at,last_login_at,date_of_birth,profile_completed) VALUES(?,?,?,?,?,?,'STUDENT','ACTIVE',?,?,?,?,1)",(f'registration:{secrets.token_urlsafe(18)}',email,0,name,first,last,now,now,now,dob));uid=cur.lastrowid
        else:
            uid=user['id'];conn.execute('UPDATE users SET display_name=?,given_name=?,family_name=?,date_of_birth=?,last_login_at=?,updated_at=? WHERE id=?',(name,first,last,dob,now,now,uid))
        conn.execute("INSERT INTO exam_enrollments(exam_id,user_id,status,registered_at,created_at,updated_at,registered_email,registration_source,created_by,full_name_snapshot) VALUES(?,?,'ENROLLED',?,?,?,?,'PUBLIC',?,?) ON CONFLICT(exam_id,user_id) DO UPDATE SET status='ENROLLED',cancelled_at=NULL,updated_at=excluded.updated_at",(exam_id,uid,now,now,now,email,uid,name))
        raw,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(24);conn.execute('INSERT INTO app_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)',(_hash(raw),uid,csrf,now+SESSION_SECONDS,now));conn.commit();user=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    secure=os.getenv('APP_BASE_URL','').startswith('https://');response.set_cookie('qb_session',raw,max_age=SESSION_SECONDS,httponly=True,samesite='lax',secure=secure);response.set_cookie('qb_csrf',csrf,max_age=SESSION_SECONDS,httponly=False,samesite='lax',secure=secure)
    return {'registered':True,'exam_id':exam_id,'user':_public_user(user)}

@router.get('/exams')
def exams(request:Request):
    user=_auth(request); where='' if user['role'] in {'ADMIN','PROCTOR'} else " WHERE e.status='OPEN'"
    with closing(db()) as conn: rows=conn.execute(f'SELECT e.*,COUNT(eq.id) question_count FROM exams e LEFT JOIN exam_questions eq ON eq.exam_id=e.id{where} GROUP BY e.id ORDER BY e.created_at DESC').fetchall()
    return [_exam(r,r['question_count']) for r in rows]
@router.get('/exams/{exam_id}')
def exam_detail(exam_id:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        row=conn.execute('SELECT e.*,COUNT(eq.id) question_count FROM exams e LEFT JOIN exam_questions eq ON eq.exam_id=e.id WHERE e.id=? GROUP BY e.id',(exam_id,)).fetchone()
    if not row or (user['role'] not in {'ADMIN','PROCTOR'} and row['status']!='OPEN'): raise HTTPException(404,'Exam not found')
    return dict(row)
@router.post('/admin/exams')
async def create_exam(request:Request):
    user=require_admin(_auth(request,True)); data=ExamIn.model_validate(await request.json());now=time.time()
    if data.status not in {'DRAFT','PUBLISHED','OPEN','CLOSED','ARCHIVED'}: raise HTTPException(400,'Invalid status')
    if data.status in {'PUBLISHED','OPEN'} and not data.question_ids:raise HTTPException(409,'Add at least one question before publishing or opening an exam')
    with closing(db()) as conn:
        cur=conn.execute('INSERT INTO exams(name,description,exam_type,subject,level,instructions,duration_minutes,negative_marking,status,max_attempts,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(*[getattr(data,k) for k in ('name','description','exam_type','subject','level','instructions','duration_minutes','negative_marking','status','max_attempts')],user['id'],now,now)); eid=cur.lastrowid
        for i,qid in enumerate(data.question_ids): conn.execute('INSERT INTO exam_questions(exam_id,question_id,display_order,marks,negative_marks,created_at) VALUES(?,?,?,?,?,?)',(eid,qid,i+1,1,data.negative_marking,now))
        conn.execute('UPDATE exams SET total_marks=(SELECT COALESCE(SUM(marks),0) FROM exam_questions WHERE exam_id=?) WHERE id=?',(eid,eid));conn.commit()
        conn.execute('UPDATE exams SET registration_start_at=?,registration_end_at=?,exam_start_at=?,exam_end_at=?,proctor_required=?,result_release_mode=?,allow_retake=?,allow_self_registration=?,allow_registration_link=? WHERE id=?',(data.registration_start_at,data.registration_end_at,data.exam_start_at,data.exam_end_at,int(data.proctor_required),data.result_release_mode,int(data.allow_retake),int(data.allow_self_registration),int(data.allow_registration_link),eid));conn.commit()
        if data.status in {'PUBLISHED','OPEN'}:
            from exam_conduct import publish_version
            publish_version(conn,eid,user['id']);conn.commit()
    return {'id':eid}
@router.put('/admin/exams/{exam_id}')
async def update_exam(exam_id:int,request:Request):
    require_admin(_auth(request,True));data=ExamIn.model_validate(await request.json());now=time.time()
    if data.status not in {'DRAFT','PUBLISHED','OPEN','CLOSED','ARCHIVED'}:raise HTTPException(400,'Invalid status')
    if data.status in {'PUBLISHED','OPEN'} and not data.question_ids:raise HTTPException(409,'Add at least one question before publishing or opening an exam')
    with closing(db()) as conn:
        if not conn.execute('SELECT 1 FROM exams WHERE id=?',(exam_id,)).fetchone():raise HTTPException(404,'Exam not found')
        conn.execute('UPDATE exams SET name=?,description=?,exam_type=?,subject=?,level=?,instructions=?,duration_minutes=?,negative_marking=?,status=?,max_attempts=?,updated_at=? WHERE id=?',(*[getattr(data,k) for k in ('name','description','exam_type','subject','level','instructions','duration_minutes','negative_marking','status','max_attempts')],now,exam_id))
        conn.execute('DELETE FROM exam_questions WHERE exam_id=?',(exam_id,))
        for i,qid in enumerate(data.question_ids):conn.execute('INSERT INTO exam_questions(exam_id,question_id,display_order,marks,negative_marks,created_at) VALUES(?,?,?,?,?,?)',(exam_id,qid,i+1,1,data.negative_marking,now))
        conn.execute('UPDATE exams SET total_marks=(SELECT COALESCE(SUM(marks),0) FROM exam_questions WHERE exam_id=?) WHERE id=?',(exam_id,exam_id));conn.commit()
        conn.execute('UPDATE exams SET registration_start_at=?,registration_end_at=?,exam_start_at=?,exam_end_at=?,proctor_required=?,result_release_mode=?,allow_retake=?,allow_self_registration=?,allow_registration_link=? WHERE id=?',(data.registration_start_at,data.registration_end_at,data.exam_start_at,data.exam_end_at,int(data.proctor_required),data.result_release_mode,int(data.allow_retake),int(data.allow_self_registration),int(data.allow_registration_link),exam_id));conn.commit()
        if data.status in {'PUBLISHED','OPEN'}:
            from exam_conduct import publish_version
            publish_version(conn,exam_id,require_admin(_auth(request))['id']);conn.commit()
    return {'id':exam_id}
@router.delete('/admin/exams/{exam_id}')
def delete_exam(exam_id:int,request:Request):
    require_admin(_auth(request,True))
    with closing(db()) as conn:
        used=conn.execute('SELECT 1 FROM exam_sessions WHERE exam_id=?',(exam_id,)).fetchone()
        registered=conn.execute('SELECT 1 FROM exam_enrollments WHERE exam_id=?',(exam_id,)).fetchone()
        pending=conn.execute('SELECT 1 FROM pending_exam_registrations WHERE exam_id=?',(exam_id,)).fetchone()
        if used or registered or pending:raise HTTPException(409,'This exam has registration or attempt history and must be closed or archived')
        # Published exams own immutable versions and may also own unused access
        # codes, links and blueprint history. Remove those children explicitly;
        # registration and attempt history remains a hard deletion boundary.
        conn.execute('DELETE FROM exam_generation_runs WHERE exam_id=?',(exam_id,))
        conn.execute('DELETE FROM exam_blueprints WHERE exam_id=?',(exam_id,))
        conn.execute('DELETE FROM exam_registration_links WHERE exam_id=?',(exam_id,))
        conn.execute('DELETE FROM exam_proctor_codes WHERE exam_id=?',(exam_id,))
        conn.execute('DELETE FROM proctor_code_failures WHERE exam_id=?',(exam_id,))
        conn.execute('UPDATE exams SET current_version_id=NULL WHERE id=?',(exam_id,))
        conn.execute('DELETE FROM exam_versions WHERE exam_id=?',(exam_id,))
        conn.execute('DELETE FROM exam_questions WHERE exam_id=?',(exam_id,));cur=conn.execute('DELETE FROM exams WHERE id=?',(exam_id,));conn.commit()
    if not cur.rowcount:raise HTTPException(404,'Exam not found')
    return {'deleted':exam_id}
@router.post('/exams/{exam_id}/enroll')
def enroll(exam_id:int,request:Request):
    user=_auth(request,True);now=time.time()
    if user['role']!='STUDENT':raise HTTPException(403,'Student access required for exam enrollment')
    if not user['email_verified']:raise HTTPException(401,'Verified Google Gmail identity required for exam enrollment')
    with closing(db()) as conn:
        exam=conn.execute("SELECT * FROM exams WHERE id=? AND status IN ('PUBLISHED','OPEN')",(exam_id,)).fetchone()
        if not exam: raise HTTPException(404,'Available exam not found')
        if not exam['allow_self_registration']:raise HTTPException(403,'This exam requires a registration link or administrator registration')
        if (exam['registration_start_at'] and now<exam['registration_start_at']) or (exam['registration_end_at'] and now>exam['registration_end_at']):raise HTTPException(403,'Registration window is closed')
        conn.execute("INSERT INTO exam_enrollments(exam_id,user_id,status,registered_at,created_at,updated_at,registered_email,registration_source,created_by) VALUES(?,?,'ENROLLED',?,?,?,?, 'SELF',?) ON CONFLICT(exam_id,user_id) DO UPDATE SET status='ENROLLED',cancelled_at=NULL,updated_at=excluded.updated_at",(exam_id,user['id'],now,now,now,user['email'],user['id']));
        from exam_conduct import audit
        audit(conn,'EXAM_ENROLLED',exam_id=exam_id,user_id=user['id']);conn.commit()
    return {'enrolled':True}
@router.get('/my/exams')
def my_exams(request:Request):
    user=_auth(request)
    with closing(db()) as conn: rows=conn.execute('SELECT e.*,r.id registration_id,r.registered_at,r.status registration_status,COALESCE(r.max_attempts_override,e.max_attempts) effective_max_attempts,CASE WHEN e.allow_retake=1 OR r.max_attempts_override IS NOT NULL THEN 1 ELSE 0 END student_allow_retake,(SELECT COUNT(*) FROM exam_sessions s WHERE s.exam_id=e.id AND s.user_id=?) attempts_used,(SELECT id FROM exam_sessions s WHERE s.exam_id=e.id AND s.user_id=? ORDER BY attempt_number DESC LIMIT 1) latest_session_id,(SELECT status FROM exam_sessions s WHERE s.exam_id=e.id AND s.user_id=? ORDER BY attempt_number DESC LIMIT 1) latest_session_status FROM exam_enrollments r JOIN exams e ON e.id=r.exam_id WHERE r.user_id=? ORDER BY r.registered_at DESC',(user['id'],user['id'],user['id'],user['id'])).fetchall()
    return [dict(r) for r in rows]

def _session(conn,sid,uid):
    row=conn.execute('SELECT * FROM exam_sessions WHERE id=? AND user_id=?',(sid,uid)).fetchone()
    if not row: raise HTTPException(404,'Exam session not found')
    if row['status']=='IN_PROGRESS' and row['expires_at']<=time.time():
        _submit(conn,row,'AUTO_SUBMITTED');row=conn.execute('SELECT * FROM exam_sessions WHERE id=?',(sid,)).fetchone()
    return row
def _submit(conn,s,status='SUBMITTED'):
    snapshot=json.loads(s['question_set_json'] or '[]') if 'question_set_json' in s.keys() else []
    if snapshot:rows=snapshot
    else:rows=[dict(r) for r in conn.execute('SELECT eq.question_id id,eq.marks,eq.negative_marks,q.answer FROM exam_questions eq JOIN questions q ON q.id=eq.question_id WHERE eq.exam_id=?',(s['exam_id'],)).fetchall()]
    score=0;correct=wrong=unanswered=0
    for r in rows:
        qid=r.get('id') or r.get('question_id');answer_row=conn.execute('SELECT selected_answer FROM exam_answers WHERE session_id=? AND question_id=?',(s['id'],qid)).fetchone();selected=(answer_row['selected_answer'] if answer_row else '').strip().upper(); expected=(r.get('answer') or '').strip().upper()
        if not selected: unanswered+=1;ok=None;marks=0
        elif selected==expected:correct+=1;ok=1;marks=r['marks'];score+=marks
        else:wrong+=1;ok=0;marks=-r['negative_marks'];score+=marks
        conn.execute('UPDATE exam_answers SET is_correct=?,marks_awarded=?,scored_at=?,updated_at=? WHERE session_id=? AND question_id=?',(ok,marks,time.time(),time.time(),s['id'],qid))
    maximum=sum(float(r.get('marks') or 0) for r in rows);now=time.time();conn.execute('UPDATE exam_sessions SET status=?,submitted_at=?,auto_submitted_at=?,score=?,max_score=?,percentage=?,correct_count=?,incorrect_count=?,unanswered_count=?,updated_at=? WHERE id=?',(status,now,now if status=='AUTO_SUBMITTED' else None,score,maximum,(score/maximum*100 if maximum else 0),correct,wrong,unanswered,now,s['id']))
    limit=conn.execute('SELECT COALESCE(r.max_attempts_override,e.max_attempts) maximum FROM exam_enrollments r JOIN exams e ON e.id=r.exam_id WHERE r.id=?',(s['registration_id'],)).fetchone()['maximum']
    if s['attempt_number']>=limit:conn.execute("UPDATE exam_enrollments SET status='COMPLETED',updated_at=? WHERE id=?",(now,s['registration_id']))
    conn.commit()

@router.post('/exams/{exam_id}/sessions')
def start_exam(exam_id:int,request:Request):
    user=_auth(request,True);now=time.time()
    with closing(db()) as conn:
        reg=conn.execute("SELECT * FROM exam_enrollments WHERE exam_id=? AND user_id=? AND status='ENROLLED'",(exam_id,user['id'])).fetchone(); exam=conn.execute("SELECT * FROM exams WHERE id=? AND status IN ('PUBLISHED','OPEN')",(exam_id,)).fetchone()
        if not reg or not exam: raise HTTPException(403,'Enrollment in a published exam is required')
        active=conn.execute("SELECT id FROM exam_sessions WHERE exam_id=? AND user_id=? AND status='IN_PROGRESS' AND expires_at>?",(exam_id,user['id'],now)).fetchone()
        if active:return {'session_id':active['id'],'resumed':True}
        if exam['proctor_required']:raise HTTPException(403,'Proctor code must be validated through secure exam start')
        if (exam['exam_start_at'] and now<exam['exam_start_at']) or (exam['exam_end_at'] and now>exam['exam_end_at']):raise HTTPException(403,'Exam is outside its permitted start window')
        attempt=conn.execute('SELECT COUNT(*) n FROM exam_sessions WHERE exam_id=? AND user_id=?',(exam_id,user['id'])).fetchone()['n']+1
        maximum=reg['max_attempts_override'] or exam['max_attempts']
        if attempt>maximum:raise HTTPException(409,'Attempt limit reached')
        version=conn.execute('SELECT * FROM exam_versions WHERE id=?',(exam['current_version_id'],)).fetchone() if exam['current_version_id'] else None
        if version:snapshot=json.loads(version['question_snapshot_json']);version_id=version['id']
        else:
            from exam_conduct import _snapshot
            snapshot=_snapshot(conn,exam_id);version_id=None
        cur=conn.execute("INSERT INTO exam_sessions(exam_id,user_id,registration_id,attempt_number,status,started_at,expires_at,duration_minutes,question_set_json,exam_version_id,created_at,updated_at) VALUES(?,?,?,?,'IN_PROGRESS',?,?,?,?,?,?,?)",(exam_id,user['id'],reg['id'],attempt,now,now+exam['duration_minutes']*60,exam['duration_minutes'],json.dumps(snapshot),version_id,now,now));conn.commit();return {'session_id':cur.lastrowid,'resumed':False}
@router.get('/sessions/{sid}')
def get_session(sid:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        s=_session(conn,sid,user['id']); exam=conn.execute('SELECT name,instructions,proctor_required FROM exams WHERE id=?',(s['exam_id'],)).fetchone()
        snapshot=json.loads(s['question_set_json'] or '[]') if 'question_set_json' in s.keys() else []
        if snapshot:
            answers={r['question_id']:r for r in conn.execute('SELECT question_id,selected_answer,answer_payload_json,status FROM exam_answers WHERE session_id=?',(sid,)).fetchall()};questions=[{'id':q['id'],'number':q['display_order'],'statement':q['statement'],'options':q['options'],'marks':q['marks'],'section':q.get('section_name',''),'selected_answer':answers[q['id']]['selected_answer'] if q['id'] in answers else '','state':answers[q['id']]['status'] if q['id'] in answers else 'NOT_VISITED'} for q in snapshot]
        else:
            rows=conn.execute('SELECT q.id,q.statement,q.options,eq.display_order,eq.marks,a.selected_answer,a.answer_payload_json,a.status FROM exam_questions eq JOIN questions q ON q.id=eq.question_id LEFT JOIN exam_answers a ON a.session_id=? AND a.question_id=q.id WHERE eq.exam_id=? ORDER BY eq.display_order',(sid,s['exam_id'])).fetchall();questions=[{'id':r['id'],'number':r['display_order'],'statement':r['statement'],'options':json.loads(r['options'] or '[]'),'marks':r['marks'],'selected_answer':r['selected_answer'] or '','state':r['status'] or 'NOT_VISITED'} for r in rows]
    safe_session={key:s[key] for key in ('id','exam_id','attempt_number','status','started_at','expires_at','duration_minutes')}
    return {'session':safe_session,'exam':dict(exam),'server_time':time.time(),'questions':questions}
@router.put('/sessions/{sid}/answers/{qid}')
async def save_answer(sid:int,qid:int,request:Request):
    user=_auth(request,True);data=await request.json();selected=str(data.get('selected_answer',''));now=time.time()
    with closing(db()) as conn:
        s=_session(conn,sid,user['id'])
        if s['status']!='IN_PROGRESS':raise HTTPException(409,'Submitted exams cannot be modified')
        snapshot=json.loads(s['question_set_json'] or '[]') if 'question_set_json' in s.keys() else [];exists=any(int(q['id'])==qid for q in snapshot) if snapshot else conn.execute('SELECT 1 FROM exam_questions WHERE exam_id=? AND question_id=?',(s['exam_id'],qid)).fetchone()
        if not exists:raise HTTPException(404,'Question not in this exam')
        state='ANSWERED' if selected else 'NOT_ANSWERED';conn.execute('INSERT INTO exam_answers(session_id,question_id,selected_answer,answer_payload_json,is_answered,answered_at,first_answered_at,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id,question_id) DO UPDATE SET selected_answer=excluded.selected_answer,answer_payload_json=excluded.answer_payload_json,is_answered=excluded.is_answered,answered_at=excluded.answered_at,first_answered_at=COALESCE(exam_answers.first_answered_at,excluded.first_answered_at),status=CASE WHEN exam_answers.status IN (\'MARKED_FOR_REVIEW\',\'ANSWERED_AND_MARKED\') THEN CASE WHEN excluded.is_answered=1 THEN \'ANSWERED_AND_MARKED\' ELSE \'MARKED_FOR_REVIEW\' END ELSE excluded.status END,updated_at=excluded.updated_at',(sid,qid,selected,json.dumps(data.get('answer_payload',{})),int(bool(selected)),now,now if selected else None,state,now));
        from exam_conduct import audit
        audit(conn,'ANSWER_SAVED',exam_id=s['exam_id'],user_id=user['id'],session_id=sid,metadata={'question_id':qid});conn.commit()
    return {'saved':True}
@router.post('/sessions/{sid}/submit')
def submit(sid:int,request:Request,background_tasks:BackgroundTasks):
    user=_auth(request,True)
    with closing(db()) as conn:
        s=_session(conn,sid,user['id'])
        if s['status']!='IN_PROGRESS':return {'submitted':True,'already_submitted':True,'status':s['status']}
        _submit(conn,s)
        from exam_conduct import audit
        audit(conn,'EXAM_SUBMITTED',exam_id=s['exam_id'],user_id=user['id'],session_id=sid);conn.commit()
    from mobile_notifications import notify_result
    background_tasks.add_task(notify_result,user['id'])
    return {'submitted':True}
@router.get('/my/results')
def results(request:Request):
    user=_auth(request)
    with closing(db()) as conn:rows=conn.execute("SELECT s.*,e.name exam_name,e.exam_type,e.subject,e.level FROM exam_sessions s JOIN exams e ON e.id=s.exam_id WHERE s.user_id=? AND s.status IN ('SUBMITTED','AUTO_SUBMITTED') ORDER BY s.submitted_at DESC",(user['id'],)).fetchall()
    return [dict(r) for r in rows]

def _student_analytics_user(request:Request):
    user=_auth(request)
    if user['role'] not in {'STUDENT','ADMIN'}:raise HTTPException(403,'Student or administrator access required')
    return user

def _completed_attempts(conn,user_id:int|None,exam_id:int|None=None):
    clauses=[];params=[]
    if user_id is not None:clauses.append('s.user_id=?');params.append(user_id)
    if exam_id is not None:clauses.append('s.exam_id=?');params.append(exam_id)
    scope=(' AND '+' AND '.join(clauses)) if clauses else ''
    return [dict(r) for r in conn.execute(f"SELECT s.*,e.name exam_name,e.exam_type,e.subject,e.level,u.email student_email,u.display_name student_name FROM exam_sessions s JOIN exams e ON e.id=s.exam_id JOIN users u ON u.id=s.user_id WHERE s.status IN ('SUBMITTED','AUTO_SUBMITTED'){scope} ORDER BY s.submitted_at ASC,s.id ASC",tuple(params)).fetchall()]

def _topic_analytics(conn,user_id:int|None,exam_id:int|None=None):
    groups={}
    for session in _completed_attempts(conn,user_id,exam_id):
        try:snapshot=json.loads(session.get('question_set_json') or '[]')
        except (TypeError,json.JSONDecodeError):snapshot=[]
        answers={int(r['question_id']):dict(r) for r in conn.execute('SELECT question_id,is_correct,marks_awarded FROM exam_answers WHERE session_id=?',(session['id'],)).fetchall()}
        for item in snapshot:
            qid=int(item.get('id') or item.get('question_id') or 0);answer=answers.get(qid)
            if not answer or answer.get('is_correct') is None:continue
            taxonomy={key:str(item.get(key) or '').strip() for key in ('subject','chapter','topic','subtopic','difficulty','qtype')}
            row=conn.execute('SELECT subject,chapter,topic,subtopic,difficulty,qtype FROM questions WHERE id=?',(qid,)).fetchone()
            if row:taxonomy={key:(value or str(row[key] or '').strip()) for key,value in taxonomy.items()}
            key=(taxonomy['subject'] or 'General',taxonomy['chapter'] or 'General',taxonomy['topic'] or taxonomy['chapter'] or 'General',taxonomy['difficulty'] or 'Unspecified')
            group=groups.setdefault(key,{'subject':key[0],'chapter':key[1],'topic':key[2],'difficulty':key[3],'attempted_count':0,'correct_count':0,'marks_total':0.0})
            group['attempted_count']+=1;group['correct_count']+=int(bool(answer['is_correct']));group['marks_total']+=float(answer.get('marks_awarded') or 0)
    result=[]
    for group in groups.values():
        attempted=group.pop('attempted_count');marks=group.pop('marks_total')
        result.append({**group,'attempted_count':attempted,'accuracy_percentage':round(group['correct_count']/attempted*100,2),'average_marks_awarded':round(marks/attempted,2)})
    return sorted(result,key=lambda row:(-row['attempted_count'],row['accuracy_percentage'],row['subject'],row['topic']))

def _analytics_scope(conn,user,student_id:int|None,exam_id:int|None):
    selected_student=user['id'] if user['role']!='ADMIN' else student_id
    student=None;exam=None
    if selected_student is not None:
        row=conn.execute('SELECT id,email,display_name FROM users WHERE id=? AND role=?',(selected_student,'STUDENT')).fetchone()
        if not row:raise HTTPException(404,'Student not found')
        student=dict(row)
    if exam_id is not None:
        row=conn.execute('SELECT id,name,exam_type,subject,level FROM exams WHERE id=?',(exam_id,)).fetchone()
        if not row:raise HTTPException(404,'Examination not found')
        exam=dict(row)
    return selected_student,student,exam

@router.get('/my/analytics/dimensions')
def analytics_dimensions(request:Request):
    user=_student_analytics_user(request)
    with closing(db()) as conn:
        if user['role']=='ADMIN':
            students=[dict(r) for r in conn.execute("SELECT u.id,u.email,u.display_name,COUNT(s.id) attempt_count FROM users u LEFT JOIN exam_sessions s ON s.user_id=u.id AND s.status IN ('SUBMITTED','AUTO_SUBMITTED') WHERE u.role='STUDENT' GROUP BY u.id,u.email,u.display_name ORDER BY u.display_name,u.email").fetchall()]
            exams=[dict(r) for r in conn.execute("SELECT e.id,e.name,e.exam_type,e.subject,e.level,COUNT(s.id) attempt_count FROM exams e LEFT JOIN exam_sessions s ON s.exam_id=e.id AND s.status IN ('SUBMITTED','AUTO_SUBMITTED') GROUP BY e.id,e.name,e.exam_type,e.subject,e.level ORDER BY e.name").fetchall()]
        else:
            students=[]
            exams=[dict(r) for r in conn.execute("SELECT e.id,e.name,e.exam_type,e.subject,e.level,COUNT(s.id) attempt_count FROM exams e JOIN exam_enrollments er ON er.exam_id=e.id AND er.user_id=? LEFT JOIN exam_sessions s ON s.exam_id=e.id AND s.user_id=? AND s.status IN ('SUBMITTED','AUTO_SUBMITTED') GROUP BY e.id,e.name,e.exam_type,e.subject,e.level ORDER BY e.name",(user['id'],user['id'])).fetchall()]
    return {'scope':'platform' if user['role']=='ADMIN' else 'student','students':students,'exams':exams}

@router.get('/my/analytics/overview')
def analytics_overview(request:Request,student_id:int|None=None,exam_id:int|None=None):
    user=_student_analytics_user(request)
    with closing(db()) as conn:
        selected_student,student,exam=_analytics_scope(conn,user,student_id,exam_id);attempts=_completed_attempts(conn,selected_student,exam_id)
    percentages=[float(row.get('percentage') or 0) for row in attempts];correct=sum(int(row.get('correct_count') or 0) for row in attempts);incorrect=sum(int(row.get('incorrect_count') or 0) for row in attempts);unanswered=sum(int(row.get('unanswered_count') or 0) for row in attempts);total=correct+incorrect+unanswered
    previous=percentages[:-1]
    return {'scope':'platform' if user['role']=='ADMIN' else 'student','student':student,'exam':exam,'total_attempts':len(attempts),'average_percentage':round(sum(percentages)/len(percentages),2) if percentages else 0,'best_percentage':round(max(percentages),2) if percentages else 0,'worst_percentage':round(min(percentages),2) if percentages else 0,'total_questions_attempted':correct+incorrect,'overall_accuracy':round(correct/(correct+incorrect)*100,2) if correct+incorrect else 0,'average_unanswered_rate':round(unanswered/total*100,2) if total else 0,'recent_trend_delta':round(percentages[-1]-sum(previous)/len(previous),2) if previous else 0}

@router.get('/my/analytics/trend')
def analytics_trend(request:Request,student_id:int|None=None,exam_id:int|None=None):
    user=_student_analytics_user(request)
    fields=('submitted_at','exam_name','percentage','score','max_score','correct_count','incorrect_count','unanswered_count','attempt_number')
    with closing(db()) as conn:
        selected_student,_,_=_analytics_scope(conn,user,student_id,exam_id)
        return [{key:row.get(key) for key in fields} for row in _completed_attempts(conn,selected_student,exam_id)]

@router.get('/my/analytics/topics')
def analytics_topics(request:Request,student_id:int|None=None,exam_id:int|None=None):
    user=_student_analytics_user(request)
    with closing(db()) as conn:
        selected_student,_,_=_analytics_scope(conn,user,student_id,exam_id)
        return _topic_analytics(conn,selected_student,exam_id)

@router.get('/my/analytics/recommendations')
def analytics_recommendations(request:Request,student_id:int|None=None,exam_id:int|None=None):
    user=_student_analytics_user(request)
    with closing(db()) as conn:
        selected_student,_,_=_analytics_scope(conn,user,student_id,exam_id)
        topics=_topic_analytics(conn,selected_student,exam_id)
    weak=sorted((row for row in topics if row['attempted_count']>=3),key=lambda row:(row['accuracy_percentage'],-row['attempted_count']))[:5]
    plan=[{'title':f"Strengthen {row['topic']}",'focus':f"{row['subject']} · {row['chapter']} · {row['difficulty']}",'action':f"Review the core concept, then complete 10 targeted questions. Your current accuracy is {row['accuracy_percentage']:.0f}% across {row['attempted_count']} attempts."} for row in weak]
    if topics and not weak:plan=[{'title':'Build a reliable baseline','focus':'More evidence needed','action':'Complete at least three questions in each topic to unlock targeted recommendations.'}]
    return {'weak_topics':weak,'study_plan':plan}
@router.get('/my/results/{sid}')
def result_detail(sid:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        s=_session(conn,sid,user['id'])
        if s['status'] not in {'SUBMITTED','AUTO_SUBMITTED'}:raise HTTPException(409,'Result unavailable while exam is active')
        exam=conn.execute('SELECT id,name,exam_type,subject,level,status,result_release_mode FROM exams WHERE id=?',(s['exam_id'],)).fetchone();released=exam['result_release_mode']=='IMMEDIATE' or (exam['result_release_mode']=='AFTER_EXAM_CLOSE' and exam['status']=='CLOSED')
        student=conn.execute('SELECT id,email,display_name FROM users WHERE id=?',(user['id'],)).fetchone()
        snapshot=json.loads(s['question_set_json'] or '[]');answers={r['question_id']:dict(r) for r in conn.execute('SELECT question_id,selected_answer,is_correct,marks_awarded FROM exam_answers WHERE session_id=?',(sid,)).fetchall()}
        questions=[]
        if released:
            for q in snapshot:
                a=answers.get(q['id'],{});questions.append({'id':q['id'],'statement':q['statement'],'options':q['options'],'answer':q.get('answer',''),'solution':q.get('solution',''),'selected_answer':a.get('selected_answer',''),'is_correct':a.get('is_correct'),'marks_awarded':a.get('marks_awarded',0)})
    return {'session':{**dict(s),'exam_name':exam['name'],'exam_type':exam['exam_type'],'subject':exam['subject'],'level':exam['level'],'student_name':student['display_name'],'student_email':student['email']},'released':released,'message':None if released else 'Exam submitted. Result pending.','questions':questions}

@router.get('/student/results/{sid}/questions/{qid}/explain')
def explain_attempt_question(sid:int,qid:int,request:Request,language:str='en'):
    user=_auth(request)
    with closing(db()) as conn:
        session=conn.execute("SELECT * FROM exam_sessions WHERE id=? AND user_id=? AND status IN ('SUBMITTED','AUTO_SUBMITTED')",(sid,user['id'])).fetchone()
        if not session:raise HTTPException(404,'Completed attempt not found')
        snapshot=json.loads(session['question_set_json'] or '[]')
        if not any(int(q.get('id',0))==qid for q in snapshot):raise HTTPException(404,'Question not found in this attempt')
    from app import explain_question
    return explain_question(qid,language)

@router.get('/student/questions/{qid}/explain')
def explain_owned_attempt_question(qid:int,request:Request,language:str='en'):
    user=_auth(request)
    with closing(db()) as conn:
        rows=conn.execute("SELECT question_set_json FROM exam_sessions WHERE user_id=? AND status IN ('SUBMITTED','AUTO_SUBMITTED')",(user['id'],)).fetchall()
        found=any(any(int(q.get('id',0))==qid for q in json.loads(row['question_set_json'] or '[]')) for row in rows)
    if not found:raise HTTPException(404,'Question not found in your completed attempts')
    from app import explain_question
    return explain_question(qid,language)

@router.get('/admin/results')
def admin_results(request:Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        rows=conn.execute("SELECT s.*,e.name exam_name,e.exam_type,e.subject,e.level,u.email student_email,u.display_name student_name FROM exam_sessions s JOIN exams e ON e.id=s.exam_id JOIN users u ON u.id=s.user_id WHERE s.status IN ('SUBMITTED','AUTO_SUBMITTED') ORDER BY s.submitted_at DESC").fetchall()
    return [dict(r) for r in rows]

@router.get('/admin/results/{sid}')
def admin_result_detail(sid:int,request:Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        s=conn.execute("SELECT s.*,e.name exam_name,e.exam_type,e.subject,e.level,u.email student_email,u.display_name student_name FROM exam_sessions s JOIN exams e ON e.id=s.exam_id JOIN users u ON u.id=s.user_id WHERE s.id=?",(sid,)).fetchone()
        if not s:raise HTTPException(404,'Attempt not found')
        if s['status'] not in {'SUBMITTED','AUTO_SUBMITTED'}:raise HTTPException(409,'Result unavailable while exam is active')
        snapshot=json.loads(s['question_set_json'] or '[]')
        answers={r['question_id']:dict(r) for r in conn.execute('SELECT question_id,selected_answer,is_correct,marks_awarded FROM exam_answers WHERE session_id=?',(sid,)).fetchall()}
        questions=[]
        for q in snapshot:
            a=answers.get(q['id'],{});questions.append({'id':q['id'],'statement':q['statement'],'options':q['options'],'answer':q.get('answer',''),'solution':q.get('solution',''),'selected_answer':a.get('selected_answer',''),'is_correct':a.get('is_correct'),'marks_awarded':a.get('marks_awarded',0)})
    return {'session':dict(s),'questions':questions}

@router.get('/admin/users')
def admin_users(request:Request):
    require_admin(_auth(request))
    with closing(db()) as conn: rows=conn.execute('SELECT id,email,display_name,role,status,created_at,last_login_at FROM users ORDER BY created_at DESC').fetchall()
    return [dict(r) for r in rows]

@router.put('/admin/users/{user_id}/role')
async def set_user_role(user_id:int,request:Request):
    admin=require_admin(_auth(request,True));data=await request.json();role=str(data.get('role','')).upper()
    if role not in {'ADMIN','PROCTOR','STUDENT'}:raise HTTPException(400,'Invalid role')
    if user_id==admin['id']:raise HTTPException(409,'Administrators cannot change their own role')
    with closing(db()) as conn:cur=conn.execute('UPDATE users SET role=?,updated_at=? WHERE id=?',(role,time.time(),user_id));conn.commit()
    if not cur.rowcount:raise HTTPException(404,'User not found')
    return {'id':user_id,'role':role}

@router.get('/dashboard')
def dashboard(request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        if user['role']=='ADMIN':
            return {'questions':conn.execute('SELECT COUNT(*) n FROM questions').fetchone()['n'],'published_exams':conn.execute("SELECT COUNT(*) n FROM exams WHERE status='PUBLISHED'").fetchone()['n'],'students':conn.execute("SELECT COUNT(*) n FROM users WHERE role='STUDENT'").fetchone()['n'],'active_sessions':conn.execute("SELECT COUNT(*) n FROM exam_sessions WHERE status='IN_PROGRESS'").fetchone()['n'],'completed_attempts':conn.execute("SELECT COUNT(*) n FROM exam_sessions WHERE status IN ('SUBMITTED','AUTO_SUBMITTED')").fetchone()['n']}
        return {'available_exams':conn.execute("SELECT COUNT(*) n FROM exams WHERE status='OPEN'").fetchone()['n'],'enrolled_exams':conn.execute("SELECT COUNT(*) n FROM exam_enrollments r JOIN exams e ON e.id=r.exam_id WHERE r.user_id=? AND e.status='OPEN'",(user['id'],)).fetchone()['n'],'completed_exams':conn.execute("SELECT COUNT(*) n FROM exam_sessions WHERE user_id=? AND status IN ('SUBMITTED','AUTO_SUBMITTED')",(user['id'],)).fetchone()['n']}
