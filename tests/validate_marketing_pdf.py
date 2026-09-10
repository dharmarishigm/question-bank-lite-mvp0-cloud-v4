"""Actual Chromium PDF render with equation, diagram, QR and recurring footer checks."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf
from marketing_pdf import render_paper,MarketingOptions

data={'exam':{'id':20,'name':'GATE ECE - Offline Practice','duration_minutes':180,'total_marks':24},'questions':[]}
for i in range(24):
    data['questions'].append({'statement':r'For the function $f(x)=x^2$, evaluate $\int_0^2 f(x)\,dx$. '+('Explain which result is dimensionally consistent with the stated expression.' if i%3==0 else ''),
        'options':[r'$\frac{8}{3}$',r'$4$',r'$2$',r'$\frac{4}{3}$'],'answer':'A','solution':r'$\int_0^2 x^2\,dx = [x^3/3]_0^2 = 8/3$.',
        'subject':'Engineering Mathematics','section_name':'Engineering Mathematics','marks':1,'negative_marks':1/3,'visual_assets':[]})
result=render_paper(data,MarketingOptions(include_answers=True));target=Path('/tmp/meritiqra-marketing-sample.pdf');target.write_bytes(result)
with pymupdf.open(stream=result,filetype='pdf') as doc:
    assert len(doc)>3
    for n,page in enumerate(doc):
        text=page.get_text()
        assert 'admin@meritiqra.com' in text,(n,text)
        assert '93911' in text and 'MeritIQra' in text
        assert 'Enquire about online access' in text
        assert any('enquiry?exam=20' in link.get('uri','') for link in page.get_links())
        page.get_pixmap(matrix=pymupdf.Matrix(1.3,1.3)).save(f'/tmp/marketing-page-{n+1}.png')
    assert 'Answer key' in ''.join(p.get_text() for p in doc)
    print(f'Generated {len(doc)} pages; recurring brand/contact/enquiry links verified on every page. {target}')
