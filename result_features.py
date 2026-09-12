"""Released-result rankings, question concerns, and private/shareable PDF summaries."""
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import secrets
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field
from blueprint_domain import Contract
from platform_api import _auth, db, require_admin
from exam_conduct import audit

router=APIRouter()
COMPLETE={'SUBMITTED','AUTO_SUBMITTED'}


def released(exam):
    return exam['result_release_mode']=='IMMEDIATE' or (exam['result_release_mode']=='AFTER_EXAM_CLOSE' and exam['status']=='CLOSED')


def exam_access(conn,eid,user):
    exam=conn.execute('SELECT * FROM exams WHERE id=?',(eid,)).fetchone()
    if not exam:raise HTTPException(404,'Exam not found')
    if user['role']!='ADMIN':
        enrolled=conn.execute("SELECT 1 FROM exam_enrollments WHERE exam_id=? AND user_id=? AND status IN ('ENROLLED','COMPLETED')",(eid,user['id'])).fetchone()
        if not enrolled:raise HTTPException(403,'Exam registration required')
        if not released(exam):raise HTTPException(403,'Results have not been released')
    return exam


def ranked_attempts(conn,eid):
    rows=conn.execute("SELECT s.id,s.user_id,s.attempt_number,s.score,s.max_score,s.percentage,s.submitted_at,u.display_name FROM exam_sessions s JOIN users u ON u.id=s.user_id WHERE s.exam_id=? AND u.role='STUDENT' AND s.status IN ('SUBMITTED','AUTO_SUBMITTED') AND s.score IS NOT NULL AND s.max_score>0 ORDER BY s.submitted_at,s.id",(eid,)).fetchall()
    best={}
    def scorekey(row):
        return (Decimal(str(row['score']))/Decimal(str(row['max_score'])),Decimal(str(row['score'])))
    for row in rows:
        value=dict(row)
        if row['user_id'] not in best or scorekey(row)>scorekey(best[row['user_id']]):best[row['user_id']]=value
    ordered=sorted(best.values(),key=lambda row:(-scorekey(row)[0],-scorekey(row)[1],row['submitted_at'],row['id']))
    previous=None;rank=0
    for index,row in enumerate(ordered,1):
        key=scorekey(row)
        if key!=previous:rank=index
        row['rank']=rank;previous=key
    return ordered


@router.get('/api/exams/{eid}/leaderboard')
def leaderboard(eid:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        exam=exam_access(conn,eid,user);rows=ranked_attempts(conn,eid)
    return {'exam_id':eid,'exam_name':exam['name'],'released':released(exam),'participants':len(rows),
        'ranking_rule':'Best completed attempt per student; percentage, then marks. Equal results share a rank (1, 1, 3).',
        'entries':[{'rank':r['rank'],'student_name':r['display_name'] or f"Candidate {r['user_id']}",'score':r['score'],'max_score':r['max_score'],'percentage':r['percentage'],'attempt_number':r['attempt_number'],'is_you':r['user_id']==user['id'],**({'session_id':r['id']} if user['role']=='ADMIN' or r['user_id']==user['id'] else {})} for r in rows]}


def owned_result(conn,sid,user,require_release=True):
    row=conn.execute("SELECT s.*,e.name exam_name,e.subject,e.level,e.exam_type,e.status exam_status,e.result_release_mode,u.display_name student_name FROM exam_sessions s JOIN exams e ON e.id=s.exam_id JOIN users u ON u.id=s.user_id WHERE s.id=?",(sid,)).fetchone()
    if not row or (user['role']!='ADMIN' and row['user_id']!=user['id']):raise HTTPException(404,'Attempt not found')
    if row['status'] not in COMPLETE:raise HTTPException(409,'Result unavailable while exam is active')
    if require_release and not released({'status':row['exam_status'],'result_release_mode':row['result_release_mode']}):raise HTTPException(403,'Results have not been released')
    if require_release:
        from admin_settings import get_setting
        if get_setting('results.release_gate',conn=conn) and not conn.execute("SELECT 1 FROM result_release_recipients WHERE session_id=? AND user_id=? AND status='PUBLISHED'",(sid,user['id'])).fetchone():raise HTTPException(403,'Results have not been published')
    return dict(row)


def report_data(conn,sid,user):
    s=owned_result(conn,sid,user,require_release=user['role']!='ADMIN')
    rows=ranked_attempts(conn,s['exam_id']);best=next((r for r in rows if r['user_id']==s['user_id']),None)
    answers={a['question_id']:dict(a) for a in conn.execute('SELECT * FROM exam_answers WHERE session_id=?',(sid,)).fetchall()}
    subjects={};sections={}
    snapshot=json.loads(s['question_set_json'] or '[]')
    for q in snapshot:
        subject=q.get('subject') or q.get('section_name') or 'General'
        section=q.get('section_name') or subject
        a=answers.get(q['id'],{})
        for groups,name in [(subjects,subject),(sections,section)]:
            group=groups.setdefault(name,{'subject':name,'questions':0,'correct':0,'incorrect':0,'unanswered':0,'score':0.0,'max_score':0.0})
            group['questions']+=1;group['max_score']+=float(q.get('marks') or 0);group['score']+=float(a.get('marks_awarded') or 0)
            group['correct' if a.get('is_correct') else 'incorrect' if a.get('selected_answer') else 'unanswered']+=1
    for group in [*subjects.values(),*sections.values()]:
        group['score']=round(group['score'],6);group['max_score']=round(group['max_score'],6)
        group['percentage']=round(100*group['score']/group['max_score'],2) if group['max_score'] else 0
    return {'session':{k:s[k] for k in ['id','exam_id','exam_name','exam_type','subject','level','student_name','attempt_number','submitted_at','started_at','duration_minutes','score','max_score','percentage','correct_count','incorrect_count','unanswered_count']},'subjects':list(subjects.values()),'sections':list(sections.values()),'rank':best['rank'] if best else None,'participants':len(rows),'rank_attempt_number':best['attempt_number'] if best else None,'released':released({'status':s['exam_status'],'result_release_mode':s['result_release_mode']})}


@router.get('/api/results/{sid}/report')
def report_summary(sid:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:return report_data(conn,sid,user)


def pdf_response(data):
    from result_pdf import render_report
    return Response(render_report(data),media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="exam-result-{data["session"]["id"]}.pdf"','Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow','Referrer-Policy':'no-referrer'})


@router.get('/api/results/{sid}/report.pdf')
def export_report(sid:int,request:Request):
    user=_auth(request);require_admin(user)
    with closing(db()) as conn:data=report_data(conn,sid,user)
    return pdf_response(data)


@router.post('/api/results/{sid}/share')
def share_report(sid:int,request:Request):
    user=_auth(request,True);require_admin(user)
    with closing(db()) as conn:
        s=owned_result(conn,sid,user,require_release=True);token=secrets.token_urlsafe(32);now=time.time();expires=now+7*86400
        conn.execute('INSERT INTO result_report_links(session_id,token_hash,created_by,created_at,expires_at) VALUES(?,?,?,?,?)',(sid,hashlib.sha256(token.encode()).hexdigest(),user['id'],now,expires))
        audit(conn,'RESULT_REPORT_SHARED',exam_id=s['exam_id'],user_id=user['id'],session_id=sid);conn.commit()
    base=os.getenv('APP_BASE_URL','https://meritiqra.com').rstrip('/')
    return {'url':base+'/reports/shared/'+token+'.pdf','expires_at':expires,'message':'Anyone with this link can download the result summary for 7 days. It contains the student name and scores, but no email, question text or answer key.'}


@router.delete('/api/results/{sid}/share')
def revoke_report(sid:int,request:Request):
    user=_auth(request,True)
    with closing(db()) as conn:
        s=owned_result(conn,sid,user,require_release=False)
        conn.execute('UPDATE result_report_links SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL',(time.time(),sid))
        audit(conn,'RESULT_REPORT_SHARES_REVOKED',exam_id=s['exam_id'],user_id=user['id'],session_id=sid);conn.commit()
    return {'revoked':True}


@router.get('/reports/shared/{token}.pdf')
def shared_report(token:str):
    if len(token)>100:raise HTTPException(404,'Report link unavailable')
    with closing(db()) as conn:
        link=conn.execute('SELECT l.session_id,s.user_id FROM result_report_links l JOIN exam_sessions s ON s.id=l.session_id JOIN users creator ON creator.id=l.created_by WHERE creator.role=? AND l.token_hash=? AND l.revoked_at IS NULL AND l.expires_at>?',('ADMIN',hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not link:raise HTTPException(404,'Report link expired or revoked')
        data=report_data(conn,link['session_id'],{'id':link['user_id'],'role':'STUDENT'})
    return pdf_response(data)


class ConcernInput(Contract):
    question_id:int=Field(gt=0)
    session_id:int|None=Field(default=None,gt=0)
    category:Literal['QUESTION','OPTIONS','ANSWER','SOLUTION','OTHER']='ANSWER'
    description:str=Field(min_length=10,max_length=3000)


@router.post('/api/question-concerns',status_code=201)
def raise_concern(data:ConcernInput,request:Request):
    user=_auth(request,True)
    with closing(db()) as conn:
        eid=None
        if data.session_id:
            active=conn.execute('SELECT * FROM exam_sessions WHERE id=?',(data.session_id,)).fetchone()
            if not active or (user['role']!='ADMIN' and active['user_id']!=user['id']):raise HTTPException(404,'Attempt not found')
            s=dict(active) if active['status']=='IN_PROGRESS' else owned_result(conn,data.session_id,user,require_release=user['role']!='ADMIN')
            eid=s['exam_id']
            if not any(q.get('id')==data.question_id for q in json.loads(s['question_set_json'] or '[]')):raise HTTPException(404,'Question is not in this attempt')
        elif user['role']!='ADMIN':raise HTTPException(403,'Report a question from your released result')
        if not conn.execute('SELECT 1 FROM questions WHERE id=?',(data.question_id,)).fetchone():raise HTTPException(404,'Question not found')
        scope='session_id IS NULL' if data.session_id is None else 'session_id=?'
        params=(data.question_id,user['id'])+(() if data.session_id is None else (data.session_id,))
        existing=conn.execute("SELECT id FROM question_concerns WHERE question_id=? AND reporter_id=? AND status='OPEN' AND "+scope,params).fetchone()
        if existing:return {'id':existing['id'],'status':'OPEN','already_reported':True}
        now=time.time();cid=conn.execute('INSERT INTO question_concerns(question_id,session_id,exam_id,reporter_id,category,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(data.question_id,data.session_id,eid,user['id'],data.category,data.description,now,now)).lastrowid
        audit(conn,'QUESTION_CONCERN_RAISED',exam_id=eid,user_id=user['id'],session_id=data.session_id,metadata={'concern_id':cid,'question_id':data.question_id});conn.commit()
    return {'id':cid,'status':'OPEN','already_reported':False}


@router.get('/api/question-concerns')
def concerns(request:Request,status:Literal['OPEN','RESOLVED','DISMISSED','ALL']='OPEN'):
    user=_auth(request)
    where=[];params=[]
    if user['role']!='ADMIN':where.append('c.reporter_id=?');params.append(user['id'])
    if status!='ALL':where.append('c.status=?');params.append(status)
    with closing(db()) as conn:
        rows=conn.execute("SELECT c.*,q.statement,q.updated_at question_updated_at,e.name exam_name,u.display_name reporter_name FROM question_concerns c JOIN questions q ON q.id=c.question_id LEFT JOIN exams e ON e.id=c.exam_id JOIN users u ON u.id=c.reporter_id"+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY c.created_at DESC LIMIT 200',tuple(params)).fetchall()
        items=[dict(r) for r in rows]
        if user['role']!='ADMIN':
            for item in items:
                if not item['session_id']:continue
                session=conn.execute('SELECT s.status,s.question_set_json,e.status exam_status,e.result_release_mode FROM exam_sessions s JOIN exams e ON e.id=s.exam_id WHERE s.id=?',(item['session_id'],)).fetchone()
                if session and (session['status'] not in COMPLETE or not released({'status':session['exam_status'],'result_release_mode':session['result_release_mode']})):
                    item['resolution']=''
                    item['statement']=next((q.get('statement','') for q in json.loads(session['question_set_json'] or '[]') if q.get('id')==item['question_id']),'')
        return items


class Resolution(Contract):
    status:Literal['RESOLVED','DISMISSED','OPEN']
    resolution:str=Field(min_length=5,max_length=3000)
    revision:int=Field(ge=1)


@router.put('/api/question-concerns/{cid}')
def resolve_concern(cid:int,data:Resolution,request:Request):
    user=require_admin(_auth(request,True))
    with closing(db()) as conn:
        row=conn.execute('SELECT * FROM question_concerns WHERE id=?',(cid,)).fetchone()
        if not row:raise HTTPException(404,'Concern not found')
        changed=conn.execute('UPDATE question_concerns SET status=?,resolution=?,revision=revision+1,resolved_by=?,updated_at=? WHERE id=? AND revision=?',(data.status,data.resolution,user['id'],time.time(),cid,data.revision)).rowcount
        if not changed:raise HTTPException(409,'Concern changed; refresh before updating')
        audit(conn,'QUESTION_CONCERN_UPDATED',exam_id=row['exam_id'],user_id=user['id'],session_id=row['session_id'],metadata={'concern_id':cid,'status':data.status});conn.commit()
    return {'id':cid,'status':data.status,'revision':data.revision+1}

@router.get('/api/sessions/{sid}/question-flags')
def question_flags(sid:int,request:Request):
    user=_auth(request)
    with closing(db()) as conn:
        session=conn.execute('SELECT user_id FROM exam_sessions WHERE id=?',(sid,)).fetchone()
        if not session or (user['role']!='ADMIN' and session['user_id']!=user['id']):raise HTTPException(404,'Attempt not found')
        return [dict(r) for r in conn.execute('SELECT question_id,status FROM question_concerns WHERE session_id=? AND reporter_id=?',(sid,session['user_id'])).fetchall()]
