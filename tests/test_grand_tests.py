"""Grand Tests: RBAC, reusable extraction, review, snapshot and secure exam flow."""
import io
import json
import time
from unittest.mock import patch, AsyncMock
import pymupdf
from fastapi.testclient import TestClient
import app
from tests.test_programs import clients, create
from grand_tests import Classifications, Classification


def pdf():
    doc=pymupdf.open()
    for _ in range(2):
        p=doc.new_page();p.insert_text((50,60),'1. Find 2 + 2. A. 3 B. 4 C. 5 D. 6')
    return doc.tobytes()


def extracted():
    return {'questions':[{'number':1,'statement':'Find 2 + 2.','options':['A. 3','B. 4','C. 5','D. 6'],'answer':'B','subject':'Math','chapter':'Arithmetic','topic':'Addition','subtopic':'Integers','qtype':'mcq_single','confidence':.9}]}


def build(admin, pid, selected=False):
    r=admin.post('/api/grand-tests',json={'program_id':pid,'name':'Grand Test','paper_name':'Paper 1'});assert r.status_code==201,r.text
    path='/api/grand-tests/'+str(r.json()['id'])
    r=admin.post(path+'/pdf?revision=1',files={'file':('paper.pdf',pdf(),'application/pdf')});assert r.status_code==200,r.text
    assert admin.get(path+'/pages/1').status_code==200
    method='app.digitise_pdf_crop' if selected else 'app.parse_pdf_paper'
    selections=[{'page':2,'bbox':[0,0,1,.5]},{'page':1,'bbox':[0,0,.5,.5]},{'page':1,'bbox':[0,0,.5,.5]}] if selected else []
    with patch(method,new=AsyncMock(return_value=extracted())) as extract, patch('grand_tests.classify',side_effect=lambda qs,pid:qs):
        r=admin.post(path+'/digitize',json={'revision':r.json()['revision'],'selections':selections});assert r.status_code==202,r.text
        assert extract.call_count==1
        if selected:assert [s.page for s in extract.call_args.args[1].selections]==[1,2]
    g=admin.get(path).json();assert g['status']=='REVIEW_REQUIRED',g
    return path,g


def finalized(admin,path,g):
    assert admin.post(path+'/finalize',json={'revision':g['revision']}).status_code==422
    q=g['questions'][0];q.update(statement='Reviewed: Find 2 + 2.',reviewed=True)
    r=admin.put(path+'/questions',json={'revision':g['revision'],'questions':[q]});assert r.status_code==200,r.text
    g=r.json()
    r=admin.post(path+'/finalize',json={'revision':g['revision']});assert r.status_code==200,r.text
    return r.json()


def test_full_lifecycle_and_multiple_students(clients):
    admin,student,anonymous=clients;pid=create(admin)['id'];path,g=build(admin,pid)
    assert admin.get('/api/questions').json()['total']==0
    assert student.get(path).status_code==403
    assert anonymous.get(path).status_code==401
    assert admin.post(path+'/generate',json={'revision':g['revision']}).status_code==409
    g=finalized(admin,path,g)
    r=admin.post(path+'/generate',json={'revision':g['revision']});assert r.status_code==200,r.text
    eid=r.json()['exam_id'];g=admin.get(path).json()
    assert admin.put(path+'/questions',json={'revision':g['revision'],'questions':[]}).status_code==409
    assert admin.post(path+'/publish',json={'revision':g['revision']}).status_code==422
    now=time.time();schedule={'revision':g['revision'],'name':'Scheduled Grand','start_at':now+3600,'end_at':now+7200,'duration_minutes':180}
    assert admin.put(path+'/schedule',json={**schedule,'end_at':now}).status_code==422
    r=admin.put(path+'/schedule',json=schedule);assert r.status_code==200,r.text
    g=r.json();r=admin.post(path+'/publish',json={'revision':g['revision']});assert r.status_code==200,r.text
    code=r.json()['proctor_code']
    assert admin.put(path+'/schedule',json={**schedule,'revision':g['revision']+1}).status_code==409
    assert student.post(f'/api/exams/{eid}/enroll').status_code==200
    assert student.post(f'/api/student/exams/{eid}/start',json={'proctor_code':code}).status_code==403
    assert student.post(f'/api/exams/{eid}/sessions').status_code==403
    with app.connect() as conn:
        conn.execute('UPDATE exams SET exam_start_at=? WHERE id=?',(now-60,eid));conn.execute('UPDATE exam_proctor_codes SET valid_from=? WHERE exam_id=?',(now-60,eid));conn.commit()
    assert student.post(f'/api/student/exams/{eid}/start',json={}).status_code==403
    assert student.post(f'/api/student/exams/{eid}/start',json={'proctor_code':'WRONG'}).status_code==403
    r=student.post(f'/api/student/exams/{eid}/start',json={'proctor_code':code});assert r.status_code==200,r.text
    sid=r.json()['session_id'];session=student.get(f'/api/sessions/{sid}').json()
    assert session['session']['expires_at']<=now+7200
    with app.connect() as conn:
        snap=json.loads(conn.execute('SELECT question_set_json FROM exam_sessions WHERE id=?',(sid,)).fetchone()['question_set_json'])
        assert snap[0]['statement']=='Reviewed: Find 2 + 2.'
    with TestClient(app.app) as second:
        assert second.post('/api/auth/mock',json={'email':'second@example.test'}).status_code==200
        second.headers['X-CSRF-Token']=second.cookies['qb_csrf']
        assert second.post(f'/api/exams/{eid}/enroll').status_code==200
        assert second.post(f'/api/student/exams/{eid}/start',json={'proctor_code':code}).status_code==200


def test_operator_ownership_permissions_and_csrf(clients):
    admin,operator,anonymous=clients;pid=create(admin)['id'];uid=operator.get('/api/auth/me').json()['id']
    email=operator.get('/api/auth/me').json()['email']
    assert admin.post('/api/admin/operator-allowlist',json={'email':email}).status_code==200
    assert admin.put(f'/api/admin/users/{uid}/role',json={'role':'OPERATOR'}).status_code==200
    path,g=build(operator,pid,True)
    assert admin.get(path).status_code==200
    for action in ['generate','publish']:
        assert operator.post(path+'/'+action,json={'revision':g['revision']}).status_code==403
    assert operator.put(path+'/schedule',json={'revision':g['revision'],'name':'x','start_at':1,'end_at':2,'duration_minutes':1}).status_code==403
    assert operator.get('/api/questions').status_code==403
    assert operator.put(f'/api/admin/users/{uid}/role',json={'role':'ADMIN'}).status_code==403
    own=admin.post('/api/grand-tests',json={'program_id':pid,'name':'Admin only'}).json()
    assert operator.get('/api/grand-tests/'+str(own['id'])).status_code==404
    operator.headers['X-CSRF-Token']='wrong'
    assert operator.post(path+'/finalize',json={'revision':g['revision']}).status_code==403


def test_regions_dedupe_order_retry_and_optimistic_lock(clients):
    admin,_,_=clients;pid=create(admin)['id'];path,g=build(admin,pid,True)
    with patch('app.digitise_pdf_crop',new=AsyncMock(return_value=extracted())),patch('grand_tests.classify',side_effect=lambda qs,pid:qs):
        assert admin.post(path+'/digitize',json={'revision':g['revision'],'selections':[{'page':1,'bbox':[0,0,1,1]}]}).status_code==202
    g=admin.get(path).json();assert len(g['questions'])==1
    assert admin.put(path+'/questions',json={'revision':1,'questions':g['questions']}).status_code==409
    assert admin.post(path+'/digitize',json={'revision':g['revision'],'selections':[{'page':1,'bbox':[1,0,0,1]}]}).status_code==422
    assert admin.post(path+'/digitize',json={'revision':g['revision'],'selections':[{'page':3,'bbox':[0,0,1,1]}]}).status_code==422


def test_classification_context_and_failure_flag(clients):
    from grand_tests import classify
    admin,_,_=clients;pid=create(admin)['id']
    q=extracted()['questions'][0]
    with patch('grand_tests.structured_call',return_value=(Classifications(questions=[Classification(index=0,subject='Arithmetic',chapter='Numbers',topic='Addition',subtopic='Integers',confidence=.8)]),{})) as model:
        result=classify([q],pid)
        assert result[0]['program_id']==pid and result[0]['classification_confidence']==.8
        assert model.call_args.args[2]['program']['name']=='Navodaya'
    with patch('grand_tests.structured_call',side_effect=RuntimeError('offline')):
        result=classify([extracted()['questions'][0]],pid)
        assert result[0]['classification_confidence']==0 and result[0]['review_required']


def test_finalization_rejects_empty_and_stale_records(clients):
    admin,_,_=clients;pid=create(admin)['id'];path,g=build(admin,pid)
    q=g['questions'][0];q.update(reviewed=True,answer='')
    r=admin.put(path+'/questions',json={'revision':g['revision'],'questions':[q]});assert r.status_code==200
    assert admin.post(path+'/finalize',json={'revision':r.json()['revision']}).status_code==422
    assert admin.put(path+'/questions',json={'revision':r.json()['revision'],'questions':[q,q]}).status_code==422


def test_extraction_failure_is_retryable(clients):
    admin,_,_=clients;pid=create(admin)['id'];path,g=build(admin,pid)
    with patch('app.parse_pdf_paper',new=AsyncMock(side_effect=RuntimeError('provider unavailable'))):
        assert admin.post(path+'/digitize',json={'revision':g['revision']}).status_code==202
    failed=admin.get(path).json()
    assert failed['status']=='REVIEW_REQUIRED' and failed['error']
    assert failed['questions']==g['questions']
