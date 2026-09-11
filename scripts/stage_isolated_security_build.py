"""Create an explicit source-only context; exclude data, secrets and Terraform state."""
import json,pathlib,shutil,tempfile,os
root=pathlib.Path(__file__).resolve().parents[1]
stage=pathlib.Path(tempfile.mkdtemp(prefix='qb-isolated-security-'))
files=[*root.glob('*.py'),root/'requirements.txt',root/'alembic.ini',root/'Dockerfile.security']
files += [p for folder in ('static','migrations','scripts','program_presets') for p in (root/folder).rglob('*') if p.is_file() and p.suffix not in {'.pyc','.log'} and p.name!='.DS_Store' and '__pycache__' not in p.parts]
for path in files:
 target=stage/path.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
image='asia-south1-docker.pkg.dev/gen-lang-client-0491787004/qb-security-staging/app:'+os.getenv('SECURITY_BUILD_TAG','security-v3')
if os.getenv('BASE_SECURITY_IMAGE'):
 base=os.environ['BASE_SECURITY_IMAGE'];assert '/qb-security-staging/' in base and '@sha256:' in base
 original=(root/'Dockerfile.security').read_text()
 overlay='FROM '+base+'\nWORKDIR /app\n'+original[original.index('COPY *.py'): ]
 (stage/'Dockerfile.security').write_text(overlay)
validate='''set -eu
docker run -d --name qb-migration-db --network cloudbuild -e POSTGRES_DB=qb_migration_test -e POSTGRES_PASSWORD=disposable-test-only postgres:17
trap 'docker rm -f qb-migration-db' EXIT
for attempt in $(seq 1 60); do docker exec qb-migration-db pg_isready -U postgres && break; sleep 1; done
docker run --rm --network cloudbuild -e DATABASE_URL=postgresql+psycopg://postgres:disposable-test-only@qb-migration-db:5432/qb_migration_test '''+image+''' python scripts/validate_release_migrations.py
'''
config={'steps':[{'name':'gcr.io/cloud-builders/docker','args':['build','-f','Dockerfile.security','-t',image,'.']},{'name':'gcr.io/cloud-builders/docker','entrypoint':'bash','args':['-c',validate]}], 'images':[image], 'timeout':'2400s','options':{'logging':'CLOUD_LOGGING_ONLY'},'serviceAccount':'projects/gen-lang-client-0491787004/serviceAccounts/qb-security-staging-build@gen-lang-client-0491787004.iam.gserviceaccount.com'}
(stage/'cloudbuild.json').write_text(json.dumps(config))
print(stage)
