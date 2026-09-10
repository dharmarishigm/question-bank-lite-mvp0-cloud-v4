"""Opt-in live setup smoke test; creates one inactive QA program and archives it."""
import argparse
import json
import subprocess
import time
import uuid

import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True)
    parser.add_argument('--service',required=True)
    parser.add_argument('--region',required=True)
    parser.add_argument('--base-url',required=True)
    args=parser.parse_args()
    def command(parts):
        result=subprocess.run(['gcloud',*parts],capture_output=True,text=True)
        if result.returncode:raise RuntimeError('GCP configuration/credential lookup failed')
        return result.stdout
    config=json.loads(command(['run','services','describe',args.service,'--project='+args.project,'--region='+args.region,'--format=json']))
    allowed={config['status']['url'].rstrip('/')}|{t['url'].rstrip('/') for t in config['status'].get('traffic',[]) if t.get('url')}
    if args.base_url.rstrip('/') not in allowed:
        raise RuntimeError('Target must be this service URL or one of its configured revision tags')
    env={e['name']:e for e in config['spec']['template']['spec']['containers'][0]['env']}
    def credential(name):
        entry=env[name]
        if 'value' in entry:return entry['value']
        ref=entry['valueFrom']['secretKeyRef']
        return command(['secrets','versions','access',ref['key'],'--secret='+ref['name'],'--project='+args.project])
    with httpx.Client(base_url=args.base_url,timeout=60) as client:
        login=client.post('/api/auth/admin-login',json={'email':credential('ADMIN_LOCAL_EMAIL'),'password':credential('ADMIN_LOCAL_PASSWORD')})
        if login.status_code!=200:raise RuntimeError(f'Admin login failed: HTTP {login.status_code}')
        client.headers['X-CSRF-Token']=client.cookies['qb_csrf']
        def api(method,path,payload=None):
            r=client.request(method,path,json=payload)
            if r.status_code>=400:raise RuntimeError(f'{method} {path}: HTTP {r.status_code}')
            return r.json()
        program=api('POST','/api/programs',{'code':'QA_SETUP_'+uuid.uuid4().hex[:12].upper(),'name':'Navodaya','status':'INACTIVE','tags':['deployment-validation']})
        pid=program['id'];root=f'/api/programs/{pid}'
        try:
            job=api('POST',root+'/setup',{'request_key':'live-'+uuid.uuid4().hex})
            deadline=time.monotonic()+240
            while time.monotonic()<deadline:
                row=next(r for r in api('GET',root+'/setup') if r['id']==job['id'])
                if row['status'] in ('READY','FAILED'):break
                time.sleep(3)
            if row['status']!='READY':raise RuntimeError('Setup did not become READY: '+row['status'])
            print(json.dumps({'stage':'generated','model':row['telemetry'].get('model'),'variant':row['proposal']['variant'],'profiles':len(row['proposal']['profiles'])}),flush=True)
            result=api('POST',root+f"/setup/{job['id']}/apply")
            blueprints=api('GET',root+'/blueprints')
            assert {b['kind'] for b in blueprints}=={'EXAM_PATTERN','EXAM_GENERATOR','QUESTION_GENERATOR'}
            for b in blueprints:
                assert all(v['status']=='DRAFT' for v in api('GET',root+f"/blueprints/{b['id']}/versions"))
            assert api('GET',root+'/curricula')[0]['status']=='DRAFT'
            assert len(api('GET',root+'/prompts')['items'])==10
            assert api('GET',root+'/sources')==[] and api('GET',root+'/historical-profiles')==[]
            runs=api('GET',root+'/paper-runs')
            assert runs[0]['payload']['sample_preview'] and runs[0]['id']==result['paper_run_id']
            assert api('GET',root+'/audit')[0]['action']=='PROGRAM_SETUP_APPLIED'
            assert client.post(root+f"/setup/{job['id']}/apply").status_code==409
            print(json.dumps({'stage':'validated','qa_program_id':pid,'blueprints':len(blueprints),'paper_run_id':result['paper_run_id'],'all_drafts':True}),flush=True)
        finally:
            current=api('GET',root)
            api('DELETE',root+'?revision='+str(current['revision']))
            assert api('GET',root)['status']=='ARCHIVED'
            print(json.dumps({'stage':'cleanup','qa_program_id':pid,'status':'ARCHIVED'}),flush=True)


if __name__=='__main__':main()
