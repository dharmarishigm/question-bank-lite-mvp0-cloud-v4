import os, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
from llm_generate import GeneratedOption, GeneratedQuestion, GeneratedQuestionBatch, GenerationRequest, PromptGuidanceRequest, generate_prompt_guidance, generate_questions, parse_generated_batch, public_prompt_preview, validate_question
from platform_api import init_platform
from visual_renderer import render_visual_panels


class PromptGenerationTests(unittest.TestCase):
    def request(self, **overrides):
        data={"exam_name":"Any Custom Examination","subject":"Any Subject","count":1,"syllabus":"line one\nline two","generation_prompt":"Preserve this EXACT instruction.\nSecond line.","extra_metadata":{"calculator_allowed":False}}
        data.update(overrides);return GenerationRequest(**data)

    def test_effective_prompt_preserves_context_and_exact_prompt(self):
        request=self.request(topic="Arbitrary Topic",level="Professional")
        preview=public_prompt_preview(request)
        self.assertIn("Any Custom Examination",preview);self.assertIn("Arbitrary Topic",preview)
        self.assertIn("line one\nline two",preview);self.assertIn(request.generation_prompt,preview)
        self.assertIn('"calculator_allowed": false',preview)

    def test_required_fields_and_structural_validation(self):
        for field in ("exam_name","subject","generation_prompt"):
            with self.assertRaises(ValueError):self.request(**{field:""})
        validate_question(GeneratedQuestion(statement="Explain consistency.",answer="A concise answer"))
        with self.assertRaises(ValueError):validate_question(GeneratedQuestion(statement="Choose.",options=[GeneratedOption(label="A",text="same"),GeneratedOption(label="B",text="same")],answer="A"))
        with self.assertRaises(ValueError):validate_question(GeneratedQuestion(statement="Choose.",options=[GeneratedOption(label="A",text="one"),GeneratedOption(label="B",text="two")],answer="C"))

    def test_structured_parser_normalizes_common_gemini_json_variations(self):
        response=type('Response',(),{'parsed':None,'text':'```json\n[{"question_text":"Choose","options":["One","Two"],"correct_answer":"Two","explanation":"Reason"}]\n```'})()
        batch=parse_generated_batch(response)
        self.assertEqual(batch.questions[0].statement,'Choose');self.assertEqual(batch.questions[0].answer,'B')
        self.assertEqual(batch.questions[0].options[0].label,'A');self.assertEqual(batch.questions[0].solution,'Reason')

    def test_generation_retries_truncated_math_json(self):
        malformed=type('Response',(),{'parsed':None,'text':'{"questions":[{"statement":"Solve $x^2','usage_metadata':None})()
        valid=type('Response',(),{'parsed':None,'text':'{"questions":[{"statement":"Solve $x^2=4$.","options":["1","2"],"answer":"B","solution":"$x=2$ for the positive root."}]}','usage_metadata':None})()
        class Models:
            def __init__(self):self.responses=[malformed,valid];self.calls=[]
            def generate_content(self,**kwargs):self.calls.append(kwargs);return self.responses.pop(0)
        client=type('Client',(),{'models':Models()})()
        with patch('llm_generate.gcp_project_id',return_value='test-project'):
            batch,_,_=generate_questions(self.request(),client=client)
        self.assertEqual(len(batch.questions),1);self.assertEqual(batch.questions[0].answer,'B');self.assertEqual(len(client.models.calls),2)
        self.assertIn('prior response was invalid or truncated',client.models.calls[1]['contents'])

    def test_gemini_can_draft_syllabus_and_generation_prompt_from_minimal_metadata(self):
        response=type('Response',(),{'parsed':None,'text':'{"syllabus":"Grade 4 matter, materials, observable properties, mixtures, and changes.","generation_prompt":"Generate age-appropriate reasoning MCQs with four distinct options, one valid answer, and concise explanations."}'})()
        models=type('Models',(),{'generate_content':lambda self,**kwargs:response})()
        client=type('Client',(),{'models':models})()
        with patch('llm_generate.gcp_project_id',return_value='test-project'):
            guidance,model=generate_prompt_guidance(PromptGuidanceRequest(exam_name='Olympiad',subject='Science',level='Grade 4'),client=client)
        self.assertIn('Grade 4',guidance.syllabus);self.assertIn('four distinct options',guidance.generation_prompt);self.assertTrue(model)

    def test_visual_question_and_each_option_render_as_separate_svg(self):
        panel={'primitives':[{'type':'LINE','x1':10,'y1':10,'x2':100,'y2':100}]}
        spec={'question_figure':panel,'options':{key:panel for key in 'ABCD'}}
        with tempfile.TemporaryDirectory() as directory:
            assets=render_visual_panels(spec,directory)
            self.assertEqual(set(assets),{'question','A','B','C','D'})
            self.assertTrue(all((Path(directory)/url.rsplit('/',1)[-1]).exists() for url in assets.values()))

    def test_generation_endpoint_persists_canonical_question_and_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            db=str(Path(directory)/"questions.db")
            with sqlite3.connect(db) as conn:conn.executescript(app.SCHEMA)
            with patch.object(app,"DB_PATH",db),patch.dict(os.environ,{"APP_ENV":"test","AUTH_MODE":"mock","ADMIN_EMAILS":"admin@example.test"},clear=False):
                init_platform();client=TestClient(app.app)
                login=client.post('/api/auth/mock',json={'email':'admin@example.test'});self.assertEqual(login.status_code,200)
                generated=GeneratedQuestionBatch(questions=[GeneratedQuestion(statement="An original $x^2$ question?",options=[GeneratedOption(label="A",text="One"),GeneratedOption(label="B",text="Two")],answer="B",solution="Because $x=2$.")])
                with patch.object(app,"generate_questions",return_value=(generated,{"total_token_count":42},"configured-model")):
                    response=client.post('/api/ai/generate',headers={'X-CSRF-Token':client.cookies.get('qb_csrf')},json=self.request().model_dump())
                self.assertEqual(response.status_code,200,response.text);body=response.json();self.assertEqual(body['accepted'],0);self.assertEqual(body['review_required'],1)
                saved=client.post(f"/api/ai/runs/{body['run_id']}/save",headers={'X-CSRF-Token':client.cookies.get('qb_csrf')},json={'indices':[0]})
                self.assertEqual(saved.status_code,200,saved.text);self.assertEqual(saved.json()['saved_count'],1)
                with app.connect() as conn:
                    question=conn.execute('SELECT * FROM questions').fetchone();run=conn.execute('SELECT * FROM ai_generation_runs').fetchone()
                self.assertEqual(question['source_type'],'AI_GENERATED');self.assertEqual(question['generation_model'],'configured-model')
                self.assertEqual(question['generation_prompt'],self.request().generation_prompt);self.assertEqual(question['verification_status'],'APPROVED')
                self.assertEqual(run['status'],'SAVED');self.assertEqual(run['accepted_count'],1)
                history=client.get('/api/ai/runs');self.assertEqual(history.status_code,200);self.assertEqual(len(history.json()),1)
                detail=client.get(f"/api/ai/runs/{body['run_id']}");self.assertEqual(detail.status_code,200)
                self.assertEqual(detail.json()['request']['generation_prompt'],self.request().generation_prompt)
                replacement=GeneratedQuestionBatch(questions=[GeneratedQuestion(statement="A different generated question",answer="A different answer")])
                with patch.object(app,"generate_questions",return_value=(replacement,{},"configured-model")):
                    regenerated=client.post(f"/api/ai/runs/{body['run_id']}/regenerate",headers={'X-CSRF-Token':client.cookies.get('qb_csrf')})
                self.assertEqual(regenerated.status_code,200,regenerated.text);self.assertNotEqual(regenerated.json()['run_id'],body['run_id'])
                self.assertEqual(len(client.get('/api/ai/runs').json()),2)
                client.close()

    def test_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            db=str(Path(directory)/"questions.db")
            with sqlite3.connect(db) as conn:conn.executescript(app.SCHEMA)
            with patch.object(app,"DB_PATH",db),patch.dict(os.environ,{"APP_ENV":"test","AUTH_MODE":"mock","ADMIN_EMAILS":"admin@example.test"},clear=False):
                init_platform();client=TestClient(app.app);client.post('/api/auth/mock',json={'email':'admin@example.test'})
                batch=GeneratedQuestionBatch(questions=[GeneratedQuestion(statement="Duplicate statement",answer="Answer")])
                with patch.object(app,"generate_questions",return_value=(batch,{},"model")):
                    headers={'X-CSRF-Token':client.cookies.get('qb_csrf')};first=client.post('/api/ai/generate',headers=headers,json=self.request().model_dump())
                    saved=client.post(f"/api/ai/runs/{first.json()['run_id']}/save",headers=headers,json={'indices':[0]})
                    second=client.post('/api/ai/generate',headers=headers,json=self.request().model_dump())
                self.assertEqual(first.json()['review_required'],1);self.assertEqual(saved.json()['saved_count'],1);self.assertEqual(second.json()['review_required'],0);self.assertEqual(second.json()['rejected'],1);client.close()


if __name__ == '__main__': unittest.main()
