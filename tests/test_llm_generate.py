import os, sqlite3, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import app
from llm_generate import BILINGUAL_GENERATION_RULE, GeneratedOption, GeneratedQuestion, GeneratedQuestionBatch, GenerationRequest, PartialGenerationError, PromptGuidanceRequest, generate_prompt_guidance, generate_questions, parse_generated_batch, public_prompt_preview, validate_question
from platform_api import init_platform
from visual_renderer import render_visual_panels


class PromptGenerationTests(unittest.TestCase):
    def request(self, **overrides):
        data={"exam_name":"Any Custom Examination","subject":"Any Subject","count":1,"syllabus":"line one\nline two","generation_prompt":"Preserve this EXACT instruction.\nSecond line.","extra_metadata":{"calculator_allowed":False}}
        data.update(overrides);return GenerationRequest(**data)

    def response(self, *statements):
        return SimpleNamespace(parsed={'questions':[{
            'statement':statement,'options':['One','Two'],'answer':'B',
            'solution':'The second option follows from the calculation.',
            'explanation_en':'Compare the values and choose the second option.',
            'explanation_te':'విలువలను పోల్చి రెండవ ఎంపికను ఎంచుకోండి.',
        } for statement in statements]},usage_metadata=SimpleNamespace(prompt_token_count=10,candidates_token_count=20,total_token_count=30))

    def client(self, *responses):
        class Models:
            def __init__(self):self.responses=list(responses);self.calls=[]
            def generate_content(self,**kwargs):
                self.calls.append(kwargs)
                response=self.responses.pop(0)
                if isinstance(response,Exception):raise response
                return response
        return SimpleNamespace(models=Models())

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

    def test_structured_parser_recovers_json_from_candidate_parts(self):
        part=type('Part',(),{'text':'{"questions":[{"statement":"Recovered","answer":"A"}]}'})()
        content=type('Content',(),{'parts':[part]})();candidate=type('Candidate',(),{'content':content})()
        response=type('Response',(),{'parsed':None,'text':'','candidates':[candidate]})()
        self.assertEqual(parse_generated_batch(response).questions[0].statement,'Recovered')

    def test_generation_retries_truncated_math_json(self):
        malformed=type('Response',(),{'parsed':None,'text':'{"questions":[{"statement":"Solve $x^2','usage_metadata':None})()
        valid=type('Response',(),{'parsed':None,'text':'{"questions":[{"statement":"Solve $x^2=4$.","options":["1","2"],"answer":"B","solution":"$x=2$ for the positive root.","explanation_en":"Use square roots to solve and verify the selected option.","explanation_te":"వర్గమూలాలను ఉపయోగించి పరిష్కరించి సరైన ఎంపికను ధృవీకరించండి."}]}','usage_metadata':None})()
        class Models:
            def __init__(self):self.responses=[malformed,valid];self.calls=[]
            def generate_content(self,**kwargs):self.calls.append(kwargs);return self.responses.pop(0)
        client=type('Client',(),{'models':Models()})()
        with patch('llm_generate.gcp_project_id',return_value='test-project'):
            batch,_,_=generate_questions(self.request(),client=client)
        self.assertEqual(len(batch.questions),1);self.assertEqual(batch.questions[0].answer,'B');self.assertEqual(len(client.models.calls),2)
        self.assertIn('prior response was invalid or truncated',client.models.calls[1]['contents'])
        self.assertIn('Represent all equations',client.models.calls[0]['config'].system_instruction)

    def test_active_legacy_prompt_gets_mandatory_bilingual_schema_and_bounded_thinking(self):
        client=self.client(self.response('A valid new question'))
        legacy={'id':42,'content_hash':'original-registry-hash','system_content':'Generate original questions.'}
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch('llm_generate.configured_vertex_model',return_value='gemini-2.5-flash'),patch('prompt_registry.resolve_active_prompt',return_value=legacy):
            _,usage,_=generate_questions(self.request(),client=client)
        config=client.models.calls[0]['config']
        self.assertIn(BILINGUAL_GENERATION_RULE,config.system_instruction)
        self.assertEqual(config.thinking_config.thinking_budget,1024)
        self.assertFalse(config.thinking_config.include_thoughts)
        schema=config.response_schema
        required=schema['properties']['questions']['items']['required']
        self.assertTrue({'solution','explanation_en','explanation_te'}.issubset(required))
        self.assertEqual(usage['prompt_content_hash'],'original-registry-hash')
        self.assertNotEqual(usage['effective_system_prompt_hash'],usage['prompt_content_hash'])

    def test_partial_provider_batch_retries_only_missing_question(self):
        first=self.response('Saved first question','Incomplete question')
        first.parsed['questions'][1].pop('explanation_te')
        client=self.client(first,self.response('Replacement second question'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_MAX_RETRIES':'1'}):
            batch,usage,_=generate_questions(self.request(count=2),client=client)
        self.assertEqual([q.statement for q in batch.questions],['Saved first question','Replacement second question'])
        self.assertIn('Question Count: 1',client.models.calls[1]['contents'])
        self.assertIn('Saved first question',client.models.calls[1]['contents'])
        self.assertEqual(usage['total_token_count'],60)

    def test_difficult_questions_use_single_question_provider_batches(self):
        client=self.client(self.response('Hard first'),self.response('Hard second'),self.response('Hard third'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'):
            batch,_,_=generate_questions(self.request(count=3,difficulty='Very Hard'),client=client)
        self.assertEqual(len(batch.questions),3)
        self.assertEqual(len(client.models.calls),3)
        self.assertTrue(all('Question Count: 1' in call['contents'] for call in client.models.calls))

    def test_completed_internal_batches_survive_later_provider_failure(self):
        client=self.client(self.response('First','Second','Third'),TimeoutError('provider timed out'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_MAX_RETRIES':'0','AI_GENERATION_BATCH_SIZE':'3'}):
            with self.assertRaises(PartialGenerationError) as failure:
                generate_questions(self.request(count=4),client=client)
        self.assertEqual([q.statement for q in failure.exception.batch.questions],['First','Second','Third'])
        self.assertEqual(failure.exception.usage['provider_calls'],2)
        self.assertEqual(failure.exception.usage['total_token_count'],30)
        self.assertTrue(failure.exception.model)

    def test_transient_provider_failure_is_retried_but_access_failure_is_not(self):
        client=self.client(TimeoutError('temporary'),self.response('Recovered'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_MAX_RETRIES':'1'}):
            batch,_,_=generate_questions(self.request(),client=client)
        self.assertEqual(batch.questions[0].statement,'Recovered')
        self.assertEqual(len(client.models.calls),2)
        class AccessDenied(Exception):code=403
        client=self.client(AccessDenied('access denied'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'):
            with self.assertRaises(AccessDenied):generate_questions(self.request(),client=client)
        self.assertEqual(len(client.models.calls),1)

    def test_generation_failure_reports_actual_attempt_count(self):
        client=self.client(SimpleNamespace(parsed=None,text='not JSON'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_MAX_RETRIES':'0'}):
            with self.assertRaisesRegex(ValueError,r'after 1 attempt\(s\)'):
                generate_questions(self.request(),client=client)
        self.assertEqual(len(client.models.calls),1)

    def test_output_budget_has_safe_floor_and_only_grows_on_token_truncation(self):
        client=self.client(self.response('Budget floor'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_GENERATION_MAX_OUTPUT_TOKENS':'1024'}):
            generate_questions(self.request(),client=client)
        self.assertEqual(client.models.calls[0]['config'].max_output_tokens,6000)
        truncated=SimpleNamespace(parsed=None,text='{"questions":[',candidates=[SimpleNamespace(finish_reason='MAX_TOKENS')])
        client=self.client(truncated,self.response('Recovered at a larger output budget'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_GENERATION_MAX_OUTPUT_TOKENS':'12000','AI_MAX_RETRIES':'1'}):
            generate_questions(self.request(),client=client)
        self.assertEqual([call['config'].max_output_tokens for call in client.models.calls],[6000,9000])

    def test_safety_block_does_not_retry_or_split(self):
        blocked=SimpleNamespace(parsed=None,text='',candidates=[SimpleNamespace(finish_reason='SAFETY')])
        client=self.client(blocked)
        with patch('llm_generate.gcp_project_id',return_value='test-project'):
            with self.assertRaisesRegex(RuntimeError,'provider blocked'):
                generate_questions(self.request(count=3),client=client)
        self.assertEqual(len(client.models.calls),1)

    def test_total_deadline_caps_request_timeout_and_preserves_completed_batch(self):
        client=self.client(self.response('First','Second','Third'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_GENERATION_BATCH_SIZE':'3','AI_GENERATION_TOTAL_TIMEOUT_SECONDS':'30','AI_MAX_RETRIES':'1'}),patch('llm_generate.time.monotonic',side_effect=[0,25,31,31]):
            with self.assertRaises(PartialGenerationError) as failure:
                generate_questions(self.request(count=4),client=client)
        self.assertEqual(len(client.models.calls),1)
        self.assertEqual(client.models.calls[0]['config'].http_options.timeout,5000)
        self.assertEqual(len(failure.exception.questions),3)
        self.assertEqual(failure.exception.usage['provider_calls'],1)

    def test_truncated_batch_splits_immediately_and_preserves_completed_split(self):
        invalid=SimpleNamespace(parsed=None,text='{"questions":[')
        client=self.client(invalid,self.response('First split question'),TimeoutError('unavailable'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_MAX_RETRIES':'0'}):
            with self.assertRaises(PartialGenerationError) as failure:
                generate_questions(self.request(count=2),client=client)
        self.assertEqual([q.statement for q in failure.exception.questions],['First split question'])
        self.assertEqual(len(client.models.calls),3)
        self.assertIn('Question Count: 1',client.models.calls[1]['contents'])

    def test_duplicate_provider_items_are_replaced_without_losing_first(self):
        client=self.client(self.response('Same stem','Same stem'),self.response('Distinct stem'))
        with patch('llm_generate.gcp_project_id',return_value='test-project'),patch.dict(os.environ,{'AI_MAX_RETRIES':'1'}):
            batch,_,_=generate_questions(self.request(count=2),client=client)
        self.assertEqual([q.statement for q in batch.questions],['Same stem','Distinct stem'])

    def test_guidance_recovers_transient_failure(self):
        client=self.client(TimeoutError('temporary'),SimpleNamespace(parsed={'syllabus':'A complete focused curriculum scope with concepts.','generation_prompt':'Generate original questions and bilingual explanations.'}))
        with patch('llm_generate.gcp_project_id',return_value='test-project'):
            guidance,_=generate_prompt_guidance(PromptGuidanceRequest(exam_name='Exam',subject='Math'),client=client)
        self.assertIn('focused',guidance.syllabus)
        self.assertEqual(len(client.models.calls),2)

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
                generated=GeneratedQuestionBatch(questions=[GeneratedQuestion(statement="An original $x^2$ question?",options=[GeneratedOption(label="A",text="One"),GeneratedOption(label="B",text="Two")],answer="B",solution="Because $x=2$.",explanation_en="English cached concept and reasoning.",explanation_te="తెలుగులో నిల్వ చేసిన భావన మరియు వివరణ.")])
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
                with patch.object(app,'llm_status',side_effect=AssertionError('Cached explanations must not call AI')):
                    english=client.get(f"/api/questions/{question['id']}/explain?language=en")
                    telugu=client.get(f"/api/questions/{question['id']}/explain?language=te")
                self.assertTrue(english.json()['cached']);self.assertIn('English cached',english.json()['explanation'])
                self.assertTrue(telugu.json()['cached']);self.assertIn('తెలుగులో',telugu.json()['explanation'])
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
