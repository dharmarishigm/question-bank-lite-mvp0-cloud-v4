"""Browser acceptance: rank, PDF/share, concern correction, multi-batch review/save."""
import asyncio,os,subprocess,tempfile
import httpx
from playwright.async_api import async_playwright,expect
BASE='http://127.0.0.1:8050'

async def main():
 with tempfile.TemporaryDirectory(prefix='result-tools-ui-') as folder:
  env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test','APP_BASE_URL':BASE};env.pop('DATABASE_URL',None)
  command="""from unittest.mock import patch
from tests.test_program_exam import author
import uvicorn
with patch('app.generate_questions',side_effect=author):uvicorn.run('app:app',host='127.0.0.1',port=8050,log_level='warning')
"""
  server=subprocess.Popen(['.venv/bin/python','-c',command],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  try:
   async with httpx.AsyncClient(base_url=BASE) as admin,httpx.AsyncClient(base_url=BASE) as student:
    for _ in range(100):
     if server.poll() is not None:raise RuntimeError(server.stderr.read().decode())
     try:
      if (await admin.get('/healthz')).status_code==200:break
     except httpx.ConnectError:pass
     await asyncio.sleep(.1)
    for client,email in [(admin,'admin@example.test'),(student,'student@example.test')]:
     (await client.post('/api/auth/mock',json={'email':email,'name':'Sample Student' if client is student else 'Admin'})).raise_for_status();client.headers['X-CSRF-Token']=client.cookies['qb_csrf']
    q=(await admin.post('/api/questions',json={'subject':'Science','statement':'Two plus two?','options':['3','4','5','6'],'answer':'B','solution':'Two plus two equals four.'})).json()
    exam=(await admin.post('/api/admin/exams',json={'name':'Browser Results Exam','status':'OPEN','question_ids':[q['id']]})).json()
    (await student.post(f'/api/exams/{exam["id"]}/enroll')).raise_for_status();sid=(await student.post(f'/api/exams/{exam["id"]}/sessions')).json()['session_id']
    await student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'});await student.post(f'/api/sessions/{sid}/submit')
    for subject in ['Physics','Chemistry']:(await admin.post('/api/ai/generate',json={'exam_name':'Batch Review Exam','subject':subject,'count':2,'generation_prompt':'Original questions.','syllabus':'Fundamentals'})).raise_for_status()
   async with async_playwright() as pw:
    browser=await pw.chromium.launch();errors=[]
    context=await browser.new_context(viewport={'width':1440,'height':1000});await context.request.post(BASE+'/api/auth/mock',data={'email':'student@example.test'})
    page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));await page.goto(BASE+'/app')
    await page.locator('#student-nav [data-view=my-results]').click();await page.get_by_role('button',name='Review result',exact=True).click()
    await expect(page.locator('[data-result-rank]')).to_contain_text('1 of 1')
    await page.get_by_role('button',name='Exam leaderboard',exact=True).click();await expect(page.locator('#result-tools-dialog tbody tr')).to_have_count(1)
    await page.locator('[data-close-result-dialog]').click()
    await expect(page.get_by_role('button',name='Export report PDF',exact=True)).to_have_count(0)
    await expect(page.get_by_role('button',name='Share report',exact=True)).to_have_count(0)
    assert await page.locator('body').evaluate("e=>e.classList.contains('student-protected-content')")
    assert await page.locator('#student-content-watermark').is_visible()
    assert await page.evaluate("!document.body.dispatchEvent(new Event('copy',{bubbles:true,cancelable:true}))")
    await page.emulate_media(media='print')
    assert not await page.locator('#app-shell').is_visible()
    await page.emulate_media(media='screen')
    await expect(page.locator('.result-subject-breakdown')).to_contain_text('Subject-wise marks')
    await expect(page.locator('.result-subject-breakdown tbody')).to_contain_text('Science')
    await page.set_viewport_size({'width':390,'height':844})
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    await page.screenshot(path='/tmp/student-subject-report-mobile.png',full_page=True)
    await page.set_viewport_size({'width':1440,'height':1000})
    await page.get_by_role('button',name='Report a concern',exact=True).click();await page.locator('[data-concern-form] textarea').fill('Please verify the answer options and calculation.');await page.get_by_role('button',name='Submit concern',exact=True).click();await expect(page.locator('[data-concern-form] [role=status]')).to_contain_text('submitted')
    await context.close()
    context=await browser.new_context(viewport={'width':1440,'height':1000});await context.request.post(BASE+'/api/auth/mock',data={'email':'admin@example.test'});page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));await page.goto(BASE+'/app')
    await page.locator('#admin-nav [data-view=admin-results]').click();await page.get_by_role('button',name='Review question concerns').click();await page.get_by_role('button',name='Edit question / options',exact=True).click();await expect(page.locator('.correction-dialog')).to_be_visible();await page.locator('.correction-dialog [name=solution]').fill('Verified: adding two and two gives four.');await page.locator('.correction-dialog [name=reviewed]').check();await page.locator('.correction-dialog button[type=submit]').click();await expect(page.locator('.correction-dialog')).to_be_hidden()
    await page.locator('#admin-nav [data-view=admin-results]').click();await page.get_by_role('button',name='Review question concerns').click();await page.locator('[data-resolve-concern] textarea').fill('Verified and clarified the solution.');await page.get_by_role('button',name='Save resolution',exact=True).click();await expect(page.locator('[data-concern-list]')).to_contain_text('No concerns')
    await page.locator('[data-close-result-dialog]').click();await page.locator('#admin-nav [data-view=ai-generate]').click();await page.locator('[data-ai-tab=saved]').click();await expect(page.locator('[data-ai-select-run]')).to_have_count(2);await page.get_by_role('button',name='Select all ready batches').click();await page.get_by_role('button',name='Review selected batches together').click();await expect(page.locator('.ai-question-card')).to_have_count(4)
    await page.locator('[data-ai-edit-draft]').first.click();await page.locator('.correction-dialog [data-option]').first.fill('Corrected distractor');await page.locator('.correction-dialog [name=reviewed]').check();await page.locator('.correction-dialog button[type=submit]').click();await expect(page.locator('.correction-dialog')).to_be_hidden();await expect(page.locator('.ai-question-card').first).to_contain_text('Corrected distractor')
    await page.get_by_role('button',name='Save all to Question Bank',exact=True).click();await expect(page.locator('#ai-generation-status')).to_contain_text('4 questions saved across 2 batches');await expect(page.locator('.ai-question-card.saved')).to_have_count(4)
    await page.set_viewport_size({'width':390,'height':844});await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right <= 1");
    if not await page.evaluate('document.documentElement.scrollWidth<=innerWidth'):
     print(await page.evaluate("[...document.querySelectorAll('*')].filter(n=>n.getBoundingClientRect().width&&n.getBoundingClientRect().right>innerWidth+1).slice(-30).map(n=>({tag:n.tagName,id:n.id,cls:n.className,width:n.getBoundingClientRect().width,right:n.getBoundingClientRect().right}))"),flush=True)
     await page.screenshot(path='/tmp/result-tools-mobile.png',full_page=True)
     raise AssertionError('Mobile overflow')
    assert not errors,errors
    await browser.close()
   print('Passed: result rank/leaderboard, sharing, concern submission/editor/resolution, multi-batch review/edit/save, and mobile layout.')
  finally:
   server.terminate()
   try:server.wait(timeout=10)
   except subprocess.TimeoutExpired:server.kill()
if __name__=='__main__':asyncio.run(main())
