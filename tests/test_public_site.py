import os, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app
from platform_api import init_platform
from exam_conduct import init_exam_conduct


class PublicSiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        db = str(Path(self.tmp.name) / 'platform.db')
        with sqlite3.connect(db) as conn: conn.executescript(app.SCHEMA)
        self.dbpatch = patch.object(app, 'DB_PATH', db); self.dbpatch.start(); self.addCleanup(self.dbpatch.stop)
        self.env = patch.dict(os.environ, {'APP_ENV': 'test', 'AUTH_MODE': 'mock', 'ADMIN_EMAILS': 'admin@example.test'}, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        init_platform(); init_exam_conduct()
        self.client = TestClient(app.app); self.addCleanup(self.client.close)

    def login(self, email):
        client = TestClient(app.app); self.addCleanup(client.close)
        client.post('/api/auth/mock', json={'email': email, 'name': email.split('@')[0]})
        return client

    def publish_exam(self, **overrides):
        admin = self.login('admin@example.test')
        with patch.dict(os.environ, {'AUTH_MODE': ''}):
            question = app.create_question(app.Question(statement='2+2?', options=['3', '4'], answer='B', solution='Add the terms.'))
        payload = {'name': 'Physics Practice Paper', 'description': 'Mechanics revision set.', 'status': 'PUBLISHED',
                   'subject': 'Physics', 'level': 'Grade 11', 'exam_type': 'PRACTICE', 'duration_minutes': 45,
                   'question_ids': [question['id']]}
        payload.update(overrides)
        created = admin.post('/api/admin/exams', headers={'X-CSRF-Token': admin.cookies.get('qb_csrf')}, json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        return {**payload, **created.json()}, question

    def test_marketing_home_is_served_anonymously_and_app_shell_stays_available(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn('Practice smarter', home.text)
        self.assertIn('/static/home.js', home.text)
        workspace = self.client.get('/app')
        self.assertEqual(workspace.status_code, 200)
        self.assertIn('platform-ui.js', workspace.text)
        self.assertIn('viewport', home.text)
        self.assertIn('/register/exam/', self.client.get('/register/exam/sometoken').request.url.path)
        self.assertEqual(self.client.get('/register/exam/sometoken').status_code, 200)

    def test_public_home_payload_lists_published_exams_without_answers(self):
        exam, question = self.publish_exam()
        response = self.client.get('/api/public/home')
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        names = [item['name'] for item in data['trending_exams']]
        self.assertIn(exam['name'], names)
        self.assertEqual(data['stats']['published_exams'], 1)
        self.assertEqual(data['trending_label'], 'Explore practice exams')
        self.assertNotIn('answer', response.text.lower().replace('answers', ''))
        self.assertNotIn(question['statement'], response.text)
        self.assertNotIn('solution', response.text.lower())

    def test_draft_exams_are_never_public(self):
        self.publish_exam(name='Hidden Draft Paper', status='DRAFT')
        listing = self.client.get('/api/public/exams')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()['exams'], [])
        self.assertEqual(self.client.get('/api/public/home').json()['trending_exams'], [])

    def test_public_exam_detail_and_filters(self):
        exam, _ = self.publish_exam()
        detail = self.client.get(f"/api/public/exams/{exam['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['mode'], 'PRACTICE')
        self.assertEqual(detail.json()['question_count'], 1)
        self.assertEqual(self.client.get('/api/public/exams?subject=Physics').json()['exams'][0]['id'], exam['id'])
        self.assertEqual(self.client.get('/api/public/exams?subject=Chemistry').json()['exams'], [])
        self.assertEqual(self.client.get('/api/public/exams?q=Mechanics').json()['exams'][0]['id'], exam['id'])
        categories = {item['value'] for item in self.client.get('/api/public/exams').json()['categories']}
        self.assertIn('Physics', categories)
        self.assertEqual(self.client.get('/api/public/exams/999999').status_code, 404)

    def test_public_endpoints_never_bypass_authenticated_apis(self):
        self.publish_exam()
        self.assertEqual(self.client.get('/api/exams').status_code, 401)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)
        self.assertEqual(self.client.get('/api/questions').status_code, 401)
        self.assertTrue(self.client.get('/api/auth/config').json()['mock'])

    def test_marketing_home_can_be_disabled_by_configuration(self):
        with patch.dict(os.environ, {'SHOW_MARKETING_HOME': '0'}):
            root = self.client.get('/')
            self.assertEqual(root.status_code, 200)
            self.assertIn('platform-ui.js', root.text)
            self.assertEqual(self.client.get('/api/public/home').status_code, 404)
        with patch.dict(os.environ, {'SHOW_PUBLIC_EXAM_CATALOG': 'false'}):
            self.assertEqual(self.client.get('/api/public/exams').status_code, 404)
            self.assertEqual(self.client.get('/api/public/home').json()['trending_exams'], [])


if __name__ == '__main__':
    unittest.main()
