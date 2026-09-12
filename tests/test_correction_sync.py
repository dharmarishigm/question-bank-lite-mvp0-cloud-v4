import json,time
import app
from tests.test_programs import clients,create
from tests.test_program_exam import build
from tests.test_question_correction import fields


def test_admin_takes_exam_and_does_not_enter_student_ranking(clients):
    admin,student,anonymous=clients
    q=admin.post('/api/questions',json={'statement':'2+2?','options':['3','4'],'answer':'B','solution':'Four','subject':'Maths'}).json()
    e=admin.post('/api/admin/exams',json={'name':'Admin participation','status':'OPEN','exam_start_at':time.time()-60,'allow_self_registration':False,'question_ids':[q['id']]}).json()
    path=f'/api/exams/{e["id"]}'
    assert student.post(path+'/enroll').status_code==403
    assert anonymous.post(path+'/enroll').status_code==401
    assert admin.post(path+'/enroll').status_code==200
    start=admin.post(f'/api/student/exams/{e["id"]}/start',json={'consent':True});assert start.status_code==200,start.text
    sid=start.json()['session_id']
    assert student.get(f'/api/sessions/{sid}').status_code==404
    assert admin.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'}).status_code==200
    assert admin.post(f'/api/sessions/{sid}/submit').status_code==200
    assert admin.get(path+'/leaderboard').json()['entries']==[]


def test_corrected_versions_future_attempts_and_historical_notices(clients):
    admin,student,_=clients
    q=admin.post('/api/questions',json={'statement':'2+2?','options':['3','4'],'answer':'B','solution':'Four','subject':'Maths','verification_status':'APPROVED'}).json()
    e=admin.post('/api/admin/exams',json={'name':'Versioned exam','status':'OPEN','exam_start_at':time.time()-60,'question_ids':[q['id']]}).json()
    student.post(f'/api/exams/{e["id"]}/enroll')
    sid=student.post(f'/api/student/exams/{e["id"]}/start',json={'consent':True}).json()['session_id']
    student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'})
    with app.connect() as conn:
        before=dict(conn.execute('SELECT * FROM exam_versions WHERE id=(SELECT current_version_id FROM exams WHERE id=?)',(e['id'],)).fetchone())
        original=conn.execute('SELECT question_set_json FROM exam_sessions WHERE id=?',(sid,)).fetchone()['question_set_json']
    value={**fields(q),'options':['4','5'],'answer':'A','solution':'Corrected option order.'}
    response=admin.put(f'/api/admin/question-corrections/{q["id"]}',json={'original':fields(q),'question':value,'reviewed':True});assert response.status_code==200,response.text
    with app.connect() as conn:
        latest=conn.execute('SELECT * FROM exam_versions WHERE id=(SELECT current_version_id FROM exams WHERE id=?)',(e['id'],)).fetchone()
        assert latest['id']!=before['id']
        assert json.loads(latest['question_snapshot_json'])[0]['answer']=='A'
        assert conn.execute('SELECT question_snapshot_json FROM exam_versions WHERE id=?',(before['id'],)).fetchone()['question_snapshot_json']==before['question_snapshot_json']
        assert conn.execute('SELECT question_set_json FROM exam_sessions WHERE id=?',(sid,)).fetchone()['question_set_json']==original
    active=student.get(f'/api/sessions/{sid}').json()['questions'][0]
    assert active['options']==['4','5'] and active['selected_answer']==''
    assert active['content_corrected'] and active['response_review_required']
    assert 'answer' not in active and 'solution' not in active
    assert student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'A','content_revision':active['content_revision']}).status_code==200
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    report=student.get(f'/api/my/results/{sid}').json()
    assert report['questions'][0]['is_correct'] and report['questions'][0]['answer']=='A'
    assert admin.post(f'/api/exams/{e["id"]}/enroll').status_code==200
    fresh=admin.post(f'/api/student/exams/{e["id"]}/start',json={'consent':True}).json()['session_id']
    assert admin.get(f'/api/sessions/{fresh}').json()['questions'][0]['options']==['4','5']


def test_all_program_previews_sync_but_old_review_cannot_publish(clients):
    admin,_,_=clients;pid=create(admin)['id'];a=build(admin,pid)
    admin.post(f'/api/programs/{pid}/exam-papers/{a["id"]}/approve',json={'reviewed':True,'publish':True})
    b=build(admin,pid,key='second-paper-correction');q=admin.get('/api/questions/'+str(a['result']['questions'][0]['question']['id'])).json()
    value={**fields(q),'solution':'Corrected explanation across every linked paper.'}
    r=admin.put(f'/api/admin/question-corrections/{q["id"]}',json={'original':fields(q),'question':value,'reviewed':True});assert r.status_code==200,r.text
    assert 'precomputed_explanations' not in r.json()['generation_metadata']
    with app.connect() as conn:
        saved=conn.execute('SELECT generation_metadata FROM questions WHERE id=?',(q['id'],)).fetchone()
        assert 'precomputed_explanations' not in json.loads(saved['generation_metadata'])
    for jid in [a['id'],b['id']]:
        current=admin.get(f'/api/programs/{pid}/exam-papers/{jid}').json();assert current['result']['questions'][0]['question']['solution']==value['solution']
    path=f'/api/programs/{pid}/exam-papers/{b["id"]}/approve'
    assert admin.post(path,json={'reviewed':True,'publish':True,'review_updated_at':b['updated_at']}).status_code==409
    assert admin.post(path,json={'reviewed':True,'publish':True,'review_updated_at':current['updated_at']}).status_code==200


def test_correction_version_does_not_publish_unrelated_bank_edits(clients):
    admin,_,_=clients
    values={'statement':'Original','options':['1','2'],'answer':'B','solution':'Original solution','verification_status':'APPROVED'}
    a=admin.post('/api/questions',json=values).json();b=admin.post('/api/questions',json={**values,'statement':'Second original'}).json()
    exam=admin.post('/api/admin/exams',json={'name':'Selective correction','status':'OPEN','exam_start_at':time.time()-60,'question_ids':[a['id'],b['id']]}).json()
    with app.connect() as conn:
        conn.execute('UPDATE questions SET statement=? WHERE id=?',('Unreviewed unrelated bank change',b['id']));conn.commit()
    r=admin.put(f'/api/admin/question-corrections/{a["id"]}',json={'original':fields(a),'question':{**fields(a),'statement':'Reviewed correction'},'reviewed':True});assert r.status_code==200
    with app.connect() as conn:
        version=conn.execute('SELECT question_snapshot_json FROM exam_versions WHERE id=(SELECT current_version_id FROM exams WHERE id=?)',(exam['id'],)).fetchone()
    qs=json.loads(version['question_snapshot_json']);assert qs[0]['statement']=='Reviewed correction' and qs[1]['statement']=='Second original'


def test_legacy_saved_run_resolves_to_current_bank_after_correction(clients):
    from tests.test_ai_batch_review import batch
    admin,_,_=clients;run=batch(admin,'Physics')
    saved=admin.post('/api/ai/review/save',json={'batches':[{'run_id':run['run_id'],'indices':[0]}],'reviewed':True}).json();qid=saved['items'][0]['question_id']
    q=admin.get(f'/api/questions/{qid}').json()
    # A legacy run may lack the saved-question link, and preserve old generated text.
    with app.connect() as conn:
        original=conn.execute('SELECT output_json FROM ai_generation_runs WHERE id=?',(run['run_id'],)).fetchone()['output_json']
        payload=json.loads(original);payload['questions'][0].pop('saved_question_id',None)
        conn.execute('UPDATE ai_generation_runs SET output_json=? WHERE id=?',(json.dumps(payload),run['run_id']));conn.commit()
    changed={**fields(q),'statement':'Corrected saved generation','options':['4','5','6','7'],'answer':'A'}
    assert admin.put(f'/api/admin/question-corrections/{qid}',json={'original':fields(q),'question':changed,'reviewed':True}).status_code==200
    with app.connect() as conn:
        propagated=json.loads(conn.execute('SELECT output_json FROM ai_generation_runs WHERE id=?',(run['run_id'],)).fetchone()['output_json'])['questions'][0]
        assert propagated['explanation_en']=='' and propagated['explanation_te']==''
    # Restore an old output blob to verify read-time resolution, not only propagation.
    with app.connect() as conn:conn.execute('UPDATE ai_generation_runs SET output_json=? WHERE id=?',(json.dumps(payload),run['run_id']));conn.commit()
    preview=admin.get(f'/api/ai/runs/{run["run_id"]}').json()['output']['questions'][0]
    assert preview['saved_question_id']==qid and preview['statement']==changed['statement'] and preview['options'][0]['text']=='4'
    assert preview['explanation_en']=='' and preview['explanation_te']==''


def test_saved_preview_reads_current_explanation_cache_instead_of_old_run_text(clients):
    from tests.test_ai_batch_review import batch
    admin,_,_=clients;run=batch(admin,'Physics')
    saved=admin.post('/api/ai/review/save',json={'batches':[{'run_id':run['run_id'],'indices':[0]}],'reviewed':True}).json();qid=saved['items'][0]['question_id']
    with app.connect() as conn:
        conn.execute("UPDATE question_explanation_translations SET explanation='Current cached explanation' WHERE question_id=? AND language='en'",(qid,));conn.commit()
    preview=admin.get(f'/api/ai/runs/{run["run_id"]}').json()['output']['questions'][0]
    assert preview['explanation_en']=='Current cached explanation'
