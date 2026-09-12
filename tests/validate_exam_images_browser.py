"""Exercise the production Markdown renderer with generated exam SVG panels."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main():
    source = (ROOT / 'static/app.js').read_text()
    renderer = source[source.index('function escapeHtml('):source.index('function typeset(')]
    async with async_playwright() as p:
        for engine in (p.chromium, p.webkit):
            browser = await engine.launch()
            for width in (390, 768, 1440):
                page = await browser.new_page(viewport={'width': width, 'height': 844})
                await page.route('https://exam.test/**', lambda route: route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><circle cx="200" cy="200" r="180" fill="none" stroke="black"/></svg>'))
                await page.route('https://exam.test/', lambda route: route.fulfill(content_type='text/html', body='<html><body></body></html>'))
                await page.goto('https://exam.test/')
                await page.set_content('<div id="exam-current-question" class="exam-question-card"><div id="figure" class="rendered"></div><div class="exam-option-item"><div id="option" class="rendered"></div></div></div>')
                await page.add_style_tag(content=(ROOT / 'static/programs.css').read_text())
                await page.add_script_tag(content='const MATH_PATTERN=/\uFFFF/g;' + renderer)
                await page.evaluate("""() => { for (const id of ['figure','option']) document.getElementById(id).innerHTML=toHtml('![Figure](/uploads/generated-visual-0123456789abcdef-a.svg)'); }""")
                await page.wait_for_function('Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)')
                assert await page.evaluate('Array.from(document.images).every(i => i.getBoundingClientRect().width > 0 && i.getBoundingClientRect().right <= innerWidth)')
                print(engine.name, width, 'figures decoded and fit viewport')
                await page.close()
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
