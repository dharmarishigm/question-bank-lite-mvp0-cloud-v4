import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class ExamRegistrationModuleTests(unittest.TestCase):
    def test_explanations_are_cached_independently_by_language(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
                conn.execute(
                    "INSERT INTO questions (statement, created_at, updated_at) VALUES (?, ?, ?)",
                    ('What is photosynthesis?', 1.0, 1.0),
                )
            with patch.object(app, 'DB_PATH', db):
                app.save_question_explanation(1, 'Plants make food using light.', language='en')
                app.save_question_explanation(1, 'మొక్కలు కాంతిని ఉపయోగించి ఆహారాన్ని తయారు చేసుకుంటాయి.', language='te')

                english = app.get_cached_question_explanation(1, 'en')
                telugu = app.get_cached_question_explanation(1, 'te')

                self.assertIn('Plants', english['explanation'])
                self.assertIn('మొక్కలు', telugu['explanation'])
                self.assertEqual(telugu['language'], 'te')

    def test_explanation_language_rejects_unsupported_values(self):
        with self.assertRaises(app.HTTPException) as raised:
            app.normalize_explanation_language('xx')
        self.assertEqual(raised.exception.status_code, 400)

    def test_structured_explanation_round_trip_preserves_sections(self):
        payload = {
            'title': 'Photosynthesis made clear',
            'summary': 'Plants convert light energy into chemical energy.',
            'concept': 'Chlorophyll absorbs light.',
            'steps': ['Light is absorbed.', 'Glucose is produced.'],
            'correct_answer': 'Option B describes the process.',
            'distractors': [{'option': 'A', 'reason': 'This describes respiration.'}],
            'background': 'The process occurs in chloroplasts.',
            'memory_tip': 'Photo means light; synthesis means making.',
            'references': ['NCERT Science chapter on Life Processes'],
        }
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
                conn.execute("INSERT INTO questions (statement, created_at, updated_at) VALUES (?, ?, ?)", ('Question', 1.0, 1.0))
            with patch.object(app, 'DB_PATH', db):
                app.save_question_explanation(1, app.explanation_markdown(payload), structured=payload)
                cached = app.get_cached_question_explanation(1)
                self.assertEqual(cached['structured']['steps'], payload['steps'])
                self.assertIn('## Memory tip', cached['explanation'])
                self.assertIn('**A**', cached['explanation'])

    def test_exam_registration_crud_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
            with patch.object(app, 'DB_PATH', db):
                created = app.create_exam_registration({
                    'first_name': 'Asha',
                    'last_name': 'Sharma',
                    'date_of_birth': '2004-06-10',
                    'full_name': 'Asha Sharma',
                    'email': 'asha@gmail.com',
                    'phone': '9876543210',
                    'exam_name': 'NEET UG',
                    'exam_date': '2026-12-15',
                    'center_preference': 'Delhi',
                    'status': 'pending',
                    'is_confirmed': True,
                })

                self.assertEqual(created['full_name'], 'Asha Sharma')
                self.assertEqual(created['status'], 'pending')

                items = app.list_exam_registrations()
                self.assertEqual(len(items), 1)

                updated = app.update_exam_registration(created['id'], {
                    'first_name': 'Asha',
                    'last_name': 'Sharma',
                    'date_of_birth': '2004-06-10',
                    'full_name': 'Asha Sharma',
                    'email': 'asha@gmail.com',
                    'phone': '9876543210',
                    'exam_name': 'NEET UG',
                    'exam_date': '2026-12-15',
                    'center_preference': 'Bengaluru',
                    'status': 'approved',
                    'is_confirmed': True,
                })
                self.assertEqual(updated['center_preference'], 'Bengaluru')
                self.assertEqual(updated['status'], 'approved')

                deleted = app.delete_exam_registration(created['id'])
                self.assertEqual(deleted['deleted'], created['id'])
                self.assertEqual(app.list_exam_registrations(), [])

    def test_sample_exam_paper_uses_real_question_bank_records(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
                conn.execute(
                    "INSERT INTO questions (subject, chapter, statement, options, answer, solution, difficulty, qtype, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    *[
                        (
                            'Mathematics', 'Algebra', 'Solve x + 3 = 7.', '["4", "5", "6", "7"]', 'A', 'Subtract 3 from both sides.', 'easy', 'mcq_single', 1.0, 1.0,
                        )
                    ]
                )
                for idx in range(15):
                    conn.execute(
                        "INSERT INTO questions (subject, chapter, statement, options, answer, solution, difficulty, qtype, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            'Physics', f'Unit {idx + 1}', f'Question {idx + 1} from the real bank.', f'["{idx + 1}", "{idx + 2}", "{idx + 3}", "{idx + 4}"]', 'B', 'Explanation', 'medium', 'mcq_single', float(idx + 2), float(idx + 2),
                        )
                    )
            with patch.object(app, 'DB_PATH', db):
                paper = app.sample_exam_paper()
                self.assertIsInstance(paper.get('questions'), list)
                self.assertEqual(len(paper['questions']), 15)
                self.assertTrue(all('statement' in question for question in paper['questions']))
                self.assertTrue(all('options' in question for question in paper['questions']))
                self.assertTrue(all(question['statement'] == 'Solve x + 3 = 7.' or 'from the real bank.' in question['statement'] for question in paper['questions']))

    def test_exam_registration_requires_gmail_and_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
            with patch.object(app, 'DB_PATH', db):
                with self.assertRaises(ValueError):
                    app.request_exam_registration_confirmation('user@example.com')

                data = app.request_exam_registration_confirmation('candidate@gmail.com')
                self.assertIn('confirmation_url', data)
                self.assertTrue(data['confirmation_url'].endswith(data['token']))

                confirmed = app.confirm_exam_registration(data['token'])
                self.assertTrue(confirmed['confirmed'])
                self.assertEqual(confirmed['email'], 'candidate@gmail.com')

    def test_explain_question_reads_text_from_candidate_parts(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
                conn.execute(
                    "INSERT INTO questions (subject, chapter, statement, options, answer, solution, difficulty, qtype, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ('Physics', 'Motion', 'A car moves at constant speed.', '["10 m/s", "20 m/s", "30 m/s", "40 m/s"]', 'A', 'It is consistent with the graph.', 'easy', 'mcq_single', 1.0, 1.0),
                )
            with patch.object(app, 'DB_PATH', db), patch.object(app, 'llm_status', return_value={'available': True, 'model': 'gemini-2.0-flash'}):
                class FakePart:
                    text = 'The key idea is constant velocity, so the net acceleration is zero.'

                class FakeContent:
                    parts = [FakePart()]

                class FakeCandidate:
                    content = FakeContent()

                class FakeResponse:
                    text = ''
                    candidates = [FakeCandidate()]

                fake_client = type('Client', (), {'models': type('Models', (), {'generate_content': lambda self, **kwargs: FakeResponse()})()})()
                fake_genai = type('GenAI', (), {'Client': staticmethod(lambda **kwargs: fake_client)})
                fake_types = type('Types', (), {'HttpOptions': staticmethod(lambda **kwargs: object()), 'GenerateContentConfig': staticmethod(lambda **kwargs: object())})
                import sys, types
                google_module = types.ModuleType('google')
                google_genai_module = types.ModuleType('google.genai')
                google_genai_module.__dict__['Client'] = fake_genai.Client
                google_genai_module.__dict__['types'] = fake_types
                google_module.__dict__['genai'] = google_genai_module
                with patch.dict(sys.modules, {'google': google_module, 'google.genai': google_genai_module}):
                    result = app.explain_question(1)
                    self.assertIn('constant velocity', result['explanation'])

    def test_explain_question_reads_dict_like_candidate_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
                conn.execute(
                    "INSERT INTO questions (subject, chapter, statement, options, answer, solution, difficulty, qtype, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ('Biology', 'Cell', 'Which organelle is called the power house of the cell?', '["Nucleus", "Mitochondria", "Ribosome", "Golgi body"]', 'B', 'Mitochondria produce ATP.', 'easy', 'mcq_single', 1.0, 1.0),
                )
            with patch.object(app, 'DB_PATH', db), patch.object(app, 'llm_status', return_value={'available': True, 'model': 'gemini-2.0-flash'}):
                fake_response = {
                    'text': '',
                    'candidates': [{
                        'content': {
                            'parts': [{'text': 'The mitochondrion is called the powerhouse because it generates ATP through cellular respiration.'}]
                        }
                    }]
                }

                fake_client = type('Client', (), {'models': type('Models', (), {'generate_content': lambda self, **kwargs: fake_response})()})()
                fake_genai = type('GenAI', (), {'Client': staticmethod(lambda **kwargs: fake_client)})
                fake_types = type('Types', (), {'HttpOptions': staticmethod(lambda **kwargs: object()), 'GenerateContentConfig': staticmethod(lambda **kwargs: object())})
                import sys, types
                google_module = types.ModuleType('google')
                google_genai_module = types.ModuleType('google.genai')
                google_genai_module.__dict__['Client'] = fake_genai.Client
                google_genai_module.__dict__['types'] = fake_types
                google_module.__dict__['genai'] = google_genai_module
                with patch.dict(sys.modules, {'google': google_module, 'google.genai': google_genai_module}):
                    result = app.explain_question(1)
                    self.assertIn('ATP', result['explanation'])

    def test_explain_question_ignores_content_type_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / 'questions.db')
            with sqlite3.connect(db) as conn:
                conn.executescript(app.SCHEMA)
                conn.execute(
                    "INSERT INTO questions (subject, chapter, statement, options, answer, solution, difficulty, qtype, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ('Chemistry', 'Thermochemistry', 'The reaction is exothermic.', '["Release heat", "Absorb heat", "No heat", "Convert heat"]', 'A', 'Exothermic reactions release heat.', 'easy', 'mcq_single', 1.0, 1.0),
                )
            with patch.object(app, 'DB_PATH', db), patch.object(app, 'llm_status', return_value={'available': True, 'model': 'gemini-2.0-flash'}):
                fake_response = {
                    'text': '',
                    'mime_type': 'application/json; charset=UTF-8',
                    'candidates': [{
                        'content': {
                            'parts': [{'text': 'This reaction releases heat because the products are at lower enthalpy than the reactants.'}]
                        }
                    }],
                    'usage_metadata': {'prompt_token_count': 18}
                }

                fake_client = type('Client', (), {'models': type('Models', (), {'generate_content': lambda self, **kwargs: fake_response})()})()
                fake_genai = type('GenAI', (), {'Client': staticmethod(lambda **kwargs: fake_client)})
                fake_types = type('Types', (), {'HttpOptions': staticmethod(lambda **kwargs: object()), 'GenerateContentConfig': staticmethod(lambda **kwargs: object())})
                import sys, types
                google_module = types.ModuleType('google')
                google_genai_module = types.ModuleType('google.genai')
                google_genai_module.__dict__['Client'] = fake_genai.Client
                google_genai_module.__dict__['types'] = fake_types
                google_module.__dict__['genai'] = google_genai_module
                with patch.dict(sys.modules, {'google': google_module, 'google.genai': google_genai_module}):
                    result = app.explain_question(1)
                    self.assertIn('releases heat', result['explanation'].lower())
                    self.assertNotIn('application/json', result['explanation'])
