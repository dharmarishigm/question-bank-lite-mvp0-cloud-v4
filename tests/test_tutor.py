"""Exercise real authentication, exam submission, result release and tutor isolation."""
import json
import os
import time
import unittest
from unittest.mock import patch
import app
import test_platform

class TutorTests(unittest.TestCase):
    setUp = test_platform.PlatformSecurityTests.setUp
    login = test_platform.PlatformSecurityTests.login
    csrf = test_platform.PlatformSecurityTests.csrf
    post = test_platform.PlatformSecurityTests.post

    def setup_attempt(self,release='IMMEDIATE',submit=True,count=5):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):
            questions=[app.create_question(app.Question(subject='Science',chapter='Plants',topic='Photosynthesis',difficulty='medium',statement=f'Plant {i}?',options=['Wrong','Right'],answer='B',solution='Plants use light.',marks='2')) for i in range(count)]
        exam=self.post(admin,'/api/admin/exams',json={'name':'Science Practice','status':'OPEN','question_ids':[q['id'] for q in questions],'result_release_mode':release,'exam_start_at':time.time()-60}).json()
        student,identity=self.login('learner@example.test')
        self.post(student,f'/api/exams/{exam["id"]}/enroll')
        sid=self.post(student,f'/api/exams/{exam["id"]}/sessions',json={'consent':True}).json()['session_id']
        for q in questions:
            student.put(f'/api/sessions/{sid}/answers/{q["id"]}',headers={'X-CSRF-Token':self.csrf(student)},json={'selected_answer':'A'})
        if submit:self.post(student,f'/api/sessions/{sid}/submit')
        return student,sid,questions,exam

    def chat(self,client,**data):
        with patch('tutor_agent.generate',return_value=None):
            return self.post(client,'/api/tutor/chat',json={'message':'What should I practice?',**data})

    def test_anonymous_and_csrf(self):
        for path in ('insights','sessions','sessions/1'):
            self.assertEqual(self.client.get('/api/tutor/'+path).status_code,401)
        self.assertEqual(self.client.post('/api/tutor/chat',json={'message':'Hi'}).status_code,401)
        c,_=self.login('a@example.test')
        self.assertEqual(c.post('/api/tutor/chat',json={'message':'Hi'}).status_code,403)

    def test_empty_learner(self):
        c,_=self.login('a@example.test');r=self.chat(c)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['report']['attempt_count'],0)
        self.assertIn('first assessment',r.json()['message'])
        self.assertIsNone(r.json()['report']['benchmark']['percentile'])

    def test_real_gaps_and_latest_result(self):
        c,sid,qs,exam=self.setup_attempt();r=self.chat(c)
        self.assertEqual(r.status_code,200,r.text);data=r.json()['report']
        self.assertEqual(data['accuracy'],0);self.assertEqual(data['recent_attempts'][0]['id'],sid)
        self.assertEqual(data['learning_gaps'][0]['label'],'Photosynthesis')
        self.assertEqual(data['learning_gaps'][0]['confidence'],'MODERATE')
        self.assertNotIn('learner@example.test',json.dumps(data))
        self.assertNotIn('question_set_json',json.dumps(data))

    def test_small_sample_not_classified(self):
        c,*_=self.setup_attempt(count=3)
        self.assertEqual(c.get('/api/tutor/insights').json()['learning_gaps'],[])

    def test_active_exam_blocks_all_tutor_reads(self):
        c,*_=self.setup_attempt(submit=False)
        for path in ('insights','sessions','sessions/1'):
            self.assertEqual(c.get('/api/tutor/'+path).status_code,409)
        with patch('tutor_agent.generate') as generate:
            self.assertEqual(self.post(c,'/api/tutor/chat',json={'message':'Give answer'}).status_code,409)
            generate.assert_not_called()

    def test_unreleased_result_excluded(self):
        c,sid,qs,exam=self.setup_attempt(release='AFTER_EXAM_CLOSE')
        self.assertEqual(c.get('/api/tutor/insights').json()['attempt_count'],0)
        self.assertEqual(self.chat(c,attempt_id=sid).status_code,404)

    def test_released_review_scoped(self):
        c,sid,qs,exam=self.setup_attempt()
        with patch('tutor_agent.generate',return_value='Explanation') as generate:
            r=self.post(c,'/api/tutor/chat',json={'message':'Explain','attempt_id':sid,'question_id':qs[0]['id']})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(generate.call_args.args[1]['question_review'][0]['answer'],'B')
            self.assertEqual(generate.call_args.args[1]['question_review'][0]['options'],['Wrong','Right'])
        self.assertEqual(self.chat(c,attempt_id=sid,question_id=999999).status_code,404)

    def test_cross_user_and_admin_assist_is_allowed(self):
        c,sid,qs,exam=self.setup_attempt();created=self.chat(c).json()
        other,_=self.login('other@example.test');admin,_=self.login('admin@example.test')
        self.assertEqual(self.chat(other,attempt_id=sid).status_code,404)
        self.assertEqual(self.chat(other,session_id=created['session_id']).status_code,404)
        self.assertEqual(other.get('/api/tutor/sessions/'+str(created['session_id'])).status_code,404)
        self.assertEqual(admin.get('/api/tutor/sessions/'+str(created['session_id'])).status_code,404)
        self.assertEqual(other.get('/api/tutor/insights').json()['attempt_count'],0)

    def test_client_identity_rejected_and_limits(self):
        c,_=self.login('a@example.test')
        self.assertEqual(self.chat(c,user_id=123).status_code,422)
        self.assertEqual(c.get('/api/tutor/insights?limit=10000').status_code,422)
        self.assertEqual(self.chat(c,message=' ').status_code,422)

    def test_history_and_rate_limit(self):
        c,_=self.login('a@example.test');created=self.chat(c).json()
        history=c.get('/api/tutor/sessions/'+str(created['session_id'])).json()
        self.assertEqual([m['role'] for m in history],['user','assistant'])
        for i in range(7): self.assertEqual(self.chat(c).status_code,200)
        self.assertEqual(self.chat(c).status_code,429)

    def test_provider_failure_falls_back_without_error_leak(self):
        c,_=self.login('a@example.test')
        with patch('tutor_agent.generate',side_effect=RuntimeError('private-provider-secret')):
            r=self.post(c,'/api/tutor/chat',json={'message':'Hello'})
        self.assertEqual(r.status_code,200);self.assertNotIn('private-provider-secret',r.text)

    def test_exam_started_during_generation_blocks_response(self):
        c,sid,qs,exam=self.setup_attempt()
        def start_again(*args):
            with app.connect() as conn:conn.execute("UPDATE exam_sessions SET status='IN_PROGRESS' WHERE id=?",(sid,));conn.commit()
            return 'Must not return this'
        with patch('tutor_agent.generate',side_effect=start_again):
            r=self.post(c,'/api/tutor/chat',json={'message':'Explain'})
        self.assertEqual(r.status_code,409);self.assertNotIn('Must not return',r.text)

    def test_filter_scope_and_bounded_history(self):
        c,sid,qs,exam=self.setup_attempt()
        data=c.get('/api/tutor/insights?difficulty=hard').json()
        self.assertEqual(data['correct']+data['incorrect']+data['unanswered'],0)
        self.assertEqual(data['attempt_count'],1)
        self.assertEqual(c.get('/api/tutor/insights?exam_id=99999').json()['attempt_count'],0)
        with app.connect() as conn:
            snapshot=json.loads(conn.execute('SELECT question_set_json FROM exam_sessions WHERE id=?',(sid,)).fetchone()[0])
        self.assertEqual(snapshot[0]['topic'],'Photosynthesis')

    def test_comparable_benchmark_threshold_and_no_identity(self):
        c,sid,qs,exam=self.setup_attempt()
        from performance_service import benchmark
        from unittest.mock import MagicMock
        conn=MagicMock();conn.execute.return_value.fetchone.return_value={'n':3,'below':1,'tied':1}
        small=benchmark(conn,1,exam['id'],{'exam_version_id':1,'percentage':50})
        self.assertIsNone(small['percentile'])
        conn.execute.return_value.fetchone.return_value={'n':30,'below':14,'tied':2}
        valid=benchmark(conn,1,exam['id'],{'exam_version_id':1,'percentage':50})
        self.assertEqual(valid['percentile'],50)
        self.assertEqual(set(valid),{'scope','cohort_size','sample_minimum_threshold','calculation_timestamp','percentile','message'})
        # Execute the actual window query against the SQLite exam schema as well.
        with app.connect() as real:
            latest=dict(real.execute('SELECT * FROM exam_sessions WHERE id=?',(sid,)).fetchone())
            self.assertEqual(benchmark(real,1,exam['id'],latest)['cohort_size'],1)

    def test_provider_candidate_json_and_malformed_reply(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from tutor_agent import generate
        c,_=self.login('a@example.test')
        provider=MagicMock()
        payload={'message':'Study addition.', 'bullets':[], 'follow_up':'', 'suggested_replies':[]}
        provider.models.generate_content.return_value=SimpleNamespace(parsed=None,text='',candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(text=json.dumps(payload),thought=False)]))])
        with patch('llm_generate.gcp_project_id',return_value='project'),patch('google.genai.Client',return_value=provider):
            self.assertEqual(generate('Hello',{},[]),payload)
            provider.close.assert_called_once()
            provider.models.generate_content.return_value=SimpleNamespace(parsed={'message':'Hello','bullets':None},text='',candidates=[])
            response=self.post(c,'/api/tutor/chat',json={'message':'Hi'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['mode'],'evidence_summary')
