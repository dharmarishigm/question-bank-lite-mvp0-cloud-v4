"""Create a small Grand Test overlay on the verified deployed application image."""
from pathlib import Path
import json, shutil, tempfile
root=Path(__file__).resolve().parents[1]
stage=Path(tempfile.mkdtemp(prefix='meritiqra-grand-tests-'))
files=['app.py','platform_api.py','exam_conduct.py','grand_tests.py','grand_test_schema.py','migrations/versions/0018_grand_tests.py','static/index.html','static/grand-tests.js','static/grand-tests.css']
for name in files:
    target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,target)
image='asia-south1-docker.pkg.dev/gen-lang-client-0491787004/question-bank/cloud-v4:grand-tests-20260910'
(stage/'Dockerfile').write_text('''FROM asia-south1-docker.pkg.dev/gen-lang-client-0491787004/question-bank/cloud-v4@sha256:b928a23191ec10a4f9999aaf6740c2f5a7b46681c36cca91404abf9b8d1ebc8c
COPY *.py /app/
COPY static/ /app/static/
COPY migrations/ /app/migrations/
''')
(stage/'cloudbuild.json').write_text(json.dumps({'steps':[{'name':'gcr.io/cloud-builders/docker','args':['build','-t',image,'.']}],'images':[image],'timeout':'1200s'}))
print(stage)
