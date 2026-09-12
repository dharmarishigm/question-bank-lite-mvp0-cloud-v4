"""Prepare a minimal release overlay on the deployed FLAG image."""
from pathlib import Path
import json,shutil,tempfile,os

root=Path(__file__).resolve().parents[1]
stage=Path(tempfile.mkdtemp(prefix='meritiqra-engagement-'))
files=['database.py','epidemiology_model.py','app.py','platform_api.py','flag_api.py','engagement.py','engagement_schema.py','marketing_pdf.py','requirements.txt',
       'migrations/versions/0017_engagement.py','static/index.html','static/home.html','static/flag.js',
       'static/engagement.js','static/engagement.css','static/flag.css','static/enquiry.html','static/enquiry.js','static/public-auth.js','scripts/validate_release_migrations.py','scripts/check_production_runtime.py','scripts/expand_explanation_jobs_schema.py']
files = sorted({*files, *[p.name for p in root.glob('*.py')],
                *[str(p.relative_to(root)) for p in (root/'static').rglob('*') if p.is_file() and p.name!='.DS_Store'],
                *[str(p.relative_to(root)) for p in (root/'migrations').rglob('*.py')]})
for name in files:
    target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,target)
tag=os.getenv('RELEASE_TAG','epidemiology-20260910')
image=f"{os.getenv('REGION','asia-south1')}-docker.pkg.dev/{os.getenv('PROJECT_ID','gen-lang-client-0491787004')}/question-bank/cloud-v4:{tag}"
base=os.getenv('BASE_IMAGE','asia-south1-docker.pkg.dev/gen-lang-client-0491787004/question-bank/cloud-v4@sha256:acf7f0207bc8c2296bc590bc728ac0423190ff45eadc90278e104782470762b7')
(stage/'Dockerfile').write_text(f'FROM {base}\n'+'''
COPY *.py requirements.txt /app/
COPY static/ /app/static/
COPY migrations/ /app/migrations/
COPY scripts/validate_release_migrations.py /app/scripts/validate_release_migrations.py
COPY scripts/check_production_runtime.py /app/scripts/check_production_runtime.py
COPY scripts/expand_explanation_jobs_schema.py /app/scripts/expand_explanation_jobs_schema.py
ENV APP_ENV=production QB_SCHEMA_MANAGED=1 SECURITY_HARDENING=1 REQUIRE_STAFF_MFA=1 DB_POOL_ENABLED=1 DB_POOL_SIZE=5 EXPECTED_SCHEMA_REVISION=0020_dqb_document_controls PYTHONUNBUFFERED=1
# The inherited image has a migration entrypoint; production migrations run only
# through the reviewed migration job, never during a Cloud Run cold start.
ENTRYPOINT []
CMD ["sh","-c","python scripts/check_production_runtime.py && exec python -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
''')
validation = f'''set -eu
docker run --rm --entrypoint python {image} -c 'from google.genai import types; from ai_runtime import thinking_config; options=types.HttpOptions(api_version="v1", timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)); types.GenerateContentConfig(http_options=options, thinking_config=thinking_config("gemini-2.5-flash")); print("AI runtime configuration validated")'
docker run -d --name qb-migration-db --network cloudbuild -e POSTGRES_DB=qb_migration_test -e POSTGRES_PASSWORD=disposable-test-only postgres:16
trap 'docker rm -f qb-migration-db' EXIT
for attempt in $(seq 1 60); do
  if docker exec qb-migration-db pg_isready -U postgres; then break; fi
  sleep 1
done
docker run --rm --network cloudbuild -e DATABASE_URL=postgresql+psycopg://postgres:disposable-test-only@qb-migration-db:5432/qb_migration_test {image} python scripts/validate_release_migrations.py
'''
(stage/'cloudbuild.json').write_text(json.dumps({'steps':[{'name':'gcr.io/cloud-builders/docker','args':['build','-t',image,'.']},{'name':'gcr.io/cloud-builders/docker','entrypoint':'bash','args':['-c',validation]}],'images':[image],'timeout':'1200s'}))
print(stage)
