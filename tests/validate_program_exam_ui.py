"""Local browser acceptance for guided papers. No live model calls."""
import asyncio
import os
import re
import subprocess
import tempfile

import httpx
from playwright.async_api import async_playwright, expect


async def main():
    with tempfile.TemporaryDirectory(prefix='guided-paper-ui-') as folder:
        env={**os.environ,'QB_DATA_DIR':folder,'AUTH_MODE':'mock','APP_ENV':'test',
             'ADMIN_EMAILS':'admin@example.test','APP_BASE_URL':'http://127.0.0.1:8048'}
        env.pop('DATABASE_URL',None)
        command="""from unittest.mock import patch
from tests.test_program_exam import author
from tests.test_official_exam import result
from program_exam import CurriculumSuggestion, PatternSuggestion, PromptSuggestion, CompleteSuggestion, Section
import uvicorn
def suggest(purpose,prompt,data,schema):
    if schema is CurriculumSuggestion:
        result=CurriculumSuggestion(curriculum='Fractions and reading comprehension.',subjects=['Arithmetic','Language'],assumptions=['Confirm the official syllabus.'])
    elif schema is CompleteSuggestion:
        result=CompleteSuggestion(curriculum='Fractions and reading comprehension.',level='VI',pattern='Suggested practice pattern.',duration_minutes=90,sections=[Section(subject='Arithmetic',count=2),Section(subject='Language',count=1)],instructions='Answer every question.',generation_prompt='Write original questions using the chosen difficulty.')
    elif schema is PatternSuggestion:
        result=PatternSuggestion(pattern='Suggested practice pattern.',duration_minutes=90,sections=[Section(subject='Arithmetic',count=2),Section(subject='Language',count=1)],instructions='Answer every question.')
    else:
        result=PromptSuggestion(generation_prompt='Write original questions aligned with the supplied curriculum and difficulty.')
    return result,{'model':'mock-browser'}
with patch('app.generate_questions',side_effect=author),patch('program_exam.structured_call',side_effect=suggest),patch('official_exam.lookup_official',side_effect=lambda *args:result()):
    uvicorn.run('app:app',host='127.0.0.1',port=8048,log_level='warning')
"""
        server=subprocess.Popen(['.venv/bin/python','-c',command],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            async with httpx.AsyncClient() as client:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError(server.stderr.read().decode())
                    try:
                        if (await client.get('http://127.0.0.1:8048/app')).status_code==200:break
                    except httpx.ConnectError:pass
                    await asyncio.sleep(.1)
                else:raise RuntimeError('UI server did not start')
            async with async_playwright() as pw:
                browser=await pw.chromium.launch()
                context=await browser.new_context(viewport={'width':1440,'height':1100})
                assert (await context.request.post('http://127.0.0.1:8048/api/auth/mock',data={'email':'admin@example.test'})).ok
                page=await context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                await page.goto('http://127.0.0.1:8048/app')
                await page.locator('#admin-nav [data-view=programs]').click()
                await page.locator('[data-program-add]').click()
                await page.locator('[data-program-form] input[name=name]').fill('Navodaya')
                await page.get_by_role('button',name='Save program',exact=True).click()
                await page.get_by_role('button',name='Create exam',exact=True).click()
                form=page.locator('.guided-exam-form')
                await form.wait_for()
                assert await form.locator('[name=difficulty] option').all_text_contents()==['Auto — balanced for level','Very Easy dominant','Easy dominant','Medium dominant','Hard dominant','Very Hard dominant']
                assert await form.locator('[name=question_source] option').all_text_contents()==['Generate all-new questions','Reuse matching approved questions, then generate missing questions']
                await expect(form.locator('[name=total_questions]')).to_have_value('80')
                await expect(form.locator('[name=total_marks]')).to_have_value('100')
                await expect(form.locator('[name=duration_minutes]')).to_have_value('120')
                await expect(page.locator('.guided-prompt-markdown').first.locator('table')).to_be_visible()
                await form.get_by_text('Question-authoring instructions',exact=True).click()
                assert 'Authoring instructions' in await form.locator('[name=generation_prompt]').input_value()
                await form.locator('[name=generation_prompt]').fill('Saved curriculum-specific authoring instructions.')
                await page.get_by_role('button',name='Save exam setup',exact=True).click()
                await page.get_by_text('Exam setup saved. It will be loaded when you reopen this program.',exact=True).wait_for()
                await page.locator('[data-program-close]').click()
                await page.get_by_role('button',name='Open program',exact=True).first.click()
                await page.get_by_role('button',name='Create exam',exact=True).click()
                await expect(form.locator('[name=generation_prompt]')).to_have_value('Saved curriculum-specific authoring instructions.')
                # An admin-edited full duration must survive a subject-wise round trip,
                # even when an official reference suggests a different full duration.
                await form.locator('[name=duration_minutes]').fill('140')
                await form.locator('[name=mode]').select_option('SUBJECT')
                await form.locator('[name=chosen_subject]').select_option('Arithmetic Test')
                await expect(form.locator('[name=duration_minutes]')).to_have_value('30')
                await form.locator('[name=mode]').select_option('FULL')
                await expect(form.locator('[name=duration_minutes]')).to_have_value('140')
                rows=form.locator('.guided-section')
                await rows.nth(0).locator('[name=count]').fill('1')
                await rows.nth(1).locator('[name=count]').fill('1')
                await rows.nth(2).locator('[name=count]').fill('1')
                await expect(form.locator('[name=total_questions]')).to_have_value('3')
                await form.get_by_text('Curriculum, official pattern and student instructions',exact=True).click()
                await form.get_by_text('Question-authoring instructions',exact=True).click()
                for label in ['Suggest curriculum with AI','Improve prompt with AI']:
                    await page.get_by_role('button',name=label,exact=True).click()
                    await page.get_by_text('AI guidance populated in the editable fields.',exact=False).wait_for()
                await form.locator('[name=difficulty]').select_option('very_hard')
                await form.locator('[name=generation_prompt]').fill('My edited prompt: include conceptual reasoning and clear worked solutions.')
                await page.get_by_role('button',name='Preview final prompt',exact=True).click()
                await expect(page.locator('.guided-prompt-markdown').first).to_contain_text('My edited prompt')
                await page.get_by_role('button',name='Generate paper for review',exact=True).click()
                await page.get_by_text('3 generated',exact=False).wait_for(timeout=60000)
                await page.get_by_text('Review question paper, answers and solutions',exact=True).click()
                assert await page.locator('.guided-review-question').count()==3
                assert await page.locator('.guided-review-question .rendered').count()==18
                assert await page.locator('.guided-answer-details:not([open])').count()==3
                assert await page.get_by_role('button',name='Approve question',exact=True).count()==3
                assert await page.get_by_role('button',name='Publish to Question Bank',exact=True).count()==3
                assert await page.get_by_role('button',name='Delete from paper',exact=True).count()==3
                await page.locator('input[name=reviewed]').check()
                await page.get_by_role('button',name='Approve and publish exam',exact=True).click()
                await page.get_by_text('Exam #1 · Published',exact=True).wait_for()
                await page.get_by_role('button',name='Create exam',exact=True).click()
                await form.locator('[name=mode]').select_option('SUBJECT')
                await form.locator('[name=chosen_subject]').select_option('Language Test')
                assert await form.locator('.guided-section').count()==1
                assert await form.locator('.guided-section input[name=subject]').input_value()=='Language Test'
                await form.locator('[name=difficulty]').select_option('very_easy')
                await page.get_by_role('button',name='Generate paper for review',exact=True).click()
                await page.get_by_text(re.compile(r'\d+ reused from the bank · \d+ generated')).last.wait_for()
                # Check the guided form at phone widths, independently of the collapsed sidebar.
                await page.set_viewport_size({'width':390,'height':844})
                await page.wait_for_function("document.querySelector('#sidebar').getBoundingClientRect().right <= 1")
                assert await form.evaluate('(node)=>node.scrollWidth<=node.clientWidth+1')
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                await page.evaluate('window.scrollTo(0,0)')
                await page.screenshot(path='/tmp/meritiqra-guided-exam-mobile.png',full_page=True)
                await page.set_viewport_size({'width':1440,'height':1100})
                await page.screenshot(path='/tmp/meritiqra-guided-exam-desktop.png',full_page=True)
                search=page.locator('[data-program-search]')
                await expect(search.locator('[name=status]')).to_have_value('ACTIVE')
                page.on('dialog',lambda dialog:dialog.accept())
                await page.locator('[data-program-close]').click()
                await page.locator('[data-program-list] [data-program-state]').click()
                await expect(page.locator('.guided-exam-form')).to_have_count(0)
                await page.get_by_role('button',name='Create exam',exact=True).click()
                await expect(page.get_by_role('button',name='Restore program and create exam',exact=True)).to_be_visible()
                await expect(page.locator('[data-program-list] article')).to_have_count(0)
                await page.locator('[data-program-close]').click()
                await search.locator('[name=status]').select_option('ARCHIVED')
                await search.get_by_role('button',name='Search',exact=True).click()
                await page.get_by_role('button',name='View archived program',exact=True).click()
                await expect(page.locator('.guided-exam-form')).to_have_count(0)
                await page.get_by_role('button',name='Create exam',exact=True).click()
                await page.get_by_role('button',name='Restore program and create exam',exact=True).click()
                await expect(page.locator('.guided-exam-form')).to_have_count(1)
                await expect(page.locator('[data-program-list] article')).to_have_count(0)
                await page.locator('[data-program-close]').click()
                await search.locator('[name=status]').select_option('ACTIVE')
                await search.get_by_role('button',name='Search',exact=True).click()
                await expect(page.locator('[data-program-list] article')).to_have_count(1)
                assert not errors,errors
                print('Passed: name-only creation, on-demand AI suggestions, editable prompt, auto/five explicit difficulties, review/publish, rendered questions, mobile layout, archived program guard and explicit restore.')
                await browser.close()
        finally:
            server.terminate();server.wait(timeout=10)


if __name__=='__main__':asyncio.run(main())
