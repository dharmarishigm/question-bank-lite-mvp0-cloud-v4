"""Isolated browser test: real admin routes, no production data or AI calls."""
import asyncio
import os
import subprocess
import tempfile
import httpx
from playwright.async_api import async_playwright,expect


async def main():
    with tempfile.TemporaryDirectory(prefix='table-actions-test-') as folder:
        env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test','APP_BASE_URL':'http://127.0.0.1:8049'}
        env.pop('DATABASE_URL',None)
        command="""from unittest.mock import patch
from llm_generate import GeneratedQuestion,GeneratedQuestionBatch
import uvicorn
def generate(payload):
    return GeneratedQuestionBatch(questions=[GeneratedQuestion(statement=payload.generation_prompt,options=[{'label':'A','text':'1'},{'label':'B','text':'2'}],answer='B',solution='One plus one is two.')]),{},'mock'
with patch('app.generate_questions',side_effect=generate):
    uvicorn.run('app:app',host='127.0.0.1',port=8049,log_level='warning')
"""
        server=subprocess.Popen(['.venv/bin/python','-c',command],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            async with httpx.AsyncClient() as client:
                for _ in range(100):
                    if server.poll() is not None:raise RuntimeError(server.stderr.read().decode())
                    try:
                        if (await client.get('http://127.0.0.1:8049/app')).status_code==200:break
                    except httpx.ConnectError:pass
                    await asyncio.sleep(.1)
            async with async_playwright() as pw:
                browser=await pw.chromium.launch()
                context=await browser.new_context(viewport={'width':1440,'height':1000})
                assert (await context.request.post('http://127.0.0.1:8049/api/auth/mock',data={'email':'admin@example.test'})).ok
                csrf=next(cookie['value'] for cookie in await context.cookies() if cookie['name']=='qb_csrf')
                await context.set_extra_http_headers({'X-CSRF-Token':csrf})
                ids=[]
                for i in range(2):
                    response=await context.request.post('http://127.0.0.1:8049/api/ai/generate',data={'exam_name':'UI test','subject':'Math','count':1,'generation_prompt':f'Choose the sum of one and one. Test {i}.'})
                    assert response.ok,await response.text()
                    ids.append((await response.json())['run_id'])
                saved=await context.request.post(f'http://127.0.0.1:8049/api/ai/runs/{ids[0]}/save',data={'indices':[0]})
                assert saved.ok,await saved.text()
                qid=(await saved.json())['questions'][0]['id']
                page=await context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                await page.goto('http://127.0.0.1:8049/app')
                await page.locator('#admin-nav [data-view=ai-generate]').click()
                await page.locator('[data-ai-tab=saved]').click()
                await expect(page.locator('#ai-run-list .table-action-menu')).to_have_count(2)
                await page.locator('#ai-run-list .table-action-menu').first.select_option(label='Review')
                await expect(page.locator('#ai-generation-results')).to_be_visible()
                await page.locator('[data-ai-tab=saved]').click()
                await page.locator('[data-ai-select-page]').check()
                await expect(page.locator('[data-ai-selected-count]')).to_have_text('2 selected')
                await page.locator('[data-ai-bulk-menu]').select_option('review')
                await expect(page.locator('#ai-generation-results .ai-question-card')).to_have_count(2)
                await page.locator('[data-ai-tab=saved]').click()
                await page.locator('[data-ai-select-page]').check()
                page.once('dialog',lambda dialog:dialog.dismiss())
                await page.locator('[data-ai-bulk-menu]').select_option('delete')
                await expect(page.locator('#ai-run-list tbody tr')).to_have_count(2)
                await page.set_viewport_size({'width':390,'height':844})
                await expect(page.locator('[data-ai-bulk-menu]')).to_be_visible()
                await page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
                await page.locator('#ai-run-list .table-action-menu').first.scroll_into_view_if_needed()
                await page.screenshot(path='/tmp/meritiqra-table-actions-mobile.png',full_page=True)
                page.once('dialog',lambda dialog:dialog.accept())
                await page.locator('[data-ai-bulk-menu]').select_option('delete')
                await expect(page.locator('#ai-run-list tbody tr')).to_have_count(0)
                assert (await context.request.get(f'http://127.0.0.1:8049/api/questions/{qid}')).ok
                await page.evaluate("""()=>{const host=document.createElement('section');host.id='table-test';host.innerHTML='<table><thead><tr><th>Name</th><th>Actions</th></tr></thead><tbody><tr><td>One</td><td><button onclick="this.dataset.clicked=1">Inspect</button><button disabled>Delete</button></td></tr></tbody></table>';document.querySelector('#main-content').append(host);}""")
                await expect(page.locator('#table-test .table-action-menu')).to_have_count(1)
                await page.locator('#table-test .table-action-menu').select_option(label='Inspect')
                await expect(page.locator('#table-test button').first).to_have_attribute('data-clicked','1')
                assert await page.locator('#table-test .table-action-menu option',has_text='Delete').is_disabled()
                await page.locator('#table-test .table-row-select').check()
                async with page.expect_download() as download:
                    await page.locator('#table-test [data-table-selected-actions]').select_option('export')
                assert (await download.value).suggested_filename=='selected-rows.csv'
                assert not errors,errors
                await browser.close()
                print('PASS: desktop/mobile menus, bulk review, cancellation, deletion preserving bank questions, selection/export, disabled actions and original handlers')
        finally:
            server.terminate();server.wait(timeout=10)


if __name__=='__main__':asyncio.run(main())
