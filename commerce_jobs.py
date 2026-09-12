"""Authenticated maintenance endpoint for Cloud Scheduler/worker invocations."""
from __future__ import annotations
import hmac,os,time
from contextlib import closing
from fastapi import APIRouter,HTTPException,Request
from platform_api import db
from communication_service import dispatch_due
from notification_providers import sender
from result_publication import publish

router=APIRouter(prefix="/api/internal/commerce",tags=["Commerce operations"])

def authenticate(request):
    expected=os.getenv("INTERNAL_JOB_TOKEN","");supplied=request.headers.get("authorization","").removeprefix("Bearer ")
    if not expected or not supplied or not hmac.compare_digest(expected,supplied):raise HTTPException(401,"Invalid worker credential")

@router.post("/run-due")
def run_due(request:Request):
    authenticate(request);now=time.time();released=0
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows=conn.execute("SELECT * FROM result_releases WHERE status='SCHEDULED' AND scheduled_at<=? ORDER BY scheduled_at LIMIT 20",(now,)).fetchall()
        for row in rows:released+=publish(conn,row,None,now)
        conn.commit();sent=dispatch_due(conn,sender,limit=100,now=now)
    return {"released_recipients":released,"notifications_sent":sent}
