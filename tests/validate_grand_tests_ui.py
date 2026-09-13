"""Browser acceptance for Grand Test creation, review and publication."""
import asyncio, os, subprocess, tempfile
import httpx
from playwright.async_api import async_playwright, expect
from tests.test_grand_tests import pdf

async def exercise_pdf(page,root,zoom_selector):
    images=root.locator('.pdf-page-surface img')
    await expect(images).to_have_count(2)
    await expect(images.first).to_be_visible()
    await page.wait_for_function('(img)=>img.complete && img.naturalWidth>0',arg=await images.first.element_handle())
    pages=root.locator('.pdf-viewer-pages')
    assert await pages.evaluate('(e)=>e.scrollHeight>e.clientHeight && getComputedStyle(e).overflowY==="scroll"')
    await root.get_by_role('button',name='Zoom in',exact=True).click()
    await expect(root.locator(zoom_selector)).to_have_value('125')
    assert await pages.evaluate('(e)=>e.scrollWidth>e.clientWidth')
    await root.get_by_role('button',name='Zoom out',exact=True).click()
    await expect(root.locator(zoom_selector)).to_have_value('100')
    await root.get_by_role('button',name='Fit width',exact=True).click()
    await root.get_by_role('button',name='Zoom in',exact=True).click()
    await root.get_by_role('button',name='Select portion',exact=True).click()
    async def draw(index):
        image=images.nth(index)
        await image.scroll_into_view_if_needed()
        await page.wait_for_function('(img)=>img.complete && img.naturalWidth>0',arg=await image.element_handle())
        # Keep target near the visible top of the scrolling viewport.
        await pages.evaluate('(e,i)=>{e.scrollTop=e.querySelectorAll("figure")[i].offsetTop-e.offsetTop; e.scrollLeft=0}',index)
        await pages.scroll_into_view_if_needed()
        box=await image.bounding_box(); viewport=await pages.bounding_box()
        x=box['x']+40; y=max(box['y']+40,viewport['y']+50)
        await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+120,y+80,steps=5);await page.mouse.up()
        return [(x-box['x'])/box['width'],(y-box['y'])/box['height'],(x+120-box['x'])/box['width'],(y+80-box['y'])/box['height']]
    first=await draw(0)
    await expect(root.locator('.pdf-selection-box')).to_have_count(1)
    await draw(1)
    await expect(root.locator('.pdf-selection-box')).to_have_count(2)
    await root.get_by_role('button',name='Redraw selection',exact=True).click()
    await expect(root.locator('.pdf-selection-box')).to_have_count(1)
    second=await draw(1)
    await expect(root.locator('.pdf-selection-box')).to_have_count(2)
    await pages.evaluate('(e)=>{e.scrollTop=0; e.scrollLeft=0}')
    await page.screenshot(path='/tmp/'+('grand-test' if zoom_selector.startswith('[data') else 'upload')+'-shared-pdf.png',full_page=True)
    return [first,second]

async def main():
    with tempfile.TemporaryDirectory(prefix='grand-test-ui-') as folder:
        env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test','ADMIN_EMAILS':'admin@example.test','APP_BASE_URL':'http://127.0.0.1:8059'}
        env['SECURITY_HARDENING']=os.getenv('VALIDATE_SECURITY','0')
        env['GOOGLE_CLIENT_ID']='test-client.apps.googleusercontent.com'
        env.pop('DATABASE_URL',None)
        command="""import uvicorn
from unittest.mock import patch, AsyncMock
from tests.test_grand_tests import extracted
with patch('google.oauth2.id_token.verify_oauth2_token',side_effect=lambda token,*a,**k:dict(sub='google:'+token,email=token,email_verified=True,name='Test User')),patch('app._parse_source',new=AsyncMock(side_effect=lambda *a,**k:extracted())),patch('app.parse_pdf_paper',new=AsyncMock(return_value=extracted())),patch('app.digitise_pdf_crop',new=AsyncMock(return_value=extracted())),patch('grand_tests.classify',side_effect=lambda qs,pid:qs):
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
                r=await ctx.request.post(base+'/api/auth/google',data={'credential':'admin@example.test'});assert r.ok
                cookies=await ctx.cookies();csrf=next(c['value'] for c in cookies if c['name']=='qb_csrf')
                r=await ctx.request.post(base+'/api/programs',headers={'X-CSRF-Token':csrf},data={'code':'GT','name':'Grand Test Program'});assert r.ok
                page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                await page.goto(base+'/app');await page.locator('nav[aria-label="DigitalQBank"] [data-view="grand-tests"]').click()
                await page.get_by_role('button',name='PDF library',exact=True).click()
                await page.locator('#gt-doc-upload [name=subject]').fill('Physics')
                await page.locator('#gt-doc-upload [name=file]').set_input_files({'name':'library.pdf','mimeType':'application/pdf','buffer':pdf()})
                await page.get_by_role('button',name='Store documents',exact=True).click()
                await expect(page.locator('[data-doc-availability]')).to_have_count(1)
                await expect(page.locator('.gt-table-wrap')).to_contain_text('Not Started')
                await page.get_by_role('button',name='PDF library',exact=True).click()
                availability=page.locator('[data-doc-availability]');before=await availability.inner_text();await page.locator('.table-action-menu').select_option(label=before)
                await expect(availability).not_to_have_text(before)
                await expect(page.locator('[data-document-status]')).to_contain_text('1 PDFs available')
                await page.locator('.workspace-tabs').get_by_role('button',name='Create workspace',exact=True).click()
                await page.locator('#gt-create [name=name]').fill('Browser Grand Test')
                await page.locator('#gt-create [name=document_id]').select_option(index=1)
                await page.locator('#gt-create').get_by_role('button',name='Create workspace',exact=True).click()
                await expect(page.locator('#gt-upload')).to_have_count(0)
                workspace=page.locator('#gt-pdf-workspace')
                expected=await exercise_pdf(page,workspace,'[data-pdf-id="pdf-viewer-zoom"]')
                async with page.expect_request(lambda r: r.url.endswith('/digitize') and r.method=='POST') as sent:
                    await workspace.locator('[data-pdf-id="pdf-selection-digitise"]').click()
                regions=(await sent.value).post_data_json['selections']
                assert [r['page'] for r in regions]==[1,2]
                for r,bbox in zip(regions,expected):
                    assert all(abs(a-b)<.002 for a,b in zip(r['bbox'],bbox)),(r,bbox)
                    assert 0 <= r['bbox'][0] < r['bbox'][2] <= 1
                    assert 0 <= r['bbox'][1] < r['bbox'][3] <= 1
                await expect(page.locator('[data-question]')).to_have_count(1,timeout=15000)
                await page.locator('[data-pdf-id="pdf-viewer-digitise"]').click()
                await expect(page.locator('[data-pdf-id="pdf-viewer-digitise"]')).to_be_enabled(timeout=20000)
                await expect(page.locator('[data-question]')).to_have_count(1,timeout=15000)
                await page.locator('[name=reviewed]').check()
                await page.get_by_role('button',name='Save selected questions',exact=True).click()
                await expect(page.locator('[data-status]')).to_contain_text('saved to the question bank')
                await expect(page.locator('[data-pick-question]')).to_be_disabled()
                await page.locator('#gt-finalize').click()
                create_exam=page.get_by_role('button',name='Create draft exam',exact=True)
                await expect(create_exam).to_be_visible()
                await create_exam.click()
                await page.locator('#gt-schedule [name=start]').fill('2026-09-15T10:00')
                await page.locator('#gt-schedule [name=end]').fill('2026-09-15T13:00')
                await page.screenshot(path='/tmp/grand-tests-desktop.png',full_page=True)
                await page.set_viewport_size({'width':390,'height':844})
                await page.screenshot(path='/tmp/grand-tests-mobile.png',full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                await page.locator('#gt-publish').click()
                await expect(page.locator('#grand-tests-panel')).to_contain_text('Proctor code:')
                operator=await browser.new_context()
                r=await operator.request.post(base+'/api/auth/google',data={'credential':'operator@example.test'});uid=(await r.json())['id']
                r=await ctx.request.post(base+'/api/admin/operator-allowlist',headers={'X-CSRF-Token':csrf},data={'email':'operator@example.test'});assert r.ok
                r=await ctx.request.put(base+f'/api/admin/users/{uid}/role',headers={'X-CSRF-Token':csrf},data={'role':'OPERATOR'});assert r.ok
                op=await operator.new_page();op.on('pageerror',lambda e:errors.append(str(e)))
                await op.goto(base+'/app')
                await op.locator('.workspace-tabs').get_by_role('button',name='Create workspace',exact=True).click()
                await expect(op.locator('#gt-create')).to_be_visible()
                await expect(op.locator('#gt-users')).to_have_count(0)
                assert await op.locator('#gt-generate,#gt-publish').count()==0
                await expect(op.locator('#admin-nav')).to_be_hidden()
                await op.locator('#gt-create [name=name]').fill('Operator workspace')
                await op.locator('#gt-create [name=document_id]').select_option(index=1)
                await op.locator('#gt-create').get_by_role('button',name='Create workspace',exact=True).click()
                await expect(op.locator('#gt-upload')).to_have_count(0)
                await exercise_pdf(op,op.locator('#gt-pdf-workspace'),'[data-pdf-id="pdf-viewer-zoom"]')
                await op.locator('[data-pdf-id="pdf-selection-digitise"]').click()
                await expect(op.locator('[data-question]')).to_have_count(1,timeout=15000)
                assert await op.locator('#gt-generate,#gt-publish').count()==0
                # Same real pointer interactions in the original Upload & Digitise viewer.
                await page.set_viewport_size({'width':1440,'height':1000})
                await page.locator('[data-view="upload-crop"]').click()
                await page.locator('#pdf-file').set_input_files({'name':'paper.pdf','mimeType':'application/pdf','buffer':pdf()})
                await exercise_pdf(page,page.locator('#pdf-viewer'),'#pdf-viewer-zoom')
                async with page.expect_response(lambda r: '/digitise-crop' in r.url) as crop:
                    await page.locator('#pdf-selection-digitise').click()
                assert (await crop.value).ok
                await expect(page.locator('#pdf-viewer .pdf-selection-box')).to_have_count(0)
                async with page.expect_response(lambda r: r.url.endswith('/api/source/parse')) as whole:
                    await page.locator('#pdf-viewer-digitise').click()
                assert (await whole.value).ok
                await expect(page.locator('#pdf-viewer-digitise')).to_be_enabled(timeout=15000)
                assert not errors,errors
                await browser.close()
                print('Grand Test browser workflow passed: creation, upload, extraction, review, schedule, publication; desktop and mobile.')
        finally:
            server.terminate();server.wait(timeout=10)
            logs=server.stderr.read().decode()
            if 'Traceback' in logs: print('Server diagnostic:',logs[logs.rfind('  File '):])

if __name__=='__main__':asyncio.run(main())
