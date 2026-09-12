from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import app
from explanation_jobs import enqueue,claim_one,process,run_batch,BilingualExplanation
from tests.test_programs import clients


def question(admin):
    response=admin.post('/api/questions',json={'statement':'What is $2+2$?','options':['3','4'],'answer':'B','solution':'$2+2=4$.','source_type':'AI_GENERATED'})
    assert response.status_code==200,response.text
    return response.json()


def queued(q):
    with app.connect() as conn:
        result=enqueue(conn,q['id']);conn.commit()
    return result


def explanation():
    return BilingualExplanation(explanation_en='Addition combines two groups: $2+2=4$, so choose B.',explanation_te='కూడిక ద్వారా రెండు సమూహాలను కలిపితే $2+2=4$. కాబట్టి B సరైన సమాధానం.')


def test_generation_without_teaching_explanations_can_be_saved_and_queued(clients):
    from llm_generate import GeneratedQuestion,GeneratedQuestionBatch
    admin,_,_=clients
    output=GeneratedQuestionBatch(questions=[GeneratedQuestion(statement='Question-only draft',answer='A',solution='Worked solution')])
    with patch('app.generate_questions',return_value=(output,{},'mock-model')),patch('explanation_jobs.generate_bilingual') as model:
        result=admin.post('/api/ai/generate',json={'exam_name':'Queued exam','subject':'Math','count':1,'generation_prompt':'Original questions'}).json()
        assert result['review_required']==1
        saved=admin.post(f'/api/ai/runs/{result["run_id"]}/save',json={})
        assert saved.status_code==200,saved.text
        model.assert_not_called()
    with app.connect() as conn:
        assert conn.execute('SELECT status FROM explanation_jobs').fetchone()['status']=='PENDING'


def test_repeated_reads_queue_once_without_provider_calls(clients):
    admin,_,_=clients;q=question(admin)
    with patch('blueprint_gemini.structured_call') as model,patch('explanation_quota.reserve_explanation_call') as quota:
        for language in ('en','te','en'):
            result=admin.get(f'/api/questions/{q["id"]}/explain?language={language}')
            assert result.status_code==200 and result.json()['pending']
        model.assert_not_called();quota.assert_not_called()
    with app.connect() as conn:
        assert conn.execute('SELECT COUNT(*) n FROM explanation_jobs').fetchone()['n']==1


def test_concurrent_workers_claim_only_once_and_expired_lease_recovers(clients):
    admin,_,_=clients;q=question(admin);queued(q)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims=list(pool.map(lambda _:claim_one(),range(4)))
    assert sum(item is not None for item in claims)==1
    original=next(item for item in claims if item)
    with app.connect() as conn:
        conn.execute('UPDATE explanation_jobs SET lease_until=0');conn.commit()
    recovered=claim_one()
    assert recovered['attempts']==2 and recovered['lease_token']!=original['lease_token']
    with patch('explanation_jobs.generate_bilingual',return_value=explanation()):
        assert process(original)=='STALE'
        assert process(recovered)=='SUCCEEDED'
    assert app.get_cached_question_explanation(q['id'],'te')['liked']


def test_cache_is_atomic_and_retry_exhaustion_requires_admin(clients):
    admin,student,_=clients;q=question(admin);queued(q)
    with patch.dict('os.environ',{'EXPLANATION_JOB_MAX_ATTEMPTS':'2'}),patch('explanation_jobs.generate_bilingual',side_effect=ValueError('secret-provider-output')):
        assert process(claim_one())=='PENDING'
        assert claim_one() is None
        with app.connect() as conn:
            conn.execute('UPDATE explanation_jobs SET next_attempt_at=0');conn.commit()
        assert process(claim_one())=='FAILED'
    assert app.get_cached_question_explanation(q['id']) is None
    assert student.post(f'/api/admin/explanation-jobs/{q["id"]}/retry').status_code==403
    report=admin.get('/api/admin/explanation-jobs')
    assert report.json()['counts']['FAILED']==1 and 'secret-provider-output' not in report.text
    assert 'lease_token' not in report.text
    assert admin.post(f'/api/admin/explanation-jobs/{q["id"]}/retry').json()['status']=='PENDING'


def test_corrected_question_requeues_and_old_work_cannot_write(clients):
    admin,_,_=clients;q=question(admin);queued(q);old=claim_one()
    changed=admin.put(f'/api/questions/{q["id"]}',json={**q,'statement':'What is $3+3$?','options':['5','6'],'solution':'$3+3=6$.'})
    assert changed.status_code==200,changed.text
    with patch('explanation_jobs.generate_bilingual',return_value=explanation()):
        assert process(old)=='STALE'
    assert app.get_cached_question_explanation(q['id']) is None
    fresh=claim_one()
    assert fresh and fresh['source_hash']!=old['source_hash'] and fresh['attempts']==1


def test_batch_limit_and_cache_hits_skip_provider(clients):
    admin,_,_=clients
    for index in range(3):
        admin.post('/api/questions',json={'statement':f'Original question {index}','answer':'2','solution':'Add one and one','source_type':'AI_GENERATED'})
    with patch.dict('os.environ',{'EXPLANATION_JOB_BATCH_SIZE':'2'}),patch('explanation_jobs.generate_bilingual',return_value=explanation()) as model:
        result=run_batch();assert result['processed']==2 and result['succeeded']==2
        result=run_batch();assert result['processed']==1 and result['succeeded']==1
        assert run_batch()['processed']==0
        assert model.call_count==3


def test_empty_and_wrong_language_output_rejected():
    import pytest
    with pytest.raises(ValueError):BilingualExplanation(explanation_en=' ',explanation_te='తెలుగు')
    with pytest.raises(ValueError):BilingualExplanation(explanation_en='English',explanation_te='English again')


def test_worker_does_not_overwrite_existing_curated_language(clients):
    admin,_,_=clients;q=question(admin)
    app.save_question_explanation(q['id'],'Curated English explanation.',language='en')
    queued(q)
    with patch('explanation_jobs.generate_bilingual',return_value=explanation()):
        assert process(claim_one())=='SUCCEEDED'
    assert app.get_cached_question_explanation(q['id'],'en')['explanation']=='Curated English explanation.'
    assert app.get_cached_question_explanation(q['id'],'te')['explanation']


def test_program_paper_review_and_publication_do_not_wait_for_explanations(clients):
    from tests.test_programs import create
    from tests.test_program_exam import settings,author
    admin,_,_=clients;pid=create(admin)['id']
    def question_only(request):
        batch,usage,model=author(request)
        for item in batch.questions:item.explanation_en='';item.explanation_te=''
        return batch,usage,model
    with patch('app.generate_questions',side_effect=question_only),patch('explanation_jobs.generate_bilingual') as explanation_model:
        response=admin.post(f'/api/programs/{pid}/exam-papers',json={'request_key':'separate-explanation-test','settings':settings()})
        assert response.status_code==202,response.text
        job=admin.get(f'/api/programs/{pid}/exam-papers').json()[0]
        assert job['status']=='REVIEW_REQUIRED'
        approved=admin.post(f'/api/programs/{pid}/exam-papers/{job["id"]}/approve',json={'reviewed':True,'publish':True})
        assert approved.status_code==200,approved.text
        explanation_model.assert_not_called()
    with app.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM explanation_jobs WHERE status='PENDING'").fetchone()['n']==2
