"""Real Vertex smoke tests with synthetic data and an isolated disposable database.

Reads only non-secret model configuration from a Cloud Run service. No application
production API, production database, or storage writes are performed. Provider
calls consume a small amount of normal Vertex usage.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--service', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cases', default='extraction,setup,official')
    args = parser.parse_args()
    config = json.loads(subprocess.run([
        'gcloud', 'run', 'services', 'describe', args.service,
        '--project=' + args.project, '--region=' + args.region, '--format=json',
    ], capture_output=True, text=True, check=True).stdout)
    allowed = {'GCP_PROJECT_ID', 'GCP_REGION', 'GOOGLE_CLOUD_PROJECT', 'GOOGLE_CLOUD_LOCATION',
        'VERTEX_MODEL_PRIMARY', 'VERTEX_MODEL_VERIFY', 'BLUEPRINT_GEMINI_MODEL',
        'BLUEPRINT_PROGRAM_SETUP_MODEL', 'BLUEPRINT_MAX_OUTPUT_TOKENS',
        'BLUEPRINT_PROGRAM_SETUP_MAX_OUTPUT_TOKENS', 'BLUEPRINT_MAX_RETRIES'}
    runtime = {entry['name']: entry['value'] for entry in
        config['spec']['template']['spec']['containers'][0].get('env', [])
        if entry['name'] in allowed and 'value' in entry}
    os.environ.update(runtime)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    report = {'service': args.service, 'deployed_revision': config['status']['latestReadyRevisionName'],
        'configuration_source': 'production Cloud Run model configuration',
        'production_application_mutations': False, 'checks': []}
    cases = set(args.cases.split(','))
    with tempfile.TemporaryDirectory(prefix='aux-ai-validation-') as folder:
        os.environ.update(APP_ENV='test', AUTH_MODE='mock', QB_DATA_DIR=folder,
            DATABASE_URL='', QB_SCHEMA_MANAGED='0', GCS_DATA_BUCKET='')
        import app  # Schema and prompt registry are initialized only in folder.
        from google.genai import types
        import pymupdf
        from llm_extract import _client, _generate_structured, _parse_structured_response, Extraction, _active_prompt
        from llm_generate import configured_vertex_model
        from blueprint_gemini import structured_call
        from blueprint_setup import PROMPT, SetupProposal
        from official_exam import discover

        def check(name, function):
            start = time.monotonic()
            try:
                result = {'case': name, 'status': 'PASSED', **function()}
            except Exception as exc:
                result = {'case': name, 'status': 'FAILED', 'error_type': type(exc).__name__}
            result['elapsed_seconds'] = round(time.monotonic() - start, 2)
            report['checks'].append(result)
            print(json.dumps(result), flush=True)
            Path(args.output).write_text(json.dumps(report, indent=2) + '\n')

        def extraction():
            with pymupdf.open() as doc:
                page = doc.new_page(width=750, height=260)
                for y, text in [(45, '1. A 2 kg body accelerates at 3 m/s^2. Find the net force.'),
                                (85, 'A. 2 N    B. 3 N    C. 6 N    D. 9 N'),
                                (125, 'Answer: C'), (165, 'Solution: F = ma = 2 x 3 = 6 N.')]:
                    page.insert_text((35, y), text, fontsize=16)
                png = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).tobytes('png')
            with _client() as client:
                response = _generate_structured(client, model=configured_vertex_model(),
                    parts=[types.Part.from_bytes(data=png, mime_type='image/png'),
                        'Faithfully transcribe this one printed question.'], schema=Extraction,
                    system_instruction=_active_prompt('DIGITIZE_TRANSCRIBE')['system_content'], max_tokens=5000)
            result = _parse_structured_response(response, Extraction)
            assert len(result.questions) == 1
            question = result.questions[0]
            assert len(question.options) == 4 and question.page == 1
            assert '6' in question.options[2] and question.answer.strip().startswith('C')
            return {'model': configured_vertex_model(), 'question_count': 1, 'options': 4,
                'printed_answer_preserved': True}

        def setup():
            result, metadata = structured_call('PROGRAM_SETUP', PROMPT,
                {'name': 'Class 6 Arithmetic Practice', 'exam_class': 'Class 6', 'language': 'English',
                 'notes': 'For this small validation draft use Arithmetic only, one Fractions chapter, two topics, and one section of 3 questions.'},
                SetupProposal)
            assert len(result.profiles) == 5
            assert 1 <= sum(section.question_count for section in result.sections) <= 20
            return {'model': metadata['model'], 'difficulty_profiles': len(result.profiles),
                'question_count': sum(section.question_count for section in result.sections),
                'attempts': metadata['attempts']}

        def official():
            result = discover('JEE Main', 'B.E./B.Tech')
            assert result['urls']
            return {'model': configured_vertex_model(), 'grounded_source_count': len(result['urls']),
                'scope': 'official source discovery; no official pattern applied'}

        for name, function in [('extraction', extraction), ('setup', setup), ('official', official)]:
            if name in cases:
                check(name, function)
    if any(result['status'] != 'PASSED' for result in report['checks']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
