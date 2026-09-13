"""Verify direct enrollment/start and real exam statistics using synthetic local data."""
import asyncio, json, os, sqlite3, subprocess, tempfile, time
from pathlib import Path
import httpx
from playwright.async_api import async_playwright
BASE='http://127.0.0.1:8058'
async def main():
 with tempfile.TemporaryDirectory() as folder:
  env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test'};env.pop('DATABASE_URL',None)
  server=subprocess.Popen(['.venv/bin/python','-m','uvicorn','app:app','--port','8058'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   async with httpx.AsyncClient(base_url=BASE) as admin:
    for _ in range(100):
     try:
      if (await admin.get('/healthz')).status_code==200:break
     except httpx.ConnectError:pass
     await asyncio.sleep(.1)
    (await admin.post('/api/auth/mock',json={'email':'admin@example.test'})).raise_for_status();admin.headers['X-CSRF-Token']=admin.cookies['qb_csrf']
    uid=(await admin.get('/api/auth/me')).json()['id']
    program=(await admin.post('/api/programs',json={'code':'JEE_MAIN_BTECH','name':'JEE Main','status':'ACTIVE'})).json()
    questions=[]
    for subject,statement in [('Mental Ability Test','Two plus two?'),('Mental Ability Test','Three plus three?'),('Environmental Studies (EVS)','Which process uses sunlight?'),('Environmental Studies (EVS)','Which organ pumps blood?')]:
     questions.append((await admin.post('/api/questions',json={'statement':statement,'options':['Option A','Option B'],'answer':'B','subject':subject,'chapter':'Foundations'})).json())
    exam=(await admin.post('/api/admin/exams',json={'name':'Direct multi-subject exam','status':'DRAFT','question_ids':[q['id'] for q in questions],'proctor_required':True,'allow_self_registration':True})).json()
    response=await admin.put(f'/api/admin/exams/{exam["id"]}/state',json={'status':'PUBLISHED'});response.raise_for_status()
    code_response=await admin.post(f'/api/admin/exams/{exam["id"]}/proctor-codes',json={'valid_minutes':60});code_response.raise_for_status();code=code_response.json()['code']
    response=await admin.put(f'/api/admin/exams/{exam["id"]}/state',json={'status':'OPEN'});response.raise_for_status()
    with sqlite3.connect(str(Path(folder)/'questions.db')) as conn:
     conn.execute('INSERT INTO program_exam_jobs(program_id,request_key,input_json,created_by,created_at,updated_at,exam_id) VALUES(?,?,?,?,?,?,?)',(program['id'],'browser-test','{}',uid,time.time(),time.time(),exam['id']));conn.commit()
   async with async_playwright() as p:
    browser=await p.chromium.launch()
    for width in [1440,390]:
     context=await browser.new_context(viewport={'width':width,'height':900});page=await context.new_page()
     await page.goto(BASE);await page.locator('.participation-summary').first.wait_for()
     assert 'Unique appeared candidates' in await page.locator('.participation-summary').first.inner_text()
     assert await page.locator('.participation-summary a').count()>=3
     assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
     await context.request.post(BASE+'/api/auth/mock',data={'email':f'student{width}@example.test'})
     await page.goto(BASE+'/app');await page.locator('#app-shell').wait_for(state='visible')
     if width<800:await page.locator('#sidebar-toggle').click()
     await page.locator('#student-nav [data-view=available-exams]').click()
     await page.locator(f'[data-enroll="{exam["id"]}"]').click()
     await page.locator('#exam-start-modal').wait_for(state='visible')
     assert await page.locator('#available-exams-panel').is_visible()
     assert await page.locator('#student-proctor-code').is_visible()
     assert await page.locator('#exam-start-details .participation-summary').count()==1
     await page.locator('#exam-start-consent').check()
     await page.locator('#student-proctor-code').fill('WRONG-CODE');await page.locator('#verify-start-exam').click()
     await page.wait_for_function("document.getElementById('exam-start-status').textContent.length>0")
     assert await page.locator('#exam-start-modal').is_visible()
     await page.locator('#student-proctor-code').fill(code);await page.locator('#verify-start-exam').click()
     await page.wait_for_function("location.hash.startsWith('#session-')")
     await page.locator('#exam-current-question').wait_for(state='visible')
     assert await page.locator('[data-exam-subject]').count()==2
     assert 'Mental Ability Test' in await page.locator('.exam-subject-tabs').inner_text()
     assert 'Environmental Studies (EVS)' in await page.locator('.exam-subject-tabs').inner_text()
     await page.locator('[data-exam-subject]').filter(has_text='Environmental Studies (EVS)').click()
     assert 'Environmental Studies (EVS)' in await page.locator('#exam-header-section').inner_text()
     assert await page.locator('.exam-question-pills [data-exam-jump]').count()==2
     assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
     await page.screenshot(path=f'/tmp/exam-layout-{width}.png',full_page=True)
     await page.locator('#exam-current-question [data-report-concern]').click()
     await page.locator('[data-concern-form] textarea').fill('Please check the equation and question wording.')
     await page.locator('[data-concern-form] button').click()
     await page.locator('[data-concern-form] [role=status]').filter(has_text='Concern submitted').wait_for()
     await page.locator('[data-close-result-dialog]').click()
     assert 'Flagged' in await page.locator('#exam-current-question [data-report-concern]').inner_text()
     assert '⚑' in await page.locator('#exam-question-nav').inner_text()
     await page.evaluate("openSecureExam(Number(document.getElementById('exam-current-question').dataset.session))")
     await page.locator('[data-exam-subject]').filter(has_text='Environmental Studies (EVS)').click()
     assert 'Flagged' in await page.locator('#exam-current-question [data-report-concern]').inner_text()
     await context.close()
    await browser.close()
   print(json.dumps({'multi_subject_exam_navigation':'passed','direct_enrollment_proctor_start':'passed','invalid_code_rejected':True,'participation_sources':'passed','widths':[1440,390]}))
  finally:server.terminate();server.wait()
if __name__=='__main__':asyncio.run(main())
