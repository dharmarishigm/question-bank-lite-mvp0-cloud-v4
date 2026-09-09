"""Android client additions; authentication and exams retain the shared web authority."""
import base64, hashlib, json, os, re, secrets, time
from contextlib import closing
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from platform_api import _auth, _hash, _public_user, db, SESSION_SECONDS
router=APIRouter()
SCHEMA="""
CREATE TABLE IF NOT EXISTS mobile_auth_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT, request_hash TEXT NOT NULL UNIQUE, challenge TEXT NOT NULL,
 user_id INTEGER REFERENCES users(id), expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_mobile_auth_expiry ON mobile_auth_requests(expires_at);
CREATE TABLE IF NOT EXISTS mobile_devices (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), token TEXT NOT NULL UNIQUE,
 enabled INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_mobile_devices_user ON mobile_devices(user_id);
"""

def init_mobile():
    with closing(db()) as conn:conn.executescript(SCHEMA);conn.commit()

class Start(BaseModel):
    model_config=ConfigDict(extra='forbid')
    challenge:str=Field(pattern=r'^[A-Za-z0-9_-]{43}$')
class Approve(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:str=Field(pattern=r'^[A-Za-z0-9_-]{43}$')
class Exchange(Approve):
    verifier:str=Field(pattern=r'^[A-Za-z0-9_-]{43,128}$')

@router.get('/api/mobile/config')
def config():return {'api_version':1,'minimum_client_version':'1.0.0','push_available':bool(os.getenv('FCM_PROJECT_ID'))}
@router.post('/api/mobile/auth/start')
def start(data:Start):
    raw=secrets.token_urlsafe(32)
    with closing(db()) as conn:
        conn.execute('DELETE FROM mobile_auth_requests WHERE expires_at<?',(time.time(),))
        conn.execute('INSERT INTO mobile_auth_requests(request_hash,challenge,expires_at) VALUES(?,?,?)',(_hash(raw),data.challenge,time.time()+300));conn.commit()
    return {'request_id':raw,'expires_in':300}
@router.post('/api/mobile/auth/approve')
def approve(data:Approve,request:Request):
    user=_auth(request,True)
    with closing(db()) as conn:
        result=conn.execute('UPDATE mobile_auth_requests SET user_id=? WHERE request_hash=? AND expires_at>? AND consumed=0 AND user_id IS NULL',(user['id'],_hash(data.request_id),time.time()));conn.commit()
        if result.rowcount!=1:raise HTTPException(409,'Sign-in request expired or already approved. Start again in the app.')
    return {'callback_path':'/mobile/callback?request_id='+data.request_id}
@router.post('/api/mobile/auth/exchange')
def exchange(data:Exchange,response:Response):
    challenge=base64.urlsafe_b64encode(hashlib.sha256(data.verifier.encode()).digest()).decode().rstrip('=')
    with closing(db()) as conn:
        row=conn.execute('SELECT * FROM mobile_auth_requests WHERE request_hash=? AND expires_at>? AND consumed=0',(_hash(data.request_id),time.time())).fetchone()
        if not row or not secrets.compare_digest(row['challenge'],challenge):raise HTTPException(401,'Invalid or expired sign-in request')
        if not row['user_id']:response.status_code=202;return {'pending':True}
        claimed=conn.execute('UPDATE mobile_auth_requests SET consumed=1 WHERE id=? AND consumed=0',(row['id'],))
        if claimed.rowcount!=1:raise HTTPException(401,'Sign-in request already used')
        user=conn.execute("SELECT * FROM users WHERE id=? AND status='ACTIVE'",(row['user_id'],)).fetchone()
        if not user:raise HTTPException(401,'Account unavailable')
        raw,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(24);now=time.time()
        conn.execute('INSERT INTO app_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)',(_hash(raw),user['id'],csrf,now+SESSION_SECONDS,now));conn.commit()
    response.set_cookie('qb_session',raw,max_age=SESSION_SECONDS,httponly=True,secure=True,samesite='lax')
    response.set_cookie('qb_csrf',csrf,max_age=SESSION_SECONDS,secure=True,samesite='lax')
    response.headers['Cache-Control']='no-store'
    return _public_user(user)

class Device(BaseModel):
    model_config=ConfigDict(extra='forbid')
    token:str=Field(min_length=16,max_length=4096)
    enabled:bool=False
@router.post('/api/mobile/devices')
def device(data:Device,request:Request):
    user=_auth(request,True)
    with closing(db()) as conn:
        conn.execute('INSERT INTO mobile_devices(user_id,token,enabled,updated_at) VALUES(?,?,?,?) ON CONFLICT(token) DO UPDATE SET user_id=excluded.user_id,enabled=excluded.enabled,updated_at=excluded.updated_at',(user['id'],data.token,int(data.enabled),time.time()));conn.commit()
    return {'enabled':data.enabled}
@router.delete('/api/mobile/devices/current')
def unregister_current(data:Device,request:Request):
    user=_auth(request,True)
    with closing(db()) as conn:
        conn.execute('DELETE FROM mobile_devices WHERE user_id=? AND token=?',(user['id'],data.token));conn.commit()
    return {'removed':True}
@router.delete('/api/mobile/devices')
def unregister(request:Request):
    user=_auth(request,True)
    with closing(db()) as conn:conn.execute('DELETE FROM mobile_devices WHERE user_id=?',(user['id'],));conn.commit()
    return {'removed':True}
@router.get('/.well-known/assetlinks.json')
def assetlinks():
    fingerprints=[x.strip().upper() for x in os.getenv('ANDROID_APP_LINK_SHA256','').split(',') if re.fullmatch(r'(?:[A-Fa-f0-9]{2}:){31}[A-Fa-f0-9]{2}',x.strip())]
    return [{'relation':['delegate_permission/common.handle_all_urls'],'target':{'namespace':'android_app','package_name':os.getenv('ANDROID_APPLICATION_ID','com.meritiqra.app'),'sha256_cert_fingerprints':fingerprints}}] if fingerprints else []
