import unittest,json
from unittest.mock import patch
from fastapi import Response
import test_platform,app
from platform_api import _create_login
from registration_identity import phone_key

class IdentityTests(unittest.TestCase):
    setUp=test_platform.PlatformSecurityTests.setUp
    login=test_platform.PlatformSecurityTests.login
    csrf=test_platform.PlatformSecurityTests.csrf
    post=test_platform.PlatformSecurityTests.post
    def link(self,maximum=5):
        admin,_=self.login('admin@example.test')
        q=self.post(admin,'/api/questions',json={'statement':'2 + 2?','options':['3','4'],'answer':'B'}).json()
        e=self.post(admin,'/api/admin/exams',json={'name':'Shared link','status':'OPEN','question_ids':[q['id']],'proctor_required':False,'allow_self_registration':False}).json()
        link=self.post(admin,f'/api/admin/exams/{e["id"]}/registration-links',json={'max_registrations':maximum}).json()
        return e,link
    def test_shared_google_mobile_enrollment_and_retry(self):
        exam,link=self.link(1);student,user=self.login('learner@example.test');url=f'/api/register/exam/{link["token"]}/enroll'
        self.assertEqual(self.client.post(url,json={'phone_number':'9876543210'}).status_code,401)
        self.assertEqual(student.post(url,json={'phone_number':'9876543210'}).status_code,403)
        first=self.post(student,url,json={'phone_number':'9876543210'});self.assertEqual(first.status_code,200,first.text)
        self.assertTrue(self.post(student,url,json={'phone_number':'+91 9876543210'}).json()['already_enrolled'])
        self.assertEqual(len(student.get('/api/my/exams').json()),1)
        self.assertEqual(self.post(student,f'/api/exams/{exam["id"]}/sessions').status_code,200)
    def test_mobile_aliases_cannot_register_another_account(self):
        exam,link=self.link();a,_=self.login('a@example.test');b,_=self.login('b@example.test');url=f'/api/register/exam/{link["token"]}/enroll'
        self.assertEqual(self.post(a,url,json={'phone_number':'9876543210'}).status_code,200)
        self.assertEqual(self.post(b,url,json={'phone_number':'+91 98765 43210'}).status_code,409)
        r=b.put('/api/student/profile',headers={'X-CSRF-Token':self.csrf(b)},json={'full_name':'B','date_of_birth':'2010-01-01','phone_number':'919876543210','school_name':'Test'});self.assertEqual(r.status_code,409)
        self.assertEqual(phone_key('9876543210'),phone_key('+91 98765 43210'))
    def test_google_login_reuses_pre_registered_account(self):
        exam,link=self.link();payload={'full_name':'Learner','email':'learner@example.test','date_of_birth':'2010-01-01','phone_number':'9876543210','school_name':'Test'}
        self.assertEqual(self.client.post(f'/api/register/exam/{link["token"]}',json=payload).status_code,200)
        r=self.client.post('/api/auth/student-registration-login',json=payload);self.assertEqual(r.status_code,200,r.text);uid=r.json()['id']
        user=_create_login({'sub':'real-google-sub','email':' Learner@example.test ','email_verified':True,'name':'Learner'},Response())
        self.assertEqual(user['id'],uid);self.assertTrue(user['email_verified'])
        with app.connect() as conn:self.assertEqual(conn.execute("SELECT COUNT(*) FROM users WHERE lower(email)='learner@example.test'").fetchone()[0],1)
    def test_pending_mobile_duplicate_and_blocked_enrollment(self):
        exam,link=self.link();url=f'/api/register/exam/{link["token"]}';data={'full_name':'A','email':'a@example.test','date_of_birth':'2010-01-01','phone_number':'9876543210','school_name':'Test'}
        self.assertEqual(self.client.post(url,json=data).status_code,200)
        self.assertEqual(self.client.post(url,json={**data,'email':'b@example.test','phone_number':'+91 9876543210'}).status_code,409)
        a,user=self.login('a@example.test')
        with app.connect() as conn:conn.execute("UPDATE exam_enrollments SET status='BLOCKED' WHERE user_id=?",(user['id'],));conn.commit()
        self.assertEqual(self.post(a,url+'/enroll',json={'phone_number':'9876543210'}).status_code,403)
    def test_conversational_payload_and_private_history(self):
        student,_=self.login('learner@example.test');turn={'message':'Let’s work on one idea.','bullets':['Start with a short example.'],'follow_up':'Which topic?','suggested_replies':['Fractions','Plants']}
        with patch('tutor_agent.generate',return_value=turn):r=self.post(student,'/api/tutor/chat',json={'message':'Help me learn'})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['follow_up'],'Which topic?');self.assertEqual(r.json()['suggested_replies'],['Fractions','Plants'])
        history=student.get('/api/tutor/sessions').json();self.assertEqual(history[0]['title'],'Help me learn')
        with patch('tutor_agent.generate',return_value=turn) as generate:
            follow=self.post(student,'/api/tutor/chat',json={'message':'Fractions','session_id':r.json()['session_id']})
            self.assertEqual(follow.status_code,200)
            self.assertIn('Which topic?',generate.call_args.args[2][-1]['content'])
