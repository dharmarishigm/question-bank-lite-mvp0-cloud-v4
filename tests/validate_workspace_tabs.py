"""Browser regression: section visibility, keyboard access and edit preservation."""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.set_content('<main id="host"><div class="page-header">Workspace</div><form id="create"><input aria-label="Name"></form><section id="library">Library</section><section id="list">Workspaces</section></main>')
    page.add_script_tag(path=str(ROOT/'static/workspace-tabs.js'))
    page.add_style_tag(path=str(ROOT/'static/workspace-tabs.css'))
    page.evaluate("WorkspaceTabs.mount(document.querySelector('#host'), [['Workspaces',[document.querySelector('#list')]],['Create',[document.querySelector('#create')]],['Library',[document.querySelector('#library')]]], 'catalog')")
    assert page.locator('#list').is_visible()
    assert not page.locator('#create').is_visible()
    page.get_by_role('button', name='Create', exact=True).click()
    page.get_by_label('Name').fill('Unsaved workspace')
    page.get_by_role('button', name='Library', exact=True).click()
    page.get_by_role('button', name='Create', exact=True).focus()
    page.keyboard.press('Enter')
    assert page.get_by_label('Name').input_value() == 'Unsaved workspace'
    assert not page.locator('#library').is_visible()
    assert page.get_by_role('button', name='Create', exact=True).get_attribute('aria-pressed') == 'true'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    browser.close()
print('Workspace tabs: mobile layout, keyboard navigation and unsaved edits passed')
