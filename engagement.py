"""Public enquiries, private admin follow-up and one-time FLAG trials."""
from contextlib import closing
from pathlib import Path
from typing import Literal
import hashlib,secrets,time
from fastapi import APIRouter,HTTPException,Request,Query
from fastapi.responses import FileResponse
from pydantic import Field,field_validator
from blueprint_domain import Contract
from platform_api import _auth,db,require_admin

router=APIRouter(tags=['Enquiries and subscriptions'])

def rate(key,limit,window=3600):
    now=time.time()
    with closing(db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT INTO engagement_limits(key,window_start,calls) VALUES(?,?,0) ON CONFLICT(key) DO NOTHING',(key,now))
        conn.execute('UPDATE engagement_limits SET calls=calls WHERE key=?',(key,))
        row=conn.execute('SELECT * FROM engagement_limits WHERE key=?',(key,)).fetchone()
        if row['window_start']+window<=now:conn.execute('UPDATE engagement_limits SET window_start=?,calls=0 WHERE key=?',(now,key))
        elif row['calls']>=limit:raise HTTPException(429,'Too many requests. Please try again later.',headers={'Retry-After':str(max(1,int(row['window_start']+window-now)))})
        conn.execute('UPDATE engagement_limits SET calls=calls+1 WHERE key=?',(key,));conn.commit()

def client_key(request):return hashlib.sha256((request.client.host if request.client else 'unknown').encode()).hexdigest()

@router.get('/enquiry')
def enquiry_page():return FileResponse(Path(__file__).parent/'static/enquiry.html',headers={'Cache-Control':'no-store'})

@router.get('/api/enquiries/challenge')
def challenge(request:Request):
    rate('challenge:'+client_key(request),20,600)
    a,b=secrets.randbelow(8)+2,secrets.randbelow(8)+2;token=secrets.token_urlsafe(24)
    with closing(db()) as conn:
        conn.execute('DELETE FROM enquiry_challenges WHERE expires_at<?',(time.time()-3600,))
        conn.execute('INSERT INTO enquiry_challenges(id,answer_hash,expires_at) VALUES(?,?,?)',(token,hashlib.sha256(f'{token}:{a+b}'.encode()).hexdigest(),time.time()+900));conn.commit()
    return {'id':token,'question':f'What is {a} + {b}?'}

class Enquiry(Contract):
    name:str=Field(min_length=2,max_length=100)
    email:str=Field(min_length=3,max_length=254)
    phone:str=Field(default='',max_length=40)
    interest:Literal['FLAG','EXAMS','GENERAL']='GENERAL'
    message:str=Field(min_length=5,max_length=3000)
    source:str=Field(default='website',max_length=100)
    consent:Literal[True]
    challenge_id:str=Field(max_length=100)
    answer:str=Field(max_length=20)
    website:str=Field(default='',max_length=200)
    @field_validator('email')
    @classmethod
    def email_valid(cls,value):
        from flag_api import Member
        return Member.valid_email(value)

@router.post('/api/enquiries',status_code=201)
def submit(data:Enquiry,request:Request):
    if data.website:raise HTTPException(422,'Unable to submit this request')
    rate('enquiry-ip:'+client_key(request),30)
    digest=hashlib.sha256(f'{data.challenge_id}:{data.answer.strip()}'.encode()).hexdigest()
    with closing(db()) as conn:
        result=conn.execute('UPDATE enquiry_challenges SET used=1 WHERE id=? AND answer_hash=? AND used=0 AND expires_at>?',(data.challenge_id,digest,time.time()))
        if not result.rowcount:raise HTTPException(422,'The verification answer is incorrect or expired. Refresh verification and try again.')
        conn.commit()
    rate('enquiry-email:'+hashlib.sha256(data.email.encode()).hexdigest(),5)
    with closing(db()) as conn:
        now=time.time();eid=conn.execute('INSERT INTO enquiries(name,email,phone,interest,message,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
            (data.name.strip(),data.email,data.phone.strip(),data.interest,data.message.strip(),data.source,now,now)).lastrowid;conn.commit()
    return {'reference':eid,'message':'Your enquiry has been received. Our team will review your request and contact you using the details provided.'}

@router.get('/api/admin/enquiries')
def enquiries(request:Request,status:Literal['','NEW','CONTACTED','RESOLVED']='',interest:Literal['','FLAG','EXAMS','GENERAL']='',offset:int=Query(default=0,ge=0)):
    require_admin(_auth(request))
    with closing(db()) as conn:
        clauses=[];params=[]
        if status:clauses.append('status=?');params.append(status)
        if interest:clauses.append('interest=?');params.append(interest)
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        total=conn.execute('SELECT COUNT(*) AS n FROM enquiries'+where,params).fetchone()['n']
        items=conn.execute('SELECT * FROM enquiries'+where+' ORDER BY created_at DESC,id DESC LIMIT 30 OFFSET ?',params+[offset]).fetchall()
    return {'items':[dict(row) for row in items],'total':total}

class Followup(Contract):
    status:Literal['NEW','CONTACTED','RESOLVED']
    admin_notes:str=Field(default='',max_length=4000)
    updated_at:float

@router.put('/api/admin/enquiries/{eid}')
def update(eid:int,data:Followup,request:Request):
    require_admin(_auth(request,True))
    with closing(db()) as conn:
        if not conn.execute('UPDATE enquiries SET status=?,admin_notes=?,updated_at=? WHERE id=? AND updated_at=?',(data.status,data.admin_notes,time.time(),eid,data.updated_at)).rowcount:raise HTTPException(409,'Enquiry changed. Refresh before saving.')
        conn.commit()
    return {'saved':True}

@router.post('/api/flag/trial')
def trial(request:Request):
    user=_auth(request,True)
    raise HTTPException(403,'FLAG access must be granted by an administrator.')
