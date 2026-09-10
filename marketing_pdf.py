"""Offline branded question paper, rendered with the app's Markdown/KaTeX helpers."""
from contextlib import closing
from pathlib import Path
from html import escape
from urllib.parse import urlsplit
import base64,json,mimetypes,re,threading,subprocess,sys,tempfile,logging,os,signal,hashlib
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import Response
from pydantic import Field
from blueprint_domain import Contract
from platform_api import _auth,require_admin

router=APIRouter(prefix='/api/admin/exams',tags=['Offline marketing papers'])
ROOT=Path(__file__).parent
LOCK=threading.BoundedSemaphore(1)

class MarketingOptions(Contract):
    contact:str=Field(default='+91 93911 03630 | admin@meritiqra.com',min_length=3,max_length=160)
    benefits:str=Field(default='Practise your syllabus. Understand mistakes with AI explanations. Track subject-wise progress.',min_length=10,max_length=220)
    include_answers:bool=False

def qr_image(url):
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderSVG
    widget=QrCodeWidget(url,barLevel='M');x,y,w,h=widget.getBounds();drawing=Drawing(100,100,transform=[100/w,0,0,100/h,0,0]);drawing.add(widget)
    return 'data:image/svg+xml;base64,'+base64.b64encode(renderSVG.drawToString(drawing).encode()).decode()

def _render_paper(data,options):
    from playwright.sync_api import sync_playwright
    import app
    exam=data['exam'];questions=data['questions'];link=f'https://meritiqra.com/enquiry?exam={exam["id"]}&interest=EXAMS'
    if not questions:raise HTTPException(422,'Add questions to the exam before exporting')
    if len(questions)>200:raise HTTPException(422,'Export up to 200 questions per paper')
    # Reuse the existing renderer, stopping before the interactive editor functions.
    renderer=(ROOT/'static/app.js').read_text().split('\nfunction formValue()')[0]
    katex=(ROOT/'static/vendor/katex.min.js').read_text();autorender=(ROOT/'static/vendor/contrib/auto-render.min.js').read_text()
    css=(ROOT/'static/vendor/katex.min.css').read_text()
    logo='data:image/png;base64,'+base64.b64encode((ROOT/'static/meritiqra-logo.png').read_bytes()).decode()
    footer=f'''<div style="font-family:Arial,sans-serif;font-size:11px;width:100%;margin:0 55px;color:#164b50;border-top:2px solid #148174;padding-top:8px;display:flex;align-items:center;gap:12px"><img src="{qr_image(link)}" style="width:92px;height:92px"><div style="flex:1"><strong style="font-size:13px">Build confidence for your competitive goals with MeritIQra</strong><div style="margin:5px 0">{escape(options.benefits)}</div><div>Contact us: {escape(options.contact)} | <a href="https://meritiqra.com">meritiqra.com</a></div><div><a href="{link}">Enquire about online access and subscriptions</a> | <a href="https://meritiqra.com/app">Sign in / Register</a></div><div style="margin-top:4px">Scan the QR to enquire. Online practice · meritiqra.com</div></div></div>'''
    header=f'<div style="width:100%;margin:0 55px;font:10px Arial;color:#184855;display:flex;align-items:center;gap:10px"><img src="{logo}" style="height:32px;width:32px;object-fit:contain"><strong style="font-size:18px">MeritIQra</strong><span>Practice. Understand. Progress.</span></div>'
    payload=json.dumps({'exam':exam,'questions':questions,'answers':options.include_answers,'offset':data.get('offset',0),'total':data.get('total',len(questions))}).replace('<','\\u003c')
    html='''<!doctype html><html><head><meta charset="utf-8"><style>'''+css+'''
    body{font:10pt/1.35 Arial,sans-serif;color:#172f3d;margin:0}h1{font-size:24pt;line-height:1.2;margin:0 0 10px}h2{font-size:14pt;color:#146b63}p{margin:5px 0}.summary{padding:12px;background:#edf6f3;border-radius:8px;margin:12px 0 20px}.question{break-inside:auto;margin:0 0 12px}.question-heading{font-weight:bold;color:#17645f;margin:0 0 6px}.options{margin:6px 0;padding-left:20px;display:grid;grid-template-columns:1fr 1fr;gap:4px 24px}.options li{padding:2px 0 2px 4px;break-inside:avoid}.options p{margin:0}.question-heading{break-after:avoid}img{max-width:100%;max-height:400px;object-fit:contain}.inline-formula{max-height:120px;vertical-align:middle}.question table{border-collapse:collapse;width:100%;font-size:10pt}.question th,.question td{border:1px solid #bfcfd4;padding:5px}.katex-display{overflow:visible;font-size:1em}.answer-key{break-before:page}.question-heading small{font-weight:normal}.instructions{font-size:10pt;color:#48616c;margin:10px 0 20px}
    </style></head><body><main id="paper"></main><script>'''+renderer+'</script><script>'+katex+'</script><script>'+autorender+'''</script><script>
    const data='''+payload+''';const host=document.getElementById('paper');
    host.innerHTML=`<h1>${escapeHtml(data.exam.name)}</h1><div class="summary">${data.total} questions · ${data.exam.duration_minutes} minutes · ${data.exam.total_marks} marks<br>Name: ________________________ &nbsp; Date: ______________</div><p class="instructions">Answer each question using the options provided. Marks and wrong-answer penalties are shown per question. This is an offline practice paper. Register online to access guided practice and progress reports.</p>`;
    data.questions.forEach((q,i)=>{const article=document.createElement('article');article.className='question';article.innerHTML=`<div class="question-heading">Question ${data.offset+i+1} <small>· ${escapeHtml(q.section_name||q.subject||'')} · ${q.marks} mark(s) · wrong answer: −${Number((q.negative_marks||0).toFixed(4))}</small></div><div>${toHtml(q.statement)}</div>${(q.visual_assets||[]).map(a=>safeUrl(a.asset)?`<figure><img src="${safeUrl(a.asset)}" alt="${escapeHtml(a.description||'Question diagram')}"></figure>`:'').join('')}<ol class="options" type="A">${(q.options||[]).map(o=>`<li>${toHtml(typeof o==='string'?o:o.text||'')}</li>`).join('')}</ol>`;host.append(article);typeset(article);});
    if(data.answers){const section=document.createElement('section');section.className='answer-key';section.innerHTML='<h1>Answer key</h1><p>Administrator edition - keep separate from the question paper.</p>';data.questions.forEach((q,i)=>{const a=document.createElement('article');a.className='question';a.innerHTML=`<h2>${data.offset+i+1}. ${escapeHtml(q.answer||'')}</h2>${toHtml(q.solution||'')}`;section.append(a);typeset(a);});host.append(section);}
    document.querySelectorAll('img').forEach(i=>i.loading='eager');
    </script></body></html>'''
    failures=[]
    def resource(route):
        url=route.request.url;path=urlsplit(url).path;target=None
        if re.fullmatch(r'/uploads/[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)',path,re.I):target=Path(app.UPLOAD_DIR)/path.rsplit('/',1)[1]
        elif url.startswith('https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/fonts/') and path.endswith('.woff2'):target=ROOT/'static/vendor/pdf-fonts'/path.rsplit('/',1)[1]
        if target and target.is_file():route.fulfill(body=target.read_bytes(),content_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        else:
            if route.request.resource_type=='image':failures.append('A question image is unavailable for offline export')
            route.abort()
    with sync_playwright() as p:
        browser=p.chromium.launch(timeout=30000,args=['--disable-dev-shm-usage']+(['--no-zygote','--single-process'] if sys.platform=='linux' else []))
        try:
            page=browser.new_page();page.set_default_timeout(60000);page.route('**/*',resource)
            script_errors=[];page.on('pageerror',lambda error:script_errors.append(str(error)))
            logging.getLogger(__name__).warning('Offline PDF: loading %s questions',len(questions));page.goto('about:blank');page.set_content(html.replace('<head>','<head><base href="https://pdf.local/">'),wait_until='networkidle')
            logging.getLogger(__name__).warning('Offline PDF: content loaded');page.evaluate('document.fonts.ready');page.wait_for_function('Array.from(document.images).every(i=>i.complete)')
            if script_errors or page.locator('#paper > article.question').count()!=len(questions):raise HTTPException(422,'Question content could not be rendered completely. Review the exam preview before exporting.')
            if failures or page.locator('img').evaluate_all('(images)=>images.some(i=>!i.naturalWidth)'):raise HTTPException(422,'One or more question images could not be rendered. Correct those images before exporting.')
            if page.locator('.katex-error').count():raise HTTPException(422,'An equation needs correction before offline export. Review the exam preview.')
            logging.getLogger(__name__).warning('Offline PDF: printing');return page.pdf(tagged=False,outline=False,format='A4',print_background=True,display_header_footer=True,header_template=header,footer_template=footer,margin={'top':'25mm','bottom':'42mm','left':'16mm','right':'16mm'},prefer_css_page_size=True)
        finally:browser.close()

def render_paper(data,options):
    import pymupdf
    questions=data['questions']
    if not questions or len(questions)>200:raise HTTPException(422,'Export requires 1 to 200 questions')
    # Bound each Chromium print layout, then join complete pages without losing content.
    merged=pymupdf.open()
    for offset in range(0,len(questions),20):
        part={**data,'questions':questions[offset:offset+20],'offset':offset,'total':len(questions)}
        with pymupdf.open(stream=_render_paper(part,options),filetype='pdf') as chunk:merged.insert_pdf(chunk,links=True)
    for index,page in enumerate(merged):
        page.draw_rect(pymupdf.Rect(10,10,page.rect.width-10,page.rect.height-8),color=(.12,.38,.40),width=.6)
        page.insert_text((page.rect.width-110,page.rect.height-12),f'Page {index+1} of {len(merged)}',fontsize=8,color=(.1,.3,.3))
    result=merged.tobytes(garbage=4,deflate=True);merged.close();return result

def _paper_cache_key(data,options):
    # Stable JSON ordering makes identical exam content and branding share one
    # immutable PDF object across requests and Cloud Run instances.
    raw=json.dumps({'template':'dense-bordered-v2','data':data,'options':options.model_dump()},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    return 'exam-pdf-cache/'+hashlib.sha256(raw).hexdigest()+'.pdf'

def _cached_pdf(key):
    try:
        from flag_api import read_bytes
        return read_bytes(os.getenv('GCS_DATA_BUCKET',''),os.getenv('FLAG_LOCAL_DIR','/tmp/meritiqra-flag-development'),key)
    except Exception:return None

def _save_cached_pdf(key,pdf):
    try:
        from flag_api import store_bytes
        store_bytes(key,pdf)
    except Exception:
        pass


@router.post('/{exam_id}/marketing-pdf')
def export(exam_id:int,options:MarketingOptions,request:Request):
    user=require_admin(_auth(request,True))
    from engagement import rate
    rate('marketing-pdf:'+str(user['id']),20)
    if not LOCK.acquire(blocking=False):raise HTTPException(429,'An offline PDF is being prepared. Retry shortly.')
    try:
        from exam_conduct import durable_exam_paper
        data=durable_exam_paper(exam_id,request)
        cache_key=_paper_cache_key(data,options)
        cached=_cached_pdf(cache_key)
        if cached:
            return Response(cached,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="meritiqra-exam-{exam_id}.pdf"','X-Paper-Cache':'HIT'})
        with tempfile.TemporaryDirectory(prefix='offline-paper-') as folder:
            source=Path(folder)/'input.json';output=Path(folder)/'paper.pdf'
            source.write_text(json.dumps({'data':data,'options':options.model_dump()}))
            try:
                job=subprocess.Popen([sys.executable,str(ROOT/'marketing_pdf.py'),str(source),str(output)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
                stdout,stderr=job.communicate(timeout=180)
            except subprocess.TimeoutExpired as exc:
                os.killpg(job.pid,signal.SIGKILL);job.communicate()
                raise HTTPException(504,'PDF preparation timed out. Please retry; the export slot has been released.') from exc
            if job.returncode or not output.exists():
                logging.getLogger(__name__).error('Offline PDF worker failed: %s',stderr.decode(errors='replace')[-2500:])
                raise HTTPException(422,'The paper could not be rendered. Check question images and equations in exam preview, then retry.')
            pdf=output.read_bytes()
        _save_cached_pdf(cache_key,pdf)
        return Response(pdf,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="meritiqra-exam-{exam_id}.pdf"'})
    finally:LOCK.release()

if __name__=='__main__':
    payload=json.loads(Path(sys.argv[1]).read_text())
    Path(sys.argv[2]).write_bytes(render_paper(payload['data'],MarketingOptions(**payload['options'])))
