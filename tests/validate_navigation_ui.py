"""Local role-navigation audit with synthetic exam/program data; never calls LLMs."""
import asyncio,json,os,subprocess,tempfile
from pathlib import Path
import httpx
from playwright.async_api import async_playwright
BASE='http://127.0.0.1:8056'
OUT=Path('/tmp/navigation-ui-audit');OUT.mkdir(exist_ok=True)
async def main():
 with tempfile.TemporaryDirectory(prefix='navigation-ui-') as folder:
  env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test'};env.pop('DATABASE_URL',None)
  server=subprocess.Popen(['.venv/bin/python','-m','uvicorn','app:app','--host','127.0.0.1','--port','8056'],env=env,stdout=subprocess.DEVNULL,stderr=open(OUT/'server.log','w'))
  try:
   async with httpx.AsyncClient(base_url=BASE) as admin,httpx.AsyncClient(base_url=BASE) as student:
    for _ in range(600):
     try:
      if (await admin.get('/healthz')).status_code==200:break
     except httpx.ConnectError:pass
     await asyncio.sleep(.1)
    for client,email in [(admin,'admin@example.test'),(student,'student@example.test')]:
     (await client.post('/api/auth/mock',json={'email':email,'name':'UI Review'})).raise_for_status();client.headers['X-CSRF-Token']=client.cookies['qb_csrf']
    description='## Exam overview\n\n**80 questions** across these subjects:\n\n- Science\n- Mathematics\n\n| Subject | Marks |\n| --- | --- |\n| Science | 40 |'
    (await admin.post('/api/programs',json={'code':'UI_REVIEW','name':'Navodaya UI review','description':description,'status':'ACTIVE'})).raise_for_status()
    q=(await admin.post('/api/questions',json={'statement':'What is two plus two?','options':['3','4'],'answer':'B','subject':'Science'})).json()
    exam=(await admin.post('/api/admin/exams',json={'name':'UI Review Exam','description':description,'status':'OPEN','question_ids':[q['id']],'allow_self_registration':True})).json()
    await student.post(f'/api/exams/{exam["id"]}/enroll');sid=(await student.post(f'/api/exams/{exam["id"]}/sessions')).json()['session_id'];await student.post(f'/api/sessions/{sid}/submit')
   errors=[];report=[]
   async with async_playwright() as p:
    browser=await p.chromium.launch()
    for role in ['admin','student']:
     context=await browser.new_context();await context.request.post(BASE+'/api/auth/mock',data={'email':role+'@example.test'})
     page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));await page.goto(BASE+'/app');await page.locator('#app-shell').wait_for(state='visible')
     views=await page.locator(f'#{role}-nav [data-view]:visible').evaluate_all('(bs)=>bs.map(b=>b.dataset.view)')
     for width in [1440,820,390]:
      await page.set_viewport_size({'width':width,'height':900})
      for view in views:
       if width<=800:await page.locator('#sidebar-toggle').click()
       await page.locator(f'#{role}-nav [data-view="{view}"]').click();await page.wait_for_timeout(300)
       panel=page.locator('#'+view+'-panel')
       await panel.wait_for(state='visible')
       metrics=await panel.evaluate('''e=>({overflow:document.documentElement.scrollWidth>innerWidth+2,headings:[...e.querySelectorAll('h2')].filter(n=>n.getClientRects().length).map(n=>n.textContent),unlabeled:[...e.querySelectorAll('input:not([type=hidden]),select,textarea')].filter(n=>n.getClientRects().length&&!n.labels?.length&&!n.getAttribute('aria-label')&&!n.getAttribute('aria-labelledby')).map(n=>n.id||n.name),overflows:[...e.querySelectorAll('*')].filter(n=>n.getClientRects().length&&n.getBoundingClientRect().right>innerWidth+2&&getComputedStyle(n).position!=='fixed').slice(-8).map(n=>({tag:n.tagName,id:n.id,cls:n.className}))})''')
       metrics.update(role=role,view=view,width=width);report.append(metrics)
       await page.screenshot(path=str(OUT/f'{role}-{view}-{width}.png'),full_page=True)
     if role=='admin':
      await page.set_viewport_size({'width':1440,'height':900});await page.locator('#admin-nav [data-view=programs]').click();await page.locator('[data-program-open]').first.click();await page.get_by_text('Advanced program workspace',exact=True).click()
      for tab in await page.locator('[data-program-tab]').evaluate_all('(bs)=>bs.map(b=>b.dataset.programTab)'):
       await page.locator(f'[data-program-tab="{tab}"]').first.click();await page.wait_for_timeout(300)
       for width in [1440,390]:
        await page.set_viewport_size({'width':width,'height':900});await page.wait_for_timeout(100)
        report.append({'role':role,'view':'program-'+tab,'width':width,'overflow':await page.evaluate('document.documentElement.scrollWidth>innerWidth+2')})
        await page.screenshot(path=str(OUT/f'program-{tab}-{width}.png'),full_page=True)
      await page.set_viewport_size({'width':1440,'height':900})
     await page.set_viewport_size({'width':1440,'height':900})
     if role=='admin':
      await page.locator('#admin-nav [data-view=programs]').click()
      assert await page.locator('[data-program-list] .rich-description strong').count()==1
      assert await page.locator('[data-program-list] .rich-description li').count()==2
      assert await page.locator('[data-program-list] .rich-description table').count()==1
      await page.locator('#admin-nav [data-view=ai-generate]').click()
      await page.locator('[data-ai-tab=new]').focus();await page.keyboard.press('ArrowRight')
      assert await page.locator('[data-ai-tab=saved]').get_attribute('aria-selected')=='true'
      assert await page.locator('#ai-saved-pane').is_visible()
     else:
      await page.locator('#student-nav [data-view=my-profile]').click()
      await page.wait_for_function("document.getElementById('profile-email').value==='student@example.test'")
      await page.wait_for_function("!document.querySelector('#student-profile-form button[type=submit]').disabled")
      for name,value in [('name','Updated Student'),('dob','2011-04-15'),('phone','9876543210'),('school','UI Test School')]:await page.locator('#profile-'+name).fill(value)
      await page.get_by_role('button',name='Save profile',exact=True).click()
      await page.locator('#notification').filter(has_text='Profile saved').wait_for()
      await page.locator('#student-nav [data-view=dashboard]').click();await page.locator('#student-nav [data-view=my-profile]').click()
      await page.wait_for_function("document.getElementById('profile-name').value==='Updated Student'")
     await page.route('**/api/dashboard',lambda route:route.fulfill(status=503,json={'detail':'Service temporarily unavailable'}))
     await page.locator(f'#{role}-nav [data-view=dashboard]').click()
     await page.locator('#dashboard-panel .page-load-status button').wait_for()
     await page.unroute('**/api/dashboard');await page.locator('#dashboard-panel .page-load-status button').click()
     await page.locator('#dashboard-panel .page-load-status').wait_for(state='hidden')
     assert await page.locator(f'#{role}-nav [data-view=dashboard]').get_attribute('aria-current')=='page'
     await page.set_viewport_size({'width':390,'height':900});await page.locator('#sidebar-toggle').click();await page.keyboard.press('Escape')
     assert await page.locator('#sidebar-toggle').get_attribute('aria-expanded')=='false'
     assert await page.locator('#sidebar').evaluate('(node)=>node.inert')
     await context.close()
    await browser.close()
   (OUT/'report.json').write_text(json.dumps({'errors':errors,'pages':report},indent=2));print(json.dumps({'errors':errors,'checks':len(report),'issues':[r for r in report if r.get('overflow') or r.get('unlabeled') or r.get('headings')==[]]},indent=2))
   assert not errors
   assert not any(r['overflow'] or r.get('unlabeled') for r in report)
  finally:server.terminate();server.wait()
if __name__=='__main__':asyncio.run(main())
