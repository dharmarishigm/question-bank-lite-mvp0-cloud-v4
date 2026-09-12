import copy
import json
from unittest.mock import patch
import app
from tests.test_programs import clients
from tests.test_program_exam import author
from llm_generate import GenerationRequest


def batch(admin,subject):
    with patch('app.generate_questions',side_effect=author):
        r=admin.post('/api/ai/generate',json=GenerationRequest(exam_name='Entrance',subject=subject,count=2,generation_prompt='Create original questions.',syllabus='Foundations').model_dump())
    assert r.status_code==200,r.text
    return r.json()


def test_generation_save_does_not_initialize_schema(clients):
    admin,_,_=clients
    with patch('prompt_registry.init_prompt_registry',side_effect=AssertionError('Runtime must not create tables')):
        result=batch(admin,'Physics')
    assert result['generated']==2
    assert result['review_required']==2


def test_bulk_save_atomic_indices_idempotency_and_partial_status(clients):
    admin,student,_=clients;a=batch(admin,'Physics');b=batch(admin,'Chemistry')
    payload={'batches':[{'run_id':a['run_id'],'indices':[0]},{'run_id':b['run_id'],'indices':[999]}],'reviewed':True}
    assert student.post('/api/ai/review/save',json=payload).status_code==403
    assert admin.post('/api/ai/review/save',json=payload).status_code==422
    assert admin.get('/api/questions').json()['items']==[]
    payload['batches'][1]['indices']=[0]
    saved=admin.post('/api/ai/review/save',json=payload);assert saved.status_code==200,saved.text
    assert saved.json()['saved_count']==2
    assert admin.get('/api/ai/runs/'+a['run_id']).json()['status']=='REVIEW_REQUIRED'
    retry=admin.post('/api/ai/review/save',json=payload).json()
    assert retry['saved_count']==0 and retry['already_saved_count']==2
    assert len(admin.get('/api/questions').json()['items'])==2
    for item in payload['batches']:item['indices']=[1]
    assert admin.post('/api/ai/review/save',json=payload).json()['saved_count']==2
    assert admin.get('/api/ai/runs/'+a['run_id']).json()['status']=='SAVED'


def test_edit_options_stale_write_and_saved_question_guard(clients):
    admin,student,_=clients;run=batch(admin,'Mathematics');q=run['questions'][0]
    original={k:v for k,v in q.items() if k not in {'review_index','fingerprint'}}
    edited=copy.deepcopy(original);edited['options'][0]['text']='A corrected option';edited['solution']='Revised explanation.'
    path=f'/api/ai/review/runs/{run["run_id"]}/questions/0'
    payload={'question':edited,'original_question':original}
    assert student.put(path,json=payload).status_code==403
    response=admin.put(path,json=payload)
    assert response.status_code==200
    assert response.json()['explanation_en']=='' and response.json()['explanation_te']==''
    assert admin.put(path,json=payload).status_code==409
    saved=admin.post('/api/ai/review/save',json={'batches':[{'run_id':run['run_id'],'indices':[0]}],'reviewed':True}).json()
    question=admin.get('/api/questions/'+str(saved['items'][0]['question_id'])).json()
    assert question['options'][0]=='A corrected option'
    with app.connect() as conn:
        assert not conn.execute('SELECT 1 FROM question_explanation_translations WHERE question_id=?',(question['id'],)).fetchone()
    assert admin.put(path,json={'question':edited,'original_question':edited}).status_code==409


def test_metadata_only_draft_edit_preserves_explanations_but_core_edit_clears_nested_cache(clients):
    admin,_,_=clients;run=batch(admin,'Physics');q=run['questions'][0]
    original={k:v for k,v in q.items() if k not in {'review_index','fingerprint'}}
    original['metadata']['precomputed_explanations']={'en':'Old English','te':'పాత వివరణ'}
    with app.connect() as conn:
        output=json.loads(conn.execute('SELECT output_json FROM ai_generation_runs WHERE id=?',(run['run_id'],)).fetchone()['output_json'])
        output['questions'][0]['metadata']=original['metadata']
        conn.execute('UPDATE ai_generation_runs SET output_json=? WHERE id=?',(json.dumps(output),run['run_id']));conn.commit()
    path=f'/api/ai/review/runs/{run["run_id"]}/questions/0'
    tagged=copy.deepcopy(original);tagged['tags']=['reviewed']
    result=admin.put(path,json={'question':tagged,'original_question':original})
    assert result.status_code==200,result.text
    assert result.json()['explanation_en']==original['explanation_en']
    current={k:v for k,v in result.json().items() if k not in {'review_index','fingerprint'}}
    changed=copy.deepcopy(current);changed['answer']='C'
    result=admin.put(path,json={'question':changed,'original_question':current})
    assert result.status_code==200,result.text
    assert result.json()['explanation_en']=='' and result.json()['explanation_te']==''
    assert 'precomputed_explanations' not in result.json()['metadata']


def test_bank_correction_preserves_ai_origin_and_versions(clients):
    admin,_,_=clients;run=batch(admin,'Physics')
    saved=admin.post('/api/ai/review/save',json={'batches':[{'run_id':run['run_id'],'indices':[0]}],'reviewed':True}).json()
    qid=saved['items'][0]['question_id']
    result=admin.put(f'/api/questions/{qid}',json={'subject':'Physics','statement':'Corrected wording for this question.','options':['1','2','3','4'],'answer':'B','solution':'Corrected reasoning.'})
    assert result.status_code==200,result.text
    assert result.json()['source_type']=='AI_GENERATED'
    assert result.json()['generation_run_id']==run['run_id']
    assert admin.get(f'/api/questions/{qid}/versions').json()
    assert 'Corrected wording' in str(result.json()['content_blocks'])

    retry=admin.post('/api/ai/review/save',json={'batches':[{'run_id':run['run_id'],'indices':[0]}],'reviewed':True}).json()
    assert retry['saved_count']==0 and retry['items'][0]['question_id']==qid
    assert len(admin.get('/api/questions').json()['items'])==1
