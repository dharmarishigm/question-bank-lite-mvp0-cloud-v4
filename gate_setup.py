"""GATE EC setup: published rules and explicit, editable MCQ allocations."""
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import requests


def is_ece(program):
    name=' '.join(str(program.get(k,'')) for k in ('code','name')).replace('_',' ')
    return bool(re.search(r'\bGATE\b',name,re.I) and re.search(r'\bEC(?:E)?\b|electronics.*communication',name,re.I))


def lookup(settings):
    from official_exam import fetch_document, normalized
    from program_exam import Settings
    preset=json.loads((Path(__file__).parent/'program_presets/gate_ece.json').read_text())
    values=preset['settings'];values.update(difficulty=settings.difficulty,language=settings.language,reuse_questions=settings.reuse_questions)
    sources=[{'url':url,'title':'GATE 2027 EC official reference'} for url in preset['sources']]
    checked=preset['checked_at'];live=False
    # Never disable certificate validation or weaken TLS to retrieve an authority page.
    # The dated reviewed setup remains usable when the authority cannot be read.
    try:
        pattern=fetch_document(sources[0]['url']);syllabus=fetch_document(sources[1]['url'])
        text=normalized(pattern['text'])
        required=['65','100','180','general aptitude','13','72','1/3','2/3']
        # Check the precise supported pattern before using the reviewed allocation.
        if any(normalized(token) not in text for token in required) or not re.search(r'10\s*general aptitude.*55\s*subject.*65',text):
            raise ValueError('Published GATE pattern has changed; review the new rules')
        if '2027' not in pattern['text'] or 'Electronics and Communication Engineering' not in syllabus['text']:
            raise ValueError('The retrieved syllabus does not match GATE 2027 EC')
        sources[0]['sha256']=pattern['sha256'];sources[1]['sha256']=syllabus['sha256']
        checked=datetime.now(timezone.utc).isoformat();live=True
        # Populate current syllabus text directly; no model guessing or schema mismatch.
        values['curriculum']='## Official EC syllabus text\n\n'+syllabus['text'][:18000]
    except (requests.RequestException,OSError):
        pass
    except ValueError as exc:
        # A readable but changed pattern must not be silently labelled current.
        return reviewed_result(values,sources,checked,False,str(exc))
    return reviewed_result(values,sources,checked,live)


def reviewed_result(values,sources,checked,live,reason=''):
    from program_exam import Settings
    Settings.model_validate(values)
    note=('Official pattern and EC syllabus retrieved live. Review the editable MCQ practice allocation.' if live else
          'Live verification was unavailable. Loaded the reviewed GATE 2027 EC reference checked on 10 September 2026. Confirm the linked official rules before publication.')
    if reason:note+=' '+reason
    return {'settings':values,'official':{'exam_name':'GATE Electronics and Communication Engineering','exam_cycle':'2027 EC','exam_year':2027,
        'total_questions':65,'total_marks':100,'duration_minutes':180,'negative_marks':None,
        'sections':[{'subject':'General Aptitude','count':10,'total_marks':15,'duration_minutes':None},
                    {'subject':'EC including Engineering Mathematics','count':55,'total_marks':85,'duration_minutes':None}]},
        'sources':sources,'checked_at':checked,'live_verified':live,'search_html':'','queries':[],
        'status_label':note,'assumptions':[note,'Chapter counts and 1-/2-mark bands are editable practice allocations. Official MCQ penalties vary by marks; MSQ/NAT have no negative marking. The app generates single-correct MCQs.']}
