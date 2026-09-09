import base64,hashlib,json,unittest
import test_platform

class MobileTests(unittest.TestCase):
    setUp=test_platform.PlatformSecurityTests.setUp
    login=test_platform.PlatformSecurityTests.login
    csrf=test_platform.PlatformSecurityTests.csrf
    post=test_platform.PlatformSecurityTests.post
    def start(self):
        verifier='x'*43;challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        r=self.client.post('/api/mobile/auth/start',json={'challenge':challenge});self.assertEqual(r.status_code,200,r.text);return r.json()['request_id'],verifier
    def test_pkce_handoff_owned_role_and_one_use(self):
        rid,verifier=self.start();student,_=self.login('student@example.test')
        self.assertEqual(self.client.post('/api/mobile/auth/exchange',json={'request_id':rid,'verifier':verifier}).status_code,202)
        self.assertEqual(self.post(student,'/api/mobile/auth/approve',json={'request_id':rid}).status_code,200)
        self.assertEqual(self.client.post('/api/mobile/auth/exchange',json={'request_id':rid,'verifier':'y'*43}).status_code,401)
        r=self.client.post('/api/mobile/auth/exchange',json={'request_id':rid,'verifier':verifier});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['role'],'STUDENT');self.assertIn('HttpOnly',r.headers.get('set-cookie'));self.assertIn('Secure',r.headers.get('set-cookie'))
        self.assertEqual(self.client.post('/api/mobile/auth/exchange',json={'request_id':rid,'verifier':verifier}).status_code,401)
    def test_handoff_requires_csrf_and_rejects_spoofing(self):
        rid,verifier=self.start()
        self.assertEqual(self.client.post('/api/mobile/auth/approve',json={'request_id':rid}).status_code,401)
        student,_=self.login('student@example.test')
        self.assertEqual(student.post('/api/mobile/auth/approve',json={'request_id':rid}).status_code,403)
        self.assertEqual(self.client.post('/api/mobile/auth/exchange',json={'request_id':rid,'verifier':verifier,'role':'ADMIN'}).status_code,422)
    def test_expired_handoff(self):
        import app
        rid,verifier=self.start()
        with app.connect() as conn:conn.execute('UPDATE mobile_auth_requests SET expires_at=0');conn.commit()
        self.assertEqual(self.client.post('/api/mobile/auth/exchange',json={'request_id':rid,'verifier':verifier}).status_code,401)
    def test_device_preferences_scoped(self):
        a,_=self.login('a@example.test');b,_=self.login('b@example.test')
        self.assertEqual(self.post(a,'/api/mobile/devices',json={'token':'valid-registration-token','enabled':True}).status_code,200)
        self.assertEqual(b.delete('/api/mobile/devices',headers={'X-CSRF-Token':self.csrf(b)}).status_code,200)
        import app
        with app.connect() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM mobile_devices').fetchone()[0],1)
    def test_assetlinks_do_not_advertise_unconfigured_signer(self):
        from unittest.mock import patch
        import os
        with patch.dict(os.environ,{'ANDROID_APP_LINK_SHA256':''}):self.assertEqual(self.client.get('/.well-known/assetlinks.json').json(),[])
    def test_background_is_signal_and_expired_answer_rejected(self):
        admin,_=self.login('admin@example.test');student,_=self.login('student@example.test')
        q=self.post(admin,'/api/questions',json={'statement':'2 + 2?','options':['3','4'],'answer':'B'}).json()
        e=self.post(admin,'/api/admin/exams',json={'name':'Mobile expiry','status':'OPEN','question_ids':[q['id']],'proctor_required':False}).json()
        self.post(student,f'/api/exams/{e["id"]}/enroll')
        sid=self.post(student,f'/api/exams/{e["id"]}/sessions').json()['session_id']
        for _ in range(4):
            r=self.post(student,f'/api/sessions/{sid}/security-events',json={'event_type':'APP_BACKGROUND'});self.assertTrue(r.json()['signal_only'])
        self.assertEqual(student.get(f'/api/sessions/{sid}').json()['session']['status'],'IN_PROGRESS')
        import app
        with app.connect() as conn:conn.execute('UPDATE exam_sessions SET expires_at=0 WHERE id=?',(sid,));conn.commit()
        r=student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'},headers={'X-CSRF-Token':self.csrf(student)})
        self.assertEqual(r.status_code,409)
        self.assertEqual(student.get(f'/api/sessions/{sid}').json()['session']['status'],'AUTO_SUBMITTED')
    def test_result_notification_is_opt_in_and_generic(self):
        from unittest.mock import patch,MagicMock
        import os,mobile_notifications
        student,user=self.login('student@example.test');other,_=self.login('other@example.test')
        self.post(student,'/api/mobile/devices',json={'token':'enabled-device-token','enabled':True})
        self.post(other,'/api/mobile/devices',json={'token':'other-device-token','enabled':True})
        credentials=MagicMock();credentials.token='test-only-token'
        with patch.dict(os.environ,{'FCM_PROJECT_ID':'test-project'}),patch('google.auth.default',return_value=(credentials,None)),patch('mobile_notifications.requests.post') as send:
            send.return_value.status_code=200;mobile_notifications.notify_result(user['id']);send.assert_called_once()
            message=send.call_args.kwargs['json']['message'];self.assertEqual(message['token'],'enabled-device-token');self.assertEqual(message['data'],{'action':'results'});self.assertNotIn(user['email'],json.dumps(message));self.assertNotIn('score',json.dumps(message))
