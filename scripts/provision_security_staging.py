"""Provision only fixed, isolated staging resources. Never read production secrets."""
import json,secrets,subprocess,requests
from cryptography.fernet import Fernet
PROJECT='gen-lang-client-0491787004';REGION='asia-south1'
INSTANCE='qb-security-staging-20260911';DB='security_staging'
BUCKET=PROJECT+'-security-staging-20260911'
def gc(*args,input=None):
    result=subprocess.run(['gcloud',*args,'--project='+PROJECT,'--quiet'],input=input,text=True,capture_output=True)
    if result.returncode:raise RuntimeError('Staging operation failed: '+args[0]+' '+args[1]+' '+result.stderr[:500])
    return result.stdout

def create_secret(name,value,identity):
    gc('secrets','create',name,'--replication-policy=automatic')
    gc('secrets','versions','add',name,'--data-file=-',input=value)
    gc('secrets','add-iam-policy-binding',name,'--member=serviceAccount:'+identity,'--role=roles/secretmanager.secretAccessor')

if __name__=='__main__':
    # Dedicated names are immutable here; this script cannot accept production targets.
    assert 'staging' in INSTANCE and 'staging' in BUCKET
    print('Creating staging identities and private bucket',flush=True)
    for name in ['qb-security-staging-runtime','qb-security-staging-migrate','qb-security-staging-build']:
        gc('iam','service-accounts','create',name,'--display-name='+name)
    runtime='qb-security-staging-runtime@'+PROJECT+'.iam.gserviceaccount.com'
    migrator='qb-security-staging-migrate@'+PROJECT+'.iam.gserviceaccount.com'
    for identity in [runtime,migrator]:
        gc('projects','add-iam-policy-binding',PROJECT,'--member=serviceAccount:'+identity,'--role=roles/cloudsql.client','--condition=None')
    gc('storage','buckets','create','gs://'+BUCKET,'--location='+REGION,'--uniform-bucket-level-access','--public-access-prevention')
    gc('storage','buckets','add-iam-policy-binding','gs://'+BUCKET,'--member=serviceAccount:'+runtime,'--role=roles/storage.objectUser')
    gc('sql','databases','create',DB,'--instance='+INSTANCE)
    token=gc('auth','print-access-token').strip()
    for user,identity,secret_name in [('qb_staging_migrator',migrator,'qb-security-staging-migration-db'),('qb_staging_app',runtime,'qb-security-staging-app-db')]:
        password=secrets.token_urlsafe(40)
        response=requests.post(f'https://sqladmin.googleapis.com/sql/v1beta4/projects/{PROJECT}/instances/{INSTANCE}/users',headers={'Authorization':'Bearer '+token},json={'name':user,'password':password,'type':'BUILT_IN'},timeout=60)
        response.raise_for_status()
        url=f'postgresql+psycopg://{user}:{password}@/{DB}?host=/cloudsql/{PROJECT}:{REGION}:{INSTANCE}'
        create_secret(secret_name,url,identity)
    create_secret('qb-security-staging-mfa-key',Fernet.generate_key().decode(),runtime)
    create_secret('qb-security-staging-admin-password',secrets.token_urlsafe(32),runtime)
    print('Staging resources created. Credentials stored only in Secret Manager.',flush=True)
