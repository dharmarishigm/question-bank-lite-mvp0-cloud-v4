import copy,json,time
from contextlib import closing
from unittest.mock import patch
import app
from tests.test_programs import clients
from question_correction import Content,Suggestion

def question(admin):
 return admin.post('/api/questions',json={'statement':'What is $2+2$?','options':['3','4'],'answer':'B','solution':'Add two and two.','subject':'Mathematics','source_image':'/uploads/original.png'}).json()
def fields(q):return {k:q[k] for k in Content.model_fields}
def test_suggestions_admin_only_and_never_save(clients):
 admin,student,anon=clients;q=question(admin);v=fields(q);v['solution']='Two plus two equals four.'
 proposal=Suggestion(question=Content(**v),changes=['Clarified solution'],uncertainties=[])
 for mode in ['correct','regenerate']:
  with patch('question_correction.structured_call',return_value=(proposal,{'model':'test-model'})) as llm:
   payload={'question':fields(q),'instructions':'Check equation','mode':mode}
   assert student.post('/api/admin/question-corrections/suggest',json=payload).status_code==403
   assert anon.post('/api/admin/question-corrections/suggest',json=payload).status_code==401
   llm.assert_not_called()
   r=admin.post('/api/admin/question-corrections/suggest',json=payload);assert r.status_code==200,r.text
   assert r.json()['saved'] is False
   assert admin.get(f'/api/questions/{q["id"]}').json()['solution']==q['solution']
 with patch('question_correction.structured_call',side_effect=RuntimeError('provider secret')):
  r=admin.post('/api/admin/question-corrections/suggest',json={'question':fields(q)})
  assert r.status_code==502 and 'provider secret' not in r.text and 'Reference:' in r.text

def test_suggestion_recovers_with_text_when_first_provider_attempt_fails(clients):
 admin,_,_=clients;q=question(admin);proposal=Suggestion(question=Content(**fields(q)),changes=[],uncertainties=['Source pixels unavailable'])
 with patch('question_correction.structured_call',side_effect=[RuntimeError('image decoding failed'),(proposal,{'model':'test-model'})]) as llm:
  r=admin.post('/api/admin/question-corrections/suggest',json={'question':fields(q),'source_image':'/uploads/missing.png'})
 assert r.status_code==200,r.text
 assert llm.call_count==2 and r.json()['saved'] is False

def test_paper_syllabus_replacement_uses_server_frozen_context(clients):
 admin,_,_=clients;q=question(admin)
 p=admin.post('/api/programs',json={'code':'REPLACE','name':'Replacement','status':'ACTIVE'}).json();uid=admin.get('/api/auth/me').json()['id']
 frozen={'settings':{'name':'JEE paper','difficulty':'VERY_HARD','language':'English','curriculum':'NCERT','sections':[{'subject':'Chemistry','topics':['Electrochemistry'],'count':1}]},'effective_prompt':'FROZEN SERVER SYLLABUS PROMPT'}
 item={'question':{**q},'origin':'BANK','section':{'subject':'Chemistry','topics':['Electrochemistry'],'marks':4,'negative_marks':1}}
 with closing(app.connect()) as conn:
  jid=conn.execute("INSERT INTO program_exam_jobs(program_id,request_key,input_json,result_json,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(p['id'],'replace-test',json.dumps(frozen),json.dumps({'questions':[item]}),'REVIEW_REQUIRED',uid,time.time(),time.time())).lastrowid;conn.commit()
 replacement=fields(q);replacement.update(statement='Which new electrochemical statement is correct?',options=['New A','New B'],answer='A',solution='New solution')
 proposal=Suggestion(question=Content(**replacement),changes=['Replaced the complete question'],uncertainties=[])
 payload={'mode':'replace_from_paper','question':fields(q),'question_id':q['id'],'program_paper_id':jid,'instructions':'client text'}
 with patch('question_correction.structured_call',return_value=(proposal,{'model':'test-model'})) as llm:
  r=admin.post('/api/admin/question-corrections/suggest',json=payload)
 assert r.status_code==200,r.text
 sent=llm.call_args.args[2]
 assert sent['paper_context']['effective_prompt']=='FROZEN SERVER SYLLABUS PROMPT'
 assert sent['paper_context']['question_slot']['subject']=='Chemistry'
 assert sent['paper_context']['paper_settings']['difficulty']=='VERY_HARD'
 assert 'paper_context' in sent and 'source_image' not in sent
 assert admin.get(f'/api/questions/{q["id"]}').json()['statement']==q['statement']
 bad={**payload,'question_id':q['id']+999}
 with patch('question_correction.structured_call') as llm:
  assert admin.post('/api/admin/question-corrections/suggest',json=bad).status_code==409
  llm.assert_not_called()

def test_review_stale_write_versions_and_explanation_invalidation(clients):
 admin,student,_=clients;q=question(admin);v=fields(q);v['options']=['4','5'];v['answer']='A'
 payload={'question':v,'original':fields(q),'reviewed':False};url=f'/api/admin/question-corrections/{q["id"]}'
 assert admin.put(url,json=payload).status_code==422
 payload['reviewed']=True
 assert student.put(url,json=payload).status_code==403
 with closing(app.connect()) as conn:
  conn.execute('INSERT INTO question_explanations(question_id,explanation,created_at,updated_at) VALUES(?,?,?,?)',(q['id'],'old',time.time(),time.time()));conn.commit()
 r=admin.put(url,json=payload);assert r.status_code==200,r.text
 assert r.json()['options']==['4','5'] and r.json()['source_image']==q['source_image']
 assert admin.put(url,json=payload).status_code==409
 assert admin.get(f'/api/questions/{q["id"]}/versions').json()[0]['payload']['options']==q['options']
 with closing(app.connect()) as conn:assert not conn.execute('SELECT * FROM question_explanations WHERE question_id=?',(q['id'],)).fetchone()

def test_program_review_snapshot_updated_atomically(clients):
 from program_exam import snapshot
 admin,_,_=clients;q=question(admin)
 p=admin.post('/api/programs',json={'code':'CORRECTION','name':'Correction','status':'ACTIVE'}).json();uid=admin.get('/api/auth/me').json()['id']
 with closing(app.connect()) as conn:
  jid=conn.execute("INSERT INTO program_exam_jobs(program_id,request_key,input_json,result_json,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(p['id'],'correct-test','{}',json.dumps({'questions':[{'question':snapshot(q),'origin':'BANK'}]}),'REVIEW_REQUIRED',uid,time.time(),time.time())).lastrowid;conn.commit()
 value=fields(q);value['statement']='Corrected equation: $2+2=?$'
 r=admin.put(f'/api/admin/question-corrections/{q["id"]}',json={'question':value,'original':fields(q),'reviewed':True,'program_paper_id':jid});assert r.status_code==200,r.text
 with closing(app.connect()) as conn:assert json.loads(conn.execute('SELECT result_json FROM program_exam_jobs WHERE id=?',(jid,)).fetchone()['result_json'])['questions'][0]['question']['statement']==value['statement']
