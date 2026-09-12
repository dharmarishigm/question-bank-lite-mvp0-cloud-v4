"""Admin notification templates, queue visibility, and safe dispatch actions."""
from __future__ import annotations
import json,time
from contextlib import closing
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from platform_api import _auth,db,require_admin
from commerce_service import audit
from communication_service import dispatch_due,render
from notification_providers import sender

router=APIRouter(prefix="/api/admin/notifications",tags=["Communication administration"])
EVENTS={"OTP","TRIAL_STARTED","PAYMENT_CAPTURED","PAYMENT_FAILED","ENTITLEMENT_ACTIVATED","ENTITLEMENT_EXPIRING","ENTITLEMENT_EXPIRED","GRAND_TEST_REDEEMED","RESULT_PUBLISHED","REFUND_COMPLETED","ORGANIZATION_ENQUIRY_RECEIVED","CONTACT_CHANGED"}
CHANNELS={"EMAIL","SMS","PUSH"}

class TemplateInput(BaseModel):
    event_type:str;channel:str;locale:str="en-IN";status:str="DRAFT";provider_template_id:str|None=None
    subject_template:str|None=None;body_template:str=Field(min_length=1,max_length=10000);allowed_variables:list[str]=Field(default_factory=list,max_length=50)

@router.post("/templates",status_code=201)
def create_template(body:TemplateInput,request:Request):
    admin=require_admin(_auth(request,True));event=body.event_type.upper();channel=body.channel.upper();now=time.time()
    if event not in EVENTS or channel not in CHANNELS:raise HTTPException(422,"Unsupported event or channel")
    if body.status not in {"DRAFT","ACTIVE","RETIRED"}:raise HTTPException(422,"Invalid template status")
    try:render(body.body_template,{x:"sample" for x in body.allowed_variables},set(body.allowed_variables))
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    with closing(db()) as conn:
        version=conn.execute("SELECT COALESCE(MAX(version),0)+1 n FROM notification_templates WHERE event_type=? AND channel=? AND locale=?",(event,channel,body.locale)).fetchone()["n"]
        if body.status=="ACTIVE":conn.execute("UPDATE notification_templates SET status='RETIRED' WHERE event_type=? AND channel=? AND locale=? AND status='ACTIVE'",(event,channel,body.locale))
        cur=conn.execute("INSERT INTO notification_templates(event_type,channel,locale,version,status,provider_template_id,subject_template,body_template,allowed_variables_json,created_by,approved_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(event,channel,body.locale,version,body.status,body.provider_template_id,body.subject_template,body.body_template,json.dumps(body.allowed_variables),admin["id"],admin["id"] if body.status=="ACTIVE" else None,now))
        audit(conn,"NOTIFICATION_TEMPLATE_CREATED","NOTIFICATION_TEMPLATE",cur.lastrowid,actor=admin["id"],metadata={"event":event,"channel":channel,"version":version});conn.commit();row=conn.execute("SELECT * FROM notification_templates WHERE id=?",(cur.lastrowid,)).fetchone()
    return dict(row)

@router.get("/templates")
def templates(request:Request):
    require_admin(_auth(request))
    with closing(db()) as conn:rows=conn.execute("SELECT * FROM notification_templates ORDER BY event_type,channel,version DESC").fetchall()
    return {"items":[dict(x) for x in rows]}

@router.get("/outbox")
def outbox(request:Request,status:str=""):
    require_admin(_auth(request));params=[];where=""
    if status:where=" WHERE status=?";params=[status.upper()]
    with closing(db()) as conn:rows=conn.execute("SELECT id,event_id,user_id,channel,template_id,status,priority,scheduled_at,attempts,next_attempt_at,provider_message_id,last_error,created_at,sent_at FROM notification_outbox"+where+" ORDER BY created_at DESC LIMIT 200",params).fetchall()
    return {"items":[dict(x) for x in rows]}

@router.post("/dispatch")
def dispatch(request:Request):
    admin=require_admin(_auth(request,True))
    with closing(db()) as conn:
        count=dispatch_due(conn,sender);audit(conn,"NOTIFICATION_DISPATCH_RUN","NOTIFICATION_OUTBOX",actor=admin["id"],metadata={"sent":count});conn.commit()
    return {"sent":count}
