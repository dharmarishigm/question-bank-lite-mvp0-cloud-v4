from unittest.mock import patch

from tests.test_programs import clients
from llm_generate import GenerationRequest,GeneratedQuestion,GeneratedQuestionBatch,PartialGenerationError


def request(count=2):
    return GenerationRequest(exam_name='Validation only',subject='Math',count=count,
        generation_prompt='Generate arithmetic questions.',syllabus='Arithmetic')


def test_completed_questions_remain_reviewable_after_provider_failure(clients):
    admin,_,_=clients
    question=GeneratedQuestion(statement='A preserved question?',answer='Two',solution='Add one and one.')
    error=PartialGenerationError('provider unavailable',[question],{'total_token_count':30},'test-model')
    with patch('app.generate_questions',side_effect=error):
        response=admin.post('/api/ai/generate',json=request().model_dump())
    assert response.status_code==200,response.text
    result=response.json()
    assert result['partial'] and result['review_required']==1 and not result['saved']
    run=admin.get('/api/ai/runs/'+result['run_id']).json()
    assert run['status']=='REVIEW_REQUIRED'
    assert len(run['output']['questions'])==1
    assert 'provider unavailable' not in (result['warning'] or '')


def test_parallel_completed_batches_survive_other_failure_and_usage_is_summed(clients):
    admin,_,_=clients
    def generate(payload):
        if 'BATCH 2 ' in payload.generation_prompt:raise TimeoutError('unavailable')
        index=1 if 'BATCH 1 ' in payload.generation_prompt else 3
        return GeneratedQuestionBatch(questions=[GeneratedQuestion(statement=f'Batch {index} question?',answer='2')]),{'total_token_count':30,'provider_calls':1},'test-model'
    with patch('app.generate_questions',side_effect=generate),patch.dict('os.environ',{'AI_INTERACTIVE_BATCH_SIZE':'1'}):
        response=admin.post('/api/ai/generate',json=request(3).model_dump())
    assert response.status_code==200,response.text
    result=response.json()
    assert result['partial'] and result['review_required']==2
    run=admin.get('/api/ai/runs/'+result['run_id']).json()
    assert run['usage']['total_token_count']==60 and run['usage']['interactive_batches']==3


def test_additional_conditions_change_bank_reuse_scope():
    from program_exam import Settings,scope_hash
    from tests.test_program_exam import settings
    first=Settings.model_validate(settings(additional_conditions='Only word problems'))
    second=Settings.model_validate(settings(additional_conditions='No word problems'))
    assert scope_hash(1,first,first.sections[0])!=scope_hash(1,second,second.sections[0])


def test_large_interactive_request_uses_only_one_worker_wave(clients):
    admin,_,_=clients
    counts=[]
    def generate(payload):
        counts.append(payload.count)
        return GeneratedQuestionBatch(questions=[GeneratedQuestion(statement=payload.generation_prompt+f' Question {index}',answer='2') for index in range(payload.count)]),{},'test-model'
    with patch('app.generate_questions',side_effect=generate):
        response=admin.post('/api/ai/generate',json=request(50).model_dump())
    assert response.status_code==200,response.text
    assert len(counts)<=4 and sum(counts)==50
    assert response.json()['review_required']==50
