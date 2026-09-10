"""Admin takes an exam, corrects options, and sees historical/current versions."""
import asyncio,os,subprocess,tempfile
import httpx
from playwright.async_api import async_playwright,expect
BASE='http://127.0.0.1:8061'
async def main():
 with tempfile.TemporaryDirectory() as folder:
  env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test'};env.pop('DATABASE_URL',None)
  server=subprocess.Popen(['.venv/bin/python','-m','uvicorn','app:app','--port','8061'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   async with httpx.AsyncClient(base_url=BASE) as client:
    for _ in range(100):
     try:
      if (await client.get('/healthz')).status_code==200:break
     except httpx.ConnectError:pass
     await asyncio.sleep(.1)
   async with async_playwright() as pw:
    browser=await pw.chromium.launch();ctx=await browser.new_context(viewport={'width':1440,'height':1000})
    await ctx.request.post(BASE+'/api/auth/mock',data={'email':'admin@example.test'})
    token=next(c['value'] for c in await ctx.cookies() if c['name']=='qb_csrf');await ctx.set_extra_http_headers({'X-CSRF-Token':token})
    r=await ctx.request.post(BASE+'/api/questions',data={'statement':'What is $2+2$?','options':['3','4'],'answer':'B','solution':'Four','verification_status':'APPROVED'});q=await r.json()
    r=await ctx.request.post(BASE+'/api/admin/exams',data={'name':'Admin exam participation','status':'OPEN','question_ids':[q['id']]});exam=await r.json()
    page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    await page.goto(BASE+'/app');await page.locator('#admin-nav [data-view=available-exams]').click()
    await page.locator(f'[data-enroll="{exam["id"]}"]').click();await expect(page.locator('#exam-start-modal')).to_be_visible()
    await page.locator('#verify-start-exam').click();await expect(page.locator('#exam-current-question')).to_contain_text('2+2')
    await expect(page.locator('#exam-current-question [data-correct-question]')).to_be_visible()
    await page.locator('#exam-current-question input[value=B]').check()
    await page.locator('#exam-current-question [data-correct-question]').click();dialog=page.locator('.correction-dialog')
    await dialog.locator('[data-option]').nth(0).fill('4');await dialog.locator('[data-option]').nth(1).fill('5');await dialog.locator('[name=answer]').fill('A');await dialog.locator('[name=reviewed]').check()
    await dialog.get_by_role('button',name='Update question',exact=True).click();await expect(dialog).to_have_count(0)
    await expect(page.locator('#exam-current-question .question-correction-notice')).to_be_visible()
    await expect(page.locator('#exam-current-question input[value=B]')).to_be_checked()
    await page.locator('.question-correction-notice summary').click();await expect(page.locator('.question-correction-notice')).to_contain_text('new attempts')
    await page.screenshot(path='/tmp/admin-taking-corrected-exam.png')
    await page.evaluate('document.fullscreenElement ? document.exitFullscreen() : undefined')
    await page.set_viewport_size({'width':390,'height':844});await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right<=1")
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    await page.screenshot(path='/tmp/admin-taking-corrected-exam-mobile.png')
    page.on('dialog',lambda d:d.accept());await page.locator('#exam-submit-button').click()
    await expect(page.locator('#my-results-panel')).to_be_visible();await page.locator('[data-review-attempt]').first.click()
    await expect(page.locator('[data-attempt-question] .question-correction-notice')).to_be_visible()
    await expect(page.locator('[data-attempt-question] [data-correct-question]')).to_be_visible()
    await expect(page.locator('.attempt-original-options')).to_contain_text('3')
    await page.set_viewport_size({'width':1440,'height':1000})
    r=await ctx.request.post(BASE+'/api/questions',data={'statement':'Legacy unverified question','options':['1','2'],'answer':'B','solution':'Two'})
    legacy=await r.json()
    r=await ctx.request.post(BASE+'/api/admin/exams',data={'name':'Legacy editor propagation','status':'OPEN','question_ids':[legacy['id']]});legacy_exam=await r.json()
    before=await (await ctx.request.get(BASE+f'/api/exams/{legacy_exam["id"]}')).json()
    await page.locator('#admin-nav [data-view=questions]').click();await page.locator(f'#list [data-edit="{legacy["id"]}"]').click()
    await page.locator('#f-statement').fill('Main editor reviewed correction')
    await page.locator('#btn-preview').click();await page.locator('#btn-save').click();await expect(page.locator('#editor-modal')).to_be_hidden()
    latest=await (await ctx.request.get(BASE+f'/api/questions/{legacy["id"]}')).json()
    assert latest['verification_status']=='APPROVED' and latest['statement']=='Main editor reviewed correction'
    after=await (await ctx.request.get(BASE+f'/api/exams/{legacy_exam["id"]}')).json()
    assert after['current_version_id']!=before['current_version_id']
    assert not errors,errors
    await browser.close();print('Passed admin enroll/start/answer/submit, in-exam correction, preserved selection, correction notices, result options and mobile layout.')
  finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':asyncio.run(main())
