"""Secure exam eligibility, proctor access, snapshots and monitoring."""
from __future__ import annotations
import hashlib,json,re,secrets,sqlite3,string,time
from contextlib import closing
from fastapi import APIRouter,HTTPException,Request

router=APIRouter(prefix="/api")

SCHEMA="""
CREATE TABLE IF NOT EXISTS exam_proctor_codes(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id INTEGER NOT NULL,code_hash TEXT NOT NULL,code_prefix TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ACTIVE',mode TEXT NOT NULL DEFAULT 'EXAM_SHARED',valid_from REAL NOT NULL,valid_until REAL NOT NULL,max_uses INTEGER,usage_count INTEGER NOT NULL DEFAULT 0,created_by INTEGER NOT NULL,created_at REAL NOT NULL,revoked_at REAL,notes TEXT NOT NULL DEFAULT '',FOREIGN KEY(exam_id) REFERENCES exams(id));
CREATE INDEX IF NOT EXISTS idx_proctor_codes_exam_status ON exam_proctor_codes(exam_id,status);
CREATE TABLE IF NOT EXISTS pending_exam_registrations(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id INTEGER NOT NULL,registered_email TEXT NOT NULL COLLATE NOCASE,status TEXT NOT NULL DEFAULT 'PENDING',registration_source TEXT NOT NULL DEFAULT 'ADMIN',created_by INTEGER NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL,UNIQUE(exam_id,registered_email),FOREIGN KEY(exam_id) REFERENCES exams(id));
CREATE TABLE IF NOT EXISTS exam_audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id INTEGER,user_id INTEGER,session_id INTEGER,event_type TEXT NOT NULL,metadata_json TEXT NOT NULL DEFAULT '{}',created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_exam_audit_exam ON exam_audit_log(exam_id,created_at);
CREATE TABLE IF NOT EXISTS proctor_code_failures(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id INTEGER NOT NULL,user_id INTEGER NOT NULL,failed_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_code_failures_user_exam ON proctor_code_failures(user_id,exam_id,failed_at);
CREATE TABLE IF NOT EXISTS exam_versions(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id INTEGER NOT NULL,version_number INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'PUBLISHED',configuration_json TEXT NOT NULL,question_snapshot_json TEXT NOT NULL,published_at REAL NOT NULL,published_by INTEGER NOT NULL,created_at REAL NOT NULL,UNIQUE(exam_id,version_number),FOREIGN KEY(exam_id) REFERENCES exams(id));
CREATE INDEX IF NOT EXISTS idx_exam_versions_current ON exam_versions(exam_id,status,version_number);
CREATE TABLE IF NOT EXISTS exam_registration_links(id INTEGER PRIMARY KEY AUTOINCREMENT,exam_id INTEGER NOT NULL,token_hash TEXT NOT NULL UNIQUE,status TEXT NOT NULL DEFAULT 'ACTIVE',valid_from REAL NOT NULL,valid_until REAL,max_registrations INTEGER,registration_count INTEGER NOT NULL DEFAULT 0,created_by INTEGER NOT NULL,created_at REAL NOT NULL,revoked_at REAL,FOREIGN KEY(exam_id) REFERENCES exams(id));
CREATE INDEX IF NOT EXISTS idx_registration_links_exam ON exam_registration_links(exam_id,status);
"""
EXAM_COLUMNS={"proctor_required":"INTEGER NOT NULL DEFAULT 0","result_release_mode":"TEXT NOT NULL DEFAULT 'IMMEDIATE'","negative_marking_enabled":"INTEGER NOT NULL DEFAULT 0","assigned_proctor_id":"INTEGER","allow_retake":"INTEGER NOT NULL DEFAULT 0","allow_self_registration":"INTEGER NOT NULL DEFAULT 1","allow_registration_link":"INTEGER NOT NULL DEFAULT 1","current_version_id":"INTEGER"}
USER_COLUMNS={"date_of_birth":"TEXT NOT NULL DEFAULT ''","phone_number":"TEXT NOT NULL DEFAULT ''","school_name":"TEXT NOT NULL DEFAULT ''","profile_completed":"INTEGER NOT NULL DEFAULT 0"}
ENROLL_COLUMNS={"registered_email":"TEXT NOT NULL DEFAULT ''","registration_source":"TEXT NOT NULL DEFAULT 'SELF'","created_by":"INTEGER","full_name_snapshot":"TEXT NOT NULL DEFAULT ''","registration_link_id":"INTEGER"}
SESSION_COLUMNS={"question_set_json":"TEXT NOT NULL DEFAULT '[]'","proctor_code_id":"INTEGER","auto_submitted_at":"REAL","exam_version_id":"INTEGER"}
ANSWER_COLUMNS={"status":"TEXT NOT NULL DEFAULT 'NOT_VISITED'","first_answered_at":"REAL","scored_at":"REAL"}
PENDING_COLUMNS={"full_name":"TEXT NOT NULL DEFAULT ''","date_of_birth":"TEXT NOT NULL DEFAULT ''","phone_number":"TEXT NOT NULL DEFAULT ''","school_name":"TEXT NOT NULL DEFAULT ''","registration_link_id":"INTEGER"}

def db():
    from app import connect
    return connect()
def init_exam_conduct():
    with closing(db()) as conn:
        conn.executescript(SCHEMA)
        for table,items in (("exams",EXAM_COLUMNS),("users",USER_COLUMNS),("exam_enrollments",ENROLL_COLUMNS),("pending_exam_registrations",PENDING_COLUMNS),("exam_sessions",SESSION_COLUMNS),("exam_answers",ANSWER_COLUMNS)):
            columns={r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name,ddl in items.items():
                if name not in columns:conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        conn.commit()

def audit(conn,event,*,exam_id=None,user_id=None,session_id=None,metadata=None):conn.execute("INSERT INTO exam_audit_log(exam_id,user_id,session_id,event_type,metadata_json,created_at) VALUES(?,?,?,?,?,?)",(exam_id,user_id,session_id,event,json.dumps(metadata or {}),time.time()))
def staff(user):
    if user["role"] not in {"ADMIN","PROCTOR"}:raise HTTPException(403,"Staff access required")
    return user
def _code_hash(exam_id,code):return hashlib.sha256(f"{exam_id}:{''.join(str(code).upper().split())}".encode()).hexdigest()
def _snapshot(conn,exam_id):
    rows=conn.execute("SELECT q.id,q.statement,q.options,q.answer,q.solution,q.qtype,eq.display_order,eq.section_name,eq.marks,eq.negative_marks FROM exam_questions eq JOIN questions q ON q.id=eq.question_id WHERE eq.exam_id=? ORDER BY eq.display_order",(exam_id,)).fetchall()
    return [dict(r)|{"options":json.loads(r["options"] or "[]")} for r in rows]
def publish_version(conn,exam_id,user_id):
    exam=conn.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone(); snapshot=_snapshot(conn,exam_id)
    if not exam or not snapshot:raise HTTPException(409,"Exam needs at least one valid question before publishing")
    version=conn.execute("SELECT COALESCE(MAX(version_number),0)+1 n FROM exam_versions WHERE exam_id=?",(exam_id,)).fetchone()["n"];now=time.time()
    config={k:exam[k] for k in exam.keys() if k not in {"current_version_id"}}
    cur=conn.execute("INSERT INTO exam_versions(exam_id,version_number,status,configuration_json,question_snapshot_json,published_at,published_by,created_at) VALUES(?,?,'PUBLISHED',?,?,?,?,?)",(exam_id,version,json.dumps(config),json.dumps(snapshot),now,user_id,now))
    conn.execute("UPDATE exams SET current_version_id=? WHERE id=?",(cur.lastrowid,exam_id));return cur.lastrowid
def _active_code(conn,exam_id,code,now):
    value=_code_hash(exam_id,code)
    return conn.execute("SELECT * FROM exam_proctor_codes WHERE exam_id=? AND code_hash=? AND status='ACTIVE' AND valid_from<=? AND valid_until>=? AND (max_uses IS NULL OR usage_count<max_uses)",(exam_id,value,now,now)).fetchone()

def evaluate_exam_start_eligibility(conn,user,exam_id,code=""):
    now=time.time();exam=conn.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone()
    if not exam:return {"eligible":False,"reason_code":"EXAM_NOT_FOUND","message":"Exam not found"}
    if user["status"]!="ACTIVE":return {"eligible":False,"reason_code":"ACCOUNT_DISABLED","message":"Account is not active"}
    reg=conn.execute("SELECT * FROM exam_enrollments WHERE exam_id=? AND user_id=?",(exam_id,user["id"])).fetchone()
    if not reg:return {"eligible":False,"reason_code":"NOT_REGISTERED","message":"Registration is required"}
    if reg["status"]=="BLOCKED":return {"eligible":False,"reason_code":"REGISTRATION_BLOCKED","message":"Registration is blocked"}
    if reg["status"] not in {"ENROLLED","COMPLETED"}:return {"eligible":False,"reason_code":"REGISTRATION_NOT_ACTIVE","message":"Registration is not active"}
    active=conn.execute("SELECT id,expires_at FROM exam_sessions WHERE exam_id=? AND user_id=? AND status='IN_PROGRESS' ORDER BY id DESC LIMIT 1",(exam_id,user["id"])).fetchone()
    if active and active["expires_at"]>now:return {"eligible":True,"reason_code":"ACTIVE_SESSION_EXISTS","message":"Resume active examination","existing_session_id":active["id"],"exam":exam,"registration":reg,"code":None}
    if exam["status"]!="OPEN":return {"eligible":False,"reason_code":"EXAM_NOT_OPEN","message":"Exam is not open"}
    if exam["exam_start_at"] and now<exam["exam_start_at"]:return {"eligible":False,"reason_code":"EXAM_NOT_STARTED","message":"Exam has not started"}
    if exam["exam_end_at"] and now>exam["exam_end_at"]:return {"eligible":False,"reason_code":"EXAM_CLOSED","message":"Exam is closed"}
    attempts=conn.execute("SELECT COUNT(*) n FROM exam_sessions WHERE exam_id=? AND user_id=?",(exam_id,user["id"])).fetchone()["n"]
    if attempts and not exam["allow_retake"]:return {"eligible":False,"reason_code":"RETAKE_DISABLED","message":"Retakes are not enabled for this exam"}
    if attempts>=exam["max_attempts"]:return {"eligible":False,"reason_code":"ATTEMPT_LIMIT_REACHED","message":"Attempt limit reached"}
    code_row=None
    if exam["proctor_required"]:
        recent=conn.execute("SELECT COUNT(*) n FROM proctor_code_failures WHERE exam_id=? AND user_id=? AND failed_at>?",(exam_id,user["id"],now-300)).fetchone()["n"]
        if recent>=5:return {"eligible":False,"reason_code":"PROCTOR_RATE_LIMITED","message":"Invalid or expired proctor code."}
        if not code:return {"eligible":False,"reason_code":"PROCTOR_CODE_REQUIRED","message":"Proctor code is required"}
        code_row=_active_code(conn,exam_id,code,now)
        if not code_row:
            conn.execute("INSERT INTO proctor_code_failures(exam_id,user_id,failed_at) VALUES(?,?,?)",(exam_id,user["id"],now))
            return {"eligible":False,"reason_code":"INVALID_PROCTOR_CODE","message":"Invalid or expired proctor code."}
    return {"eligible":True,"reason_code":"OK","message":"Eligible to start exam","existing_session_id":None,"exam":exam,"registration":reg,"code":code_row,"attempt":attempts+1}

@router.post("/student/exams/{exam_id}/start")
async def start(exam_id:int,request:Request):
    from platform_api import _auth
    user=_auth(request,True);body=await request.json();now=time.time()
    with closing(db()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE");result=evaluate_exam_start_eligibility(conn,user,exam_id,str(body.get("proctor_code","")))
            if not result["eligible"]:
                audit(conn,"START_DENIED",exam_id=exam_id,user_id=user["id"],metadata={"reason":result["reason_code"]});conn.commit();raise HTTPException(403,detail={"reason_code":result["reason_code"],"message":result["message"]})
            if result.get("existing_session_id"):
                audit(conn,"SESSION_RESUMED",exam_id=exam_id,user_id=user["id"],session_id=result["existing_session_id"]);conn.commit();return {"session_id":result["existing_session_id"],"resumed":True}
            exam,reg=result["exam"],result["registration"]
            version=conn.execute("SELECT * FROM exam_versions WHERE id=? AND exam_id=?",(exam["current_version_id"],exam_id)).fetchone() if exam["current_version_id"] else None
            if not version:raise HTTPException(409,"Exam has no published version")
            snapshot=json.loads(version["question_snapshot_json"])
            if not snapshot:raise HTTPException(409,"Exam has no questions")
            cur=conn.execute("INSERT INTO exam_sessions(exam_id,user_id,registration_id,attempt_number,status,started_at,expires_at,duration_minutes,question_set_json,proctor_code_id,exam_version_id,created_at,updated_at) VALUES(?,?,?,?,'IN_PROGRESS',?,?,?,?,?,?,?,?)",(exam_id,user["id"],reg["id"],result["attempt"],now,now+exam["duration_minutes"]*60,exam["duration_minutes"],json.dumps(snapshot),result["code"]["id"] if result["code"] else None,version["id"],now,now));sid=cur.lastrowid
            if result["code"]:conn.execute("UPDATE exam_proctor_codes SET usage_count=usage_count+1 WHERE id=?",(result["code"]["id"],))
            audit(conn,"START_ATTEMPT",exam_id=exam_id,user_id=user["id"],session_id=sid);conn.commit();return {"session_id":sid,"resumed":False}
        except HTTPException:conn.rollback();raise
        except sqlite3.IntegrityError:conn.rollback();active=conn.execute("SELECT id FROM exam_sessions WHERE exam_id=? AND user_id=? AND status='IN_PROGRESS' ORDER BY id DESC LIMIT 1",(exam_id,user["id"])).fetchone();
        if active:return {"session_id":active["id"],"resumed":True}
        raise HTTPException(409,"Could not start examination")

@router.post("/admin/exams/{exam_id}/proctor-codes")
async def generate_code(exam_id:int,request:Request):
    from platform_api import _auth
    user=staff(_auth(request,True));body=await request.json();now=time.time();minutes=max(1,min(1440,int(body.get("valid_minutes",60))));alphabet="23456789ABCDEFGHJKLMNPQRSTUVWXYZ";code="".join(secrets.choice(alphabet) for _ in range(6))
    with closing(db()) as conn:
        if not conn.execute("SELECT 1 FROM exams WHERE id=?",(exam_id,)).fetchone():raise HTTPException(404,"Exam not found")
        conn.execute("UPDATE exam_proctor_codes SET status='REVOKED',revoked_at=? WHERE exam_id=? AND status='ACTIVE'",(now,exam_id));cur=conn.execute("INSERT INTO exam_proctor_codes(exam_id,code_hash,code_prefix,status,valid_from,valid_until,max_uses,created_by,created_at,notes) VALUES(?,?,?,'ACTIVE',?,?,?,?,?,?)",(exam_id,_code_hash(exam_id,code),code[:2],float(body.get("valid_from") or now),float(body.get("valid_until") or now+minutes*60),body.get("max_uses"),user["id"],now,str(body.get("notes",""))));audit(conn,"PROCTOR_CODE_GENERATED",exam_id=exam_id,user_id=user["id"],metadata={"code_id":cur.lastrowid});conn.commit()
    return {"id":cur.lastrowid,"code":code,"valid_until":float(body.get("valid_until") or now+minutes*60)}

@router.post("/admin/exams/{exam_id}/proctor-codes/{code_id}/revoke")
def revoke_code(exam_id:int,code_id:int,request:Request):
    from platform_api import _auth
    user=staff(_auth(request,True));now=time.time()
    with closing(db()) as conn:cur=conn.execute("UPDATE exam_proctor_codes SET status='REVOKED',revoked_at=? WHERE id=? AND exam_id=? AND status='ACTIVE'",(now,code_id,exam_id));audit(conn,"PROCTOR_CODE_REVOKED",exam_id=exam_id,user_id=user["id"],metadata={"code_id":code_id});conn.commit()
    if not cur.rowcount:raise HTTPException(404,"Active code not found")
    return {"revoked":True}

@router.get("/admin/exams/{exam_id}/access")
def access(exam_id:int,request:Request):
    from platform_api import _auth
    staff(_auth(request))
    with closing(db()) as conn:exam=conn.execute("SELECT proctor_required,exam_start_at,exam_end_at,status FROM exams WHERE id=?",(exam_id,)).fetchone();code=conn.execute("SELECT id,code_prefix,status,valid_from,valid_until,max_uses,usage_count,created_at,revoked_at FROM exam_proctor_codes WHERE exam_id=? ORDER BY id DESC LIMIT 1",(exam_id,)).fetchone()
    if not exam:raise HTTPException(404,"Exam not found")
    return {"exam":dict(exam),"code":dict(code) if code else None}

@router.put("/admin/exams/{exam_id}/state")
async def exam_state(exam_id:int,request:Request):
    from platform_api import _auth
    user=staff(_auth(request,True));body=await request.json();status=str(body.get("status","")).upper()
    if status not in {"PUBLISHED","OPEN","CLOSED"}:raise HTTPException(400,"Invalid exam state")
    with closing(db()) as conn:
        exam=conn.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone();questions=conn.execute("SELECT COUNT(*) n FROM exam_questions WHERE exam_id=? AND marks>0",(exam_id,)).fetchone()["n"]
        if not exam:raise HTTPException(404,"Exam not found")
        if status in {"PUBLISHED","OPEN"} and (not questions or exam["duration_minutes"]<=0):raise HTTPException(409,"Exam needs questions with marks and a valid duration")
        if status=="OPEN" and exam["proctor_required"] and not conn.execute("SELECT 1 FROM exam_proctor_codes WHERE exam_id=? AND status='ACTIVE' AND valid_until>?",(exam_id,time.time())).fetchone():raise HTTPException(409,"Generate an active proctor code before opening this exam")
        version_id=exam["current_version_id"]
        if status=="PUBLISHED":version_id=publish_version(conn,exam_id,user["id"])
        if status=="OPEN" and not version_id:version_id=publish_version(conn,exam_id,user["id"])
        now=time.time()
        if status=="OPEN":
            conn.execute("UPDATE exams SET status='OPEN',exam_start_at=CASE WHEN exam_start_at IS NULL OR exam_start_at>? THEN ? ELSE exam_start_at END,updated_at=? WHERE id=?",(now,now,now,exam_id))
        else:conn.execute("UPDATE exams SET status=?,updated_at=? WHERE id=?",(status,now,exam_id))
        audit(conn,"EXAM_STARTED" if status=="OPEN" else "EXAM_CLOSED" if status=="CLOSED" else "EXAM_PUBLISHED",exam_id=exam_id,user_id=user["id"],metadata={"version_id":version_id});conn.commit()
    return {"id":exam_id,"status":status,"version_id":version_id}

@router.put("/admin/exams/{exam_id}/retake")
async def configure_retake(exam_id:int,request:Request):
    from platform_api import _auth
    user=_auth(request,True)
    if user["role"]!="ADMIN":raise HTTPException(403,"Administrator access required")
    body=await request.json();allowed=bool(body.get("allow_retake"));maximum=max(1,min(20,int(body.get("max_attempts",2 if allowed else 1))))
    if not allowed:maximum=1
    with closing(db()) as conn:cur=conn.execute("UPDATE exams SET allow_retake=?,max_attempts=?,updated_at=? WHERE id=?",(int(allowed),maximum,time.time(),exam_id));audit(conn,"RETAKE_CONFIGURATION_CHANGED",exam_id=exam_id,user_id=user["id"],metadata={"allow_retake":allowed,"max_attempts":maximum});conn.commit()
    if not cur.rowcount:raise HTTPException(404,"Exam not found")
    return {"id":exam_id,"allow_retake":allowed,"max_attempts":maximum}

@router.post("/admin/exams/{exam_id}/questions/from-bank")
async def add_questions_from_bank(exam_id:int,request:Request):
    from platform_api import _auth
    user=_auth(request,True)
    if user["role"]!="ADMIN":raise HTTPException(403,"Administrator access required")
    body=await request.json();limit=max(1,min(100,int(body.get("count",15))));now=time.time()
    with closing(db()) as conn:
        exam=conn.execute("SELECT * FROM exams WHERE id=?",(exam_id,)).fetchone()
        if not exam:raise HTTPException(404,"Exam not found")
        subject=str(exam["subject"] or "").strip()
        rows=conn.execute("""SELECT q.id,q.marks FROM questions q LEFT JOIN
          (SELECT question_id,COUNT(*) uses FROM exam_questions GROUP BY question_id) u ON u.question_id=q.id
          WHERE q.statement<>'' AND (?='' OR lower(q.subject)=lower(?))
          AND q.id NOT IN (SELECT question_id FROM exam_questions WHERE exam_id=?)
          ORDER BY CASE lower(q.verification_status) WHEN 'approved' THEN 0 WHEN 'ai_validated' THEN 1 ELSE 2 END,
          q.confidence DESC,COALESCE(u.uses,0),q.id LIMIT ?""",(subject,subject,exam_id,limit)).fetchall()
        start=conn.execute("SELECT COALESCE(MAX(display_order),0) n FROM exam_questions WHERE exam_id=?",(exam_id,)).fetchone()["n"]
        for offset,row in enumerate(rows,1):
            try:marks=float(row["marks"] or 1)
            except (TypeError,ValueError):marks=1
            conn.execute("INSERT OR IGNORE INTO exam_questions(exam_id,question_id,display_order,marks,negative_marks,created_at) VALUES(?,?,?,?,?,?)",(exam_id,row["id"],start+offset,max(.01,marks),float(exam["negative_marking"] or 0),now))
        conn.execute("UPDATE exams SET total_marks=(SELECT COALESCE(SUM(marks),0) FROM exam_questions WHERE exam_id=?),updated_at=? WHERE id=?",(exam_id,now,exam_id));audit(conn,"EXAM_QUESTIONS_ADDED",exam_id=exam_id,user_id=user["id"],metadata={"count":len(rows)});conn.commit()
    if not rows:raise HTTPException(409,"No additional Question Bank questions are available")
    return {"exam_id":exam_id,"added":len(rows)}

@router.get("/admin/exams/{exam_id}/paper")
def durable_exam_paper(exam_id:int,request:Request):
    from platform_api import _auth
    staff(_auth(request))
    with closing(db()) as conn:
        exam=conn.execute("SELECT id,name,subject,status,duration_minutes,total_marks FROM exams WHERE id=?",(exam_id,)).fetchone()
        if not exam:raise HTTPException(404,"Exam not found")
        rows=conn.execute("SELECT q.id,q.subject,q.chapter,q.topic,q.statement,q.options,q.answer,q.solution,q.difficulty,q.qtype,eq.display_order,eq.section_name,eq.marks,eq.negative_marks FROM exam_questions eq JOIN questions q ON q.id=eq.question_id WHERE eq.exam_id=? ORDER BY eq.display_order",(exam_id,)).fetchall()
    return {"exam":dict(exam),"questions":[dict(row)|{"options":json.loads(row["options"] or "[]")} for row in rows]}

@router.post("/admin/exams/{exam_id}/registrations")
async def preregister(exam_id:int,request:Request):
    from platform_api import _auth
    admin=_auth(request,True)
    if admin["role"]!="ADMIN":raise HTTPException(403,"Administrator access required")
    body=await request.json();email=str(body.get("email","")).strip().lower()
    if "@" not in email:raise HTTPException(422,"Valid email required")
    now=time.time()
    with closing(db()) as conn:
        user=conn.execute("SELECT * FROM users WHERE lower(email)=? AND email_verified=1",(email,)).fetchone()
        if user:conn.execute("INSERT INTO exam_enrollments(exam_id,user_id,status,registered_at,created_at,updated_at,registered_email,registration_source,created_by) VALUES(?,?,'ENROLLED',?,?,?,?, 'ADMIN',?) ON CONFLICT(exam_id,user_id) DO UPDATE SET status='ENROLLED',updated_at=excluded.updated_at",(exam_id,user["id"],now,now,now,email,admin["id"]))
        else:conn.execute("INSERT INTO pending_exam_registrations(exam_id,registered_email,status,registration_source,created_by,created_at,updated_at) VALUES(?,?,'PENDING','ADMIN',?,?,?) ON CONFLICT(exam_id,registered_email) DO UPDATE SET status='PENDING',updated_at=excluded.updated_at",(exam_id,email,admin["id"],now,now))
        conn.commit()
    return {"email":email,"status":"ENROLLED" if user else "PENDING"}

@router.get("/admin/exams/{exam_id}/registrations")
def registrations(exam_id:int,request:Request):
    from platform_api import _auth
    staff(_auth(request))
    with closing(db()) as conn:
        linked=[dict(r) for r in conn.execute("SELECT r.*,u.email,u.display_name,(SELECT COUNT(*) FROM exam_sessions s WHERE s.registration_id=r.id) attempts_used FROM exam_enrollments r JOIN users u ON u.id=r.user_id WHERE r.exam_id=?",(exam_id,)).fetchall()];pending=[dict(r) for r in conn.execute("SELECT * FROM pending_exam_registrations WHERE exam_id=?",(exam_id,)).fetchall()]
    return {"linked":linked,"pending":pending}

def _registration_link(conn,token):
    digest=hashlib.sha256(token.encode()).hexdigest();now=time.time()
    row=conn.execute("SELECT l.*,e.name,e.description,e.subject,e.level,e.duration_minutes FROM exam_registration_links l JOIN exams e ON e.id=l.exam_id WHERE l.token_hash=?",(digest,)).fetchone()
    if not row:raise HTTPException(404,"Registration link is invalid")
    if row["status"]!="ACTIVE":raise HTTPException(410,"Registration link has been revoked")
    if row["valid_from"]>now or (row["valid_until"] and row["valid_until"]<now):raise HTTPException(410,"Registration link has expired")
    if row["max_registrations"] is not None and row["registration_count"]>=row["max_registrations"]:raise HTTPException(410,"Registration link has reached its limit")
    return row

@router.post("/admin/exams/{exam_id}/registration-links")
async def create_registration_link(exam_id:int,request:Request):
    from platform_api import _auth
    admin=_auth(request,True)
    if admin["role"]!="ADMIN":raise HTTPException(403,"Administrator access required")
    body=await request.json();now=time.time();raw=secrets.token_urlsafe(32)
    valid_until=body.get("valid_until");maximum=body.get("max_registrations")
    with closing(db()) as conn:
        exam=conn.execute("SELECT status,allow_registration_link FROM exams WHERE id=?",(exam_id,)).fetchone()
        if not exam:raise HTTPException(404,"Exam not found")
        if exam["status"] not in {"PUBLISHED","OPEN"}:raise HTTPException(409,"Publish the exam before sharing registration")
        if not exam["allow_registration_link"]:raise HTTPException(409,"Registration links are disabled for this exam")
        cur=conn.execute("INSERT INTO exam_registration_links(exam_id,token_hash,status,valid_from,valid_until,max_registrations,created_by,created_at) VALUES(?,?,'ACTIVE',?,?,?,?,?)",(exam_id,hashlib.sha256(raw.encode()).hexdigest(),now,float(valid_until) if valid_until else None,int(maximum) if maximum else None,admin["id"],now));audit(conn,"REGISTRATION_LINK_CREATED",exam_id=exam_id,user_id=admin["id"],metadata={"link_id":cur.lastrowid});conn.commit()
    base=str(request.base_url).rstrip("/");return {"id":cur.lastrowid,"url":f"{base}/register/exam/{raw}","token":raw,"valid_until":valid_until}

@router.post("/admin/exams/{exam_id}/registration-links/{link_id}/revoke")
def revoke_registration_link(exam_id:int,link_id:int,request:Request):
    from platform_api import _auth
    admin=_auth(request,True)
    if admin["role"]!="ADMIN":raise HTTPException(403,"Administrator access required")
    with closing(db()) as conn:cur=conn.execute("UPDATE exam_registration_links SET status='REVOKED',revoked_at=? WHERE id=? AND exam_id=? AND status='ACTIVE'",(time.time(),link_id,exam_id));conn.commit()
    if not cur.rowcount:raise HTTPException(404,"Active registration link not found")
    return {"revoked":True}

@router.get("/register/exam/{token}")
def public_registration_details(token:str):
    with closing(db()) as conn:row=_registration_link(conn,token)
    return {k:row[k] for k in ("name","description","subject","level","duration_minutes","valid_until")}

@router.post("/register/exam/{token}")
async def public_registration(token:str,request:Request):
    body=await request.json();email=str(body.get("email","")).strip().lower();name=str(body.get("full_name","")).strip();dob=str(body.get("date_of_birth","")).strip();phone=str(body.get("phone_number","")).strip();school=str(body.get("school_name","")).strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):raise HTTPException(422,"Enter a valid email address")
    if not name or not dob or not re.fullmatch(r"[+0-9 ()-]{7,20}",phone) or not school:raise HTTPException(422,"Complete all registration fields")
    now=time.time()
    with closing(db()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE");link=_registration_link(conn,token)
            existing=conn.execute("SELECT 1 FROM pending_exam_registrations WHERE exam_id=? AND lower(registered_email)=? AND status IN ('PENDING','LINKED')",(link["exam_id"],email)).fetchone()
            if existing:raise HTTPException(409,"This email is already registered for the exam")
            conn.execute("INSERT INTO pending_exam_registrations(exam_id,registered_email,status,registration_source,created_by,created_at,updated_at,full_name,date_of_birth,phone_number,school_name,registration_link_id) VALUES(?,?,'PENDING','SHARED_LINK',?,?,?,?,?,?,?,?)",(link["exam_id"],email,link["created_by"],now,now,name,dob,phone,school,link["id"]));conn.execute("UPDATE exam_registration_links SET registration_count=registration_count+1 WHERE id=?",(link["id"],));conn.commit()
        except HTTPException:conn.rollback();raise
    return {"registered":True,"email":email,"message":"Registration saved. Sign in with this exact Google email to access the exam."}

@router.get("/student/profile")
def student_profile(request:Request):
    from platform_api import _auth
    user=_auth(request)
    return {k:user[k] for k in ("email","display_name","date_of_birth","phone_number","school_name","profile_completed")}

@router.put("/student/profile")
async def update_student_profile(request:Request):
    from platform_api import _auth
    user=_auth(request,True);body=await request.json();name=str(body.get("full_name","")).strip();dob=str(body.get("date_of_birth","")).strip();phone=str(body.get("phone_number","")).strip();school=str(body.get("school_name","")).strip()
    if not name or not dob or not re.fullmatch(r"[+0-9 ()-]{7,20}",phone) or not school:raise HTTPException(422,"Complete all profile fields")
    with closing(db()) as conn:conn.execute("UPDATE users SET display_name=?,date_of_birth=?,phone_number=?,school_name=?,profile_completed=1,updated_at=? WHERE id=?",(name,dob,phone,school,time.time(),user["id"]));conn.commit()
    return {"saved":True}

@router.put("/admin/exams/{exam_id}/registrations/{registration_id}/status")
async def registration_status(exam_id:int,registration_id:int,request:Request):
    from platform_api import _auth
    user=_auth(request,True)
    if user["role"]!="ADMIN":raise HTTPException(403,"Administrator access required")
    body=await request.json();status=str(body.get("status","")).upper()
    if status not in {"ENROLLED","BLOCKED","CANCELLED"}:raise HTTPException(400,"Invalid registration status")
    now=time.time()
    with closing(db()) as conn:
        cur=conn.execute("UPDATE exam_enrollments SET status=?,cancelled_at=?,updated_at=? WHERE id=? AND exam_id=?",(status,now if status=="CANCELLED" else None,now,registration_id,exam_id));audit(conn,"REGISTRATION_"+status,exam_id=exam_id,user_id=user["id"],metadata={"registration_id":registration_id});conn.commit()
    if not cur.rowcount:raise HTTPException(404,"Registration not found")
    return {"id":registration_id,"status":status}

@router.delete("/admin/exams/{exam_id}/registrations/{kind}/{registration_id}")
def delete_registration(exam_id:int,kind:str,registration_id:int,request:Request):
    from platform_api import _auth
    user=_auth(request,True)
    if user["role"]!="ADMIN":raise HTTPException(403,"Administrator access required")
    with closing(db()) as conn:
        if kind == "pending":
            cur=conn.execute("DELETE FROM pending_exam_registrations WHERE id=? AND exam_id=?",(registration_id,exam_id))
        elif kind == "enrollment":
            if conn.execute("SELECT 1 FROM exam_sessions WHERE registration_id=?",(registration_id,)).fetchone():
                raise HTTPException(409,"This registration has attempt history and cannot be deleted")
            cur=conn.execute("DELETE FROM exam_enrollments WHERE id=? AND exam_id=?",(registration_id,exam_id))
        else:
            raise HTTPException(400,"Invalid registration type")
        if not cur.rowcount:raise HTTPException(404,"Registration not found")
        audit(conn,"REGISTRATION_DELETED",exam_id=exam_id,user_id=user["id"],metadata={"registration_id":registration_id,"kind":kind});conn.commit()
    return {"deleted":registration_id,"kind":kind}

@router.get("/admin/exams/{exam_id}/sessions")
def sessions(exam_id:int,request:Request):
    from platform_api import _auth
    staff(_auth(request))
    with closing(db()) as conn:rows=conn.execute("SELECT s.id,s.attempt_number,s.started_at,s.expires_at,s.submitted_at,s.status,u.email,u.display_name,(SELECT COUNT(*) FROM exam_answers a WHERE a.session_id=s.id AND a.is_answered=1) answered_count FROM exam_sessions s JOIN users u ON u.id=s.user_id WHERE s.exam_id=? ORDER BY s.started_at DESC",(exam_id,)).fetchall()
    return [dict(r) for r in rows]

@router.get("/admin/exams/{exam_id}/results")
def exam_results(exam_id:int,request:Request):
    from platform_api import _auth
    staff(_auth(request))
    with closing(db()) as conn:rows=conn.execute("SELECT s.id,s.attempt_number,s.score,s.max_score,s.percentage,s.correct_count,s.incorrect_count,s.unanswered_count,s.submitted_at,s.status,u.email,u.display_name FROM exam_sessions s JOIN users u ON u.id=s.user_id WHERE s.exam_id=? AND s.status IN ('SUBMITTED','AUTO_SUBMITTED') ORDER BY s.submitted_at DESC",(exam_id,)).fetchall()
    return [dict(r) for r in rows]

@router.put("/student/sessions/{sid}/questions/{qid}/review")
async def mark_review(sid:int,qid:int,request:Request):
    from platform_api import _auth,_session
    user=_auth(request,True);body=await request.json();now=time.time()
    with closing(db()) as conn:
        session=_session(conn,sid,user["id"])
        if session["status"]!="IN_PROGRESS":raise HTTPException(409,"Submitted exams cannot be modified")
        current=conn.execute("SELECT selected_answer FROM exam_answers WHERE session_id=? AND question_id=?",(sid,qid)).fetchone();answered=bool(current and current["selected_answer"]);marked=bool(body.get("marked",True));status="ANSWERED_AND_MARKED" if answered and marked else "MARKED_FOR_REVIEW" if marked else "ANSWERED" if answered else "VISITED"
        conn.execute("INSERT INTO exam_answers(session_id,question_id,status,updated_at) VALUES(?,?,?,?) ON CONFLICT(session_id,question_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at",(sid,qid,status,now));conn.commit()
    return {"status":status}

@router.get("/proctor/exams/{exam_id}/dashboard")
def proctor_dashboard(exam_id:int,request:Request):
    from platform_api import _auth
    staff(_auth(request))
    with closing(db()) as conn:
        exam=conn.execute("SELECT id,name,status,exam_start_at,exam_end_at,assigned_proctor_id FROM exams WHERE id=?",(exam_id,)).fetchone();counts=conn.execute("SELECT COUNT(*) total,SUM(CASE WHEN status='IN_PROGRESS' THEN 1 ELSE 0 END) active,SUM(CASE WHEN status IN ('SUBMITTED','AUTO_SUBMITTED') THEN 1 ELSE 0 END) submitted FROM exam_sessions WHERE exam_id=?",(exam_id,)).fetchone();registered=conn.execute("SELECT COUNT(*) n FROM exam_enrollments WHERE exam_id=? AND status='ENROLLED'",(exam_id,)).fetchone()["n"]
    if not exam:raise HTTPException(404,"Exam not found")
    return {"exam":dict(exam),"registered_students":registered,"students_started":counts["total"],"currently_active":counts["active"] or 0,"submitted":counts["submitted"] or 0,"not_started":max(0,registered-(counts["total"] or 0))}
