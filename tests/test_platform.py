import os, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app
from platform_api import init_platform

class PlatformSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        db=str(Path(self.tmp.name)/'platform.db')
        with sqlite3.connect(db) as conn:conn.executescript(app.SCHEMA)
        self.dbpatch=patch.object(app,'DB_PATH',db);self.dbpatch.start();self.addCleanup(self.dbpatch.stop)
        self.env=patch.dict(os.environ,{'APP_ENV':'test','AUTH_MODE':'mock','ADMIN_EMAILS':'admin@example.test'},clear=False);self.env.start();self.addCleanup(self.env.stop)
        init_platform();self.client=TestClient(app.app);self.addCleanup(self.client.close)
    def login(self,email):
        c=TestClient(app.app);r=c.post('/api/auth/mock',json={'email':email,'name':email.split('@')[0]});self.assertEqual(r.status_code,200,r.text);return c,r.json()
    def csrf(self,c):return c.cookies.get('qb_csrf')
    def post(self,c,url,**kwargs):return c.post(url,headers={'X-CSRF-Token':self.csrf(c)},**kwargs)
    def test_one_time_local_admin_bootstrap(self):
        config=self.client.get('/api/auth/config')
        self.assertEqual(config.status_code,200);self.assertTrue(config.json()['bootstrap_available'])
        created=self.client.post('/api/auth/bootstrap-admin',json={'name':'Platform Owner','email':'owner@example.test','role':'STUDENT'})
        self.assertEqual(created.status_code,200,created.text);self.assertEqual(created.json()['role'],'ADMIN')
        self.assertEqual(self.client.get('/api/auth/me').json()['email'],'owner@example.test')
        self.assertFalse(self.client.get('/api/auth/config').json()['bootstrap_available'])
        second=TestClient(app.app)
        try:self.assertEqual(second.post('/api/auth/bootstrap-admin',json={'name':'Second Owner','email':'second@example.test'}).status_code,409)
        finally:second.close()
    def test_identity_roles_and_admin_protection(self):
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        student,u=self.login('student@example.test');self.assertEqual(u['role'],'STUDENT')
        self.assertEqual(self.post(student,'/api/admin/exams',json={'name':'Forbidden'}).status_code,403)
        self.assertEqual(student.get('/api/questions').status_code,403)
        admin,a=self.login('admin@example.test');self.assertEqual(a['role'],'ADMIN')
        again,a2=self.login('admin@example.test');self.assertEqual(a['id'],a2['id'])

    def test_configured_local_admin_login(self):
        admin,_=self.login('admin@example.test');admin.close()
        with patch.dict(os.environ,{'ADMIN_LOCAL_EMAIL':'admin@example.test','ADMIN_LOCAL_PASSWORD':'strong-test-password'}):
            client=TestClient(app.app)
            try:
                self.assertTrue(client.get('/api/auth/config').json()['local_admin'])
                self.assertNotIn('local_admin_email',client.get('/api/auth/config').json())
                self.assertEqual(client.post('/api/auth/admin-login',json={'email':'admin@example.test','password':'wrong'}).status_code,401)
                signed_in=client.post('/api/auth/admin-login',json={'email':'admin@example.test','password':'strong-test-password'})
                self.assertEqual(signed_in.status_code,200,signed_in.text);self.assertEqual(signed_in.json()['role'],'ADMIN')
            finally:client.close()

    def test_public_site_seo_and_private_navigation_boundary(self):
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        html=response.text
        self.assertIn('<title>MeritIQra | AI-Powered Question Bank',html)
        self.assertIn('name="description"',html)
        self.assertIn('rel="canonical"',html)
        self.assertIn('property="og:title"',html)
        self.assertEqual(html.count('<h1>'),1)
        self.assertIn('id="public-site"',html)
        self.assertNotIn('id="admin-nav"',html)
        self.assertNotIn('id="student-nav"',html)
        self.assertNotIn('Generate Questions by AI',html)
        self.assertNotIn('value="admin@example.test"',html)
        robots=self.client.get('/robots.txt')
        self.assertEqual(robots.status_code,200)
        self.assertIn('Disallow: /admin',robots.text)
        sitemap=self.client.get('/sitemap.xml')
        self.assertEqual(sitemap.status_code,200)
        self.assertIn('https://meritiqra.com/features',sitemap.text)
        self.assertNotIn('/admin',sitemap.text)
        self.assertNotIn('/student',sitemap.text)
        admin,_=self.login('admin@example.test')
        private_html=admin.get('/').text
        self.assertIn('id="admin-nav"',private_html)
        self.assertNotIn('id="public-site"',private_html)

    def test_public_exam_catalog_exposes_only_safe_open_metadata(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):
            q=app.create_question(app.Question(statement='Private answer test',options=['A','B'],answer='B',solution='Secret solution'))
        opened=self.post(admin,'/api/admin/exams',json={'name':'Open Assessment','status':'OPEN','question_ids':[q['id']]}).json()
        self.post(admin,'/api/admin/exams',json={'name':'Draft Assessment','status':'DRAFT'})
        catalog=self.client.get('/api/public/exams')
        self.assertEqual(catalog.status_code,200)
        self.assertEqual([row['id'] for row in catalog.json()],[opened['id']])
        self.assertTrue(catalog.json()[0]['allow_self_registration'])
        raw=catalog.text
        self.assertNotIn('Private answer test',raw)
        self.assertNotIn('Secret solution',raw)
        self.assertNotIn('answer',raw.lower())
    def test_isolated_exam_sessions_answers_and_results(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):
            q1=app.create_question(app.Question(statement='2+2?',options=['3','4'],answer='B'))
            q2=app.create_question(app.Question(statement='3+3?',options=['5','6'],answer='B'))
        created=self.post(admin,'/api/admin/exams',json={'name':'Grade 8 Mathematics Olympiad','status':'OPEN','question_ids':[q1['id'],q2['id']],'duration_minutes':30}).json();eid=created['id']
        alice,_=self.login('alice@example.test');bob,_=self.login('bob@example.test')
        self.assertEqual(len(alice.get('/api/exams').json()),1)
        self.post(alice,f'/api/exams/{eid}/enroll');self.post(alice,f'/api/exams/{eid}/enroll')
        self.post(bob,f'/api/exams/{eid}/enroll')
        self.assertEqual(len(alice.get('/api/my/exams').json()),1)
        a_sid=self.post(alice,f'/api/exams/{eid}/sessions').json()['session_id'];b_sid=self.post(bob,f'/api/exams/{eid}/sessions').json()['session_id'];self.assertNotEqual(a_sid,b_sid)
        active=alice.get(f'/api/sessions/{a_sid}').json();raw=str(active);self.assertNotIn("'answer'",raw);self.assertNotIn("'solution'",raw)
        self.assertEqual(bob.get(f'/api/sessions/{a_sid}').status_code,404)
        r=alice.put(f'/api/sessions/{a_sid}/answers/{q1["id"]}',headers={'X-CSRF-Token':self.csrf(alice)},json={'selected_answer':'B'});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(alice.get(f'/api/sessions/{a_sid}').json()['questions'][0]['selected_answer'],'B')
        self.assertEqual(self.post(alice,f'/api/sessions/{a_sid}/submit').status_code,200)
        self.assertEqual(alice.put(f'/api/sessions/{a_sid}/answers/{q2["id"]}',headers={'X-CSRF-Token':self.csrf(alice)},json={'selected_answer':'B'}).status_code,409)
        results=alice.get('/api/my/results').json();self.assertEqual(len(results),1);self.assertEqual(results[0]['score'],1)
        self.assertEqual(bob.get(f'/api/my/results/{a_sid}').status_code,404)
        detail=alice.get(f'/api/my/results/{a_sid}');self.assertEqual(detail.status_code,200);self.assertIn('answer',detail.text);self.assertEqual(detail.json()['questions'][0]['id'],q1['id'])
        admin_detail=admin.get(f'/api/admin/results/{a_sid}');self.assertEqual(admin_detail.status_code,200,admin_detail.text);self.assertEqual(admin_detail.json()['session']['student_email'],'alice@example.test');self.assertEqual(admin_detail.json()['questions'][0]['selected_answer'],'B')
        self.assertEqual(bob.get(f'/api/admin/results/{a_sid}').status_code,403)
        self.assertEqual(bob.get(f'/api/student/questions/{q1["id"]}/explain').status_code,404)
        self.assertEqual(len(bob.get('/api/my/results').json()),0)

    def test_proctored_exam_enforces_registration_code_snapshot_and_isolation(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):q=app.create_question(app.Question(statement='Secure question?',options=['No','Yes'],answer='B',solution='Yes.'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Secure Exam','status':'OPEN','question_ids':[q['id']],'duration_minutes':30,'proctor_required':True}).json()['id']
        code_response=self.post(admin,f'/api/admin/exams/{eid}/proctor-codes',json={'valid_minutes':30});self.assertEqual(code_response.status_code,200,code_response.text);code=code_response.json()['code']
        alice,_=self.login('alice@example.test');bob,_=self.login('bob@example.test');outsider,_=self.login('outsider@example.test')
        self.post(alice,f'/api/exams/{eid}/enroll');self.post(bob,f'/api/exams/{eid}/enroll')
        denied=self.post(outsider,f'/api/student/exams/{eid}/start',json={'proctor_code':code});self.assertEqual(denied.status_code,403);self.assertEqual(denied.json()['detail']['reason_code'],'NOT_REGISTERED')
        wrong=self.post(alice,f'/api/student/exams/{eid}/start',json={'proctor_code':'WRONG1'});self.assertEqual(wrong.status_code,403);self.assertEqual(wrong.json()['detail']['reason_code'],'INVALID_PROCTOR_CODE')
        started_a=self.post(alice,f'/api/student/exams/{eid}/start',json={'proctor_code':code});self.assertEqual(started_a.status_code,200,started_a.text);a_sid=started_a.json()['session_id']
        resumed=self.post(alice,f'/api/student/exams/{eid}/start',json={});self.assertEqual(resumed.json(),{'session_id':a_sid,'resumed':True})
        started_b=self.post(bob,f'/api/student/exams/{eid}/start',json={'proctor_code':code});b_sid=started_b.json()['session_id'];self.assertNotEqual(a_sid,b_sid)
        active=alice.get(f'/api/sessions/{a_sid}');self.assertEqual(active.status_code,200);self.assertNotIn('solution',active.text);self.assertNotIn('"answer"',active.text)
        self.assertEqual(bob.get(f'/api/sessions/{a_sid}').status_code,404)
        self.assertEqual(bob.put(f'/api/sessions/{a_sid}/answers/{q["id"]}',headers={'X-CSRF-Token':self.csrf(bob)},json={'selected_answer':'B'}).status_code,404)
        self.assertEqual(self.post(alice,f'/api/sessions/{a_sid}/submit').status_code,200)
        self.assertEqual(self.post(alice,f'/api/sessions/{a_sid}/submit').json()['already_submitted'],True)
        self.assertEqual(bob.get(f'/api/my/results/{a_sid}').status_code,404)
        access=admin.get(f'/api/admin/exams/{eid}/access').json();self.assertNotIn('code_hash',str(access));self.assertNotIn(code,str(access))
        closed=admin.put(f'/api/admin/exams/{eid}/state',headers={'X-CSRF-Token':self.csrf(admin)},json={'status':'CLOSED'});self.assertEqual(closed.status_code,200,closed.text);self.assertEqual(closed.json()['status'],'CLOSED')

    def test_empty_draft_can_add_question_bank_questions_then_publish(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):app.create_question(app.Question(statement='Bank question',options=['A','B'],answer='A',marks='2'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Draft Exam','status':'DRAFT','duration_minutes':20}).json()['id']
        blocked=admin.put(f'/api/admin/exams/{eid}/state',headers={'X-CSRF-Token':self.csrf(admin)},json={'status':'PUBLISHED'});self.assertEqual(blocked.status_code,409)
        added=self.post(admin,f'/api/admin/exams/{eid}/questions/from-bank',json={'count':15});self.assertEqual(added.status_code,200,added.text);self.assertEqual(added.json()['added'],1)
        paper=admin.get(f'/api/admin/exams/{eid}/paper');self.assertEqual(paper.status_code,200,paper.text);question_ids=[q['id'] for q in paper.json()['questions']]
        self.assertEqual(question_ids,[admin.get(f'/api/admin/exams/{eid}/paper').json()['questions'][0]['id']])
        published=admin.put(f'/api/admin/exams/{eid}/state',headers={'X-CSRF-Token':self.csrf(admin)},json={'status':'PUBLISHED'});self.assertEqual(published.status_code,200,published.text)

    def test_blueprint_generation_is_metadata_driven_and_durable(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):
            algebra=[app.create_question(app.Question(subject='Mathematics',chapter='Algebra',topic='Equations',exam='Grade 8 Olympiad',difficulty='hard',qtype='mcq_single',statement=f'Algebra problem {i}?',options=['One','Two'],answer='A',verification_status='APPROVED',confidence=.95)) for i in range(3)]
            geometry=[app.create_question(app.Question(subject='Mathematics',chapter='Geometry',exam='Grade 8 Olympiad',difficulty='hard',qtype='mcq_single',statement=f'Geometry problem {i}?',options=['One','Two'],answer='B',verification_status='APPROVED',confidence=.9)) for i in range(2)]
            app.create_question(app.Question(subject='Science',chapter='Algebra',exam='Grade 8 Olympiad',difficulty='hard',qtype='mcq_single',statement='Wrong subject?',options=['One','Two'],answer='A',verification_status='APPROVED'))
            app.create_question(app.Question(subject='Mathematics',chapter='Algebra',exam='Grade 9 Olympiad',difficulty='hard',qtype='mcq_single',statement='Wrong grade?',options=['One','Two'],answer='A',verification_status='APPROVED'))
        blueprint={'exam_name':'Grade 8 Mathematics Olympiad','exam_type':'Olympiad','total_questions':3,'duration_minutes':45,'global_filters':{'grade':'Grade 8','subject':'Mathematics','verification_statuses':['APPROVED']},'rules':[{'id':'algebra','count':2,'filters':{'chapter':'Algebra','difficulty':'hard','question_type':'mcq_single'}},{'id':'geometry','count':1,'filters':{'chapter':'Geometry','difficulty':'hard','question_type':'mcq_single'}}],'random_seed':42}
        available=self.post(admin,'/api/admin/exam-blueprints/availability',json=blueprint);self.assertEqual(available.status_code,200,available.text);self.assertTrue(available.json()['ready']);self.assertEqual([x['available'] for x in available.json()['rules']],[3,2])
        first=self.post(admin,'/api/admin/exam-blueprints/preview',json=blueprint);second=self.post(admin,'/api/admin/exam-blueprints/preview',json=blueprint);self.assertEqual(first.status_code,200,first.text);self.assertEqual([q['id'] for q in first.json()['questions']],[q['id'] for q in second.json()['questions']]);self.assertEqual([q['chapter'] for q in first.json()['questions']],['Algebra','Algebra','Geometry'])
        approved=self.post(admin,'/api/admin/exam-blueprints/approve',json={'blueprint':blueprint,'question_ids':[q['id'] for q in first.json()['questions']],'status':'PUBLISHED'});self.assertEqual(approved.status_code,200,approved.text)
        paper=admin.get(f"/api/admin/exams/{approved.json()['id']}/paper").json();self.assertEqual(len(paper['questions']),3)
        with app.connect() as conn:conn.execute("UPDATE questions SET statement='Changed after publication' WHERE id=?",(algebra[0]['id'],));conn.commit()
        self.assertNotIn('Changed after publication',str(admin.get(f"/api/admin/exams/{approved.json()['id']}/paper").json()))

    def test_blueprint_shortage_never_fills_from_unrelated_questions(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):
            app.create_question(app.Question(subject='Mathematics',chapter='Geometry',exam='Grade 8',difficulty='hard',statement='Only geometry?',options=['A','B'],answer='A',verification_status='APPROVED'))
            app.create_question(app.Question(subject='Mathematics',chapter='Algebra',exam='Grade 8',difficulty='hard',statement='Unrelated algebra?',options=['A','B'],answer='A',verification_status='APPROVED'))
        bp={'exam_name':'Shortage','total_questions':2,'global_filters':{'grade':'Grade 8','subject':'Mathematics','verification_statuses':['APPROVED']},'rules':[{'id':'geometry','count':2,'filters':{'chapter':'Geometry','difficulty':'hard'}}]}
        availability=self.post(admin,'/api/admin/exam-blueprints/availability',json=bp).json();self.assertFalse(availability['ready']);self.assertEqual(availability['rules'][0]['available'],1)
        generated=self.post(admin,'/api/admin/exam-blueprints/preview',json=bp);self.assertEqual(generated.status_code,409);self.assertIn('Only 1 matching',generated.text)

    def test_saved_draft_template_can_receive_generated_question_paper(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):q=app.create_question(app.Question(subject='Science',chapter='Light',exam='Class 8',statement='Reflection question?',options=['A','B'],answer='A',verification_status='APPROVED'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Saved Science Template','subject':'Science','level':'Grade 8','status':'DRAFT'}).json()['id']
        bp={'exam_id':eid,'exam_name':'Saved Science Template','total_questions':1,'global_filters':{'grade':'Grade 8','subject':'Science','verification_statuses':['APPROVED']},'rules':[{'id':'light','count':1,'filters':{'chapter':'Light'}}]}
        preview=self.post(admin,'/api/admin/exam-blueprints/preview',json=bp);self.assertEqual(preview.status_code,200,preview.text)
        approved=self.post(admin,'/api/admin/exam-blueprints/approve',json={'blueprint':bp,'question_ids':[q['id']],'status':'DRAFT'});self.assertEqual(approved.status_code,200,approved.text);self.assertEqual(approved.json()['id'],eid)
        self.assertEqual(admin.get(f'/api/exams/{eid}').json()['question_count'],1)

    def test_admin_can_delete_published_exam_without_registration_history(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):q=app.create_question(app.Question(statement='Disposable question',options=['A','B'],answer='A'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Disposable Exam','status':'PUBLISHED','question_ids':[q['id']]}).json()['id']
        deleted=admin.delete(f'/api/admin/exams/{eid}',headers={'X-CSRF-Token':self.csrf(admin)})
        self.assertEqual(deleted.status_code,200,deleted.text)
        self.assertEqual(admin.get(f'/api/exams/{eid}').status_code,404)

    def test_admin_can_delete_unused_exam_registrations(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):q=app.create_question(app.Question(statement='Registration cleanup question',options=['A','B'],answer='A'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Registration Cleanup','status':'PUBLISHED','question_ids':[q['id']]}).json()['id']
        self.post(admin,f'/api/admin/exams/{eid}/registrations',json={'email':'pending@example.test'})
        pending=admin.get(f'/api/admin/exams/{eid}/registrations').json()['pending'][0]
        deleted=admin.delete(f"/api/admin/exams/{eid}/registrations/pending/{pending['id']}",headers={'X-CSRF-Token':self.csrf(admin)})
        self.assertEqual(deleted.status_code,200,deleted.text)
        self.assertEqual(admin.get(f'/api/admin/exams/{eid}/registrations').json()['pending'],[])

    def test_admin_can_grant_one_student_an_additional_attempt(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):q=app.create_question(app.Question(statement='One more attempt?',options=['No','Yes'],answer='B'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Individual Retake','status':'OPEN','question_ids':[q['id']],'max_attempts':1}).json()['id']
        student,_=self.login('retake-student@example.test');self.post(student,f'/api/exams/{eid}/enroll')
        sid=self.post(student,f'/api/exams/{eid}/sessions').json()['session_id'];self.post(student,f'/api/sessions/{sid}/submit')
        registration=admin.get(f'/api/admin/exams/{eid}/registrations').json()['linked'][0]
        granted=self.post(admin,f"/api/admin/exams/{eid}/registrations/{registration['id']}/attempts/increase",json={'increment':1})
        self.assertEqual(granted.status_code,200,granted.text);self.assertEqual(granted.json()['max_attempts'],2)
        mine=student.get('/api/my/exams').json()[0];self.assertEqual(mine['effective_max_attempts'],2);self.assertTrue(mine['student_allow_retake']);self.assertEqual(mine['registration_status'],'ENROLLED')
        second=self.post(student,f'/api/exams/{eid}/sessions');self.assertEqual(second.status_code,200,second.text)

    def test_admin_pending_registration_links_only_matching_verified_login(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):q=app.create_question(app.Question(statement='Q',answer='A'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Pre-registered Exam','status':'PUBLISHED','question_ids':[q['id']]}).json()['id']
        pending=self.post(admin,f'/api/admin/exams/{eid}/registrations',json={'email':'intended@example.test'});self.assertEqual(pending.json()['status'],'PENDING')
        wrong,_=self.login('different@example.test');self.assertEqual(len(wrong.get('/api/my/exams').json()),0)
        intended,_=self.login('intended@example.test');self.assertEqual(len(intended.get('/api/my/exams').json()),1)
        deletion=admin.delete(f'/api/admin/exams/{eid}',headers={'X-CSRF-Token':self.csrf(admin)})
        self.assertEqual(deletion.status_code,409)
        self.assertEqual(admin.get(f'/api/exams/{eid}').status_code,200)

    def test_secure_share_link_registration_profile_and_email_binding(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):q=app.create_question(app.Question(statement='Shared link question',options=['A','B'],answer='A'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Shareable Exam','status':'PUBLISHED','question_ids':[q['id']]}).json()['id']
        made=self.post(admin,f'/api/admin/exams/{eid}/registration-links',json={'max_registrations':2});self.assertEqual(made.status_code,200,made.text)
        token=made.json()['token'];self.assertNotIn('exam_id=',made.json()['url']);self.assertGreaterEqual(len(token),40)
        details=self.client.get(f'/api/register/exam/{token}');self.assertEqual(details.json()['name'],'Shareable Exam');self.assertNotIn('question',details.text.lower())
        registration=self.client.post(f'/api/register/exam/{token}',json={'full_name':'Student One','email':'student1@example.test','date_of_birth':'2012-05-04','phone_number':'+91 9876543210','school_name':'Example School'})
        self.assertEqual(registration.status_code,200,registration.text)
        wrong,_=self.login('student2@example.test');self.assertEqual(wrong.get('/api/my/exams').json(),[])
        student=TestClient(app.app);self.addCleanup(student.close)
        login=student.post('/api/auth/student-registration-login',json={'email':'student1@example.test','date_of_birth':'2012-05-04','phone_number':'+91 9876543210'});self.assertEqual(login.status_code,200,login.text);self.assertEqual(login.json()['role'],'STUDENT');self.assertEqual(len(student.get('/api/my/exams').json()),1)
        self.assertEqual(student.get('/api/exams').json(),[])
        profile=student.get('/api/student/profile').json();self.assertEqual(profile['school_name'],'Example School');self.assertEqual(profile['profile_completed'],1)
        returning=TestClient(app.app);self.addCleanup(returning.close)
        again=returning.post('/api/auth/student-registration-login',json={'email':'student1@example.test','date_of_birth':'2012-05-04','phone_number':'919876543210'});self.assertEqual(again.status_code,200,again.text);self.assertEqual(len(returning.get('/api/my/exams').json()),1)

    def test_published_version_is_immutable_and_retake_creates_new_attempt(self):
        admin,_=self.login('admin@example.test')
        with patch.dict(os.environ,{'AUTH_MODE':''}):q=app.create_question(app.Question(statement='Original published wording',options=['Right','Wrong'],answer='A',solution='Original solution'))
        eid=self.post(admin,'/api/admin/exams',json={'name':'Durable Exam','status':'OPEN','question_ids':[q['id']],'max_attempts':1}).json()['id']
        with app.connect() as conn:conn.execute("UPDATE questions SET statement='Changed bank wording',answer='B' WHERE id=?",(q['id'],));conn.commit()
        student,_=self.login('durable@example.test');self.post(student,f'/api/exams/{eid}/enroll')
        first=self.post(student,f'/api/student/exams/{eid}/start',json={});self.assertEqual(first.status_code,200,first.text);sid1=first.json()['session_id']
        active=student.get(f'/api/sessions/{sid1}').json();self.assertEqual(active['questions'][0]['statement'],'Original published wording')
        self.post(student,f'/api/sessions/{sid1}/submit')
        denied=self.post(student,f'/api/student/exams/{eid}/start',json={});self.assertEqual(denied.json()['detail']['reason_code'],'RETAKE_DISABLED')
        with app.connect() as conn:conn.execute("UPDATE exams SET allow_retake=1,max_attempts=2,status='OPEN' WHERE id=?",(eid,));conn.commit()
        second=self.post(student,f'/api/student/exams/{eid}/start',json={});self.assertEqual(second.status_code,200,second.text);self.assertNotEqual(second.json()['session_id'],sid1)
        attempts=student.get('/api/my/results').json();self.assertEqual(len(attempts),1);self.assertEqual(attempts[0]['attempt_number'],1)
