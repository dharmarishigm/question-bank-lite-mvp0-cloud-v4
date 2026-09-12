"""Render the real shell/styles with role fixtures, without calling production APIs."""
from pathlib import Path
import re
import tempfile
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'static/index.html').read_text()
styles=re.findall(r'<link[^>]+href="(/static/[^"?]+\.css)',html)
html=re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S)
html=re.sub(r'<link\b[^>]*>', '', html)
evidence=Path(tempfile.mkdtemp(prefix='meritiqra-role-ui-'))
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    for role in ('ADMIN','STUDENT','OPERATOR'):
        for width in (1440,390):
            page=browser.new_page(viewport={'width':width,'height':900})
            page.route('**/*',lambda route:route.abort())
            page.set_content(html)
            for style in styles:
                path=ROOT/style.lstrip('/')
                if path.exists():page.add_style_tag(path=str(path))
            page.evaluate('''role => {
                document.querySelector('#app-shell').hidden=false;
                document.querySelector('#app-shell').classList.add('nav-open');
                document.querySelectorAll('.sidebar nav').forEach(n=>n.hidden=true);
                if(role==='OPERATOR') {
                    const nav=document.createElement('nav');nav.innerHTML='<button data-view="grand-tests">DigitalQBank</button>';
                    document.querySelector('.sidebar').append(nav);
                } else document.querySelector(role==='ADMIN'?'#admin-nav':'#student-nav').hidden=false;
                window.clickedPage='';document.querySelectorAll('nav [data-view]').forEach(b=>b.onclick=()=>window.clickedPage=b.dataset.view);
            }''',role)
            page.add_script_tag(path=str(ROOT/'static/role-navigation.js'))
            query='DigitalQBank' if role=='OPERATOR' else 'exam'
            page.get_by_label('Find a page',exact=True).fill(query)
            buttons=page.locator('.navigation-finder-results button')
            assert buttons.count()>0
            if role=='STUDENT':assert 'Exam Admin' not in buttons.all_text_contents()
            if role=='OPERATOR':assert buttons.all_text_contents()==['DigitalQBank']
            page.get_by_label('Find a page',exact=True).press('ArrowDown')
            page.keyboard.press('Enter')
            assert page.evaluate('Boolean(window.clickedPage)')
            page.get_by_label('Find a page',exact=True).fill('no matching page')
            assert page.get_by_text('No matching pages in this workspace.',exact=True).is_visible()
            page.get_by_label('Find a page',exact=True).press('Escape')
            assert page.locator('.navigation-finder-results').is_hidden()
            page.evaluate("document.querySelectorAll('.tab-panel').forEach(p=>{p.hidden=p.id!=='available-exams-panel';p.classList.toggle('active',!p.hidden);})")
            assert page.locator('#available-exams-panel').is_visible()
            page.screenshot(path=str(evidence/f'{role.lower()}-{width}.png'),full_page=False)
            page.evaluate("document.body.classList.add('exam-focus')")
            assert page.locator('.navigation-finder').is_hidden()
            page.close()
    browser.close()
print('Role navigation passed: Admin/Student/Operator, keyboard, search, exam focus, desktop/mobile')
print(evidence)
