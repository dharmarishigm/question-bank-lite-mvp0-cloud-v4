"""Authenticated examination platform layered on the existing question bank."""
from __future__ import annotations

import hashlib, json, os, re, secrets, sqlite3, time
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

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

def _hash(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()
def _admins(): return {x.strip().lower() for x in os.getenv('ADMIN_EMAILS','').split(',') if x.strip()}
def _public_user(row):
    return {k: row[k] for k in ('id','email','display_name','given_name','family_name','profile_picture','role','status')}

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
    sub, email = str(identity.get('sub','')), str(identity.get('email','')).lower()
    if not sub or not email or not identity.get('email_verified'): raise HTTPException(401,'Verified Google identity required')
    now=time.time(); role='ADMIN' if email in _admins() else 'STUDENT'
    with closing(db()) as conn:
        row=conn.execute('SELECT * FROM users WHERE google_sub=?',(sub,)).fetchone()
        if not row:
            bootstrap=conn.execute("SELECT * FROM users WHERE lower(email)=? AND google_sub LIKE 'bootstrap:%'",(email,)).fetchone()
            if bootstrap:
                conn.execute('UPDATE users SET google_sub=? WHERE id=?',(sub,bootstrap['id']))
                row=conn.execute('SELECT * FROM users WHERE id=?',(bootstrap['id'],)).fetchone()
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
    return {'client_id':os.getenv('GOOGLE_CLIENT_ID',''),'mock':os.getenv('AUTH_MODE')=='mock' and os.getenv('APP_ENV') in {'test','development'},'bootstrap_available':_bootstrap_available(request),'local_admin':bool(local_email and os.getenv('ADMIN_LOCAL_PASSWORD')),'local_admin_email':local_email}
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
        pending=conn.execute("SELECT * FROM pending_exam_registrations WHERE lower(registered_email)=? AND status='PENDING' ORDER BY id DESC",(email,)).fetchall()
        match=next((r for r in pending if r['date_of_birth']==dob and re.sub(r'\D','',r['phone_number'])==phone),None)
        if not match:raise HTTPException(401,'Registration details do not match. Use the email, date of birth and phone entered during registration.')
        user=conn.execute("SELECT * FROM users WHERE lower(email)=?",(email,)).fetchone()
        if user and user['role']!='STUDENT':raise HTTPException(403,'This email belongs to a staff account')
        if not user:
            cur=conn.execute("INSERT INTO users(google_sub,email,email_verified,display_name,role,status,created_at,updated_at,last_login_at,date_of_birth,phone_number,school_name,profile_completed) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",(f"registration:{secrets.token_urlsafe(18)}",email,0,match['full_name'],'STUDENT','ACTIVE',now,now,now,match['date_of_birth'],match['phone_number'],match['school_name']));uid=cur.lastrowid
        else:
            uid=user['id'];conn.execute("UPDATE users SET display_name=?,date_of_birth=?,phone_number=?,school_name=?,profile_completed=1,last_login_at=?,updated_at=? WHERE id=?",(match['full_name'],match['date_of_birth'],match['phone_number'],match['school_name'],now,now,uid))
        for registration in pending:
            if registration['date_of_birth']==dob and re.sub(r'\D','',registration['phone_number'])==phone:
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

def _exam(row, count=0):
    return {**dict(row),'question_count':count}

@router.get('/exams')
def exams(request:Request):
    user=_auth(request); where='' if user['role'] in {'ADMIN','PROCTOR'} else " WHERE e.status IN ('PUBLISHED','OPEN')"
    with closing(db()) as conn: rows=conn.execute(f'SELECT e.*,COUNT(eq.id) question_count FROM exams e LEFT JOIN exam_questions eq ON eq.exam_id=e.id{where} GROUP BY e.id ORDER BY e.created_at DESC').fetchall()
    return [_exam(r,r['question_count']) for r in rows]
@router.get('/exams/{exam_id}')
def exam_detail(exam_id:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        row=conn.execute('SELECT e.*,COUNT(eq.id) question_count FROM exams e LEFT JOIN exam_questions eq ON eq.exam_id=e.id WHERE e.id=? GROUP BY e.id',(exam_id,)).fetchone()
    if not row or (user['role'] not in {'ADMIN','PROCTOR'} and row['status'] not in {'PUBLISHED','OPEN'}): raise HTTPException(404,'Exam not found')
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
        conn.execute('DELETE FROM exam_questions WHERE exam_id=?',(exam_id,));cur=conn.execute('DELETE FROM exams WHERE id=?',(exam_id,));conn.commit()
    if not cur.rowcount:raise HTTPException(404,'Exam not found')
    return {'deleted':exam_id}
@router.post('/exams/{exam_id}/enroll')
def enroll(exam_id:int,request:Request):
    user=_auth(request,True);now=time.time()
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
    with closing(db()) as conn: rows=conn.execute('SELECT e.*,r.id registration_id,r.registered_at,r.status registration_status,(SELECT COUNT(*) FROM exam_sessions s WHERE s.exam_id=e.id AND s.user_id=?) attempts_used,(SELECT id FROM exam_sessions s WHERE s.exam_id=e.id AND s.user_id=? ORDER BY attempt_number DESC LIMIT 1) latest_session_id,(SELECT status FROM exam_sessions s WHERE s.exam_id=e.id AND s.user_id=? ORDER BY attempt_number DESC LIMIT 1) latest_session_status FROM exam_enrollments r JOIN exams e ON e.id=r.exam_id WHERE r.user_id=? ORDER BY r.registered_at DESC',(user['id'],user['id'],user['id'],user['id'])).fetchall()
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
    if s['attempt_number']>=conn.execute('SELECT max_attempts FROM exams WHERE id=?',(s['exam_id'],)).fetchone()['max_attempts']:conn.execute("UPDATE exam_enrollments SET status='COMPLETED',updated_at=? WHERE id=?",(now,s['registration_id']))
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
        if attempt>exam['max_attempts']:raise HTTPException(409,'Attempt limit reached')
        cur=conn.execute("INSERT INTO exam_sessions(exam_id,user_id,registration_id,attempt_number,status,started_at,expires_at,duration_minutes,created_at,updated_at) VALUES(?,?,?,?,'IN_PROGRESS',?,?,?,?,?)",(exam_id,user['id'],reg['id'],attempt,now,now+exam['duration_minutes']*60,exam['duration_minutes'],now,now));conn.commit();return {'session_id':cur.lastrowid,'resumed':False}
@router.get('/sessions/{sid}')
def get_session(sid:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        s=_session(conn,sid,user['id']); exam=conn.execute('SELECT name,instructions FROM exams WHERE id=?',(s['exam_id'],)).fetchone()
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
def submit(sid:int,request:Request):
    user=_auth(request,True)
    with closing(db()) as conn:
        s=_session(conn,sid,user['id'])
        if s['status']!='IN_PROGRESS':return {'submitted':True,'already_submitted':True,'status':s['status']}
        _submit(conn,s)
        from exam_conduct import audit
        audit(conn,'EXAM_SUBMITTED',exam_id=s['exam_id'],user_id=user['id'],session_id=sid);conn.commit()
    return {'submitted':True}
@router.get('/my/results')
def results(request:Request):
    user=_auth(request)
    with closing(db()) as conn:rows=conn.execute("SELECT s.*,e.name exam_name FROM exam_sessions s JOIN exams e ON e.id=s.exam_id WHERE s.user_id=? AND s.status IN ('SUBMITTED','AUTO_SUBMITTED') ORDER BY s.submitted_at DESC",(user['id'],)).fetchall()
    return [dict(r) for r in rows]
@router.get('/my/results/{sid}')
def result_detail(sid:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        s=_session(conn,sid,user['id'])
        if s['status'] not in {'SUBMITTED','AUTO_SUBMITTED'}:raise HTTPException(409,'Result unavailable while exam is active')
        exam=conn.execute('SELECT status,result_release_mode FROM exams WHERE id=?',(s['exam_id'],)).fetchone();released=exam['result_release_mode']=='IMMEDIATE' or (exam['result_release_mode']=='AFTER_EXAM_CLOSE' and exam['status']=='CLOSED')
        snapshot=json.loads(s['question_set_json'] or '[]');answers={r['question_id']:dict(r) for r in conn.execute('SELECT question_id,selected_answer,is_correct,marks_awarded FROM exam_answers WHERE session_id=?',(sid,)).fetchall()}
        questions=[]
        if released:
            for q in snapshot:
                a=answers.get(q['id'],{});questions.append({'statement':q['statement'],'options':q['options'],'answer':q.get('answer',''),'solution':q.get('solution',''),'selected_answer':a.get('selected_answer',''),'is_correct':a.get('is_correct'),'marks_awarded':a.get('marks_awarded',0)})
    return {'session':dict(s),'released':released,'message':None if released else 'Exam submitted. Result pending.','questions':questions}

@router.get('/admin/results')
def admin_results(request:Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        rows=conn.execute("SELECT s.*,e.name exam_name,u.email student_email,u.display_name student_name FROM exam_sessions s JOIN exams e ON e.id=s.exam_id JOIN users u ON u.id=s.user_id ORDER BY s.created_at DESC").fetchall()
    return [dict(r) for r in rows]

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
        return {'available_exams':conn.execute("SELECT COUNT(*) n FROM exams WHERE status='PUBLISHED'").fetchone()['n'],'enrolled_exams':conn.execute('SELECT COUNT(*) n FROM exam_enrollments WHERE user_id=?',(user['id'],)).fetchone()['n'],'completed_exams':conn.execute("SELECT COUNT(*) n FROM exam_sessions WHERE user_id=? AND status IN ('SUBMITTED','AUTO_SUBMITTED')",(user['id'],)).fetchone()['n']}
