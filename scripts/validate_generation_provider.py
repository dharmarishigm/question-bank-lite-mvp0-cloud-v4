"""Opt-in synthetic Vertex probe; never reads or writes application data.

Run with the production project/model environment and local ADC credentials.
Only the prompt registry is created, in disposable local SQLite. Output contains
timings, structural checks and provider metadata; no credentials or user content.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scenario',choices=['linear','jee-chemistry'],default='linear')
    args=parser.parse_args()
    from google import genai
    from google.genai import types
    from ai_runtime import response_metadata,response_payload
    from llm_extract import gcp_project_id,gcp_region
    from llm_generate import GenerationRequest,PromptGuidanceRequest,configured_vertex_model,generate_questions,generate_prompt_guidance
    from prompt_registry import init_prompt_registry,resolve_active_prompt

    def probe(kind):
        receipts=[];started=time.monotonic()
        real=genai.Client(vertexai=True,project=gcp_project_id(),location=gcp_region(),http_options=types.HttpOptions(api_version='v1',timeout=90000,retry_options=types.HttpRetryOptions(attempts=1)))
        class Models:
            def generate_content(self,**kwargs):
                response=real.models.generate_content(**kwargs)
                receipt=response_metadata(response)
                try:
                    decoded=response_payload(response)
                    if isinstance(decoded,dict) and isinstance(decoded.get('questions'),list):
                        receipt['response_question_count']=len(decoded['questions'])
                        receipt['field_lengths']=[{field:len(str(item.get(field,''))) for field in ('statement','solution','explanation_en','explanation_te')} for item in decoded['questions']]
                except ValueError:pass
                receipts.append(receipt)
                return response
        client=type('Client',(),{'models':Models()})()
        try:
            if kind=='generation':
                request=GenerationRequest(exam_name='Synthetic provider validation',subject='Mathematics',level='Grade 8',difficulty='medium',question_type='mcq_single',count=1,syllabus='Linear equations in one variable.',generation_prompt='Create an original concise word problem whose solution reduces to 3x+5=20, asking for x. Supply four distinct numeric options, exactly one correct option x=5, a worked solution, and both teaching explanations. Use valid LaTeX.')
                if args.scenario=='jee-chemistry':
                    request=GenerationRequest(exam_name='IIT JEE Main B.E./B.Tech. synthetic validation',subject='Chemistry',level='Class 12',difficulty='very_hard',question_type='mcq_single',count=3,syllabus='Chemical thermodynamics, chemical equilibrium, and electrochemistry at JEE Main level.',generation_prompt='Create three original challenging multi-step calculation questions, one per supplied topic. State every needed constant and assumption. Supply exactly four distinct options with one correct answer, concise independently useful worked solutions, English and Telugu teaching explanations, and valid LaTeX for all notation. Do not reproduce published examination questions.')
                batch,usage,model=generate_questions(request,client=client)
                q=batch.questions[0]
                checks={'one_question':len(batch.questions)==1,'four_options':len(q.options)==4,'solution':bool(q.solution.strip()),'english':bool(q.explanation_en.strip()),'telugu_script':any('\u0c00'<=c<='\u0c7f' for c in q.explanation_te),'latex':'$' in q.statement+q.solution,'known_answer':any(o.label.upper()==q.answer.upper() and '5' in o.text for o in q.options)}
                if args.scenario=='jee-chemistry':
                    checks={'three_questions':len(batch.questions)==3,'four_options':all(len(item.options)==4 for item in batch.questions),'solution':all(item.solution.strip() for item in batch.questions),'english':all(item.explanation_en.strip() for item in batch.questions),'telugu_script':all(any('\u0c00'<=c<='\u0c7f' for c in item.explanation_te) for item in batch.questions),'latex':all('$' in item.statement+item.solution for item in batch.questions)}
                checks.pop('english',None);checks.pop('telugu_script',None)
                checks['teaching_explanations_deferred']=all(not item.explanation_en and not item.explanation_te for item in batch.questions)
            else:
                guidance,model=generate_prompt_guidance(PromptGuidanceRequest(exam_name='Synthetic provider validation',subject='Mathematics',level='Grade 8',topic='Linear equations',count=1),client=client)
                checks={'syllabus':len(guidance.syllabus)>=20,'generation_prompt':len(guidance.generation_prompt)>=20}
            return {'case':kind,'ok':all(checks.values()),'seconds':round(time.monotonic()-started,2),'model':model,'checks':checks,'responses':receipts}
        except Exception as exc:
            return {'case':kind,'ok':False,'seconds':round(time.monotonic()-started,2),'error_type':type(exc).__name__,'responses':receipts}
        finally:
            real.close()

    with tempfile.TemporaryDirectory(prefix='generation-provider-probe-') as directory:
        conn=sqlite3.connect(str(Path(directory)/'registry.db'),check_same_thread=False);conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)');init_prompt_registry(conn)
        try:
            with patch('prompt_registry.resolve_active_prompt',side_effect=lambda key:resolve_active_prompt(key,conn=conn)):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results=list(pool.map(probe,['generation'] if args.scenario=='jee-chemistry' else ['generation','guidance']))
        finally:
            conn.close()
    print(json.dumps({'project':gcp_project_id(),'region':gcp_region(),'configured_model':configured_vertex_model(),'production_application_data_touched':False,'results':results},ensure_ascii=False))
    return 0 if all(result['ok'] for result in results) else 1


if __name__=='__main__':raise SystemExit(main())
