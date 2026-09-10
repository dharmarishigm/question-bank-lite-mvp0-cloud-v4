"""Validate a deployed candidate with a small real PDF and a closed smoke exam."""
import asyncio, json, subprocess, sys, time
from pathlib import Path
import httpx
import pymupdf

PROJECT='gen-lang-client-0491787004'
def command(args):
    result=subprocess.run(['gcloud',*args],capture_output=True,text=True,check=True)
    return result.stdout.strip()
config=json.loads(command(['run','services','describe','question-bank-cloud-v4','--project='+PROJECT,'--region=asia-south1','--format=json']))
base=sys.argv[1].rstrip('/')
allowed={config['status']['url'],'https://meritiqra.com'}|{r['url'] for r in config['status'].get('traffic',[]) if r.get('url')}
assert base in allowed,'Unrecognized deployment URL'
env={e['name']:e for e in config['spec']['template']['spec']['containers'][0]['env']}
def credential(key):
    entry=env[key]
    if 'value' in entry:return entry['value']
    ref=entry['valueFrom']['secretKeyRef']
    return command(['secrets','versions','access',ref['key'],'--secret='+ref['name'],'--project='+PROJECT])
async def browser_check(cookies):
    from playwright.async_api import async_playwright, expect
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        context=await browser.new_context(viewport={'width':1440,'height':1000})
        await context.add_cookies([{'name':c.name,'value':c.value,'domain':c.domain,'path':c.path,'secure':True} for c in cookies])
        page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(base+'/app')
        await page.locator('[data-view="grand-tests"]').click()
        await expect(page.locator('#gt-create')).to_be_visible()
        await page.screenshot(path='/tmp/grand-tests-live-desktop.png')
        await page.set_viewport_size({'width':390,'height':844})
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path='/tmp/grand-tests-live-mobile.png')
        assert not errors,errors
        await browser.close()
report={'base_url':base,'checks':{}}
with httpx.Client(base_url=base,timeout=180) as c:
    for path in ['/healthz','/app','/static/grand-tests.js','/static/grand-tests.css']:
        r=c.get(path);r.raise_for_status();report['checks'][path]=r.status_code
        if path.startswith('/static/'):assert r.content==Path(path.lstrip('/')).read_bytes()
    assert c.get('/api/grand-tests').status_code==401
    assert not c.get('/api/auth/config').json().get('mock')
    r=c.post('/api/auth/admin-login',json={'email':credential('ADMIN_LOCAL_EMAIL'),'password':credential('ADMIN_LOCAL_PASSWORD')});r.raise_for_status()
    c.headers['X-CSRF-Token']=c.cookies['qb_csrf']
    eid=None
    try:
        programs=c.get('/api/programs?limit=100&status=ACTIVE').json()['items'];assert programs
        program=next((p for p in programs if 'NEET' in p['name'].upper()),programs[0])
        r=c.post('/api/grand-tests',json={'program_id':program['id'],'name':'Deployment validation — Grand Test','paper_name':'Synthetic validation paper','description':'Automated deployment validation. Not a student exam.'});r.raise_for_status()
        g=r.json();path='/api/grand-tests/'+str(g['id']);report['workspace_id']=g['id']
        doc=pymupdf.open();p=doc.new_page()
        p.insert_text((50,60),'Grand Test - Physics',fontsize=16)
        p.insert_text((50,100),'1. A body of mass 2 kg has acceleration 3 m/s^2. What is the net force?',fontsize=11)
        p.insert_text((50,130),'A. 2 N     B. 3 N     C. 6 N     D. 9 N',fontsize=11)
        p.insert_text((50,160),'Answer: C. Explanation: F = m a = 2 x 3 = 6 N.',fontsize=11)
        r=c.post(path+'/pdf',params={'revision':g['revision']},files={'file':('grand-test-validation.pdf',doc.tobytes(),'application/pdf')});r.raise_for_status();g=r.json()
        assert c.get(path+'/pages/1').status_code==200
        def digitize(regions):
            global g
            r=c.post(path+'/digitize',json={'revision':g['revision'],'selections':regions});r.raise_for_status()
            for index in range(120):
                time.sleep(5);r=c.get(path);r.raise_for_status();g=r.json()
                if g['status']!='DIGITIZING':break
                if index%6==0:print('GCP PDF extraction is still running.',flush=True)
            assert g['status']=='REVIEW_REQUIRED' and g['questions'],g.get('error') or g['status']
        digitize([])
        report['checks']['whole_pdf_questions']=len(g['questions']);print('Whole PDF extraction passed.',flush=True)
        assert any('force' in q['statement'].lower() for q in g['questions'])
        report['checks']['classification_confidence']=[q.get('classification_confidence',0) for q in g['questions']]
        digitize([{'page':1,'bbox':[.06,.09,.97,.22]},{'page':1,'bbox':[.06,.09,.97,.22]}])
        report['checks']['selected_portions_questions']=len(g['questions']);print('Selected PDF regions passed.',flush=True)
        q=next(q for q in g['questions'] if 'force' in q['statement'].lower())
        q.update(statement='A body of mass 2 kg has acceleration 3 m/s². What is the net force?',options=['A. 2 N','B. 3 N','C. 6 N','D. 9 N'],answer='C',solution='F = ma = 2 × 3 = 6 N.',subject='Physics',chapter='Mechanics',topic='Laws of Motion',subtopic='Newton second law',difficulty='easy',qtype='mcq_single',reviewed=True)
        r=c.put(path+'/questions',json={'revision':g['revision'],'questions':[q]});r.raise_for_status();g=r.json()
        r=c.post(path+'/finalize',json={'revision':g['revision']});r.raise_for_status();g=r.json()
        r=c.post(path+'/generate',json={'revision':g['revision']});r.raise_for_status();eid=r.json()['exam_id'];report['exam_id']=eid
        g=c.get(path).json();now=time.time()
        r=c.put(path+'/schedule',json={'revision':g['revision'],'name':'Deployment validation — no student enrollment','start_at':now+86400,'end_at':now+90000,'duration_minutes':30,'allow_self_registration':False});r.raise_for_status();g=r.json()
        assert c.post(path+'/publish',json={'revision':1}).status_code==409
        r=c.post(path+'/publish',json={'revision':g['revision']});r.raise_for_status();assert r.json()['proctor_code']
        exam=c.get(f'/api/exams/{eid}').json();assert exam['proctor_required'] and not exam['allow_self_registration'] and exam['current_version_id']
        report['checks']['publication']='Scheduled snapshot and existing proctor code created; self-enrollment disabled'
        for route in ['/api/questions?limit=1','/api/programs?limit=1','/api/exams','/api/admin/users']:
            r=c.get(route);r.raise_for_status();report['checks']['regression '+route]=r.status_code
        asyncio.run(browser_check(c.cookies.jar));report['checks']['live_browser']='Admin workspace and mobile layout passed'
    finally:
        if eid:
            r=c.put(f'/api/admin/exams/{eid}/state',json={'status':'CLOSED'});r.raise_for_status();report['validation_exam_closed']=True
        c.post('/api/auth/logout')
Path('/tmp/grand-tests-live-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
