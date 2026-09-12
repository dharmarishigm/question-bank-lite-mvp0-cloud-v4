"""Administrator-controlled result release and notification fan-out."""
from __future__ import annotations
import hashlib,json,time
from contextlib import closing
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from platform_api import _auth,db,require_admin
from commerce_service import audit,token
from communication_service import enqueue

router=APIRouter(prefix="/api",tags=["Result publication"])
class ReleaseInput(BaseModel):
    exam_id:int;release_mode:str="IMMEDIATE";scheduled_at:float|None=None;audience_rules:dict=Field(default_factory=dict)

@router.post("/admin/result-releases",status_code=201)
def create_release(body:ReleaseInput,request:Request):
    admin=require_admin(_auth(request,True));now=time.time()
    if body.release_mode not in {"IMMEDIATE","SCHEDULED"}:raise HTTPException(422,"Invalid release mode")
    if body.release_mode=="SCHEDULED" and (not body.scheduled_at or body.scheduled_at<=now):raise HTTPException(422,"Scheduled release must be in the future")
    rid=token("rel_");status="SCHEDULED" if body.release_mode=="SCHEDULED" else "DRAFT"
    with closing(db()) as conn:
        if not conn.execute("SELECT 1 FROM exams WHERE id=?",(body.exam_id,)).fetchone():raise HTTPException(404,"Exam not found")
        conn.execute("INSERT INTO result_releases(id,exam_id,status,release_mode,scheduled_at,audience_rules_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(rid,body.exam_id,status,body.release_mode,body.scheduled_at,json.dumps(body.audience_rules),now,now));audit(conn,"RESULT_RELEASE_CREATED","RESULT_RELEASE",rid,actor=admin["id"]);conn.commit()
    return {"id":rid,"status":status,"exam_id":body.exam_id}

def publish(conn,release,admin_id,now):
    sessions=conn.execute("SELECT s.*,u.email FROM exam_sessions s JOIN users u ON u.id=s.user_id WHERE s.exam_id=? AND s.status IN ('SUBMITTED','AUTO_SUBMITTED')",(release["exam_id"],)).fetchall()
    for session in sessions:
        digest=hashlib.sha256(json.dumps({"score":session["score"],"max_score":session["max_score"],"percentage":session["percentage"]},sort_keys=True).encode()).hexdigest()
        conn.execute("INSERT INTO result_release_recipients(release_id,user_id,session_id,status,result_snapshot_hash) VALUES(?,?,?,'PUBLISHED',?) ON CONFLICT(release_id,session_id) DO NOTHING",(release["id"],session["user_id"],session["id"],digest))
        enqueue(conn,event_id=f"result:{release['id']}:{session['id']}",user_id=session["user_id"],channel="EMAIL",destination=session["email"],payload={"event":"RESULT_PUBLISHED","exam_id":release["exam_id"],"session_id":session["id"]})
    conn.execute("UPDATE result_releases SET status='PUBLISHED',released_at=?,released_by=?,updated_at=? WHERE id=?",(now,admin_id,now,release["id"]));audit(conn,"RESULT_PUBLISHED","RESULT_RELEASE",release["id"],actor=admin_id,metadata={"recipients":len(sessions)})
    return len(sessions)

@router.post("/admin/result-releases/{release_id}/publish")
def publish_release(release_id:str,request:Request):
    admin=require_admin(_auth(request,True));now=time.time()
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE");release=conn.execute("SELECT * FROM result_releases WHERE id=?",(release_id,)).fetchone()
        if not release:raise HTTPException(404,"Release not found")
        if release["status"]=="PUBLISHED":return {"id":release_id,"status":"PUBLISHED","duplicate":True}
        count=publish(conn,release,admin["id"],now);conn.commit()
    return {"id":release_id,"status":"PUBLISHED","recipients":count}

@router.get("/admin/result-releases")
def releases(request:Request):
    require_admin(_auth(request))
    with closing(db()) as conn:rows=conn.execute("SELECT * FROM result_releases ORDER BY created_at DESC").fetchall()
    return {"items":[dict(x) for x in rows]}
