"""Browser acceptance for Grand Test creation, review and publication."""
import asyncio, os, subprocess, tempfile
import httpx
from playwright.async_api import async_playwright, expect
from tests.test_grand_tests import pdf

async def main():
    with tempfile.TemporaryDirectory(prefix='grand-test-ui-') as folder:
        env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test','APP_BASE_URL':'http://127.0.0.1:8059'}
        env.pop('DATABASE_URL',None)
        command="""import uvicorn
from unittest.mock import patch, AsyncMock
from tests.test_grand_tests import extracted
with patch('app.parse_pdf_paper',new=AsyncMock(return_value=extracted())),patch('grand_tests.classify',side_effect=lambda qs,pid:qs):
    uvicorn.run('app:app',host='127.0.0.1',port=8059,log_level='warning')
"""
        server=subprocess.Popen(['.venv/bin/python','-c',command],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                try:
                    if httpx.get('http://127.0.0.1:8059/healthz').status_code==200:break
                except httpx.ConnectError:pass
                await asyncio.sleep(.1)
            async with async_playwright() as p:
                browser=await p.chromium.launch()
                ctx=await browser.new_context(viewport={'width':1440,'height':1000})
                base='http://127.0.0.1:8059'
                r=await ctx.request.post(base+'/api/auth/mock',data={'email':'admin@example.test'});assert r.ok
                cookies=await ctx.cookies();csrf=next(c['value'] for c in cookies if c['name']=='qb_csrf')
                r=await ctx.request.post(base+'/api/programs',headers={'X-CSRF-Token':csrf},data={'code':'GT','name':'Grand Test Program'});assert r.ok
                page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto(base+'/app');await page.locator('[data-view="grand-tests"]').click()
                await page.locator('#gt-create [name=name]').fill('Browser Grand Test')
                await page.locator('#gt-create button').click()
                await page.locator('#gt-upload input').set_input_files({'name':'paper.pdf','mimeType':'application/pdf','buffer':pdf()})
                await page.locator('#gt-upload button').click()
                await expect(page.locator('#gt-page-image')).to_be_visible()
                box=await page.locator('#gt-page-image').bounding_box()
                await page.mouse.move(box['x']+30,box['y']+30);await page.mouse.down();await page.mouse.move(box['x']+200,box['y']+130);await page.mouse.up()
                await expect(page.locator('[data-selection]')).to_have_count(1)
                await page.locator('#gt-page').fill('2');await page.locator('#gt-page').dispatch_event('change')
                await expect(page.locator('[data-selection]')).to_have_count(1)
                await page.locator('#gt-whole').click()
                await expect(page.locator('[data-question]')).to_have_count(1,timeout=15000)
                await page.locator('[name=reviewed]').check()
                await page.locator('#gt-finalize').click()
                await expect(page.locator('#gt-generate')).to_be_visible()
                await page.locator('#gt-generate').click()
                await page.locator('#gt-schedule [name=start]').fill('2026-09-15T10:00')
                await page.locator('#gt-schedule [name=end]').fill('2026-09-15T13:00')
                await page.screenshot(path='/tmp/grand-tests-desktop.png',full_page=True)
                await page.set_viewport_size({'width':390,'height':844})
                await page.screenshot(path='/tmp/grand-tests-mobile.png',full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                await page.locator('#gt-publish').click()
                await expect(page.locator('#grand-tests-panel')).to_contain_text('Proctor code:')
                operator=await browser.new_context()
                r=await operator.request.post(base+'/api/auth/mock',data={'email':'operator@example.test'});uid=(await r.json())['id']
                r=await ctx.request.put(base+f'/api/admin/users/{uid}/role',headers={'X-CSRF-Token':csrf},data={'role':'OPERATOR'});assert r.ok
                op=await operator.new_page();op.on('pageerror',lambda e:errors.append(str(e)))
                await op.goto(base+'/app')
                await expect(op.locator('#gt-create')).to_be_visible()
                await expect(op.locator('#gt-users')).to_have_count(0)
                assert await op.locator('#gt-generate,#gt-publish').count()==0
                await expect(op.locator('#admin-nav')).to_be_hidden()
                assert not errors,errors
                await browser.close()
                print('Grand Test browser workflow passed: creation, upload, extraction, review, schedule, publication; desktop and mobile.')
        finally:
            server.terminate();server.wait(timeout=10)

if __name__=='__main__':asyncio.run(main())
