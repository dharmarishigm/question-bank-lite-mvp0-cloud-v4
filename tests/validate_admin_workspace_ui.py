"""Local browser acceptance: filters, batch selection, review/publish and compact UI."""
import asyncio,os,subprocess,tempfile
from pathlib import Path
import httpx
from playwright.async_api import async_playwright,expect
from tests.test_program_exam import settings

async def main():
 with tempfile.TemporaryDirectory(prefix='admin-workspace-') as folder:
  env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test','APP_BASE_URL':'http://127.0.0.1:8057'};env.pop('DATABASE_URL',None)
  code="""from unittest.mock import patch
from tests.test_program_exam import author
import uvicorn
with patch('app.generate_questions',side_effect=author):
 uvicorn.run('app:app',host='127.0.0.1',port=8057,log_level='warning')
"""
  server=subprocess.Popen(['.venv/bin/python','-c',code],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  try:
   async with httpx.AsyncClient() as client:
    for _ in range(100):
     try:
      if (await client.get('http://127.0.0.1:8057/healthz')).status_code==200:break
     except httpx.ConnectError:pass
     await asyncio.sleep(.1)
    else:raise RuntimeError('Server failed to start')
   async with async_playwright() as pw:
    browser=await pw.chromium.launch();context=await browser.new_context(viewport={'width':1440,'height':1000})
    base='http://127.0.0.1:8057'
    assert (await context.request.post(base+'/api/auth/mock',data={'email':'admin@example.test'})).ok
    token=next(c['value'] for c in await context.cookies() if c['name']=='qb_csrf')
    await context.set_extra_http_headers({'X-CSRF-Token':token})
    for subject in ['Maths','English']:
     response=await context.request.post(base+'/api/ai/generate',data={'exam_name':'Navodaya','subject':subject,'level':'VI','difficulty':'easy','count':2,'generation_prompt':'Generate original questions','syllabus':'Foundations'});assert response.ok
    response=await context.request.post(base+'/api/programs',data={'code':'REVIEW_TEST','name':'Review queue program'});pid=(await response.json())['id']
    response=await context.request.post(base+f'/api/programs/{pid}/exam-papers',data={'request_key':'browser-review-001','settings':settings()});assert response.ok
    page=await context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    await page.goto(base+'/app');await page.locator('#admin-nav [data-view=ai-generate]').click();await page.locator('[data-ai-tab=saved]').click()
    await expect(page.locator('#ai-run-list tbody tr')).to_have_count(3)
    filters=page.locator('#ai-run-filters');await filters.locator('[name=subject]').fill('Maths');await filters.get_by_role('button',name='Apply filters').click()
    await expect(page.locator('#ai-run-list tbody tr')).to_have_count(1)
    await expect(page.locator('#ai-run-list')).to_contain_text('Maths')
    await page.locator('[data-ai-select-run]').check();await page.locator('[data-ai-review-selected-batches]').click()
    await expect(page.locator('.ai-question-card')).to_have_count(2)
    await page.locator('[data-ai-tab=saved]').click();await filters.locator('[name=q]').fill('does-not-exist');await filters.get_by_role('button',name='Apply filters').click()
    await expect(page.locator('#ai-run-summary')).to_have_text('No runs match these filters.')
    await filters.get_by_role('button',name='Clear',exact=True).click();await expect(page.locator('#ai-run-list tbody tr')).to_have_count(3)
    await page.screenshot(path='/tmp/admin-workspace-history-desktop.png')
    await page.set_viewport_size({'width':390,'height':844});await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right<=1")
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    await page.locator('#ai-run-filters').scroll_into_view_if_needed();await page.screenshot(path='/tmp/admin-workspace-history-mobile.png')
    await page.set_viewport_size({'width':1440,'height':1000});await page.locator('#admin-nav [data-view=admin-exams]').click()
    await expect(page.locator('[data-review-paper]')).to_have_count(1)
    await page.screenshot(path='/tmp/admin-workspace-publishing-desktop.png')
    await page.locator('[data-review-paper]').click();await expect(page.locator('#admin-paper-review')).to_be_visible()
    await expect(page.locator('#admin-paper-review .guided-exam-form')).to_be_hidden()
    await page.get_by_role('button',name='Approve and publish exam',exact=True).click()
    await expect(page.locator('#admin-paper-review')).to_contain_text('select the review checkbox first')
    await page.get_by_text('Review question paper, answers and solutions',exact=True).click();await expect(page.locator('.guided-review-question')).to_have_count(2)
    await page.locator('#admin-paper-review input[name=reviewed]').check();await page.get_by_role('button',name='Approve and publish exam',exact=True).click()
    await expect(page.locator('[data-review-paper]')).to_have_count(0)
    await expect(page.locator('#admin-exams-list')).to_contain_text('PUBLISHED')
    await page.set_viewport_size({'width':390,'height':844});await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right<=1")
    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    await page.locator('#admin-review-close').click();await page.locator('#admin-publishing').scroll_into_view_if_needed();await page.screenshot(path='/tmp/admin-workspace-publishing-mobile.png')
    assert not errors,errors
    await browser.close();print('Passed filters, empty/reset, selected batch review, admin queue, explicit review/publish, desktop and mobile layout.')
  finally:server.terminate();server.wait(timeout=10)

if __name__=='__main__':asyncio.run(main())
