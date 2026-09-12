"""Explicit, bounded production AI smoke checks using the service's admin login.

No question is saved or paper published. Credentials are never printed or written.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx

PROJECT = 'gen-lang-client-0491787004'
SERVICE = 'question-bank-cloud-v4'
REGION = 'asia-south1'


def command(*args):
    result = subprocess.run(['gcloud', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('GCP credential/configuration lookup failed')
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='https://meritiqra.com')
    parser.add_argument('--mode', choices=['inspect','correction','generation'], default='inspect')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    config = json.loads(command('run','services','describe',SERVICE,'--project='+PROJECT,'--region='+REGION,'--format=json'))
    env = {entry['name']:entry for entry in config['spec']['template']['spec']['containers'][0]['env']}
    allowed = {config['status']['url'],'https://meritiqra.com'} | {row['url'] for row in config['status'].get('traffic',[]) if row.get('url')}
    if args.base_url.rstrip('/') not in allowed:
        raise RuntimeError('Unrecognized production or candidate URL')
    def credential(key):
        entry = env[key]
        if 'value' in entry:
            return entry['value']
        ref = entry['valueFrom']['secretKeyRef']
        return command('secrets','versions','access',ref['key'],'--secret='+ref['name'],'--project='+PROJECT)
    report = {'base_url':args.base_url,'checks':[],'traffic':config['status']['traffic']}
    with httpx.Client(base_url=args.base_url,timeout=210) as client:
        def check(method,path,payload=None):
            started = time.monotonic()
            response = client.request(method,path,json=payload)
            entry = {'path':path,'status':response.status_code,'seconds':round(time.monotonic()-started,2)}
            if response.status_code >= 400:
                try: entry['detail'] = str(response.json().get('detail',''))[:500]
                except ValueError: entry['detail']='Non-JSON error'
            report['checks'].append(entry)
            print(json.dumps(entry),flush=True)
            return response
        try:
            check('GET','/api/health')
            login = check('POST','/api/auth/admin-login',{'email':credential('ADMIN_LOCAL_EMAIL'),'password':credential('ADMIN_LOCAL_PASSWORD')})
            login.raise_for_status()
            if 'qb_csrf' in client.cookies:
                client.headers['X-CSRF-Token']=client.cookies['qb_csrf']
            me = check('GET','/api/auth/me')
            me.raise_for_status()
            if me.json().get('role') != 'ADMIN':
                raise RuntimeError('Authenticated administrator session required; complete MFA if requested')
            if args.mode == 'inspect':
                response=check('GET','/api/admin/prompts')
                if response.status_code==200:
                    body=response.json()
                    report['prompt_inventory']=body
                for path in ['/api/system/status','/api/ai/runs?limit=10','/api/programs?limit=10']:
                    response=check('GET',path)
                    if '/runs?' in path and response.status_code==200:
                        report['recent_runs']=[{k:r.get(k) for k in ('id','status','requested_count','generated_count','error_message','model')} for r in response.json()]
            if args.mode == 'correction':
                q={'statement':'If $x=2$, evaluate $\\frac{x^2+4}{2}$.','options':['$2$','$4$','$6$','$8$'],'answer':'B','solution':'Substitute $x=2$: $\\frac{4+4}{2}=4$.'}
                for mode in ('correct','regenerate'):
                    r=check('POST','/api/admin/question-corrections/suggest',{'mode':mode,'question':q,'instructions':'Use valid LaTeX and return a complete question for administrator review.'})
                    if r.status_code==200:
                        body=r.json();assert body.get('saved') is False and len(body['question']['options'])==4 and body['question']['solution']
                        report['checks'][-1]['mode']=mode
                        report['checks'][-1]['valid_proposal']=True
            if args.mode == 'generation':
                r=check('POST','/api/ai/generate',{'exam_name':'QA AI audit — do not publish','subject':'Mathematics','count':1,'difficulty':'easy','question_type':'mcq_single','syllabus':'Linear equations with integer coefficients.','generation_prompt':'Create one original question with four options, worked solution and explanations in English and Telugu.','extra_metadata':{'validation_only':True}})
                if r.status_code==200:
                    body=r.json();report['qa_run_id']=body['run_id']
                    assert body['questions'] and all(q.get('explanation_en') and q.get('explanation_te') for q in body['questions'])
                    report['checks'][-1]['bilingual']=True
        finally:
            # No credentials, tokens or cookies are included in the receipt.
            report['outcome']='BLOCKED_MFA' if any('MFA_REQUIRED' in entry.get('detail','') for entry in report['checks']) else 'FAILED' if any(entry['status']>=400 for entry in report['checks']) else 'PASSED'
            Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            client.post('/api/auth/logout')
    if report['outcome']!='PASSED':raise SystemExit(2)


if __name__=='__main__':
    main()
