"""Prepare a minimal release overlay on the deployed FLAG image."""
from pathlib import Path
import json,shutil,tempfile,os

root=Path(__file__).resolve().parents[1]
stage=Path(tempfile.mkdtemp(prefix='meritiqra-engagement-'))
files=['database.py','epidemiology_model.py','app.py','platform_api.py','flag_api.py','engagement.py','engagement_schema.py','marketing_pdf.py','requirements.txt',
       'migrations/versions/0017_engagement.py','static/index.html','static/home.html','static/flag.js',
       'static/engagement.js','static/engagement.css','static/flag.css','static/enquiry.html','static/enquiry.js','static/public-auth.js']
files = sorted({*files, *[p.name for p in root.glob('*.py')],
                *[str(p.relative_to(root)) for p in (root/'static').rglob('*') if p.is_file() and p.name!='.DS_Store'],
                *[str(p.relative_to(root)) for p in (root/'migrations').rglob('*.py')]})
for name in files:
    target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,target)
tag=os.getenv('RELEASE_TAG','epidemiology-20260910')
image=f'asia-south1-docker.pkg.dev/gen-lang-client-0491787004/question-bank/cloud-v4:{tag}'
(stage/'Dockerfile').write_text('''FROM asia-south1-docker.pkg.dev/gen-lang-client-0491787004/question-bank/cloud-v4@sha256:45bbd1e1c2b9803326ff536c87a15132dcb6c31c5e1d8a98cd607058665c44e4
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN pip install --no-cache-dir playwright==1.62.0 && python -m playwright install --with-deps chromium
COPY *.py requirements.txt /app/
COPY static/ /app/static/
COPY migrations/ /app/migrations/
''')
(stage/'cloudbuild.json').write_text(json.dumps({'steps':[{'name':'gcr.io/cloud-builders/docker','args':['build','-t',image,'.']}],'images':[image],'timeout':'1200s'}))
print(stage)
