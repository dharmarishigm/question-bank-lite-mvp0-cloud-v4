"""Initialize the authorized FLAG library and existing GATE ECE program via admin API.
No learners are granted access and no questions/exams are generated or published.
"""
import argparse,hashlib,io,json,sys,time,uuid,zipfile
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.seed_competitive_programs import command
from gate_setup import is_ece

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--apply',action='store_true')
 parser.add_argument('--pdf',type=Path,default=Path.home()/'Downloads/Essentials of Pharma Forecasting Material.pdf')
 parser.add_argument('--zip',type=Path,default=Path.home()/'Downloads/excelworkingtemplatessimulatedreferencesampledataset.zip')
 args=parser.parse_args()
 originals={args.pdf.name:args.pdf.read_bytes()}
 with zipfile.ZipFile(args.zip) as archive:
  for name in archive.namelist():
   if name.lower().endswith('.xlsx'):originals[Path(name).name]=archive.read(name)
 preset=json.loads((ROOT/'program_presets/gate_ece.json').read_text())
 if not args.apply:
  print(f'Validated inputs: {len(originals)} originals and GATE ECE preset. Add --apply to initialize production.');return
 project='gen-lang-client-0491787004';base='https://meritiqra.com'
 config=json.loads(command(['run','services','describe','question-bank-cloud-v4','--project='+project,'--region=asia-south1','--format=json']))
 env={entry['name']:entry for entry in config['spec']['template']['spec']['containers'][0]['env']}
 def credential(name):
  entry=env[name]
  if 'value' in entry:return entry['value']
  ref=entry['valueFrom']['secretKeyRef'];return command(['secrets','versions','access',ref['key'],'--secret='+ref['name'],'--project='+project])
 report={'base_url':base,'materials':[],'questions_generated':0,'exams_published':0,'members_added':0}
 with httpx.Client(base_url=base,timeout=240) as c:
  r=c.post('/api/auth/admin-login',json={'email':credential('ADMIN_LOCAL_EMAIL'),'password':credential('ADMIN_LOCAL_PASSWORD')});r.raise_for_status();c.headers['X-CSRF-Token']=c.cookies['qb_csrf']
  try:
   existing=c.get('/api/flag/materials');existing.raise_for_status();items=existing.json()
   for path,kind in [(args.pdf,'PDF'),(args.zip,'WORKBOOK')]:
    current=[item for item in items if item['kind']==kind]
    if not current:
     r=c.post('/api/flag/materials',files={'file':(path.name,path.read_bytes())});r.raise_for_status();print('Uploaded',r.json()['uploaded'],kind,flush=True)
   response=c.get('/api/flag/materials');response.raise_for_status();items=response.json()
   for filename,raw in originals.items():
    item=next((x for x in items if x['filename']==filename),None)
    if not item:raise RuntimeError('Existing library is incomplete; preserve current material and review missing filename: '+filename)
    r=c.get(f'/api/flag/materials/{item["id"]}/download');r.raise_for_status()
    if hashlib.sha256(r.content).digest()!=hashlib.sha256(raw).digest():raise RuntimeError('Preserving different existing material: '+filename)
    report['materials'].append({'id':item['id'],'filename':filename,'sha256':hashlib.sha256(raw).hexdigest(),'pages':item.get('pages'),'sheets':len(item.get('sheets',[]))})
   response=c.get('/api/programs',params={'q':'GATE','limit':100});response.raise_for_status();matches=[p for p in response.json()['items'] if is_ece(p)]
   if len(matches)>1:raise RuntimeError('Multiple GATE ECE programs found; refusing to guess')
   if matches:p=matches[0]
   else:r=c.post('/api/programs',json=preset['program']);r.raise_for_status();p=r.json()
   if p['status']!='ACTIVE':raise RuntimeError('Restore the existing ECE program before setup')
   pid=p['id'];r=c.get(f'/api/programs/{pid}/exam-setup');r.raise_for_status();saved=r.json()
   if not saved:
    # Use the same automated lookup path used by the administrator UI.
    r=c.post(f'/api/programs/{pid}/official-pattern',json={'request_key':'ece-setup-'+uuid.uuid4().hex,'settings':preset['settings']});r.raise_for_status();job=r.json()
    deadline=time.monotonic()+180
    while job['status'] in ('QUEUED','RUNNING') and time.monotonic()<deadline:
     time.sleep(2);r=c.get(f'/api/programs/{pid}/official-pattern');r.raise_for_status();job=r.json()
    if job['status']!='READY':raise RuntimeError('GATE ECE setup lookup did not finish: '+str(job.get('error',job['status'])))
    settings=job['result']['settings'];r=c.put(f'/api/programs/{pid}/exam-setup',json={'settings':settings,'revision':0});r.raise_for_status()
    report['official_lookup']={'id':job['id'],'live_verified':job['result'].get('live_verified'),'status_label':job['result'].get('status_label')}
   else:
    settings=saved['settings']
    r=c.get(f'/api/programs/{pid}/official-pattern');r.raise_for_status();job=r.json()
    if job and job['status']=='READY':report['official_lookup']={'id':job['id'],'live_verified':job['result'].get('live_verified'),'status_label':job['result'].get('status_label')}
   # Fill missing descriptive metadata without replacing the user's existing name/code or text.
   r=c.get(f'/api/programs/{pid}');r.raise_for_status();p=r.json()
   keys=['code','name','description','authority','region','category','levels','languages','tags','status']
   original={**p.get('payload',{}),**{key:p[key] for key in ('code','name','status')}}
   values={key:original.get(key,preset['program'][key]) for key in keys}
   for key in keys:
    if key not in ('code','name','status') and not values[key]:values[key]=preset['program'][key]
   if any(values[k]!=original.get(k) for k in keys):
    r=c.put(f'/api/programs/{pid}?revision={p["revision"]}',json=values);r.raise_for_status()
   for variant in [settings]+[{**settings,'mode':'SUBJECT','sections':[section]} for section in settings['sections']]:
    r=c.post(f'/api/programs/{pid}/exam-prompt',json=variant);r.raise_for_status();prompt=r.json()
    assert prompt['question_count']==sum(s['count'] for s in variant['sections'])
    assert '| Subject |' in prompt['effective_prompt']
   report['program']={'id':pid,'name':p['name'],'sections':len(settings['sections']),'questions':sum(s['count'] for s in settings['sections']),'marks':sum(s['count']*s['marks'] for s in settings['sections']),'full_and_subject_prompts_verified':True}
   (ROOT/'docs/validation/flag-materials-initialization.json').write_text(json.dumps(report,indent=2)+'\n')
   print(json.dumps({'materials_verified':len(report['materials']),'program':report['program'],'official_lookup':report.get('official_lookup')},indent=2))
  finally:c.post('/api/auth/logout')
if __name__=='__main__':main()
