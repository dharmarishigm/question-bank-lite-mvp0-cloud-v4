"""Synthetic browser acceptance: reviewed suggestions, persistence and role controls."""
import asyncio,json,os,subprocess,tempfile
import httpx
from playwright.async_api import async_playwright,expect
BASE='http://127.0.0.1:8059'
async def main():
 with tempfile.TemporaryDirectory() as folder:
  env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test'};env.pop('DATABASE_URL',None)
  server=subprocess.Popen(['.venv/bin/python','-m','uvicorn','app:app','--port','8059'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  try:
   async with httpx.AsyncClient(base_url=BASE) as admin:
    for _ in range(100):
     try:
      if (await admin.get('/healthz')).status_code==200:break
     except httpx.ConnectError:pass
     await asyncio.sleep(.1)
    await admin.post('/api/auth/mock',json={'email':'admin@example.test'});admin.headers['X-CSRF-Token']=admin.cookies['qb_csrf']
    q=(await admin.post('/api/questions',json={'statement':'What is $2+2$?','options':['3','4'],'answer':'B','solution':'Addition'})).json()
    async with async_playwright() as p:
     browser=await p.chromium.launch();context=await browser.new_context();await context.request.post(BASE+'/api/auth/mock',data={'email':'admin@example.test'})
     page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));await page.goto(BASE+'/app');await page.locator('#app-shell').wait_for(state='visible')
     await page.locator('#admin-nav [data-view=questions]').click()
     for width,mode in [(1440,'correct'),(390,'regenerate')]:
      await page.set_viewport_size({'width':width,'height':900})
      await page.locator(f'#list [data-correct-question="{q["id"]}"]').click()
      modal=page.locator('.correction-dialog');await modal.wait_for(state='visible')
      new={'statement':f'Corrected {mode}: $2+2=?$','options':['4','5'],'answer':'A','solution':'$2+2=4$.'}
      await page.route('**/api/admin/question-corrections/suggest',lambda route:route.fulfill(json={'question':new,'changes':['Fixed equation and options'],'uncertainties':[],'model':'mock','saved':False}))
      await modal.locator(f'[data-ai={mode}]').click();await modal.locator('[data-proposal]').wait_for(state='visible')
      assert (await admin.get(f'/api/questions/{q["id"]}')).json()['statement']!=new['statement']
      await modal.locator('[data-apply-proposal]').click()
      await modal.locator('[name=reviewed]').check()
      assert await modal.locator('.katex').count()>0
      assert not await modal.evaluate('(e)=>e.scrollWidth>e.clientWidth+2')
      await page.screenshot(path=f'/tmp/question-correction-{width}.png',full_page=True)
      await modal.locator('button[type=submit]').click();await modal.wait_for(state='hidden')
      assert (await admin.get(f'/api/questions/{q["id"]}')).json()['statement']==new['statement']
      await page.unroute('**/api/admin/question-corrections/suggest')
     await page.locator(f'#list [data-explain="{q["id"]}"]').click()
     await expect(page.locator('#explain-content')).to_contain_text('scheduled batch')
     await expect(page.locator('#explain-like')).to_be_hidden()
     queued=(await admin.get('/api/admin/explanation-jobs')).json()
     assert queued['counts']['PENDING']==1
     assert not errors,errors
     await context.close();context=await browser.new_context();await context.request.post(BASE+'/api/auth/mock',data={'email':'student@example.test'});page=await context.new_page();await page.goto(BASE+'/app');await page.locator('#app-shell').wait_for(state='visible')
     assert await page.locator('[data-correct-question]').count()==0
     await browser.close()
   print(json.dumps({'desktop_mobile_correction_regeneration':'passed','suggestion_does_not_save':True,'equation_rendering':True,'scheduled_explanation_pending_ui':True,'student_controls_absent':True,'page_errors':errors}))
  finally:server.terminate();server.wait()
if __name__=='__main__':asyncio.run(main())
