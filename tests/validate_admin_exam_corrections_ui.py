"""Admin takes an exam, corrects options, and sees historical/current versions."""
import asyncio,os,subprocess,tempfile,time
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
    r=await ctx.request.post(BASE+'/api/admin/exams',data={'name':'Admin exam participation','status':'OPEN','exam_start_at':time.time()-60,'question_ids':[q['id']]});exam=await r.json()
    page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    await page.goto(BASE+'/app');await page.locator('#admin-nav [data-view=available-exams]').click()
    await page.locator(f'[data-enroll="{exam["id"]}"]').click();await expect(page.locator('#exam-start-modal')).to_be_visible()
    await page.locator('#exam-start-consent').check();await page.locator('#verify-start-exam').click();await expect(page.locator('#exam-current-question')).to_contain_text('2+2')
    await expect(page.locator('#exam-current-question [data-correct-question]')).to_be_visible()
    async with page.expect_response(lambda response:'/answers/' in response.url and response.request.method=='PUT') as saved:
     await page.locator('#exam-current-question input[value=B]').check()
    assert (await saved.value).status==200
    await page.locator('#exam-current-question [data-correct-question]').click();dialog=page.locator('.correction-dialog')
    await dialog.locator('[data-option]').nth(0).fill('4');await dialog.locator('[data-option]').nth(1).fill('5');await dialog.locator('[name=answer]').fill('A');await dialog.locator('[name=reviewed]').check()
    await dialog.get_by_role('button',name='Update question',exact=True).click();await expect(dialog).to_have_count(0)
    await expect(page.locator('#exam-current-question .question-correction-notice')).to_be_visible()
    await expect(page.locator('#exam-current-question input:checked')).to_have_count(0)
    await expect(page.locator('#exam-current-question .question-correction-notice')).to_contain_text('choose your answer again')
    await expect(page.locator('#exam-current-question')).to_contain_text('5')
    async with page.expect_response(lambda response:'/answers/' in response.url and response.request.method=='PUT') as saved:
     await page.locator('#exam-current-question input[value=A]').check()
    assert (await saved.value).status==200
    assert (await saved.value).request.post_data_json['content_revision']
    await page.screenshot(path='/tmp/admin-taking-corrected-exam.png')
    await page.evaluate('document.fullscreenElement ? document.exitFullscreen() : undefined')
    await page.set_viewport_size({'width':390,'height':844});await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right<=1")
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    await page.screenshot(path='/tmp/admin-taking-corrected-exam-mobile.png')
    page.on('dialog',lambda d:d.accept());await page.locator('#exam-submit-button').click()
    await expect(page.locator('#my-results-panel')).to_be_visible();await page.locator('[data-review-attempt]').first.click()
    await expect(page.locator('[data-attempt-question] [data-correct-question]')).to_be_visible()
    await expect(page.locator('.attempt-original-options')).to_contain_text('4')
    # A second admin view must preserve unsaved edits when the completed result is corrected.
    peer=await ctx.new_page();peer.on('pageerror',lambda e:errors.append(str(e)));await peer.goto(BASE+'/app')
    await peer.locator('#admin-nav [data-view=questions]').click();await peer.locator(f'#list [data-edit="{q["id"]}"]').click()
    await peer.locator('#f-statement').fill('Unsaved author draft to preserve')
    await page.locator('[data-attempt-question] [data-correct-question]').click();dialog=page.locator('.correction-dialog')
    await dialog.locator('[name=statement]').fill('Current corrected question: what is 2+3?')
    await dialog.locator('[data-option]').nth(0).fill('6');await dialog.locator('[data-option]').nth(1).fill('5');await dialog.locator('[name=answer]').fill('B');await dialog.locator('[name=solution]').fill('Five');await dialog.locator('[name=reviewed]').check()
    await dialog.get_by_role('button',name='Update question',exact=True).click();await expect(dialog).to_have_count(0)
    await expect(page.locator('[data-attempt-question]')).to_contain_text('Current corrected question')
    await expect(page.locator('.attempt-original-options li').first).to_have_text('6')
    await expect(page.locator('.answer-selected')).to_contain_text('Recorded answer (original question)')
    await expect(page.locator('.answer-selected')).to_contain_text('A. 4')
    await expect(page.locator('.outcome-badge')).to_contain_text('Recorded result: Correct')
    await expect(peer.locator('#f-statement')).to_have_value('Unsaved author draft to preserve')
    await expect(peer.locator('#save-status')).to_contain_text('unsaved draft is still here')
    await expect(peer.locator('#btn-save')).to_be_disabled()
    await peer.get_by_role('button',name='Load corrected question',exact=True).click()
    await expect(peer.locator('#f-statement')).to_have_value('Current corrected question: what is 2+3?')
    await peer.close()
    await page.set_viewport_size({'width':1440,'height':1000})
    r=await ctx.request.post(BASE+'/api/questions',data={'statement':'Legacy unverified question','options':['1','2'],'answer':'B','solution':'Two'})
    legacy=await r.json()
    r=await ctx.request.post(BASE+'/api/admin/exams',data={'name':'Legacy editor propagation','status':'OPEN','exam_start_at':time.time()-60,'question_ids':[legacy['id']]});legacy_exam=await r.json()
    before=await (await ctx.request.get(BASE+f'/api/exams/{legacy_exam["id"]}')).json()
    await page.locator('#admin-nav [data-view=questions]').click();await page.locator(f'#list [data-edit="{legacy["id"]}"]').click()
    await page.locator('#f-statement').fill('Main editor reviewed correction')
    await page.locator('#btn-preview').click();await page.locator('#btn-save').click();await expect(page.locator('#editor-modal')).to_be_hidden()
    latest=await (await ctx.request.get(BASE+f'/api/questions/{legacy["id"]}')).json()
    assert latest['verification_status']=='APPROVED' and latest['statement']=='Main editor reviewed correction'
    after=await (await ctx.request.get(BASE+f'/api/exams/{legacy_exam["id"]}')).json()
    assert after['current_version_id']!=before['current_version_id']
    # Fixture only for the DigitalQBank browser cache; backend hydration has API tests.
    saved_question={**legacy,'id':'saved-row','saved_question_id':legacy['id'],'reviewed':True}
    unsaved_question={**legacy,'id':'unsaved-row','saved_question_id':None,'statement':'Unsaved source question','reviewed':False}
    workspace={'id':77,'name':'Correction preview fixture','paper_name':'Local fixture','status':'REVIEW_REQUIRED','revision':1,'exam_id':None,'exam':None,'operator_email':'admin@example.test','source':{'id':None},'questions':[saved_question,unsaved_question]}
    async def workspace_route(route):
     path=route.request.url.split('/api/grand-tests',1)[1]
     await route.fulfill(json=workspace if path=='/77' else [workspace] if not path else [])
    await page.route('**/api/grand-tests**',workspace_route)
    await page.locator('[data-view=grand-tests]').click();await page.locator('[data-open="77"]').click()
    saved_row=page.locator('#gt-questions [data-question="saved-row"]');draft_row=page.locator('#gt-questions [data-question="unsaved-row"]')
    await draft_row.locator('[name=statement]').fill('Unrelated unsaved source edit')
    await saved_row.locator('[data-exam-question]').uncheck()
    workspace['questions'][0]={**saved_question,**{key:latest[key] for key in ['statement','options','answer','solution']}};workspace['revision']=2
    await page.evaluate("q=>document.dispatchEvent(new CustomEvent('question:corrected',{detail:q}))",latest)
    await expect(saved_row.locator('[name=statement]')).to_have_value('Main editor reviewed correction')
    await expect(saved_row.locator('[data-review-preview]')).to_contain_text('Main editor reviewed correction')
    await expect(draft_row.locator('[name=statement]')).to_have_value('Unrelated unsaved source edit')
    await expect(saved_row.locator('[data-exam-question]')).not_to_be_checked()
    # The legacy source/fullscreen preview and open explanation must not retain old content.
    await page.evaluate("q=>{parsed=[{...q,saved:true,saved_question_id:q.id}];$('pdf-list').innerHTML=pdfItemHtml(parsed[0],0);renderPdfPreview(0);openCompareModal(0);$('explain-modal').dataset.questionId=String(q.id);$('explain-content').dataset.rawExplanation='stale explanation';$('explain-content').dataset.structured='{}';}",legacy)
    await page.evaluate("q=>document.dispatchEvent(new CustomEvent('question:corrected',{detail:q}))",latest)
    await expect(page.locator('#compare-transformed')).to_contain_text('Main editor reviewed correction')
    assert await page.locator('#explain-content').get_attribute('data-raw-explanation') is None
    assert await page.locator('#explain-content').get_attribute('data-structured') is None
    await expect(page.locator('#explain-like')).to_be_hidden()
    assert not errors,errors
    await browser.close();print('Passed admin enroll/start/answer/submit, revised active answers, current result options with historical grading, cross-tab dirty-editor protection, legacy propagation, DigitalQBank/source preview cache refresh, explanation invalidation and mobile layout.')
  finally:server.terminate();server.wait(timeout=10)
if __name__=='__main__':asyncio.run(main())
