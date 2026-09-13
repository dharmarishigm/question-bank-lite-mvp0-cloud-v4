"""Exercise the real supplied FLAG material locally; no real AI calls."""
import asyncio,json,os,subprocess,tempfile
from pathlib import Path
import httpx
from playwright.async_api import async_playwright,expect
BASE='http://127.0.0.1:8062'
PDF=Path('/Users/dharmaofficial/Downloads/Essentials of Pharma Forecasting Material.pdf')
ZIP=Path('/Users/dharmaofficial/Downloads/excelworkingtemplatessimulatedreferencesampledataset.zip')
async def main():
 with tempfile.TemporaryDirectory() as folder:
  env={**os.environ,'QB_DATA_DIR':folder,'FLAG_LOCAL_DIR':folder+'/private','AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test'}
  for key in ['DATABASE_URL','GCS_DATA_BUCKET']:env.pop(key,None)
  log=open('/tmp/flag-ui-server.log','w')
  server=subprocess.Popen(['.venv/bin/python','-m','uvicorn','app:app','--port','8062'],env=env,stdout=log,stderr=log)
  try:
   async with httpx.AsyncClient(base_url=BASE,timeout=120) as client:
    for _ in range(100):
     try:
      if (await client.get('/healthz')).status_code==200:break
     except httpx.ConnectError:pass
     await asyncio.sleep(.1)
    r=await client.post('/api/auth/mock',json={'email':'admin@example.test'});r.raise_for_status();client.headers['X-CSRF-Token']=client.cookies['qb_csrf']
    for path in [PDF,ZIP]:
     r=await client.post('/api/flag/materials',files={'file':(path.name,path.read_bytes())});r.raise_for_status()
    r=await client.get('/api/flag/materials');files=r.json();assert len(files)==23
    pdf=next(f for f in files if f['kind']=='PDF');assert pdf['pages']==149
    # Inspect every workbook and every sheet via the authenticated renderer.
    sheet_count=0
    for f in ([] if os.getenv('FLAG_UI_ONLY') else files):
     if f['kind']!='WORKBOOK':continue
     for sheet in f['sheets']:
      r=await client.get(f'/api/flag/materials/{f["id"]}/sheet',params={'name':sheet['name']});r.raise_for_status();assert r.json()['rows'];sheet_count+=1
    print('Validated',sheet_count,'sheets in 22 workbooks',flush=True)
   async with async_playwright() as pw:
    browser=await pw.chromium.launch();ctx=await browser.new_context(viewport={'width':1440,'height':1000})
    await ctx.request.post(BASE+'/api/auth/mock',data={'email':'admin@example.test'})
    page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    await page.goto(BASE+'/app');await page.locator('#admin-nav [data-view=flag-reader]').click();await expect(page.locator('#flag-pages .flag-text-layer').first).to_be_visible(timeout=20000)
    await page.locator('#flag-page-number').fill('12');await page.locator('#flag-go').click();target=page.locator('.flag-pdf-page[data-page="12"]');await expect(target.locator('.flag-text-layer')).to_be_visible()
    await page.wait_for_function("document.querySelector('.flag-pdf-page[data-page=\"12\"] img')?.complete")
    box=await target.bounding_box();await page.mouse.move(box['x']+60,box['y']+160);await page.mouse.down();await page.mouse.move(box['x']+200,box['y']+230);await page.mouse.up()
    await expect(page.locator('#flag-selection-label')).to_contain_text('Area selected');await expect(page.locator('#flag-explain')).to_be_enabled();assert await page.locator('#flag-selection').input_value()
    await page.locator('.flag-intent-options [data-question]').first.click();assert 'background' in (await page.locator('#flag-question').input_value()).lower()
    await page.route('**/api/flag/materials/*/explain',lambda route:route.fulfill(json={'markdown':'## Background\n\nA forecasting model tracks patients over time.\n\n## Core concept\n\nIncidence measures new cases.','page':12,'material_id':pdf['id']}))
    await page.locator('#flag-explain').click();await expect(page.locator('#flag-explanation h2').first).to_have_text('Background')
    await page.screenshot(path='/tmp/flag-reader-desktop.png')
    await page.locator('#flag-close-mentor').click();await page.locator('#flag-clear-selection').click();await expect(page.locator('#flag-selection-label')).to_have_text('No area selected')
    await page.locator('#admin-nav [data-view=flag-excel]').click();await expect(page.locator('.flag-template-tile')).to_have_count(22)
    await page.locator('#flag-template-search').fill('Excel Working');await page.locator('.flag-template-tile').click();await page.locator('#flag-sheet-select').select_option('Age_adjusted_Incidence_Prevalen');await expect(page.locator('#flag-sheet-grid td').first).to_be_visible();await expect(page.locator('#flag-sheet-status')).not_to_have_text('Loading sheet…')
    await page.locator('#flag-sheet-grid td').first.click();await expect(page.locator('#flag-formula')).not_to_have_text('Select a cell to see its value or formula.')
    await page.screenshot(path='/tmp/flag-workbook-desktop.png')
    await page.set_viewport_size({'width':390,'height':844});await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right<=1")
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),await page.evaluate('document.documentElement.scrollWidth')
    await page.screenshot(path='/tmp/flag-workbook-mobile.png')
    await page.evaluate("showView('flag-reader')");await expect(page.locator('#flag-pages .flag-text-layer').first).to_be_visible();assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    await page.wait_for_function("document.querySelector('#flag-pages img')?.complete");await page.screenshot(path='/tmp/flag-reader-mobile.png')
    await page.set_viewport_size({'width':1440,'height':1000});await page.locator('#admin-nav [data-view=flag-admin]').click();await page.locator('#flag-member-form [name=email]').fill('student@example.test');await page.locator('#flag-member-form button').click();await expect(page.locator('#flag-admin-content table')).to_contain_text('student@example.test')
    student=await browser.new_context();await student.request.post(BASE+'/api/auth/mock',data={'email':'student@example.test'});sp=await student.new_page();await sp.goto(BASE+'/app');await expect(sp.locator('#student-nav [data-view=flag-reader]')).to_be_visible();await sp.locator('#student-nav [data-view=flag-reader]').click();await expect(sp.locator('#flag-pages .flag-text-layer').first).to_be_visible()
    await page.locator('[data-edit-member]').click();await page.locator('#flag-member-form [name=active]').uncheck();await page.locator('#flag-member-form button').click();await expect(page.locator('#flag-admin-content table')).to_contain_text('Disabled')
    assert (await student.request.get(BASE+f'/api/flag/materials/{pdf["id"]}/download')).status==403
    await sp.evaluate("showView('flag-excel')");await expect(sp.locator('#flag-excel-content')).to_contain_text('FLAG LEARNING MEMBERSHIP')
    assert not errors,errors
    await browser.close();print('FLAG browser checks passed: desktop, mobile, selection, Markdown, area selection, membership and revocation.',flush=True)
  finally:
   server.terminate();server.wait(timeout=10);log.close()
asyncio.run(main())
