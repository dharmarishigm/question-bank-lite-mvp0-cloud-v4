"""A reviewed correction changes active display and grading together."""
import json
import time

import app
from platform_api import _question_content_revision
from tests.test_programs import clients
from tests.test_question_correction import fields


def attempt(admin,student,release='IMMEDIATE',question_changes=None):
    question=admin.post('/api/questions',json={'statement':'What is two plus two?',
        'options':['3','4'],'answer':'B','solution':'Four.','verification_status':'APPROVED',**(question_changes or {})}).json()
    exam=admin.post('/api/admin/exams',json={'name':'Correction synchronization',
        'status':'OPEN','exam_start_at':time.time()-60,'question_ids':[question['id']],
        'result_release_mode':release}).json()
    assert student.post(f'/api/exams/{exam["id"]}/enroll').status_code==200
    started=student.post(f'/api/student/exams/{exam["id"]}/start',json={'consent':True})
    assert started.status_code==200,started.text
    sid=started.json()['session_id']
    return question,exam,sid


def correct(admin,question,**changes):
    result=admin.put(f'/api/admin/question-corrections/{question["id"]}',
        json={'original':fields(question),'question':{**fields(question),**changes},'reviewed':True})
    assert result.status_code==200,result.text
    return result.json()


def test_active_changed_options_reset_only_response_and_reject_stale_save(clients):
    admin,student,_=clients;q,e,sid=attempt(admin,student)
    before=student.get(f'/api/sessions/{sid}').json()['questions'][0]
    path=f'/api/sessions/{sid}/answers/{q["id"]}'
    assert student.put(path,json={'selected_answer':'B','content_revision':before['content_revision']}).status_code==200
    with app.connect() as conn:
        original=dict(conn.execute('SELECT * FROM exam_sessions WHERE id=?',(sid,)).fetchone())
    correct(admin,q,options=['4','5'],answer='A',solution='Corrected option order.')
    active=student.get(f'/api/sessions/{sid}').json()['questions'][0]
    assert active['options']==['4','5'] and active['selected_answer']==''
    assert active['content_corrected'] and active['response_review_required']
    assert 'answer' not in active and 'solution' not in active
    assert active['content_revision']!=before['content_revision']
    with app.connect() as conn:
        session=dict(conn.execute('SELECT * FROM exam_sessions WHERE id=?',(sid,)).fetchone())
        for key in ('exam_version_id','started_at','expires_at','duration_minutes','section_timing_json'):
            assert session[key]==original[key]
        old_question=json.loads(original['question_set_json'])[0]
        new_question=json.loads(session['question_set_json'])[0]
        for key in ('marks','negative_marks','display_order','section_name'):
            assert old_question[key]==new_question[key]
        audits=conn.execute("SELECT metadata_json FROM exam_audit_log WHERE session_id=? AND event_type='ACTIVE_QUESTION_CORRECTED'",(sid,)).fetchall()
        assert len(audits)==1
        metadata=json.loads(audits[0]['metadata_json'])
        assert metadata['original_question']['options']==['3','4']
        assert metadata['prior_response']['selected_answer']=='B'
    assert student.put(path,json={'selected_answer':'B','content_revision':before['content_revision']}).status_code==409
    assert student.put(path,json={'selected_answer':'B'}).status_code==409
    assert student.put(f'/api/student/sessions/{sid}/questions/{q["id"]}/review',json={'marked':True,'content_revision':before['content_revision']}).status_code==409
    assert student.post(f'/api/sessions/{sid}/submit').status_code==409
    saved=student.put(path,json={'selected_answer':'A','content_revision':active['content_revision']})
    assert saved.status_code==200 and not saved.json()['response_review_required']
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    result=student.get(f'/api/my/results/{sid}').json()
    assert result['questions'][0]['answer']=='A' and result['questions'][0]['is_correct']
    assert result['session']['score']==1


def test_answer_only_correction_retains_selection_and_uses_corrected_grading(clients):
    admin,student,_=clients;q,_,sid=attempt(admin,student)
    visible=student.get(f'/api/sessions/{sid}').json()['questions'][0]
    assert student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'A'}).status_code==200
    correct(admin,q,answer='A',solution='Reviewed answer key.')
    updated=student.get(f'/api/sessions/{sid}').json()['questions'][0]
    assert updated['selected_answer']=='A' and not updated['response_review_required']
    assert updated['content_revision']==visible['content_revision']
    assert updated['content_corrected']
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    assert student.get(f'/api/my/results/{sid}').json()['session']['score']==1


def test_submitted_scores_and_snapshot_survive_corrected_primary_review(clients):
    admin,student,_=clients;q,_,sid=attempt(admin,student)
    assert student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'}).status_code==200
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    with app.connect() as conn:
        original=dict(conn.execute('SELECT * FROM exam_sessions WHERE id=?',(sid,)).fetchone())
    correct(admin,q,statement='Reviewed replacement.',options=['4','5'],answer='A')
    for client,path in [(student,f'/api/my/results/{sid}'),(admin,f'/api/admin/results/{sid}')]:
        result=client.get(path).json();item=result['questions'][0]
        assert item['statement']=='Reviewed replacement.' and item['answer']=='A'
        assert item['original_answer']=='B' and item['original_question']['options']==['3','4']
        assert item['historical_grading'] and item['is_correct']
        assert result['session']['score']==1
    with app.connect() as conn:
        stored=dict(conn.execute('SELECT * FROM exam_sessions WHERE id=?',(sid,)).fetchone())
        assert stored==original


def test_unapproved_bank_changes_never_replace_active_content(clients):
    admin,student,_=clients;q,_,sid=attempt(admin,student)
    with app.connect() as conn:
        conn.execute("UPDATE questions SET statement='Unreviewed draft',answer='A',verification_status='REVIEW_REQUIRED' WHERE id=?",(q['id'],));conn.commit()
    item=student.get(f'/api/sessions/{sid}').json()['questions'][0]
    assert item['statement']==q['statement'] and not item['content_corrected']
    assert student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'}).status_code==200
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    assert student.get(f'/api/my/results/{sid}').json()['session']['score']==1


def test_submit_detects_unseen_correction_and_expiry_still_completes(clients):
    admin,student,_=clients;q,_,sid=attempt(admin,student)
    assert student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'}).status_code==200
    correct(admin,q,statement='Updated question wording.',options=['4','5'],answer='A')
    assert student.post(f'/api/sessions/{sid}/submit').status_code==409
    with app.connect() as conn:
        row=conn.execute('SELECT question_set_json,status FROM exam_sessions WHERE id=?',(sid,)).fetchone()
        assert row['status']=='IN_PROGRESS' and json.loads(row['question_set_json'])[0]['response_review_required']
        conn.execute('UPDATE exam_sessions SET expires_at=? WHERE id=?',(time.time()-1,sid));conn.commit()
    result=student.get(f'/api/sessions/{sid}').json()
    assert result['session']['status']=='AUTO_SUBMITTED'
    report=student.get(f'/api/my/results/{sid}').json()
    assert report['session']['unanswered_count']==1 and report['session']['score']==0


def test_same_embedded_figure_metadata_does_not_reset_an_existing_response(clients):
    admin,student,_=clients
    asset={'type':'diagram','asset':'/uploads/unchanged-figure.png','description':'A visible diagram'}
    q,_,sid=attempt(admin,student,question_changes={'visual_assets':[asset]})
    with app.connect() as conn:
        snapshot=json.loads(conn.execute('SELECT question_set_json FROM exam_sessions WHERE id=?',(sid,)).fetchone()['question_set_json'])
        assert asset['asset'] in snapshot[0]['statement'] and not snapshot[0].get('visual_assets')
        conn.execute("INSERT INTO exam_answers(session_id,question_id,selected_answer,is_answered,status,updated_at) VALUES(?,?,?,1,'ANSWERED',?)",(sid,q['id'],'B',time.time()));conn.commit()
    visible=student.get(f'/api/sessions/{sid}').json()['questions'][0]
    assert visible['selected_answer']=='B' and not visible['response_review_required']
    assert not visible['content_corrected']
    assert visible['content_revision']==_question_content_revision(snapshot[0])
    with app.connect() as conn:
        assert not conn.execute("SELECT 1 FROM exam_audit_log WHERE session_id=? AND event_type='ACTIVE_QUESTION_CORRECTED'",(sid,)).fetchone()
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    assert student.get(f'/api/my/results/{sid}').json()['session']['score']==1


def test_unreleased_results_never_expose_raw_snapshot_answers_or_corrections(clients):
    admin,student,_=clients;q,_,sid=attempt(admin,student,release='AFTER_EXAM_CLOSE',
        question_changes={'solution':'Private unreleased worked solution sentinel'})
    assert student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'}).status_code==200
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    correct(admin,q,solution='Private corrected explanation sentinel')
    detail=student.get(f'/api/my/results/{sid}')
    assert detail.status_code==200 and not detail.json()['released']
    assert detail.json()['questions']==[] and 'question_set_json' not in detail.json()['session']
    listing=student.get('/api/my/results')
    assert listing.status_code==200 and all('question_set_json' not in row for row in listing.json())
    for response in (detail,listing):
        assert 'Private unreleased worked solution sentinel' not in response.text
        assert 'Private corrected explanation sentinel' not in response.text


def test_session_hides_answer_figures_but_released_results_keep_them(clients):
    admin,student,_=clients
    diagram={'type':'diagram','asset':'/uploads/public-question-diagram.png','description':'Question diagram'}
    answer_figure={'type':'answer_figures','asset':'/uploads/private-answer-figure-sentinel.png','description':'Answer diagram'}
    q,e,sid=attempt(admin,student,release='AFTER_EXAM_CLOSE',question_changes={'visual_assets':[diagram,answer_figure]})
    active=student.get(f'/api/sessions/{sid}')
    assert active.status_code==200 and diagram['asset'] in active.text
    assert answer_figure['asset'] not in active.text
    assert active.json()['questions'][0]['visual_assets']==[diagram]
    assert student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'}).status_code==200
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    correct(admin,q,statement='Reviewed diagram wording.')
    completed=student.get(f'/api/sessions/{sid}')
    assert completed.status_code==200 and diagram['asset'] in completed.text
    assert answer_figure['asset'] not in completed.text
    pending=student.get(f'/api/my/results/{sid}')
    assert not pending.json()['released'] and answer_figure['asset'] not in pending.text
    with app.connect() as conn:
        conn.execute("UPDATE exams SET status='CLOSED' WHERE id=?",(e['id'],));conn.commit()
    released=student.get(f'/api/my/results/{sid}')
    assert released.json()['released'] and answer_figure['asset'] in released.text
