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
        c,_=self.login('a@example.test');self.assertEqual(c.get('/api/tutor/availability').json(),{'available':True,'reason':''});r=self.chat(c)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['report']['attempt_count'],0)
        self.assertIn('first assessment',r.json()['message'])
        self.assertIsNone(r.json()['report']['benchmark']['percentile'])

    def test_learning_gap_question_and_empty_recommendations_do_not_fail(self):
        c,_=self.login('gap-check@example.test')
        from tutor_agent import performance as real_performance
        def without_recommendations(*args,**kwargs):
            result=real_performance(*args,**kwargs);result['recommendations']=[];return result
        with patch('tutor_agent.generate',return_value=None),patch('tutor_agent.performance',side_effect=without_recommendations):
            response=self.post(c,'/api/tutor/chat',json={'message':'What are my learning gaps?','page_title':'Performance Lab'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['report']['seven_day_plan']),7)

    def test_real_gaps_and_latest_result(self):
        c,sid,qs,exam=self.setup_attempt();r=self.chat(c)
        self.assertEqual(r.status_code,200,r.text);data=r.json()['report']
        self.assertEqual(data['accuracy'],0);self.assertEqual(data['recent_attempts'][0]['id'],sid)
        self.assertEqual(data['learning_gaps'][0]['label'],'Photosynthesis')
        self.assertEqual(data['learning_gaps'][0]['confidence'],'MODERATE')
        self.assertNotIn('learner@example.test',json.dumps(data))
        self.assertNotIn('question_set_json',json.dumps(data))

    def test_agent_routes_exam_result_and_analysis_tools_for_signed_in_user(self):
        c,sid,qs,exam=self.setup_attempt()
        with patch('tutor_agent.generate',return_value=None) as generate:
            response=self.post(c,'/api/tutor/chat',json={'message':'Show my exams, results and performance analysis'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(set(response.json()['tools_invoked']),{'my_exams','released_results','performance_analysis'})
        tools=generate.call_args.args[1]['agent_tools']
        self.assertEqual(tools['my_exams'][0]['id'],exam['id'])
        self.assertEqual(tools['released_results'][-1]['id'],sid)
        self.assertNotIn('question_set_json',json.dumps(tools))
        with patch('tutor_agent.generate',return_value=None):
            count=self.post(c,'/api/tutor/chat',json={'message':'How many exams have I written?'})
        self.assertIn('completed 1 exam attempt',count.json()['message'])

    def test_small_sample_not_classified(self):
        c,*_=self.setup_attempt(count=3)
        self.assertEqual(c.get('/api/tutor/insights').json()['learning_gaps'],[])

    def test_active_exam_blocks_all_tutor_reads(self):
        c,*_=self.setup_attempt(submit=False)
        self.assertEqual(c.get('/api/tutor/availability').json(),{'available':False,'reason':'ACTIVE_ASSESSMENT'})
        for path in ('insights','sessions','sessions/1'):
            self.assertEqual(c.get('/api/tutor/'+path).status_code,409)
        with patch('tutor_agent.generate') as generate:
            for message in ('Give answer','Hi','How many exams I have written?'):
                self.assertEqual(self.post(c,'/api/tutor/chat',json={'message':message}).status_code,409)
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

    def test_corrected_review_teaches_current_content_with_recorded_grade_context(self):
        from tests.test_question_correction import fields
        c,sid,questions,_=self.setup_attempt(count=1)
        original=questions[0]
        with app.connect() as conn:
            before=dict(conn.execute('SELECT question_set_json,score,percentage FROM exam_sessions WHERE id=?',(sid,)).fetchone())
        admin,_=self.login('admin@example.test')
        changed={**fields(original),'statement':'Reviewed plant question?','options':['Right','Wrong'],'answer':'A','solution':'Current reviewed teaching solution.'}
        result=admin.put(f'/api/admin/question-corrections/{original["id"]}',headers={'X-CSRF-Token':self.csrf(admin)},json={'original':fields(original),'question':changed,'reviewed':True})
        self.assertEqual(result.status_code,200,result.text)
        with patch('tutor_agent.generate',return_value='Review current explanation') as generate:
            response=self.post(c,'/api/tutor/chat',json={'message':'Explain my answer','attempt_id':sid,'question_id':original['id']})
        self.assertEqual(response.status_code,200,response.text)
        review=generate.call_args.args[1]['question_review'][0]
        self.assertEqual(review['statement'],changed['statement'])
        self.assertEqual(review['options'],changed['options'])
        self.assertEqual(review['answer'],'A')
        self.assertEqual(review['solution'],changed['solution'])
        self.assertTrue(review['corrected'])
        self.assertEqual(review['recorded_grade']['selected_answer'],'A')
        self.assertEqual(review['recorded_grade']['is_correct'],0)
        self.assertEqual(review['recorded_grade']['original_answer'],'B')
        self.assertEqual(review['recorded_grade']['original_options'],['Wrong','Right'])
        with app.connect() as conn:
            self.assertEqual(dict(conn.execute('SELECT question_set_json,score,percentage FROM exam_sessions WHERE id=?',(sid,)).fetchone()),before)

    def test_unapproved_bank_edit_does_not_override_tutor_review(self):
        c,sid,questions,_=self.setup_attempt(count=1)
        with app.connect() as conn:
            conn.execute("UPDATE questions SET statement='Unreviewed replacement',solution='Unreviewed answer' WHERE id=?",(questions[0]['id'],));conn.commit()
        with patch('tutor_agent.generate',return_value='Original reviewed context') as generate:
            response=self.post(c,'/api/tutor/chat',json={'message':'Explain','attempt_id':sid,'question_id':questions[0]['id']})
        self.assertEqual(response.status_code,200,response.text)
        review=generate.call_args.args[1]['question_review'][0]
        self.assertEqual(review['statement'],questions[0]['statement'])
        self.assertEqual(review['solution'],questions[0]['solution'])
        self.assertNotIn('corrected',review)

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

    def test_authenticated_profile_page_context_and_general_fallback(self):
        c,identity=self.login('mentor-learner@example.test')
        with patch('tutor_agent.generate',return_value=None) as generate:
            response=self.post(c,'/api/tutor/chat',json={'message':'What can you do?','page_title':'Performance Lab','page_content':'My visible learning gaps'})
        self.assertEqual(response.status_code,200,response.text)
        trusted=generate.call_args.args[1]
        self.assertEqual(trusted['learner_profile']['role'],'STUDENT')
        self.assertEqual(trusted['untrusted_page'],{'title':'Performance Lab','content':'My visible learning gaps'})
        self.assertIn('current page',response.json()['message'])

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
