import json, pathlib, time
import httpx
from playwright.sync_api import sync_playwright
import os
BASE=os.environ.get('UI_TEST_BASE_URL','http://127.0.0.1:8018')
from urllib.parse import urlparse
assert urlparse(BASE).hostname in {'127.0.0.1','localhost'}, 'Fixtures may only be created on a local test server'
out=pathlib.Path('/tmp/meritiqra-ui-evidence');out.mkdir(exist_ok=True)
def login(email):
 c=httpx.Client(base_url=BASE);r=c.post('/api/auth/mock',json={'email':email});r.raise_for_status();return c
def post(c,path,data={}):
 r=c.post(path,json=data,headers={'X-CSRF-Token':c.cookies['qb_csrf']});r.raise_for_status();return r.json()
a=login('admin@example.test');s=login('learner@example.test')
qs=[]
for i in range(8):
 r=post(a,'/api/questions',{'statement':f'A plant receives sunlight for {i+2} hours. Which process uses this energy?','options':['Respiration','Photosynthesis'],'answer':'B','solution':'Photosynthesis converts light energy.','subject':'Science','chapter':'Plants','topic':'Photosynthesis' if i<5 else 'Cells','difficulty':'medium','qtype':'mcq','marks':'2'});qs.append(r['id'])
for i in range(5):
 e=post(a,'/api/admin/exams',{'name':f'Science Practice {i+1}','status':'OPEN','question_ids':qs,'duration_minutes':30,'allow_self_registration':True})
 post(s,f'/api/exams/{e["id"]}/enroll');sid=post(s,f'/api/exams/{e["id"]}/sessions')['session_id']
 for n,qid in enumerate(qs):
  r=s.put(f'/api/sessions/{sid}/answers/{qid}',json={'selected_answer':'B' if n>=5 or n<i-1 else 'A'},headers={'X-CSRF-Token':s.cookies['qb_csrf']});r.raise_for_status()
 post(s,f'/api/sessions/{sid}/submit')
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 errors=[];measurements=[]
 for role,client,views in [('student',s,['dashboard','available-exams','my-exams','my-results','student-analytics','my-profile']),('admin',a,['dashboard','questions','ai-generate','upload-crop','exam','admin-exams','admin-results','student-analytics'])]:
  context=browser.new_context();context.add_cookies([{'name':k,'value':v,'url':BASE} for k,v in client.cookies.items()]);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(BASE+'/app');page.wait_for_selector('#app-shell:not([hidden])')
  for width,height in [(1440,900),(820,1180),(390,844)]:
   page.set_viewport_size({'width':width,'height':height})
   for view in views:
    page.evaluate('(name)=>showView(name)',view);page.wait_for_timeout(350)
    if view=='student-analytics':page.wait_for_selector('#analytics-content:not([hidden])')
    overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth + 2')
    measurements.append({'role':role,'view':view,'width':width,'scroll_height':page.evaluate('document.documentElement.scrollHeight'),'overflow':overflow})
    page.screenshot(path=str(out/f'{role}-{view}-{width}.png'),full_page=True)
  if role=='student':
   page.set_viewport_size({'width':1440,'height':900});page.evaluate("showView('student-analytics')");page.wait_for_timeout(300)
   measurements.append({'lab_chart_bottom':page.locator('#analytics-trend').bounding_box(),'lab_recommendation':page.locator('#analytics-gap-section').bounding_box()})
   page.get_by_role('button',name='Ask IQraMentor',exact=True).first.click();page.get_by_role('textbox',name='Ask IQraMentor').fill('Generate my performance report');page.get_by_role('button',name='Send',exact=True).click();page.wait_for_selector('.mentor-report',timeout=40000);page.screenshot(path=str(out/'mentor-desktop.png'))
   page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(out/'mentor-mobile.png'))
  context.close()
 context=browser.new_context();page=context.new_page();page.goto(BASE);page.get_by_role('button',name='✦ IQraMentor',exact=True).click();page.get_by_text('Sign in to MeritIQra to get personalized guidance from IQraMentor.',exact=True).wait_for();page.screenshot(path=str(out/'anonymous.png'));context.close();browser.close()
 (out/'measurements.json').write_text(json.dumps({'measurements':measurements,'errors':errors},indent=2))
 print(json.dumps({'errors':errors,'overflow':[m for m in measurements if m.get('overflow')],'screenshots':len(list(out.glob('*.png')))},indent=2))

assert not errors, errors
assert not [m for m in measurements if m.get('overflow')], 'Page overflow detected'
