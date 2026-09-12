from unittest.mock import patch

from tests.test_programs import clients
from tests.test_ai_partial_generation import request
from llm_generate import GeneratedQuestion, GeneratedQuestionBatch, PartialGenerationError


def test_pause_preserves_completed_questions_and_can_continue(clients):
    admin,_,_=clients
    def generate(payload):
        run=admin.get('/api/ai/runs').json()[0]
        assert admin.post(f"/api/ai/runs/{run['id']}/pause").status_code==200
        from generation_control import is_paused
        assert is_paused()
        raise PartialGenerationError('paused',[GeneratedQuestion(statement='Preserved?',answer='2',solution='1+1')],{},'test')
    with patch('app.generate_questions',side_effect=generate):
        result=admin.post('/api/ai/generate',json=request().model_dump()).json()
    rid=result['run_id']
    assert admin.get('/api/ai/runs/'+rid).json()['status']=='PAUSED'
    with patch('app.generate_questions',return_value=(GeneratedQuestionBatch(questions=[GeneratedQuestion(statement='New concept?',answer='3')]),{},'test')) as mock:
        continued=admin.post(f'/api/ai/runs/{rid}/resume')
    assert continued.status_code==200,continued.text
    assert continued.json()['run_id']!=rid
    assert mock.call_args.args[0].count==1
    assert 'Preserved?' in mock.call_args.args[0].generation_prompt
    assert admin.post(f'/api/ai/runs/{rid}/resume').status_code==409
    assert len(admin.get('/api/ai/runs/'+rid).json()['output']['questions'])==1


def test_delete_hides_run_but_preserves_bank_question(clients):
    admin,_,_=clients
    batch=GeneratedQuestionBatch(questions=[GeneratedQuestion(statement='Keep in bank?',answer='2',solution='1+1')])
    with patch('app.generate_questions',return_value=(batch,{},'test')):
        rid=admin.post('/api/ai/generate',json=request(1).model_dump()).json()['run_id']
    saved=admin.post(f'/api/ai/runs/{rid}/save',json={'indices':[0]})
    assert saved.status_code==200,saved.text
    qid=saved.json()['questions'][0]['id']
    assert admin.delete('/api/ai/runs/'+rid).status_code==200
    assert rid not in [r['id'] for r in admin.get('/api/ai/runs').json()]
    assert admin.get('/api/questions/'+str(qid)).status_code==200
    assert admin.post(f'/api/ai/runs/{rid}/save',json={'indices':[0]}).status_code==409


def test_running_run_cannot_be_deleted(clients):
    admin,_,_=clients
    def generate(payload):
        rid=admin.get('/api/ai/runs').json()[0]['id']
        assert admin.delete('/api/ai/runs/'+rid).status_code==409
        return GeneratedQuestionBatch(questions=[]),{},'test'
    with patch('app.generate_questions',side_effect=generate):
        assert admin.post('/api/ai/generate',json=request(1).model_dump()).status_code==200


def test_partial_failure_continues_only_remaining_questions(clients):
    admin,_,_=clients
    partial=PartialGenerationError('Invalid output',[GeneratedQuestion(statement='Keep this question',answer='2',solution='1+1')],{},'test')
    with patch('app.generate_questions',side_effect=partial):
        rid=admin.post('/api/ai/generate',json=request(3).model_dump()).json()['run_id']
    with patch('app.generate_questions',return_value=(GeneratedQuestionBatch(questions=[]),{},'test')) as generate:
        assert admin.post(f'/api/ai/runs/{rid}/resume').status_code==200
    assert generate.call_args.args[0].count==2
    assert admin.post(f'/api/ai/runs/{rid}/save',json={'indices':[0]}).status_code==200
    assert admin.post(f'/api/ai/runs/{rid}/resume').status_code==409


def test_interrupted_run_can_be_recovered(clients):
    from contextlib import closing
    from app import connect
    admin,_,_=clients
    with patch('app.generate_questions',return_value=(GeneratedQuestionBatch(questions=[]),{},'test')):
        rid=admin.post('/api/ai/generate',json=request(1).model_dump()).json()['run_id']
    with closing(connect()) as conn:
        conn.execute("UPDATE ai_generation_runs SET status='RUNNING',created_at=1 WHERE id=?",(rid,));conn.commit()
    assert admin.post(f'/api/ai/runs/{rid}/pause').status_code==200
    assert admin.get('/api/ai/runs/'+rid).json()['status']=='PAUSED'
