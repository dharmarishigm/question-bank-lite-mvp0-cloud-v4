"""Trial conversion, protected reading, English voice and admin marketing export."""
import asyncio,os,subprocess,tempfile,re
from pathlib import Path
import httpx
from playwright.async_api import async_playwright,expect
BASE='http://127.0.0.1:8063'
async def main():
 with tempfile.TemporaryDirectory() as folder:
  env={**os.environ,'QB_DATA_DIR':folder,'FLAG_LOCAL_DIR':folder+'/private','AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test'}
  for key in ['DATABASE_URL','GCS_DATA_BUCKET']:env.pop(key,None)
  log=open('/tmp/engagement-ui.log','w');server=subprocess.Popen(['.venv/bin/python','-m','uvicorn','app:app','--port','8063'],env=env,stdout=log,stderr=log)
  try:
   async with httpx.AsyncClient(base_url=BASE) as c:
    for _ in range(100):
     try:
      if (await c.get('/healthz')).status_code==200:break
     except httpx.ConnectError:pass
     await asyncio.sleep(.1)
   async with async_playwright() as pw:
    browser=await pw.chromium.launch();admin=await browser.new_context(viewport={'width':1440,'height':1000})
    await admin.request.post(BASE+'/api/auth/mock',data={'email':'admin@example.test'})
    token=next(c['value'] for c in await admin.cookies() if c['name']=='qb_csrf');headers={'X-CSRF-Token':token}
    pdf=Path('/Users/dharmaofficial/Downloads/Essentials of Pharma Forecasting Material.pdf')
    r=await admin.request.post(BASE+'/api/flag/materials',headers=headers,multipart={'file':{'name':pdf.name,'mimeType':'application/pdf','buffer':pdf.read_bytes()}});assert r.ok,await r.text();mid=(await r.json())['ids'][0]
    archive=Path('/Users/dharmaofficial/Downloads/excelworkingtemplatessimulatedreferencesampledataset.zip')
    r=await admin.request.post(BASE+'/api/flag/materials',headers=headers,multipart={'file':{'name':archive.name,'mimeType':'application/zip','buffer':archive.read_bytes()}});assert r.ok,await r.text()
    student=await browser.new_context(viewport={'width':1440,'height':1000});await student.request.post(BASE+'/api/auth/mock',data={'email':'student@example.test'})
    # Intercept synthesis only, to assert voice selection in a browser with no OS audio device.
    await student.add_init_script("""window.testSpeech=[];window.SpeechSynthesisUtterance=class{constructor(text){this.text=text;}};Object.defineProperty(window,'speechSynthesis',{value:{getVoices:()=>[{name:'Hindi',lang:'hi-IN',voiceURI:'hindi'},{name:'English Natural',lang:'en-GB',voiceURI:'english'}],addEventListener:()=>{},removeEventListener:()=>{},cancel:()=>{},speak:s=>window.testSpeech.push({lang:s.lang,voice:s.voice.voiceURI,text:s.text}),pause:()=>{},resume:()=>{}}});""")
    page=await student.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));await page.goto(BASE+'/app')
    await page.locator('#student-nav [data-view=flag-reader]').click();await expect(page.locator('#flag-start-trial')).to_be_visible();await page.locator('#flag-start-trial').click()
    await expect(page.locator('.flag-premium-banner').first).to_contain_text('Your FLAG trial is active');await expect(page.locator('.flag-pdf-page')).to_have_count(10)
    await expect(page.locator('#flag-pages .flag-text-layer').first).to_be_visible();assert not await page.locator('#flag-reader-panel a[download],#flag-reader-panel a[href$="/download"]').count()
    import base64
    illustration='data:image/svg+xml;base64,'+base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="100"><rect width="600" height="100" fill="teal"/></svg>').decode()
    await page.route('**/materials/*/explain',lambda route:route.fulfill(json={'agent_name':'iqraflagmentor','markdown':'## Core concept\n\n**Patient flow** links assumptions to a forecast.\n\n| Input | Output |\n| --- | --- |\n| Patients | Demand |','visuals':[{'title':'Patient flow','steps':['Eligible patients','Expected demand'],'caption':'Illustrative concept','image':illustration}]}))
    await page.evaluate("(()=>{const e=document.querySelector('.flag-text-layer span');const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r);document.dispatchEvent(new Event('selectionchange'));})()")
    await page.get_by_role('button',name='ASK iqraFlgmentor',exact=True).click()
    await expect(page.locator('#flag-mentor-dialog')).to_be_visible();await expect(page.locator('#flag-explanation table')).to_be_visible();await expect(page.locator('#flag-visuals img')).to_be_visible()
    await page.screenshot(path='/tmp/flag-mentor-desktop.png');await page.set_viewport_size({'width':390,'height':844});await page.screenshot(path='/tmp/flag-mentor-mobile.png');await page.locator('#flag-close-mentor').click();await page.set_viewport_size({'width':1440,'height':1000})
    await page.locator('#flag-read').click();await page.wait_for_function('window.testSpeech.length>0');assert await page.evaluate('testSpeech[0].lang')=='en-GB'
    assert await page.locator('#flag-voice option').count()==1
    assert await page.evaluate("(()=>{const e=new Event('copy',{bubbles:true,cancelable:true});document.querySelector('#flag-pages').dispatchEvent(e);return e.defaultPrevented;})()")
    assert (await student.request.get(BASE+f'/api/flag/materials/{mid}/download')).status==403
    assert (await student.request.get(BASE+f'/api/flag/materials/{mid}/pages/11')).status==403
    await page.emulate_media(media='print');assert await page.locator('#app-shell').evaluate("e=>getComputedStyle(e).display")=='none';await page.emulate_media(media='screen')
    await page.screenshot(path='/tmp/premium-trial-desktop.png')
    await page.locator('#student-nav [data-view=flag-excel]').click();await expect(page.locator('.flag-template-tile')).to_have_count(2)
    await page.locator('.flag-template-tile').first.click();await expect(page.locator('#flag-sheet-grid td').first).to_be_visible()
    await page.set_viewport_size({'width':390,'height':844});await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right<=1");assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    await page.screenshot(path='/tmp/premium-workbook-mobile.png')
    enquiry=await student.new_page();await enquiry.goto(BASE+'/enquiry?interest=FLAG');await enquiry.locator('[name=name]').fill('Trial learner');await enquiry.locator('[name=email]').fill('learner@example.test');await enquiry.locator('[name=consent]').check();await expect(enquiry.locator('#challenge-label')).to_contain_text('What is')
    numbers=re.findall(r'\d+',await enquiry.locator('#challenge-label').inner_text());await enquiry.locator('[name=answer]').fill(str(sum(map(int,numbers))));await enquiry.locator('[type=submit]').click();await expect(enquiry.locator('#enquiry-status')).to_contain_text('Your enquiry has been received')
    await enquiry.screenshot(path='/tmp/enquiry-desktop.png');await enquiry.set_viewport_size({'width':390,'height':844});assert await enquiry.evaluate('document.documentElement.scrollWidth<=innerWidth');await enquiry.screenshot(path='/tmp/enquiry-mobile.png')
    ap=await admin.new_page();ap.on('pageerror',lambda e:errors.append(str(e)));await ap.goto(BASE+'/app');await ap.locator('#admin-nav [data-view=enquiries]').click();await expect(ap.locator('#enquiry-list')).to_contain_text('Trial learner');await ap.locator('[data-enquiry-status]').select_option('CONTACTED');await ap.locator('[data-enquiry-notes]').fill('Follow-up requested');await ap.locator('[data-enquiry-save]').click();await expect(ap.locator('[data-enquiry-status]')).to_have_value('CONTACTED');await ap.screenshot(path='/tmp/enquiry-admin.png')
    r=await admin.request.post(BASE+'/api/questions',headers=headers,data={'statement':'Evaluate $2^3$.','options':['4','6','8','16'],'answer':'C','solution':'Eight.'});assert r.ok;question=await r.json()
    r=await admin.request.post(BASE+'/api/admin/exams',headers=headers,data={'name':'Offline marketing demonstration','status':'OPEN','question_ids':[question['id']]});assert r.ok;exam=await r.json()
    await ap.locator('#admin-nav [data-view=admin-exams]').click();await ap.locator(f'[data-marketing-pdf="{exam["id"]}"]').click();await expect(ap.locator('.marketing-dialog [name=contact]')).to_have_value('+91 93911 03630 | admin@meritiqra.com')
    async with ap.expect_download(timeout=120000) as download:
     await ap.locator('.marketing-dialog [type=submit]').click()
    await (await download.value).save_as('/tmp/marketing-ui-download.pdf');await expect(ap.locator('.marketing-status')).to_contain_text('PDF downloaded')
    assert not errors,errors
    await browser.close();print('Engagement UI passed: trial bounds, download/copy/print restrictions, English voice, enquiry/admin follow-up, PDF download, mobile layouts.')
  finally:server.terminate();server.wait(timeout=10);log.close()
asyncio.run(main())
