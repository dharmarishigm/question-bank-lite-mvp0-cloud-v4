"""Guided exam integration tests: shared generation, review and publication."""
from unittest.mock import patch
import pytest
from tests.test_programs import clients, create
from llm_generate import GeneratedQuestionBatch, GeneratedQuestion, GeneratedOption
from program_exam import CurriculumSuggestion, CompleteSuggestion, Section


def settings(**changes):
    return {'name':'Navodaya practice', 'mode':'FULL', 'level':'VI', 'language':'English',
        'duration_minutes':90, 'difficulty':'medium', 'curriculum':'Fractions and number reasoning.',
        'pattern':'Custom practice paper, single correct MCQs.', 'instructions':'Answer all questions.',
        'generation_prompt':'Cover the supplied topics with original reasoning questions.',
        'sections':[{'subject':'Arithmetic','count':2,'marks':2.5,'negative_marks':.5,'topics':'Fractions'}],
        'reuse_questions':True, **changes}


def author(request):
    return GeneratedQuestionBatch(questions=[GeneratedQuestion(
        statement=f'{request.subject} {request.difficulty}: Find the value for problem {i+1}.',
        options=[GeneratedOption(label=chr(65+j),text=str(j+1)) for j in range(4)],
        answer='B',solution='The answer is 2, by the stated calculation.',
        explanation_en='The stored English explanation connects the concept, calculation, and answer.',
        explanation_te='నిల్వ చేసిన తెలుగు వివరణ భావన, లెక్కింపు మరియు సమాధానాన్ని వివరిస్తుంది.',
        subject=request.subject,qtype='mcq_single',difficulty=request.difficulty)
        for i in range(request.count)]), {}, 'mock-model'


def build(admin, pid, value=None, key='paper-request-001'):
    with patch('app.generate_questions',side_effect=author):
        result=admin.post(f'/api/programs/{pid}/exam-papers',json={'request_key':key,'settings':value or settings()})
    assert result.status_code==202,result.text
    return admin.get(f'/api/programs/{pid}/exam-papers').json()[0]


@pytest.mark.parametrize('difficulty',['very_easy','easy','medium','hard','very_hard'])
def test_difficulty_generation_review_publish_and_reuse(clients,difficulty):
    admin,student,anonymous=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    value=settings(difficulty=difficulty)
    job=build(admin,pid,value)
    assert job['status']=='REVIEW_REQUIRED',job
    assert job['result']['generated']==2 and job['exam_id'] is None
    assert difficulty in job['input']['effective_prompt']
    questions=admin.get('/api/questions').json()['items']
    assert len(questions)==2 and all(q['verification_status']=='REVIEW_REQUIRED' for q in questions)
    assert all(q['difficulty']==difficulty for q in questions)
    with patch('app.llm_status',side_effect=AssertionError('Generated explanation must be cached')):
        assert admin.get(f'/api/questions/{questions[0]["id"]}/explain?language=en').json()['cached'] is True
        assert admin.get(f'/api/questions/{questions[0]["id"]}/explain?language=te').json()['cached'] is True
    path=root+f'/exam-papers/{job["id"]}/approve'
    assert student.post(path,json={'reviewed':True,'publish':True}).status_code==403
    assert anonymous.get(root+'/exam-papers').status_code==401
    assert admin.post(path,json={'reviewed':False,'publish':True}).status_code==422
    saved=admin.post(path,json={'reviewed':True,'publish':True})
    assert saved.status_code==200,saved.text
    eid=saved.json()['exam_id']
    exam=admin.get(f'/api/exams/{eid}').json()
    assert exam['status']=='PUBLISHED' and exam['total_marks']==5 and exam['duration_minutes']==90
    assert exam['current_version_id']
    assert admin.post(path,json={'reviewed':True,'publish':True}).json()['exam_id']==eid
    replay=build(admin,pid,value)
    assert replay['id']==job['id']
    with patch('app.generate_questions',side_effect=AssertionError('Must reuse matching approved bank questions')):
        reused=admin.post(root+'/exam-papers',json={'request_key':'reuse-request-002','settings':value})
    assert reused.status_code==202
    next_job=admin.get(root+'/exam-papers').json()[0]
    assert next_job['status']=='REVIEW_REQUIRED' and next_job['result']['reused']==2


def test_subject_scope_full_sections_and_prompt(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    value=settings(sections=[{'subject':'Arithmetic','count':2},{'subject':'Language','count':1}])
    job=build(admin,pid,value)
    assert job['status']=='REVIEW_REQUIRED',job
    assert [q['section']['subject'] for q in job['result']['questions']]==['Arithmetic','Arithmetic','Language']
    invalid=admin.post(root+'/exam-papers',json={'request_key':'invalid-subject','settings':{**value,'mode':'SUBJECT'}})
    assert invalid.status_code==422
    scoped=settings(mode='SUBJECT',difficulty='very_hard',sections=[{'subject':'Language','count':1}],generation_prompt='My edited prompt: vocabulary only.')
    one=build(admin,pid,scoped,key='subject-request-002')
    assert one['status']=='REVIEW_REQUIRED'
    assert one['result']['questions'][0]['question']['subject']=='Language'
    preview=admin.post(root+'/exam-prompt',json=scoped).json()['effective_prompt']
    for expected in ['vocabulary only','very_hard','Language','90','Fractions and number reasoning']:
        assert expected in preview


def test_additional_conditions_are_frozen_into_final_prompt(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    condition='Include exactly one data-interpretation question and avoid calculator-dependent arithmetic.'
    value=settings(additional_conditions=condition)
    preview=admin.post(root+'/exam-prompt',json=value).json()['effective_prompt']
    assert 'Additional conditions supplied by the administrator' in preview and condition in preview
    job=build(admin,pid,value,key='additional-condition-paper')
    assert job['input']['settings']['additional_conditions']==condition
    assert condition in job['input']['effective_prompt']


def test_failed_generation_atomicity_retry_and_stale_preview(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    with patch('app.generate_questions',side_effect=RuntimeError('secret upstream error')):
        admin.post(root+'/exam-papers',json={'request_key':'failed-request','settings':settings()})
    job=admin.get(root+'/exam-papers').json()[0]
    assert job['status']=='FAILED' and 'secret' not in job['error']
    assert not admin.get('/api/questions').json()['items']
    with patch('app.generate_questions',side_effect=author):
        assert admin.post(root+f'/exam-papers/{job["id"]}/retry').status_code==202
    job=admin.get(root+'/exam-papers').json()[0]
    assert job['status']=='REVIEW_REQUIRED'
    q=job['result']['questions'][0]['question']
    assert admin.put(f'/api/questions/{q["id"]}',json={**q,'statement':'Changed after review'}).status_code==200
    assert admin.post(root+f'/exam-papers/{job["id"]}/approve',json={'reviewed':True,'publish':True}).status_code==409


def test_draft_then_publish_and_external_edit_guard(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    job=build(admin,pid)
    path=root+f'/exam-papers/{job["id"]}/approve'
    result=admin.post(path,json={'reviewed':True,'publish':False})
    assert result.status_code==200,result.text
    assert result.json()['status']=='DRAFT'
    assert admin.post(path,json={'reviewed':True,'publish':True}).json()['status']=='PUBLISHED'
    second=build(admin,pid,key='second-draft-job')
    path=root+f'/exam-papers/{second["id"]}/approve'
    assert admin.post(path,json={'reviewed':True,'publish':False}).status_code==200
    q=second['result']['questions'][0]['question']
    admin.put(f'/api/questions/{q["id"]}',json={**q,'solution':'Changed after draft review'})
    assert admin.post(path,json={'reviewed':True,'publish':True}).status_code==409


def test_on_demand_suggestions_and_idempotency_conflict(clients):
    admin,student,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    with patch('program_exam.structured_call',return_value=(CurriculumSuggestion(curriculum='Editable syllabus',subjects=['Arithmetic']),{'model':'mock'})) as call:
        response=admin.post(root+'/exam-assist',json={'field':'curriculum','settings':settings()})
        assert response.status_code==200,response.text
        assert call.call_count==1
    assert admin.get(root+'/exam-papers').json()==[]
    proposal=CompleteSuggestion(curriculum='Fractions and numbers',level='VI',pattern='Suggested custom pattern',
        duration_minutes=90,sections=[Section(subject='Arithmetic',count=2)],generation_prompt='Use the selected difficulty and syllabus.')
    with patch('program_exam.structured_call',return_value=(proposal,{'model':'mock'})):
        all_inputs=admin.post(root+'/exam-assist',json={'field':'all','settings':settings(difficulty='very_easy')})
        assert all_inputs.status_code==200,all_inputs.text
        assert all_inputs.json()['level']=='VI' and len(all_inputs.json()['sections'])==1
    assert student.post(root+'/exam-assist',json={'field':'prompt','settings':settings()}).status_code==403
    job=build(admin,pid)
    conflict=admin.post(root+'/exam-papers',json={'request_key':'paper-request-001','settings':settings(difficulty='hard')})
    assert conflict.status_code==409
    admin.headers.pop('X-CSRF-Token')
    assert admin.post(root+f'/exam-papers/{job["id"]}/approve',json={'reviewed':True}).status_code==403


def test_large_paper_batches_and_partial_failure_do_not_save_partial_bank(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    calls=[]
    def sequential(request):
        calls.append(request.count)
        batch,usage,model=author(request)
        for q in batch.questions:q.statement=f'Batch {len(calls)}: '+q.statement
        return batch,usage,model
    value=settings(sections=[{'subject':'Arithmetic','count':80}])
    with patch('app.generate_questions',side_effect=sequential):
        admin.post(root+'/exam-papers',json={'request_key':'large-paper-key','settings':value})
    job=admin.get(root+'/exam-papers').json()[0]
    assert job['status']=='REVIEW_REQUIRED',job
    assert calls==[10]*8 and job['result']['generated']==80
    before=admin.get('/api/questions').json()['total']
    def partial(request):
        if request.subject=='Language':raise RuntimeError('Second section unavailable')
        batch,usage,model=author(request)
        for q in batch.questions:q.statement='A new partial draft: '+q.statement
        return batch,usage,model
    with patch('app.generate_questions',side_effect=partial):
        admin.post(root+'/exam-papers',json={'request_key':'partial-paper-key','settings':settings(sections=[{'subject':'Arithmetic','count':1},{'subject':'Language','count':1}])})
    assert admin.get(root+'/exam-papers').json()[0]['status']=='FAILED'
    assert admin.get('/api/questions').json()['total']==before


def test_wrong_subject_or_difficulty_cannot_fill_slots(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    def invalid(request):
        batch,usage,model=author(request)
        for q in batch.questions:q.difficulty='hard';q.subject='Unrelated'
        return batch,usage,model
    with patch('app.generate_questions',side_effect=invalid):
        admin.post(root+'/exam-papers',json={'request_key':'invalid-paper-key','settings':settings()})
    assert admin.get(root+'/exam-papers').json()[0]['status']=='FAILED'
    assert not admin.get('/api/questions').json()['items']


def test_rejected_bank_question_blocks_draft_publication(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    job=build(admin,pid);path=root+f'/exam-papers/{job["id"]}/approve'
    assert admin.post(path,json={'reviewed':True,'publish':False}).status_code==200
    qid=job['result']['questions'][0]['question']['id']
    assert admin.put(f'/api/ai/questions/{qid}/status',json={'status':'REJECTED'}).status_code==200
    assert admin.post(path,json={'reviewed':True,'publish':True}).status_code==409


def test_checkpoint_retry_keeps_completed_batches(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    calls=[]
    def interrupted(request):
        calls.append(request.count)
        if len(calls)>1:raise RuntimeError('Temporary upstream failure')
        batch,usage,model=author(request)
        for q in batch.questions:q.statement='Checkpoint original: '+q.statement
        return batch,usage,model
    with patch('app.generate_questions',side_effect=interrupted),patch('program_exam.time.sleep'):
        admin.post(root+'/exam-papers',json={'request_key':'checkpoint-request','settings':settings(sections=[{'subject':'Arithmetic','count':13}])})
    job=admin.get(root+'/exam-papers').json()[0]
    assert job['status']=='FAILED' and job['result']['progress']['completed']==10
    assert admin.get('/api/questions').json()['total']==0
    stems=[x['question']['statement'] for x in job['result']['questions']]
    resumed=[]
    def remaining(request):
        resumed.append(request.count)
        return author(request)
    with patch('app.generate_questions',side_effect=remaining):
        admin.post(root+f'/exam-papers/{job["id"]}/retry')
    job=admin.get(root+'/exam-papers').json()[0]
    assert job['status']=='REVIEW_REQUIRED' and resumed==[3]
    assert len(job['result']['questions'])==13
    assert [x['question']['statement'] for x in job['result']['questions'][:10]]==stems
    assert admin.get('/api/questions').json()['total']==13


def test_manual_batch_save_does_not_break_paper_and_is_reusable(clients):
    import app
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    original=app.generate_ai_questions_core
    def save_during_generation(payload):
        batch=original(payload)
        saved=admin.post(f'/api/ai/runs/{batch["run_id"]}/save',json={})
        assert saved.status_code==200,saved.text
        return batch
    with patch('app.generate_questions',side_effect=author),patch('app.generate_ai_questions_core',side_effect=save_during_generation):
        admin.post(root+'/exam-papers',json={'request_key':'manual-save-during-paper','settings':settings()})
    job=admin.get(root+'/exam-papers').json()[0]
    assert job['status']=='REVIEW_REQUIRED',job
    assert admin.get('/api/questions').json()['total']==2
    with patch('app.generate_questions',side_effect=AssertionError('Saved batches must be reused')):
        admin.post(root+'/exam-papers',json={'request_key':'reuse-manual-batch','settings':settings()})
    job=admin.get(root+'/exam-papers').json()[0]
    assert job['status']=='REVIEW_REQUIRED' and job['result']['reused']==2


def test_compatible_question_corrected_during_generation_is_finalized_for_review(clients):
    import app
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    original=app.generate_ai_questions_core
    def save_and_correct_during_generation(payload):
        batch=original(payload)
        saved=admin.post(f'/api/ai/runs/{batch["run_id"]}/save',json={})
        assert saved.status_code==200,saved.text
        question=admin.get('/api/questions').json()['items'][0]
        corrected=admin.put(f'/api/questions/{question["id"]}',json={**question,'solution':'Administrator-corrected solution retained for review.'})
        assert corrected.status_code==200,corrected.text
        return batch
    with patch('app.generate_questions',side_effect=author),patch('app.generate_ai_questions_core',side_effect=save_and_correct_during_generation):
        admin.post(root+'/exam-papers',json={'request_key':'corrected-during-finalization','settings':settings()})
    job=admin.get(root+'/exam-papers').json()[0]
    assert job['status']=='REVIEW_REQUIRED',job
    assert any(item['question']['solution']=='Administrator-corrected solution retained for review.' for item in job['result']['questions'])


def test_repeated_click_joins_identical_running_paper(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    with patch('program_exam.run_build') as worker:
        first=admin.post(root+'/exam-papers',json={'request_key':'first-generate-click','settings':settings()})
        second=admin.post(root+'/exam-papers',json={'request_key':'second-generate-click','settings':settings()})
        assert first.json()['id']==second.json()['id']
        assert worker.call_count==1


def test_reused_bank_figures_survive_review_and_published_snapshot(clients):
    from program_exam import scope_hash,Settings,Section
    from platform_api import db
    from contextlib import closing
    import json
    admin,_,_=clients;pid=create(admin)['id'];value=settings(sections=[{'subject':'Arithmetic','count':1}])
    scope=scope_hash(pid,Settings.model_validate(value),Section(subject='Arithmetic',count=1))
    q={'subject':'Arithmetic','qtype':'mcq_single','difficulty':'medium','statement':'Identify this figure.','options':['A','B','C','D'],'answer':'A','solution':'The figure matches A.','verification_status':'APPROVED','generation_metadata':{'extra_metadata':{'program_exam_scope':scope}},'visual_assets':[{'type':'diagram','asset':'/uploads/bank-figure.png'}]}
    assert admin.post('/api/questions',json=q).status_code==200
    with patch('app.generate_questions',side_effect=AssertionError('Reuse the approved figure')):
        admin.post(f'/api/programs/{pid}/exam-papers',json={'request_key':'reuse-bank-figure','settings':value})
    job=admin.get(f'/api/programs/{pid}/exam-papers').json()[0]
    assert job['status']=='REVIEW_REQUIRED'
    assert '/uploads/bank-figure.png' in job['result']['questions'][0]['question']['statement']
    response=admin.post(f'/api/programs/{pid}/exam-papers/{job["id"]}/approve',json={'reviewed':True,'publish':True})
    assert response.status_code==200,response.text
    eid=response.json()['exam_id']
    assert '/uploads/bank-figure.png' in admin.get(f'/api/admin/exams/{eid}/paper').json()['questions'][0]['statement']
    with closing(db()) as conn:
        frozen=json.loads(conn.execute('SELECT question_snapshot_json FROM exam_versions WHERE exam_id=?',(eid,)).fetchone()[0])
    assert '/uploads/bank-figure.png' in frozen[0]['statement']


def test_saved_setup_authorization_revision_and_persistence(clients):
    admin,student,anonymous=clients;pid=create(admin)['id'];path=f'/api/programs/{pid}/exam-setup'
    assert admin.get(path).json() is None
    assert anonymous.get(path).status_code==401
    assert student.put(path,json={'settings':settings()}).status_code==403
    first=admin.put(path,json={'settings':settings()});assert first.status_code==200,first.text
    assert first.json()['revision']==1
    assert admin.put(path,json={'settings':settings()}).status_code==409
    edited=settings(generation_prompt='Saved custom authoring instructions.')
    assert admin.put(path,json={'settings':edited,'revision':1}).json()['revision']==2
    assert admin.get(path).json()['settings']['generation_prompt']==edited['generation_prompt']
    assert admin.get(f'/api/programs/{pid}/exam-papers').json()==[]
    assert admin.put(path,json={'settings':settings(curriculum=''),'revision':2}).status_code==422
    assert admin.delete(f'/api/programs/{pid}?revision=1').status_code==200
    assert admin.put(path,json={'settings':settings(),'revision':2}).status_code==409


def test_saved_setup_through_postgres_adapter(clients):
    """The setup table is keyed by program_id, not the adapter's default id."""
    from database import PostgresConnection
    from platform_api import db
    class Cursor:
        def __init__(self, cursor):self.cursor=cursor
        @property
        def rowcount(self):return self.cursor.rowcount
        def fetchone(self):
            row=self.cursor.fetchone()
            return dict(row) if row is not None else None
    class Connection:
        def __init__(self):self.conn=db()
        def execute(self, sql, params):return Cursor(self.conn.execute(sql.replace('%s','?'),params))
        def commit(self):self.conn.commit()
        def close(self):self.conn.close()
    admin,_,_=clients;pid=create(admin)['id']
    with patch('program_exam.db',side_effect=lambda:PostgresConnection(Connection())):
        saved=admin.put(f'/api/programs/{pid}/exam-setup',json={'settings':settings()})
        assert saved.status_code==200,saved.text
        assert admin.put(f'/api/programs/{pid}/exam-setup',json={'settings':settings()}).status_code==409
