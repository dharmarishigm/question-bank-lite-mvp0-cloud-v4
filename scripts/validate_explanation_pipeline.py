"""Opt-in real-provider queue smoke test; synthetic isolated database only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='explanation-pipeline-validation-') as directory:
        os.environ.update(APP_ENV='test',AUTH_MODE='mock',QB_DATA_DIR=directory,
            DATABASE_URL='',QB_SCHEMA_MANAGED='0',GCS_DATA_BUCKET='',SECURITY_HARDENING='0')
        import app
        from explanation_jobs import run_batch
        question=app.create_question(app.Question(statement='A cell transfers $2$ moles of electrons at $E=1.10\\,V$. Find $\\Delta G$ using $F=96485\\,C\\,mol^{-1}$.',options=['$-212.27\\,kJ$','$212.27\\,kJ$','$-106.14\\,kJ$','$0\\,kJ$'],answer='A',solution='$\\Delta G=-nFE=-2(96485)(1.10)=-212267\\,J=-212.27\\,kJ$.',subject='Chemistry',source_type='AI_GENERATED'))
        started=time.monotonic();pending=app._generate_question_explanation(question['id'],'te')
        assert pending['pending'] and not pending['cached']
        enqueue_seconds=time.monotonic()-started
        started=time.monotonic();result=run_batch();elapsed=time.monotonic()-started
        assert result['succeeded']==1,result
        from unittest.mock import patch
        with patch('blueprint_gemini.structured_call',side_effect=AssertionError('Cache read must not call AI')):
            for language in ('en','te'):
                cached=app._generate_question_explanation(question['id'],language)
                assert cached['cached'] and cached['explanation']
        print(json.dumps({'production_data_touched':False,'queued_without_ai':True,'queue_seconds':round(enqueue_seconds,3),'worker_seconds':round(elapsed,2),'result':result,'both_language_cache_reads_without_ai':True}))


if __name__=='__main__':main()
