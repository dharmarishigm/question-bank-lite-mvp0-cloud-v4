"""Local browser checks with disposable accounts; never accesses production."""
import asyncio, os, subprocess, tempfile, time
import httpx
from cryptography.fernet import Fernet
from playwright.async_api import async_playwright, expect
from security_mfa import code_for

async def main():
    base='http://127.0.0.1:8063'
    with tempfile.TemporaryDirectory(prefix='security-ui-') as folder:
        env={**os.environ,'QB_DATA_DIR':folder,'APP_ENV':'test','AUTH_MODE':'mock','ADMIN_EMAILS':'admin@example.test','APP_BASE_URL':base,'SECURITY_HARDENING':'1','REQUIRE_STAFF_MFA':'1','MFA_ENCRYPTION_KEY':Fernet.generate_key().decode(),'GOOGLE_CLIENT_ID':'test.apps.googleusercontent.com'}
        for key in ['DATABASE_URL','QB_SCHEMA_MANAGED','K_SERVICE']:env.pop(key,None)
        command="""from unittest.mock import patch
import uvicorn
with patch('google.oauth2.id_token.verify_oauth2_token',side_effect=lambda token,*a,**k:dict(sub='test:'+token,email=token,email_verified=True,name='Test User')):
 uvicorn.run('app:app',host='127.0.0.1',port=8063,log_level='error')
"""
        server=subprocess.Popen(['.venv/bin/python','-c',command],env=env,stdout=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    if httpx.get(base+'/api/health').status_code==200:break
                except httpx.ConnectError:pass
                await asyncio.sleep(.1)
            async with async_playwright() as p:
                browser=await p.chromium.launch()
                student=await browser.new_context()
                assert (await student.request.post(base+'/api/auth/google',data={'credential':'student@example.test'})).ok
                page=await student.new_page();await page.goto(base+'/app')
                await expect(page.locator('#app-shell')).to_be_visible()
                await expect(page.locator('#admin-nav')).to_be_hidden()
                assert (await student.request.get(base+'/api/admin/users')).status==403
                print('PASS Student UI hides Admin navigation and Admin API denies access')
                admin=await browser.new_context()
                assert (await admin.request.post(base+'/api/auth/google',data={'credential':'admin@example.test'})).ok
                a=await admin.new_page();await a.goto(base+'/app');await a.wait_for_url('**/static/mfa.html')
                assert (await admin.request.get(base+'/api/admin/users')).status==403
                await expect(a.locator('#secret')).not_to_be_empty()
                key=await a.locator('#secret').inner_text()
                await a.locator('#code').fill(code_for(key,int(time.time()//30)))
                await a.locator('#verify button').click();await a.wait_for_url('**/app')
                await expect(a.locator('#app-shell')).to_be_visible()
                assert (await admin.request.get(base+'/api/admin/users')).status==200
                print('PASS Admin redirected to MFA; access granted only after valid TOTP')
                # Re-authentication must create a session without the prior MFA grant.
                assert (await admin.request.post(base+'/api/auth/google',data={'credential':'admin@example.test'})).ok
                assert (await admin.request.get(base+'/api/admin/users')).status==403
                await a.reload();await a.wait_for_url('**/static/mfa.html')
                print('PASS New Admin login requires MFA again')
                await browser.close()
        finally:
            server.terminate();server.wait(timeout=10)

if __name__=='__main__':asyncio.run(main())
