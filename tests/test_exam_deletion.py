"""Exam deletion preserves reusable authoring work and student history."""
from contextlib import closing
import json
import os
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app
from platform_api import init_platform


@pytest.fixture
def deletion_clients(tmp_path):
    with patch.object(app,'DB_PATH',str(tmp_path/'exam-deletion.db')),patch.dict(os.environ,{
        'DATABASE_URL':'','APP_ENV':'test','AUTH_MODE':'mock','QB_SCHEMA_MANAGED':'0',
        'ADMIN_EMAILS':'deletion-admin@example.test','REQUIRE_STAFF_MFA':'0',
    }):
        with closing(app.connect()) as conn:
            assert conn.execute('PRAGMA foreign_keys').fetchone()[0]==1
            conn.executescript(app.SCHEMA);conn.commit()
        init_platform()
        with TestClient(app.app) as admin,TestClient(app.app) as student,TestClient(app.app) as anonymous:
            for client,email in ((admin,'deletion-admin@example.test'),(student,'deletion-student@example.test')):
                response=client.post('/api/auth/mock',json={'email':email})
                assert response.status_code==200,response.text
                client.headers['X-CSRF-Token']=client.cookies['qb_csrf']
            yield admin,student,anonymous


PRESERVED_TABLES=('questions','question_explanations','question_explanation_translations',
    'explanation_jobs','source_documents','extraction_runs','program_documents',
    'grand_test_page_status','grand_test_page_status_audit')
DOMAIN_TABLES=PRESERVED_TABLES+('exams','exam_questions','exam_versions','grand_tests',
    'program_exam_jobs','exam_blueprints','exam_generation_runs','exam_registration_links',
    'exam_proctor_codes','proctor_code_failures','exam_enrollments','exam_sessions',
    'pending_exam_registrations','question_concerns')


def snapshot(tables):
    with closing(app.connect()) as conn:
        return {table:[dict(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()] for table in tables}


def linked_exam(admin):
    now=time.time();uid=admin.get('/api/auth/me').json()['id']
    program=admin.post('/api/programs',json={'code':'DELETE_TEST','name':'Reusable program','status':'ACTIVE'})
    assert program.status_code==201,program.text
    pid=program.json()['id']
    response=admin.post('/api/questions',json={'statement':'What is $2+2$?','options':['3','4'],
        'answer':'B','solution':'Adding gives $4$.','subject':'Mathematics','verification_status':'APPROVED'})
    assert response.status_code==200,response.text
    question=response.json();qid=question['id']
    def exam(name):
        response=admin.post('/api/admin/exams',json={'name':name,'status':'PUBLISHED',
            'exam_start_at':now+3600,'question_ids':[qid]})
        assert response.status_code==200,response.text
        return response.json()['id']
    eid=exam('Delete this unused exam');other=exam('Unrelated exam shares the question')
    source={'id':'deletion-source','filename':'retained-paper.pdf','page_count':1,
        'selected_regions':[{'page':1,'bbox':[0,0,1,1]}]}
    result={'questions':[{'question':question,'origin':'BANK','section':{'subject':'Mathematics','count':1}}],
        'generated':0,'reused':1,'draft_hash':'old-exam-specific-hash','review_notes':['Keep this authoring evidence']}
    frozen={'settings':{'generation_prompt':'Frozen syllabus and exact question paper prompt'},'effective_prompt':'Preserve this prompt'}
    with closing(app.connect()) as conn:
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0]==1
        conn.execute("INSERT INTO source_documents(id,filename,sha256,mime_type,page_count,local_path,created_at) VALUES(?,?,?,?,?,?,?)",
            (source['id'],source['filename'],'deletion-source-hash','application/pdf',1,'/synthetic/retained-paper.pdf',now))
        conn.execute("INSERT INTO extraction_runs(id,source_document_id,status,created_at) VALUES(?,?,?,?)",('deletion-extraction',source['id'],'SUCCEEDED',now))
        conn.execute('INSERT INTO program_documents(program_id,source_document_id,original_filename,created_by,created_at) VALUES(?,?,?,?,?)',(pid,source['id'],source['filename'],uid,now))
        conn.execute('INSERT INTO question_explanations(question_id,explanation,liked,created_at,updated_at) VALUES(?,?,?,?,?)',(qid,'Retained legacy explanation',1,now,now))
        for lang,text in (('en','Retained English explanation'),('te','నిల్వ చేసిన తెలుగు వివరణ')):
            conn.execute('INSERT INTO question_explanation_translations(question_id,language,explanation,liked,created_at,updated_at) VALUES(?,?,?,?,?,?)',(qid,lang,text,1,now,now))
        conn.execute("INSERT INTO explanation_jobs(question_id,source_hash,status,next_attempt_at,created_at,updated_at) VALUES(?,?,'SUCCEEDED',?,?,?) ON CONFLICT(question_id) DO UPDATE SET status='SUCCEEDED'",(qid,'retained-question-hash',now,now,now))
        gid=conn.execute("INSERT INTO grand_tests(program_id,name,status,source_json,questions_json,revision,exam_id,created_by,updated_by,created_at,updated_at) VALUES(?,?,'PUBLISHED',?,?,7,?,?,?,?,?)",(pid,'Retained source workspace',json.dumps(source),json.dumps([question]),eid,uid,uid,now,now)).lastrowid
        conn.execute("INSERT INTO grand_test_page_status(workspace_id,source_document_id,page_number,status,created_at,updated_at,created_by,updated_by) VALUES(?,?,1,'Completed',?,?,?,?)",(gid,source['id'],now,now,uid,uid))
        conn.execute("INSERT INTO grand_test_page_status_audit(workspace_id,source_document_id,page_number,new_status,changed_at,changed_by,reason) VALUES(?,?,1,'Completed',?,?,'Reviewed source')",(gid,source['id'],now,uid))
        jid=conn.execute("INSERT INTO program_exam_jobs(program_id,request_key,status,input_json,result_json,exam_id,created_by,created_at,updated_at) VALUES(?,?,'PUBLISHED',?,?,?,?,?,?)",(pid,'linked-delete-exam',json.dumps(frozen),json.dumps(result),eid,uid,now,now)).lastrowid
        # A second workspace/job must remain linked to the unrelated exam.
        conn.execute("INSERT INTO grand_tests(program_id,name,status,exam_id,created_by,updated_by,created_at,updated_at) VALUES(?,?,'PUBLISHED',?,?,?,?,?)",(pid,'Unrelated workspace',other,uid,uid,now,now))
        conn.execute("INSERT INTO program_exam_jobs(program_id,request_key,status,input_json,result_json,exam_id,created_by,created_at,updated_at) VALUES(?,?,'PUBLISHED','{}','{}',?,?,?,?)",(pid,'unrelated-delete-exam',other,uid,now,now))
        blueprint=conn.execute('INSERT INTO exam_blueprints(exam_id,name,blueprint_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)',(eid,'Unused delivery blueprint','{}',uid,now,now)).lastrowid
        conn.execute("INSERT INTO exam_generation_runs(exam_id,blueprint_id,requested_questions,status,request_json,result_json,created_by,created_at) VALUES(?,?,1,'COMPLETE','{}','{}',?,?)",(eid,blueprint,uid,now))
        conn.execute('INSERT INTO exam_registration_links(exam_id,token_hash,valid_from,created_by,created_at) VALUES(?,?,?,?,?)',(eid,'unused-delete-link',now,uid,now))
        conn.execute('INSERT INTO exam_proctor_codes(exam_id,code_hash,code_prefix,valid_from,valid_until,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(eid,'unused-delete-code','DEL',now,now+3600,uid,now))
        conn.execute('INSERT INTO proctor_code_failures(exam_id,user_id,failed_at) VALUES(?,?,?)',(eid,uid,now))
        conn.commit()
    return {'exam_id':eid,'other_exam_id':other,'grand_test_id':gid,'paper_id':jid,'question_id':qid,
        'admin_id':uid,'source':source,'result':result,'frozen':frozen}


def test_unused_exam_deletion_detaches_sources_and_preserves_questions_and_caches(deletion_clients):
    admin,_,_=deletion_clients;linked=linked_exam(admin);eid=linked['exam_id']
    before=snapshot(DOMAIN_TABLES)
    response=admin.delete(f'/api/admin/exams/{eid}')
    assert response.status_code==200,response.text
    assert response.json()['deleted']==eid
    assert snapshot(PRESERVED_TABLES)=={table:before[table] for table in PRESERVED_TABLES}
    after=snapshot(DOMAIN_TABLES)
    assert all(row['id']!=eid for row in after['exams'])
    for table in ('exam_questions','exam_versions','exam_blueprints','exam_generation_runs','exam_registration_links','exam_proctor_codes','proctor_code_failures'):
        assert not any(row['exam_id']==eid for row in after[table])
        assert [row for row in after[table] if row['exam_id']==linked['other_exam_id']]==[row for row in before[table] if row['exam_id']==linked['other_exam_id']]
    assert [row for row in after['exams'] if row['id']==linked['other_exam_id']]==[row for row in before['exams'] if row['id']==linked['other_exam_id']]
    workspace=next(row for row in after['grand_tests'] if row['id']==linked['grand_test_id'])
    original=next(row for row in before['grand_tests'] if row['id']==linked['grand_test_id'])
    assert workspace['exam_id'] is None and workspace['status']=='REVIEW_REQUIRED' and workspace['revision']==original['revision']+1
    assert workspace['source_json']==original['source_json'] and workspace['questions_json']==original['questions_json']
    paper=next(row for row in after['program_exam_jobs'] if row['id']==linked['paper_id'])
    assert paper['exam_id'] is None and paper['status']=='REVIEW_REQUIRED'
    assert json.loads(paper['input_json'])==linked['frozen']
    assert json.loads(paper['result_json'])=={key:value for key,value in linked['result'].items() if key!='draft_hash'}
    for table in ('grand_tests','program_exam_jobs'):
        assert [row for row in after[table] if row['exam_id']==linked['other_exam_id']]==[row for row in before[table] if row['exam_id']==linked['other_exam_id']]
    detail=admin.get(f'/api/grand-tests/{linked["grand_test_id"]}')
    assert detail.status_code==200,detail.text
    assert detail.json()['exam_id'] is None and detail.json()['source']==linked['source']
    assert detail.json()['questions']==json.loads(original['questions_json'])
    assert admin.delete(f'/api/admin/exams/{eid}').status_code==404
    assert snapshot(DOMAIN_TABLES)==after
    with closing(app.connect()) as conn:assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]


@pytest.mark.parametrize('history',['registration','attempt','pending_registration','concern'])
def test_student_history_blocks_deletion_without_changing_linked_records(deletion_clients,history):
    admin,student,_=deletion_clients;linked=linked_exam(admin);eid=linked['exam_id'];now=time.time()
    uid=student.get('/api/auth/me').json()['id']
    with closing(app.connect()) as conn:
        if history=='registration':
            conn.execute("INSERT INTO exam_enrollments(exam_id,user_id,status,registered_at,created_at,updated_at) VALUES(?,?,'CANCELLED',?,?,?)",(eid,uid,now,now,now))
        elif history=='attempt':
            # Legacy attempt history must also be protected without enrollment.
            conn.execute("INSERT INTO exam_sessions(exam_id,user_id,registration_id,attempt_number,status,started_at,expires_at,duration_minutes,created_at,updated_at) VALUES(?,?,0,1,'SUBMITTED',?,?,30,?,?)",(eid,uid,now,now+1800,now,now))
        elif history=='pending_registration':
            conn.execute("INSERT INTO pending_exam_registrations(exam_id,registered_email,status,created_by,created_at,updated_at) VALUES(?,?,'LINKED',?,?,?)",(eid,'prior-registration@example.test',linked['admin_id'],now,now))
        else:
            conn.execute("INSERT INTO question_concerns(question_id,exam_id,reporter_id,category,description,status,created_at,updated_at) VALUES(?,?,?,'ANSWER','Reviewed concern','RESOLVED',?,?)",(linked['question_id'],eid,uid,now,now))
        conn.commit()
    before=snapshot(DOMAIN_TABLES)
    response=admin.delete(f'/api/admin/exams/{eid}')
    assert response.status_code==409,response.text
    assert snapshot(DOMAIN_TABLES)==before


def test_deletion_requires_admin_and_valid_csrf(deletion_clients):
    admin,student,anonymous=deletion_clients;linked=linked_exam(admin);path=f'/api/admin/exams/{linked["exam_id"]}'
    before=snapshot(DOMAIN_TABLES)
    assert anonymous.delete(path).status_code==401
    assert student.delete(path).status_code==403
    assert admin.delete(path,headers={'X-CSRF-Token':'incorrect'}).status_code==403
    csrf=admin.headers.pop('X-CSRF-Token')
    try:assert admin.delete(path).status_code==403
    finally:admin.headers['X-CSRF-Token']=csrf
    assert snapshot(DOMAIN_TABLES)==before


def test_unexpected_foreign_key_rolls_back_workspace_detachment_and_delivery_deletes(deletion_clients):
    admin,_,_=deletion_clients;linked=linked_exam(admin);eid=linked['exam_id']
    with closing(app.connect()) as conn:
        conn.execute('CREATE TABLE deletion_external_refs(id INTEGER PRIMARY KEY,exam_id INTEGER NOT NULL REFERENCES exams(id))')
        conn.execute('INSERT INTO deletion_external_refs(id,exam_id) VALUES(1,?)',(eid,));conn.commit()
    before=snapshot(DOMAIN_TABLES+('deletion_external_refs',))
    response=admin.delete(f'/api/admin/exams/{eid}')
    assert response.status_code==409,response.text
    assert snapshot(DOMAIN_TABLES+('deletion_external_refs',))==before
    with closing(app.connect()) as conn:assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]


@pytest.mark.parametrize('published',[False,True],ids=['draft','published'])
def test_deleted_guided_exam_can_be_reviewed_again_without_regeneration(deletion_clients,published):
    from tests.test_program_exam import build,settings
    admin,_,_=deletion_clients
    response=admin.post('/api/programs',json={'code':'RESTORE_PAPER','name':'Restorable paper','status':'ACTIVE'})
    assert response.status_code==201,response.text
    pid=response.json()['id'];job=build(admin,pid,value=settings())
    path=f'/api/programs/{pid}/exam-papers/{job["id"]}'
    approved=admin.post(path+'/approve',json={'reviewed':True,'publish':published})
    assert approved.status_code==200,approved.text
    old_exam_id=approved.json()['exam_id']
    preview=admin.get(path).json()
    question_ids=[item['question']['id'] for item in preview['result']['questions']]
    cache=snapshot(('question_explanation_translations','explanation_jobs'))
    deleted=admin.delete(f'/api/admin/exams/{old_exam_id}')
    assert deleted.status_code==200,deleted.text
    with patch('app.generate_questions',side_effect=AssertionError('Saved paper must not regenerate')),patch('program_exam.structured_call',side_effect=AssertionError('Review must not call AI')):
        restored=admin.get(path)
        assert restored.status_code==200,restored.text
        restored=restored.json()
        assert restored['status']=='REVIEW_REQUIRED' and restored['exam_id'] is None
        assert restored['input']==preview['input']
        assert restored['result']['questions']==preview['result']['questions']
        reapproved=admin.post(path+'/approve',json={'reviewed':True,'publish':True,'review_updated_at':restored['updated_at']})
        assert reapproved.status_code==200,reapproved.text
    new_exam_id=reapproved.json()['exam_id']
    assert new_exam_id!=old_exam_id and reapproved.json()['status']=='PUBLISHED'
    with closing(app.connect()) as conn:
        assert [row['question_id'] for row in conn.execute('SELECT question_id FROM exam_questions WHERE exam_id=? ORDER BY display_order',(new_exam_id,)).fetchall()]==question_ids
        assert conn.execute('SELECT COUNT(*) FROM questions').fetchone()[0]==len(question_ids)
    assert snapshot(('question_explanation_translations','explanation_jobs'))==cache
