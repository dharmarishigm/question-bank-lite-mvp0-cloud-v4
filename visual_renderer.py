"""Deterministic, safe SVG rendering for Gemini visual reasoning specifications."""
from html import escape
from pathlib import Path
import hashlib,json

def _n(value,default=0):
    try:return max(0,min(400,float(value)))
    except:return default

def _primitive(p):
    kind=str(p.get('type') or p.get('kind') or '').upper();stroke='black';fill={'DARK':'black','LIGHT':'#d7dce2'}.get(str(p.get('fill','')).upper(),'none');w=max(1,min(8,_n(p.get('stroke_width'),2)))
    if kind in {'RECTANGLE','RECT','SQUARE'}:return f'<rect x="{_n(p.get("x"))}" y="{_n(p.get("y"))}" width="{_n(p.get("width"),40)}" height="{_n(p.get("height"),40)}" fill="{fill}" stroke="{stroke}" stroke-width="{w}"/>'
    if kind in {'CIRCLE','DOT'}:return f'<circle cx="{_n(p.get("cx",p.get("x")))}" cy="{_n(p.get("cy",p.get("y")))}" r="{_n(p.get("r"),5 if kind=="DOT" else 20)}" fill="{"black" if kind=="DOT" else fill}" stroke="{stroke}" stroke-width="{w}"/>'
    if kind=='LINE':return f'<line x1="{_n(p.get("x1"))}" y1="{_n(p.get("y1"))}" x2="{_n(p.get("x2"))}" y2="{_n(p.get("y2"))}" stroke="{stroke}" stroke-width="{w}"/>'
    points=p.get('points') or []
    if kind in {'POLYGON','POLYLINE','TRIANGLE'} and isinstance(points,list):
        pts=' '.join(f'{_n(x[0])},{_n(x[1])}' for x in points if isinstance(x,list) and len(x)>=2);return f'<{kind.lower() if kind!="TRIANGLE" else "polygon"} points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{w}"/>'
    if kind=='TEXT_SYMBOL':return f'<text x="{_n(p.get("x"))}" y="{_n(p.get("y"))}" font-size="{_n(p.get("size"),24)}">{escape(str(p.get("text",p.get("value",""))))}</text>'
    return ''

def render_visual_spec(spec,output_dir):
    panels=[('Question',spec.get('question_figure') or {})]+[(k,(spec.get('options') or {}).get(k) or {}) for k in 'ABCD']
    cells=[]
    for i,(label,panel) in enumerate(panels):
        x=(i%3)*220;y=(i//3)*240;shapes=''.join(_primitive(p) for p in panel.get('primitives',[]) if isinstance(p,dict));cells.append(f'<g transform="translate({x},{y})"><text x="100" y="18" text-anchor="middle" font-weight="bold">{label}</text><rect x="10" y="28" width="190" height="190" fill="white" stroke="#94a3b8"/><g transform="translate(10,28) scale(.475)">{shapes}</g></g>')
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="660" height="480" viewBox="0 0 660 480"><rect width="100%" height="100%" fill="white"/>{"".join(cells)}</svg>'
    name='generated-visual-'+hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:16]+'.svg';Path(output_dir).mkdir(parents=True,exist_ok=True);(Path(output_dir)/name).write_text(svg);return '/uploads/'+name

def render_visual_panels(spec,output_dir):
    """Render question and options separately so MCQ options remain durable images."""
    panels={'question':spec.get('question_figure') or {}}
    panels.update({key:(spec.get('options') or {}).get(key) or {} for key in 'ABCD'})
    digest=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:16];result={}
    Path(output_dir).mkdir(parents=True,exist_ok=True)
    for label,panel in panels.items():
        shapes=''.join(_primitive(p) for p in panel.get('primitives',[]) if isinstance(p,dict))
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400"><rect width="100%" height="100%" fill="white"/>{shapes}</svg>'
        name=f'generated-visual-{digest}-{label.lower()}.svg';(Path(output_dir)/name).write_text(svg);result[label]='/uploads/'+name
    return result
