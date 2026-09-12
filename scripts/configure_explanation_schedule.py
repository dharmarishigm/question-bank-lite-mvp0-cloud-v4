"""Deploy the dedicated worker, optionally enabling its five-minute scheduler.

Uses the established worker's runtime identity/configuration references. Does
not read secret values, modify the existing worker, or grant project-wide IAM.
"""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--image',required=True)
    parser.add_argument('--project',default='gen-lang-client-0491787004')
    parser.add_argument('--region',default='asia-south1')
    parser.add_argument('--batch-size',type=int,default=10)
    parser.add_argument('--enable-schedule',action='store_true')
    args=parser.parse_args()
    if not 1<=args.batch_size<=50:raise ValueError('Batch size must be 1–50')
    if not args.image.startswith(args.region+'-docker.pkg.dev/'+args.project+'/question-bank/cloud-v4@sha256:'):raise ValueError('Use a verified release digest')
    def command(*parts,check=True):
        result=subprocess.run(['gcloud',*parts,'--project='+args.project],text=True,capture_output=True)
        if check and result.returncode:raise RuntimeError(result.stderr)
        return result
    source=json.loads(command('run','jobs','describe','qb-production-digitaliq-worker','--region='+args.region,'--format=json').stdout)
    name='qb-production-explanation-worker'
    manifest={'apiVersion':'run.googleapis.com/v1','kind':'Job','metadata':{'name':name,'namespace':source['metadata']['namespace']},'spec':copy.deepcopy(source['spec'])}
    execution=manifest['spec']['template']['spec'];execution['taskCount']=1;execution['parallelism']=1
    task=execution['template']['spec'];task['maxRetries']=0;task['timeoutSeconds']='420'
    container=task['containers'][0];container['image']=args.image;container['command']=['python'];container['args']=['-m','explanation_jobs']
    settings={'EXPLANATION_JOB_BATCH_SIZE':str(args.batch_size),'EXPLANATION_JOB_BUDGET_SECONDS':'240','EXPLANATION_JOB_MAX_ATTEMPTS':'5'}
    container['env']=[entry for entry in container.get('env',[]) if entry['name'] not in settings]+[{'name':key,'value':value} for key,value in settings.items()]
    with tempfile.TemporaryDirectory(prefix='explanation-worker-config-') as folder:
        path=Path(folder)/'job.json';path.write_text(json.dumps(manifest))
        command('run','jobs','replace',str(path),'--region='+args.region,'--quiet')
    print('Worker configured: '+name)
    if not args.enable_schedule:return
    identity=task['serviceAccountName']
    command('run','jobs','add-iam-policy-binding',name,'--region='+args.region,'--member=serviceAccount:'+identity,'--role=roles/run.invoker','--quiet')
    scheduler='qb-production-explanations'
    existing=command('scheduler','jobs','describe',scheduler,'--location='+args.region,'--format=json',check=False)
    if existing.returncode and 'NOT_FOUND' not in existing.stderr:raise RuntimeError(existing.stderr)
    operation='update' if existing.returncode==0 else 'create'
    command('scheduler','jobs',operation,'http',scheduler,'--location='+args.region,
        '--schedule=*/5 * * * *','--time-zone=Asia/Kolkata','--http-method=POST',
        '--uri=https://run.googleapis.com/v2/projects/'+args.project+'/locations/'+args.region+'/jobs/'+name+':run',
        '--oauth-service-account-email='+identity,'--oauth-token-scope=https://www.googleapis.com/auth/cloud-platform',
        '--attempt-deadline=60s','--max-retry-attempts=0','--quiet')
    if existing.returncode==0 and json.loads(existing.stdout).get('state')=='PAUSED':
        command('scheduler','jobs','resume',scheduler,'--location='+args.region,'--quiet')
    print('Scheduler enabled every five minutes: '+scheduler)


if __name__=='__main__':main()
