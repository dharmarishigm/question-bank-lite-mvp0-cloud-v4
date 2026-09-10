"""Opt-in localhost browser check; creates only synthetic program records."""
import asyncio
import time

from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(viewport={'width': 1440, 'height': 1000})
        response = await context.request.post('http://127.0.0.1:8044/api/auth/mock', data={'email':'admin@example.test','name':'Programs QA'})
        assert response.ok
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto('http://127.0.0.1:8044/app')
        await page.locator('#admin-nav [data-view="programs"]').click()
        await page.get_by_role('button', name='Add program', exact=True).click()
        code = 'QA_' + str(time.time_ns())
        form = page.locator('[data-program-form]')
        await form.get_by_text('Optional program details',exact=True).click()
        await form.locator('[name=code]').fill(code)
        await form.locator('[name=name]').fill('QA Navodaya sample')
        await form.locator('[name=languages]').fill('English, Telugu')
        await form.get_by_role('button',name='Save program').click()
        await page.locator('[data-program-editor]').wait_for(state='hidden')
        search = page.locator('[data-program-search]')
        await search.locator('[name=q]').fill(code)
        await search.get_by_role('button',name='Search',exact=True).click()
        card = page.locator('[data-program-list] article').filter(has_text='QA Navodaya sample')
        await card.get_by_role('button',name='Create exam',exact=True).click()
        await page.get_by_text('Advanced program workspace',exact=True).click()
        await page.locator('[data-program-tab="QUESTION_GENERATOR"]').click()
        await page.get_by_role('button',name='Create blueprint',exact=True).click()
        blueprint = page.locator('[data-blueprint-form]')
        await blueprint.locator('[name=name]').fill('Question defaults')
        medium = blueprint.get_by_role('group', name='MEDIUM', exact=True)
        await medium.get_by_label('Seconds', exact=True).fill('75')
        await blueprint.locator('[name=summary]').fill('QA fixture')
        await blueprint.get_by_role('button',name='Save new draft version').click()
        await page.get_by_role('button',name='Edit / versions').click()
        await page.get_by_text('Version 1 · DRAFT',exact=True).wait_for()
        await page.get_by_role('button',name='Effective profiles',exact=True).click()
        await page.locator('[data-effective-view]').wait_for()
        assert '75' in await page.locator('[data-effective-view]').inner_text()
        for tab in ['curriculum','evidence','gemini','papers']:
            await page.locator(f'[data-program-tab="{tab}"]').click()
            await page.wait_for_function("!document.querySelector('[data-program-content]').textContent.startsWith('Loading')")
            await page.locator('[data-program-content] h4').first.wait_for()
            assert 'Internal Server Error' not in await page.locator('[data-program-content]').inner_text()
        await page.locator('[data-program-tab="QUESTION_GENERATOR"]').click()
        await page.get_by_role('button',name='Edit / versions').click()
        await page.get_by_text('Version 1 · DRAFT',exact=True).wait_for()
        for width in [1440, 820, 390]:
            await page.set_viewport_size({'width':width,'height':1000})
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}'
            await page.locator('[data-blueprint-form]').scroll_into_view_if_needed()
            await page.screenshot(path=f'/tmp/programs-ui-{width}.png',full_page=False)
        assert not errors, errors
        await browser.close()
        print('PASS: Program create/search/open, question blueprint draft/version history, difficulty override, effective inheritance, curriculum/evidence/Gemini/paper tabs; 1440/820/390px without overflow or JavaScript errors')


if __name__ == '__main__':
    asyncio.run(main())
