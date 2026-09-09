"""Local-only browser acceptance for minimal-input setup; Gemini is mocked."""
import asyncio
import os
import subprocess
import tempfile

import httpx
from playwright.async_api import async_playwright


async def main():
    with tempfile.TemporaryDirectory(prefix='program-setup-ui-') as folder:
        env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test','APP_BASE_URL':'http://127.0.0.1:8046'}
        env.pop('DATABASE_URL',None)
        command="""from unittest.mock import patch
from tests.test_program_setup import proposal
import uvicorn
with patch('blueprint_setup.structured_call',return_value=(proposal(),{'model':'mock-browser'})):
    uvicorn.run('app:app',host='127.0.0.1',port=8046,log_level='warning')
"""
        server=subprocess.Popen(['.venv/bin/python','-c',command],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            async with httpx.AsyncClient() as client:
                for _ in range(100):
                    try:
                        if (await client.get('http://127.0.0.1:8046/app')).status_code==200:break
                    except httpx.ConnectError:pass
                    await asyncio.sleep(.1)
                else:raise RuntimeError('Local UI server did not start')
            async with async_playwright() as pw:
                browser=await pw.chromium.launch()
                context=await browser.new_context(viewport={'width':1440,'height':1000})
                assert (await context.request.post('http://127.0.0.1:8046/api/auth/mock',data={'email':'admin@example.test'})).ok
                csrf=next(c['value'] for c in await context.cookies() if c['name']=='qb_csrf')
                created=await context.request.post('http://127.0.0.1:8046/api/programs',headers={'X-CSRF-Token':csrf},data={'code':'NAVODAYA','name':'Navodaya'})
                assert created.status==201
                page=await context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('dialog',lambda dialog:dialog.accept())
                await page.goto('http://127.0.0.1:8046/app')
                await page.locator('#admin-nav [data-view=programs]').click()
                await page.locator('[data-program-open]').click()
                await page.locator('nav [data-program-tab=setup]').click()
                await page.get_by_role('button',name='Generate setup',exact=True).click()
                await page.get_by_role('button',name='Apply setup as drafts').wait_for()
                await page.get_by_role('button',name='Apply setup as drafts').click()
                await page.get_by_text('Drafts saved',exact=False).wait_for()
                for width in (1440,820,390):
                    await page.set_viewport_size({'width':width,'height':1000})
                    if width<=800:
                        await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right <= 1")
                    await page.locator('.program-setup-card').scroll_into_view_if_needed()
                    box=await page.locator('.program-setup-card').bounding_box()
                    assert box['x']+box['width']<=width+1, (width,box)
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow at {width}'
                    await page.screenshot(path=f'/tmp/program-setup-{width}.png')
                for tab in ('overview','EXAM_PATTERN','EXAM_GENERATOR','QUESTION_GENERATOR','curriculum','evidence','gemini','papers','audit'):
                    await page.locator(f'nav [data-program-tab="{tab}"]').click()
                    await page.wait_for_function("Boolean(document.querySelector('[data-program-content]').textContent.trim()) && document.querySelector('[data-program-content]').textContent !== 'Loading…'")
                    content=await page.locator('[data-program-content]').inner_text()
                    assert content.strip() and 'Internal Server Error' not in content, (tab,content)
                assert not errors,errors
                await browser.close()
                print('PASS: name-only Gemini setup, review/apply, all nine workspace tabs; 1440/820/390px, no overflow or JavaScript errors')
        finally:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()


if __name__=='__main__':asyncio.run(main())
