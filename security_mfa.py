"""TOTP step-up authentication. Secrets are encrypted with a staging-specific key."""
import base64,hashlib,hmac,os,secrets,struct,time
from contextlib import closing
from urllib.parse import urlencode
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from cryptography.fernet import Fernet

router=APIRouter(prefix='/api/auth/mfa')
SCHEMA='''CREATE TABLE IF NOT EXISTS security_mfa (
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
 secret_ciphertext TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,last_counter BIGINT NOT NULL DEFAULT -1);
CREATE TABLE IF NOT EXISTS security_session_state (
 id INTEGER PRIMARY KEY AUTOINCREMENT,token_hash TEXT NOT NULL UNIQUE,
 last_seen REAL NOT NULL,mfa_at REAL NOT NULL DEFAULT 0);'''

def required(user):return os.getenv('REQUIRE_STAFF_MFA')=='1' and user['role'] in {'ADMIN','OPERATOR','PROCTOR'}
def cipher():
    key=os.getenv('MFA_ENCRYPTION_KEY')
    if not key:raise HTTPException(503,'MFA is not configured')
    return Fernet(key.encode())

def code_for(secret,counter):
    digest=hmac.new(base64.b32decode(secret),struct.pack('>Q',counter),hashlib.sha1).digest()
    offset=digest[-1]&15
    return str((struct.unpack('>I',digest[offset:offset+4])[0]&0x7fffffff)%1000000).zfill(6)

def state(request,user):
    from platform_api import db,_hash
    now=time.time();token=_hash(request.cookies.get('qb_session',''))
    with closing(db()) as conn:
        row=conn.execute('SELECT * FROM security_session_state WHERE token_hash=?',(token,)).fetchone()
        session=conn.execute('SELECT created_at FROM app_sessions WHERE token_hash=?',(token,)).fetchone()
        if not session:raise HTTPException(401,'Session expired')
        last=row['last_seen'] if row else session['created_at']
        if now-last>int(os.getenv('SESSION_IDLE_SECONDS','3600')):
            conn.execute('DELETE FROM app_sessions WHERE token_hash=?',(token,));conn.commit()
            raise HTTPException(401,'Session idle timeout; sign in again')
        conn.execute('INSERT INTO security_session_state(token_hash,last_seen) VALUES(?,?) ON CONFLICT(token_hash) DO UPDATE SET last_seen=excluded.last_seen',(token,now));conn.commit()
        enrolled=conn.execute('SELECT enabled FROM security_mfa WHERE user_id=?',(user['id'],)).fetchone()
    return {'mfa_required':required(user) and (not row or now-row['mfa_at']>3600),
      'mfa_enrolled':bool(enrolled and enrolled['enabled'])}

@router.post('/setup')
def setup(request:Request):
    from platform_api import db,_auth
    user=_auth(request,True)
    if not required(user):raise HTTPException(403,'MFA enrollment is not available for this account')
    secret=base64.b32encode(secrets.token_bytes(20)).decode()
    encrypted=cipher().encrypt(secret.encode()).decode()
    with closing(db()) as conn:
        row=conn.execute('SELECT enabled FROM security_mfa WHERE user_id=?',(user['id'],)).fetchone()
        if row and row['enabled']:raise HTTPException(409,'MFA is already enrolled; recovery requires administrator verification')
        conn.execute('INSERT INTO security_mfa(user_id,secret_ciphertext) VALUES(?,?) ON CONFLICT(user_id) DO NOTHING',(user['id'],encrypted));conn.commit()
        row=conn.execute('SELECT secret_ciphertext FROM security_mfa WHERE user_id=?',(user['id'],)).fetchone()
    secret=cipher().decrypt(row['secret_ciphertext'].encode()).decode()
    return {'secret':secret,'uri':'otpauth://totp/MeritIQra:account-'+str(user['id'])+'?'+urlencode({'secret':secret,'issuer':'MeritIQra','digits':6,'period':30})}

class Verify(BaseModel):
    code:str=Field(pattern=r'^\d{6}$')

@router.post('/verify')
def verify(payload:Verify,request:Request):
    from platform_api import db,_auth,_hash
    from security_boundary import reserve
    user=_auth(request,True);reserve('mfa:'+str(user['id']),'mfa',5)
    with closing(db()) as conn:
        row=conn.execute('SELECT * FROM security_mfa WHERE user_id=?',(user['id'],)).fetchone()
        if not row:raise HTTPException(409,'Enroll an authenticator first')
        secret=cipher().decrypt(row['secret_ciphertext'].encode()).decode()
        now=time.time();counter=int(now//30)
        matched=next((n for n in (counter-1,counter,counter+1) if n>row['last_counter'] and hmac.compare_digest(payload.code,code_for(secret,n))),None)
        if matched is None:raise HTTPException(401,'Invalid or already-used authenticator code')
        claimed=conn.execute('UPDATE security_mfa SET enabled=1,last_counter=? WHERE user_id=? AND last_counter<?',(matched,user['id'],matched))
        if claimed.rowcount!=1:raise HTTPException(401,'Authenticator code already used')
        conn.execute('INSERT INTO security_session_state(token_hash,last_seen,mfa_at) VALUES(?,?,?) ON CONFLICT(token_hash) DO UPDATE SET last_seen=excluded.last_seen,mfa_at=excluded.mfa_at',(_hash(request.cookies.get('qb_session','')),now,now));conn.commit()
    return {'ok':True}
