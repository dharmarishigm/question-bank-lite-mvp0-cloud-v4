"""Purpose-bound phone/email OTP challenges with encrypted destinations."""
from __future__ import annotations
import base64,hashlib,hmac,os,re,secrets,time
from contextlib import closing
from cryptography.fernet import Fernet,InvalidToken
from fastapi import APIRouter,HTTPException,Request,Response
from pydantic import BaseModel,Field
from platform_api import _auth,db
from admin_settings import get_setting
from communication_service import enqueue
from commerce_service import token,audit

router=APIRouter(prefix="/api/auth/otp",tags=["Identity verification"])
PURPOSES={"LOGIN","REGISTRATION","PHONE_CHANGE","EMAIL_VERIFY"}

def normalize(channel,value):
    value=value.strip()
    if channel=="SMS":
        digits=re.sub(r"\D","",value)
        if len(digits)==10:digits="91"+digits
        if len(digits)<10 or len(digits)>15:raise HTTPException(422,"Enter a valid mobile number")
        return "+"+digits
    if channel=="EMAIL":
        value=value.lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",value):raise HTTPException(422,"Enter a valid email address")
        return value
    raise HTTPException(422,"Channel must be SMS or EMAIL")

def _secret(name):
    value=os.getenv(name)
    if value:return value
    if os.getenv("APP_ENV") in {"test","development"}:return "development-only-"+name
    raise HTTPException(503,f"{name} is not configured")

def _fernet():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(_secret("CONTACT_ENCRYPTION_KEY").encode()).digest()))
def encrypt(value):return _fernet().encrypt(value.encode()).decode()
def decrypt(value):
    try:return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:raise HTTPException(500,"Contact encryption key mismatch") from exc
def destination_hash(value):return hmac.new(_secret("OTP_PEPPER").encode(),value.encode(),hashlib.sha256).hexdigest()
def code_hash(challenge_id,code):return hmac.new(_secret("OTP_PEPPER").encode(),f"{challenge_id}:{code}".encode(),hashlib.sha256).hexdigest()

class OtpRequest(BaseModel):
    channel:str
    destination:str=Field(min_length=3,max_length=254)
    purpose:str

@router.post("/request",status_code=202)
def request_otp(body:OtpRequest,request:Request):
    channel=body.channel.upper();purpose=body.purpose.upper();user=None
    if purpose not in PURPOSES:raise HTTPException(422,"Invalid OTP purpose")
    if purpose in {"PHONE_CHANGE","EMAIL_VERIFY"}:user=_auth(request,True)
    else:
        try:user=_auth(request)
        except HTTPException:pass
    value=normalize(channel,body.destination);digest=destination_hash(value);now=time.time()
    with closing(db()) as conn:
        recent=conn.execute("SELECT COUNT(*) n FROM verification_challenges WHERE destination_hash=? AND created_at>?",(digest,now-3600)).fetchone()["n"]
        if recent>=5:raise HTTPException(429,"Too many OTP requests. Try again later.",headers={"Retry-After":"3600"})
        latest=conn.execute("SELECT next_send_at FROM verification_challenges WHERE destination_hash=? ORDER BY created_at DESC LIMIT 1",(digest,)).fetchone()
        if latest and latest["next_send_at"]>now:raise HTTPException(429,"Please wait before requesting another OTP",headers={"Retry-After":str(max(1,int(latest["next_send_at"]-now)))})
        challenge=token("otp_");code=f"{secrets.randbelow(1000000):06d}";expiry=int(get_setting("otp.expiry_seconds",conn=conn));attempts=int(get_setting("otp.max_attempts",conn=conn));resend=int(get_setting("otp.resend_seconds",conn=conn))
        if user:conn.execute("UPDATE verification_challenges SET status='SUPERSEDED' WHERE user_id=? AND channel=? AND purpose=? AND status='PENDING'",(user["id"],channel,purpose))
        else:conn.execute("UPDATE verification_challenges SET status='SUPERSEDED' WHERE user_id IS NULL AND destination_hash=? AND channel=? AND purpose=? AND status='PENDING'",(digest,channel,purpose))
        conn.execute("INSERT INTO verification_challenges(id,user_id,channel,purpose,destination_hash,destination_encrypted,code_hash,status,attempts,max_attempts,resend_count,expires_at,next_send_at,created_at) VALUES(?,?,?,?,?,?,?,'PENDING',0,?,0,?,?,?)",(challenge,user["id"] if user else None,channel,purpose,digest,encrypt(value),code_hash(challenge,code),attempts,now+expiry,now+resend,now))
        enqueue(conn,event_id="otp:"+challenge,user_id=user["id"] if user else None,channel=channel,destination=encrypt(value),payload={"event":"OTP","code_encrypted":encrypt(code),"purpose":purpose,"expires_minutes":max(1,expiry//60)},priority=1);conn.commit()
    response={"challenge_id":challenge,"expires_at":now+expiry,"next_send_at":now+resend,"message":"If the destination can receive messages, an OTP was sent."}
    if os.getenv("APP_ENV") in {"test","development"} and os.getenv("OTP_EXPOSE_TEST_CODE","1")=="1":response["test_code"]=code
    return response

class OtpVerify(BaseModel):challenge_id:str;code:str=Field(pattern=r"^\d{6}$")

def _create_phone_session(conn,user_id,response,now):
    from platform_api import SESSION_SECONDS,_hash
    raw,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(24)
    conn.execute("INSERT INTO app_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",(_hash(raw),user_id,csrf,now+SESSION_SECONDS,now))
    secure=bool(os.getenv("K_SERVICE")) or os.getenv("APP_BASE_URL","").startswith("https://")
    response.set_cookie("qb_session",raw,max_age=SESSION_SECONDS,httponly=True,samesite="lax",secure=secure)
    response.set_cookie("qb_csrf",csrf,max_age=SESSION_SECONDS,httponly=False,samesite="lax",secure=secure)

@router.post("/verify")
def verify_otp(body:OtpVerify,request:Request,response:Response):
    user=None
    try:user=_auth(request,True)
    except HTTPException:pass
    now=time.time()
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE");row=conn.execute("SELECT * FROM verification_challenges WHERE id=?",(body.challenge_id,)).fetchone()
        if not row:raise HTTPException(404,"Verification challenge not found")
        if row["user_id"] is not None and (not user or row["user_id"]!=user["id"]):raise HTTPException(404,"Verification challenge not found")
        if row["status"]!="PENDING" or row["expires_at"]<=now:raise HTTPException(409,"OTP is expired or already used")
        attempts=int(row["attempts"])+1
        if attempts>int(row["max_attempts"]):
            conn.execute("UPDATE verification_challenges SET status='LOCKED',attempts=? WHERE id=?",(attempts,row["id"]));conn.commit();raise HTTPException(429,"OTP attempts exceeded")
        if not hmac.compare_digest(code_hash(row["id"],body.code),row["code_hash"]):
            conn.execute("UPDATE verification_challenges SET attempts=?,status=? WHERE id=?",(attempts,"LOCKED" if attempts>=int(row["max_attempts"]) else "PENDING",row["id"]));conn.commit();raise HTTPException(422,"OTP is incorrect")
        value=decrypt(row["destination_encrypted"]);contact_id=token("con_");user_id=user["id"] if user else None
        if user_id is None:
            identity=conn.execute("SELECT * FROM authentication_identities WHERE channel=? AND normalized_value_hash=?",(row["channel"],row["destination_hash"])).fetchone()
            if identity:user_id=identity["user_id"]
            elif row["purpose"]=="REGISTRATION" and row["channel"]=="SMS":
                synthetic=f"phone-{row['destination_hash'][:24]}@phone.meritiqra.invalid";sub="phone:"+row["destination_hash"];uid=conn.execute("INSERT INTO users(google_sub,email,email_verified,display_name,role,status,created_at,updated_at,last_login_at,phone_number,profile_completed) VALUES(?,?,0,'','STUDENT','ACTIVE',?,?,?,?,1)",(sub,synthetic,now,now,now,value)).lastrowid
                user_id=uid
            else:raise HTTPException(404,"No account is registered for this verified contact")
        conn.execute("UPDATE verification_challenges SET status='VERIFIED',attempts=?,verified_at=? WHERE id=?",(attempts,now,row["id"]))
        conn.execute("INSERT INTO verified_contacts(id,user_id,channel,normalized_value_hash,encrypted_value,verified_at,is_primary,status) VALUES(?,?,?,?,?,?,1,'ACTIVE') ON CONFLICT(channel,normalized_value_hash) DO UPDATE SET user_id=excluded.user_id,encrypted_value=excluded.encrypted_value,verified_at=excluded.verified_at,status='ACTIVE'",(contact_id,user_id,row["channel"],row["destination_hash"],row["destination_encrypted"],now))
        conn.execute("INSERT INTO authentication_identities(id,user_id,channel,normalized_value_hash,created_at,last_used_at) VALUES(?,?,?,?,?,?) ON CONFLICT(channel,normalized_value_hash) DO UPDATE SET last_used_at=excluded.last_used_at",(token("aid_"),user_id,row["channel"],row["destination_hash"],now,now))
        if row["channel"]=="SMS" and row["purpose"] in {"PHONE_CHANGE","REGISTRATION"}:conn.execute("UPDATE users SET phone_number=?,updated_at=?,last_login_at=? WHERE id=?",(value,now,now,user_id))
        if row["channel"]=="EMAIL" and row["purpose"]=="EMAIL_VERIFY" and user and value.lower()==user["email"].lower():conn.execute("UPDATE users SET email_verified=1,updated_at=? WHERE id=?",(now,user_id))
        if not user:_create_phone_session(conn,user_id,response,now)
        audit(conn,"CONTACT_VERIFIED","VERIFIED_CONTACT",contact_id,actor=user_id,metadata={"channel":row["channel"],"purpose":row["purpose"]});conn.commit()
    return {"verified":True,"channel":row["channel"],"purpose":row["purpose"],"destination_masked":("***"+value[-4:] if row["channel"]=="SMS" else value[0]+"***@"+value.split("@",1)[1])}
