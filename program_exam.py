"""Guided program papers built through the canonical AI/question/exam pipeline."""
from contextlib import closing
import json
import logging
import os
import time
from typing import Literal
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import Field, model_validator

from blueprint_api import audit, program_row
from blueprint_domain import Contract, canonical, content_hash
from blueprint_gemini import structured_call
from llm_generate import GenerationRequest, GeneratedQuestion, fingerprint, is_near_duplicate, validate_question, SYSTEM_PROMPT_VERSION
from platform_api import _auth, db, require_admin
from multimodal import statement_with_question_figures

router = APIRouter(prefix='/api/programs', tags=['Guided exams'])


class Section(Contract):
    subject: str = Field(min_length=1, max_length=200)
    count: int = Field(default=10, ge=1, le=200)
    marks: float = Field(default=1, gt=0, le=100, allow_inf_nan=False)
    negative_marks: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    topics: str = Field(default='', max_length=5000)
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)


class Settings(Contract):
    name: str = Field(default='', max_length=200)
    mode: Literal['FULL', 'SUBJECT'] = 'FULL'
    level: str = Field(default='', max_length=200)
    language: str = Field(default='English', min_length=1, max_length=100)
    duration_minutes: int = Field(default=60, ge=1, le=1440)
    difficulty: Literal['auto', 'very_easy', 'easy', 'medium', 'hard', 'very_hard'] = 'auto'
    assessment_kind: Literal['PRACTICE_TEST','ASSIGNMENT','GRAND_TEST','MOCK_EXAM'] = 'PRACTICE_TEST'
    curriculum: str = Field(default='', max_length=20000)
    pattern: str = Field(default='', max_length=10000)
    instructions: str = Field(default='', max_length=5000)
    generation_prompt: str = Field(default='', max_length=20000)
    additional_conditions: str = Field(default='', max_length=10000)
    sections: list[Section] = Field(default_factory=list, max_length=20)
    reuse_questions: bool = True
    official_lookup_id: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def quotas(self):
        if sum(s.count for s in self.sections) > 200:
            raise ValueError('A paper supports at most 200 questions')
        names = [s.subject.casefold() for s in self.sections]
        if len(set(names)) != len(names):
            raise ValueError('Use one section per subject')
        if self.mode == 'SUBJECT' and len(self.sections) > 1:
            raise ValueError('Subject-wise papers require exactly one subject')
        return self


def ready(settings):
    if not settings.sections or not settings.curriculum or not settings.generation_prompt:
        raise HTTPException(422, 'Add subjects, curriculum and a generation prompt before generating')


ASSESSMENT_LABELS={'PRACTICE_TEST':'Practice Test','ASSIGNMENT':'Assignment','GRAND_TEST':'Grand Test','MOCK_EXAM':'Mock Examination'}


def meaningful_exam_name(program_name: str, settings, created_at: float | None=None, paper_id: int | None=None) -> str:
    """Stable, readable default instead of repeating the bare Program name."""
    date=datetime.fromtimestamp(created_at or time.time()).strftime('%d %b %Y')
    kind=ASSESSMENT_LABELS[settings.assessment_kind]
    base=settings.name.strip() or program_name
    scope=(settings.sections[0].subject if settings.mode=='SUBJECT' and settings.sections else settings.level.strip() or 'All Subjects')
    parts=[base]
    for value in (scope,kind,date,f'Set {paper_id:02d}' if paper_id else ''):
        if value and value.casefold() not in base.casefold():parts.append(value)
    return ' · '.join(parts)[:200]


DIFFICULTIES=('very_easy','easy','medium','hard','very_hard')
SELECTED_DIFFICULTY_WEIGHTS={
    'very_easy':(.55,.27,.13,.05,0),
    'easy':(.18,.52,.21,.07,.02),
    'medium':(.07,.20,.46,.21,.06),
    'hard':(.02,.08,.22,.50,.18),
    'very_hard':(0,.05,.14,.27,.54),
}


def allocate_difficulties(count: int, weights) -> list[str]:
    raw=[count*weight for weight in weights];allocated=[int(value) for value in raw]
    for index in sorted(range(5),key=lambda i:(raw[i]-allocated[i],weights[i],-i),reverse=True)[:count-sum(allocated)]:
        allocated[index]+=1
    pool=[difficulty for difficulty,n in zip(DIFFICULTIES,allocated) for _ in range(n)]
    order=[]
    while pool:
        target=min(range(len(pool)),key=lambda i:abs(DIFFICULTIES.index(pool[i])-2)) if not order else max(range(len(pool)),key=lambda i:abs(DIFFICULTIES.index(pool[i])-DIFFICULTIES.index(order[-1])))
        order.append(pool.pop(target))
    return order


def difficulty_distribution(count: int, level: str, program_name: str = '') -> list[str]:
    """Create a reproducible, age-aware difficulty contract for one section.

    The model must execute this distribution; it never gets to relabel an
    unexpectedly easy or hard paper after authoring it.
    """
    text=f'{program_name} {level}'.casefold()
    roman={'iv':4,'v':5,'vi':6,'vii':7,'viii':8,'ix':9,'x':10,'xi':11,'xii':12}
    match=__import__('re').search(r'\b(?:class|grade)?\s*(\d{1,2}|iv|v|vi|vii|viii|ix|x|xi|xii)\b',text)
    grade=int(match.group(1)) if match and match.group(1).isdigit() else roman.get(match.group(1),0) if match else 0
    competitive=any(word in text for word in ('jee','neet','gate','cat','cgl','eapcet','entrance','olympiad'))
    if competitive: weights=(.05,.15,.35,.30,.15)
    elif grade and grade<=5: weights=(.20,.35,.35,.10,0)
    elif grade and grade<=8: weights=(.10,.25,.40,.20,.05)
    else: weights=(.05,.20,.40,.25,.10)
    return allocate_difficulties(count,weights)


def planned_difficulties(settings, section, program_name=''):
    return (difficulty_distribution(section.count,settings.level,program_name) if settings.difficulty=='auto'
            else allocate_difficulties(section.count,SELECTED_DIFFICULTY_WEIGHTS[settings.difficulty]))


class SavedSetupInput(Contract):
    settings: Settings
    revision: int = Field(default=0, ge=0)


@router.get('/papers/review-queue')
def review_queue(request: Request, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    require_admin(_auth(request))
    with closing(db()) as conn:
        where = " FROM program_exam_jobs j JOIN programs p ON p.id=j.program_id LEFT JOIN exams e ON e.id=j.exam_id WHERE p.status='ACTIVE' AND (j.status='REVIEW_REQUIRED' OR (j.status='DRAFT' AND e.status='DRAFT'))"
        total = conn.execute('SELECT COUNT(*) n'+where).fetchone()['n']
        rows = conn.execute('SELECT j.id,j.program_id,j.status,j.exam_id,j.input_json,p.name program_name'+where+' ORDER BY j.id DESC LIMIT ? OFFSET ?', (limit,offset)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            settings = json.loads(item.pop('input_json'))['settings']
            item.update(name=settings.get('name') or item['program_name'], mode=settings['mode'],
                        question_count=sum(s['count'] for s in settings['sections']), duration_minutes=settings['duration_minutes'],
                        subjects=[s['subject'] for s in settings['sections']])
            items.append(item)
        return {'items':items, 'total':total}


@router.get('/{pid}/exam-papers/{jid}')
def paper_detail(pid: int, jid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        row = conn.execute('SELECT * FROM program_exam_jobs WHERE program_id=? AND id=?', (pid,jid)).fetchone()
        if not row:
            raise HTTPException(404, 'Paper not found')
        return unpack(row)


@router.get('/{pid}/exam-setup')
def get_setup(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        row = conn.execute('SELECT * FROM program_exam_setups WHERE program_id=?', (pid,)).fetchone()
        return {'settings': json.loads(row['settings_json']), 'revision': row['revision'], 'updated_at': row['updated_at']} if row else None


@router.put('/{pid}/exam-setup')
def save_setup(pid: int, data: SavedSetupInput, request: Request):
    user = require_admin(_auth(request, True))
    ready(data.settings)
    if data.settings.official_lookup_id:
        from official_exam import reference
        reference(pid, data.settings.official_lookup_id)
    with closing(db()) as conn:
        program_row(conn, pid, True)
        conn.execute('UPDATE programs SET revision=revision WHERE id=?', (pid,))
        now = time.time()
        if data.revision == 0:
            changed = conn.execute('INSERT INTO program_exam_setups(program_id,settings_json,updated_by,updated_at) VALUES(?,?,?,?) ON CONFLICT(program_id) DO NOTHING RETURNING program_id',
                (pid, canonical(data.settings), user['id'], now)).fetchone() is not None
        else:
            changed = conn.execute('UPDATE program_exam_setups SET settings_json=?,revision=revision+1,updated_by=?,updated_at=? WHERE program_id=? AND revision=?',
                (canonical(data.settings), user['id'], now, pid, data.revision)).rowcount
        if not changed:
            raise HTTPException(409, 'This setup changed. Reopen the program before saving again.')
        audit(conn, user, pid, 'EXAM_SETUP_SAVED', pid)
        conn.commit()
        return {'settings': data.settings.model_dump(), 'revision': data.revision+1, 'updated_at': now}


def effective_prompt(program, settings):
    """All editable fields are frozen into the request sent to authoring."""
    difficulty_guidance = {
        'very_easy':'Familiar facts and direct recognition; one simple reasoning step.',
        'easy':'Routine applications with one or two straightforward steps.',
        'medium':'Combine concepts with moderate reasoning and plausible distractors.',
        'hard':'Multi-step reasoning and non-routine applications within the syllabus.',
        'very_hard':'Deep multi-step reasoning and subtle distinctions, remaining age-appropriate and within the syllabus.',
    }
    def cell(value):
        return str(value).replace('|', '/').replace('\n', ' ')
    total = sum(s.count for s in settings.sections)
    marks = sum(s.count*s.marks for s in settings.sections)
    title = meaningful_exam_name(program['name'],settings)
    lines = ['# Question paper generation prompt', '', f'## {title}', '',
        f'- **Program:** {program["name"]}',
        f'- **Paper type:** {"Full Exam" if settings.mode == "FULL" else "Subject-wise"}',
        f'- **Assessment category:** {ASSESSMENT_LABELS[settings.assessment_kind]}',
        f'- **Class / level:** {settings.level or "Use the program context"}',
        f'- **Language:** {settings.language}',
        f'- **Difficulty:** {settings.difficulty}',
        f'- **Duration:** {settings.duration_minutes} minutes',
        f'- **Total questions:** {total}', f'- **Total marks:** {marks:g}', '',
        '## Subject-wise pattern', '',
        '| Subject | Questions | Marks each | Section marks | Wrong-answer penalty | Section time |',
        '| --- | ---: | ---: | ---: | ---: | --- |']
    for section in settings.sections:
        section_time=f'{section.duration_minutes} minutes' if section.duration_minutes else 'Not specified'
        lines.append(f'| {cell(section.subject)} | {section.count} | {section.marks:g} | {section.count*section.marks:g} | {section.negative_marks:g} | {section_time} |')
    lines += ['', '## Difficulty distribution contract', '']
    for section in settings.sections:
        counts=Counter(planned_difficulties(settings,section,program['name']))
        lines.append(f'- **{section.subject}:** '+', '.join(f'{name.replace("_"," ")} {counts[name]}' for name in DIFFICULTIES if counts[name]))
    distribution_basis=('learner level and program type' if settings.difficulty=='auto' else f'the selected dominant level, {settings.difficulty.replace("_"," ")}')
    lines += ['', f'These exact counts are fixed by the application from {distribution_basis}. Author each slot at its assigned cognitive demand; do not relabel items after generation and do not let wording complexity substitute for reasoning difficulty.']
    lines += ['', 'Generate questions only for these subjects. The structured counts, marks, duration and selected difficulty take precedence over conflicting prose.',
              '', '### Subject topics and exclusions', '']
    lines += [f'- **{section.subject}:** {section.topics or "Follow the curriculum."}' for section in settings.sections]
    if settings.official_lookup_id:
        from official_exam import reference
        source = reference(program['id'], settings.official_lookup_id)
        lines += ['', '## Official source reference', '',
                  f'- **Exam cycle:** {source["official"]["exam_cycle"]}',
                  f'- **Checked:** {source["checked_at"]}']
        lines += [f'- [{entry["title"]}]({entry["url"]})' for entry in source['sources']]
        lines += [f'- **Evidence checksum ({index + 1}):** `{entry["sha256"]}`' for index,entry in enumerate(source['sources']) if entry.get('sha256')]
        if source.get('status_label'):lines += ['', source['status_label']]
        lines += ['', '**Grounding status: primary-source grounded.** The application retrieved the allow-listed official documents, verified quoted evidence against their contents, and froze the source checksums above. The sources describe the reference exam. Editable inputs above define this practice paper and may differ from the official full examination.']
    else:
        lines += ['', '## Evidence status', '',
                  '**Grounding status: administrator-authored practice configuration; no live official source is attached.**',
                  'Use only the frozen curriculum and pattern below. Do not claim exact official alignment, invent missing rules, or supplement curriculum gaps from model memory. A close-to-official difficulty claim requires an administrator-reviewed official lookup or sample/specification evidence.']
    lines += ['', '## Curriculum / syllabus', '', settings.curriculum,
              '', '## Exam pattern notes', '', settings.pattern,
              '', '## Student instructions', '', settings.instructions,
              '', '## Editable authoring instructions', '', settings.generation_prompt,
              '', '## Additional conditions supplied by the administrator', '', settings.additional_conditions or 'None specified.',
              '', 'Apply these additional conditions to every generated question unless they conflict with the structured paper settings, syllabus boundaries, output schema, or system safety requirements.',
              '', '## Difficulty guidance', '', difficulty_guidance.get(settings.difficulty,'Use the autonomous section distribution above. Calibrate each item to its assigned difficulty.'),
              '', '## Output requirements', '',
              '- Create original single-correct MCQs (`mcq_single`) with four distinct options A–D.',
              '- Supply one unambiguous correct answer and a worked solution for every question.',
              '- Treat official sources and the frozen curriculum as the authority hierarchy. Never fill a curriculum gap from memory while presenting it as official.',
              '- Make every question self-contained. State all facts, figures, constants, units and assumptions needed to answer it; do not rely on live news or web access.',
              '- Use realistic situations but never invent current statistics, official rules, citations, quotations, URLs or named-source claims.',
              '- Internally solve each item and verify the answer label against the solution before returning it. Reject ambiguous stems and choices where more than one answer is defensible.',
              '- Difficulty means cognitive demand and reasoning depth—not obscure vocabulary, missing information, needless calculation or trick wording.',
              '- Build distractors from different plausible misconceptions; avoid joke choices, giveaways, overlapping ranges and cosmetic variants.',
              '- Spread the paper across the applicable syllabus chapters and concepts; follow supplied coverage allocations and prioritize concepts not yet represented.',
              '- Avoid repeated reasoning tasks: changing only numbers, names or wording is not concept variety. A short paper is a syllabus sample, not exhaustive coverage.',
              '- Return the application question schema; leave questions pending review.',
              '- Put every mathematical expression wholly inside `\\( ... \\)` or `\\[ ... \\]` in a single field. Close all delimiters, braces, environments and `\\left`/`\\right` pairs; never emit partial LaTeX or empty operands.',
              '- This is an original practice paper, not an official examination paper.']
    return '\n'.join(lines)



class SuggestInput(Contract):
    field: Literal['all', 'curriculum', 'pattern', 'prompt']
    settings: Settings


class CurriculumSuggestion(Contract):
    curriculum: str = Field(min_length=1, max_length=20000)
    level: str = Field(default='', max_length=200)
    subjects: list[str] = Field(min_length=1, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class PatternSuggestion(Contract):
    pattern: str = Field(min_length=1, max_length=10000)
    duration_minutes: int = Field(ge=1, le=1440)
    sections: list[Section] = Field(min_length=1, max_length=20)
    instructions: str = Field(default='', max_length=5000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)


class PromptSuggestion(Contract):
    generation_prompt: str = Field(min_length=1, max_length=20000)


class CompleteSuggestion(PatternSuggestion):
    curriculum: str = Field(min_length=1, max_length=20000)
    level: str = Field(default='', max_length=200)
    generation_prompt: str = Field(min_length=1, max_length=20000)


@router.post('/{pid}/exam-assist')
def suggest(pid: int, data: SuggestInput, request: Request):
    require_admin(_auth(request, True))
    with closing(db()) as conn:
        program = program_row(conn, pid, True)
    schema = {'all': CompleteSuggestion, 'curriculum': CurriculumSuggestion, 'pattern': PatternSuggestion, 'prompt': PromptSuggestion}[data.field]
    instruction = (f'Propose only the requested {data.field} for this educational program. '
        'Use its name, level, language, full/subject mode and all supplied editable inputs. '
        'When all is requested, fill the complete setup and ready-to-use generation prompt together. '
        'Preserve a supplied class/level; otherwise suggest the likely class/level and disclose that assumption. '
        'For subject mode keep exactly the chosen subject; ask for no extra subjects. '
        'Curriculum should describe learning objectives, topics and exclusions. '
        'Pattern should have one section per subject, up to 200 questions total, positive marks, '
        'nonnegative penalties, duration and student instructions. Use single-correct four-option MCQs. '
        'Suggest a useful complete paper, not a tiny demonstration. Treat all pattern numbers '
        'as unverified suggestions; disclose assumptions and never invent official evidence. '
        'Prompt guidance should specify curriculum coverage, reasoning, distractor quality, '
        'difficulty, solutions and visual requirements. For auto difficulty describe cognitive progression without inventing percentages; the application fixes the final grade-aware counts. '
        'Require self-contained realistic contexts, explicit facts/units/assumptions, an internal solve-and-key check, and rejection of ambiguity or fabricated current claims. Do not generate questions now.')
    try:
        proposal, telemetry = structured_call('PROGRAM_SETUP', instruction,
            {'program': program['name'], 'settings': data.settings.model_dump()}, schema)
        if data.field in {'pattern','all'}:
            Settings.model_validate({**data.settings.model_dump(), **proposal.model_dump(exclude={'assumptions'})})
            if data.settings.mode == 'SUBJECT' and data.settings.sections and proposal.sections[0].subject.casefold() != data.settings.sections[0].subject.casefold():
                raise ValueError('Suggestion changed the selected subject')
        return {**proposal.model_dump(), 'model': telemetry['model']}
    except Exception as exc:
        raise HTTPException(502, 'AI suggestions could not be prepared. Retry or fill the fields manually.') from exc


@router.post('/{pid}/exam-prompt')
def preview(pid: int, data: Settings, request: Request):
    require_admin(_auth(request, True))
    with closing(db()) as conn:
        program = program_row(conn, pid, True)
    return {'effective_prompt': effective_prompt(program, data), 'question_count': sum(s.count for s in data.sections),
            'total_marks':sum(s.count*s.marks for s in data.sections)}


class BuildInput(Contract):
    request_key: str = Field(min_length=8, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    settings: Settings


def unpack(row):
    item = dict(row)
    item['input'] = json.loads(item.pop('input_json'))
    item['result'] = json.loads(item.pop('result_json'))
    return item


def schedule_build(tasks, jid):
    # Starlette waits for BackgroundTasks before completing the HTTP request.
    # In Cloud Run that kept a nominal 202 request open for the whole AI build
    # and exposed it to the request timeout. Production has always-allocated CPU,
    # so detach the resumable/checkpointed worker and return the job immediately.
    if os.getenv('APP_ENV') == 'test':
        tasks.add_task(run_build,jid)
    else:
        from threading import Thread
        Thread(target=run_build,args=(jid,),name=f'program-paper-{jid}',daemon=True).start()


@router.post('/{pid}/exam-papers', status_code=202)
def build(pid: int, data: BuildInput, request: Request, tasks: BackgroundTasks):
    user = require_admin(_auth(request, True))
    ready(data.settings)
    with closing(db()) as conn:
        program = program_row(conn, pid, True)
        conn.execute('UPDATE programs SET revision=revision WHERE id=?',(pid,))
        old = conn.execute('SELECT * FROM program_exam_jobs WHERE program_id=? AND request_key=?', (pid, data.request_key)).fetchone()
        if old:
            if json.loads(old['input_json'])['settings'] != data.settings.model_dump():
                raise HTTPException(409, 'This request key already belongs to different inputs')
            return unpack(old)
        for running in conn.execute("SELECT * FROM program_exam_jobs WHERE program_id=? AND status IN ('QUEUED','RUNNING') AND updated_at>? ORDER BY id DESC",(pid,time.time()-1800)):
            if json.loads(running['input_json'])['settings']==data.settings.model_dump():
                return unpack(running)
        frozen = {'settings': data.settings.model_dump(), 'program_name': program['name'],
                  'effective_prompt': effective_prompt(program, data.settings)}
        now = time.time()
        inserted = conn.execute('INSERT INTO program_exam_jobs(program_id,request_key,input_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(program_id,request_key) DO NOTHING',
            (pid, data.request_key, canonical(frozen), user['id'], now, now))
        row = conn.execute('SELECT * FROM program_exam_jobs WHERE program_id=? AND request_key=?', (pid, data.request_key)).fetchone()
        if row['input_json'] != canonical(frozen):
            raise HTTPException(409, 'This request key already belongs to different inputs')
        conn.commit()
        if inserted.rowcount:
            schedule_build(tasks,row['id'])
        return unpack(row)


@router.get('/{pid}/exam-papers')
def papers(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        return [unpack(r) for r in conn.execute('SELECT * FROM program_exam_jobs WHERE program_id=? ORDER BY id DESC LIMIT 30', (pid,))]


@router.post('/{pid}/exam-papers/{jid}/retry', status_code=202)
def retry(pid: int, jid: int, request: Request, tasks: BackgroundTasks):
    require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        changed = conn.execute("UPDATE program_exam_jobs SET status='QUEUED',error='',updated_at=? WHERE id=? AND program_id=? AND (status='FAILED' OR (status IN ('QUEUED','RUNNING') AND updated_at<?))",
            (time.time(), jid, pid, time.time()-1800))
        if not changed.rowcount:
            raise HTTPException(409, 'Only failed or interrupted generation can be retried')
        conn.commit()
    schedule_build(tasks,jid)
    return {'id': jid, 'status': 'QUEUED'}


def scope_hash(pid, settings, section):
    # Exact authoring context: free-text curriculum/prompt constraints must not be
    # silently ignored when retrieving old bank questions.
    return content_hash({'program_id': pid, 'subject': section.subject.casefold(),
        'level': settings.level, 'language': settings.language, 'curriculum': settings.curriculum,
        'topics': section.topics, 'difficulty': settings.difficulty, 'pattern': settings.pattern,
        'prompt': settings.generation_prompt, 'instructions': settings.instructions,
        'additional_conditions': settings.additional_conditions})


def question_scope(question):
    metadata=question.get('generation_metadata') or {}
    return metadata.get('program_exam_scope') or metadata.get('extra_metadata',{}).get('program_exam_scope')


def snapshot(question):
    result={k: question[k] for k in ('id', 'statement', 'options', 'answer', 'solution', 'subject', 'qtype', 'difficulty')}
    result['statement']=statement_with_question_figures(result['statement'],question.get('visual_assets',[]))
    return result


def run_build(jid):
    from app import generate_ai_questions_core, Question, FIELDS, values_of, row_to_dict
    with closing(db()) as conn:
        lease = time.time()
        if not conn.execute("UPDATE program_exam_jobs SET status='RUNNING',updated_at=? WHERE id=? AND status='QUEUED'", (lease, jid)).rowcount:
            return
        job = unpack(conn.execute('SELECT * FROM program_exam_jobs WHERE id=?', (jid,)).fetchone())
        conn.commit()
    settings = Settings.model_validate(job['input']['settings'])
    try:
        selected=job['result'].get('questions',[])
        pending=[Question.model_validate(item['question']) for item in selected if item.get('pending_index') is not None]
        seen={item.get('fingerprint') or fingerprint(item['question']['statement']) for item in selected}
        seen_statements=[item['question']['statement'] for item in selected]
        total=sum(section.count for section in settings.sections)
        def checkpoint(section_name):
            nonlocal lease
            result={'questions':selected,'reused':sum(item['origin']=='BANK' for item in selected),
                    'generated':sum(item['origin']=='GENERATED' for item in selected),
                    'progress':{'completed':len(selected),'total':total,'section':section_name}}
            with closing(db()) as conn:
                new_lease=time.time()
                if not conn.execute("UPDATE program_exam_jobs SET result_json=?,updated_at=? WHERE id=? AND status='RUNNING' AND updated_at=?",
                    (canonical(result),new_lease,jid,lease)).rowcount:
                    raise RuntimeError('Generation lease was replaced')
                conn.commit();lease=new_lease

        for section in settings.sections:
            scope = scope_hash(job['program_id'], settings, section)
            found = []
            existing_count=sum(item['section']['subject']==section.subject for item in selected)
            if existing_count==section.count:continue
            target_counts=Counter(planned_difficulties(settings,section,job['input']['program_name']))
            existing_difficulties=Counter(item['question'].get('difficulty') for item in selected if item['section']['subject']==section.subject)
            if settings.reuse_questions:
                with closing(db()) as conn:
                    rows = conn.execute("SELECT * FROM questions WHERE lower(subject)=lower(?) AND qtype='mcq_single' AND verification_status IN ('APPROVED','VERIFIED') ORDER BY id", (section.subject,))
                    for row in rows:
                        q = row_to_dict(row)
                        difficulty=q['difficulty'].casefold().replace(' ','_')
                        if (question_scope(q) != scope or difficulty not in target_counts
                                or existing_difficulties[difficulty]>=target_counts[difficulty]
                                or fingerprint(q['statement']) in seen
                                or is_near_duplicate(q['statement'],seen_statements)):
                            continue
                        found.append({'question': snapshot(q), 'section': section.model_dump(), 'origin': 'BANK','review_status':q['verification_status'],'fingerprint':q.get('generation_fingerprint') or fingerprint(q['statement'])})
                        existing_difficulties[difficulty]+=1
                        seen.add(fingerprint(q['statement']))
                        seen_statements.append(q['statement'])
                        if len(found) == section.count-existing_count:
                            break
            selected.extend(found)
            missing = section.count - existing_count - len(found)
            checkpoint(section.subject)
            stalled=0
            # Allow replacement batches for rejected/duplicate items while bounding cost.
            for attempt in range(max(3,section.count)):
                if not missing:
                    break
                while missing:
                    # Persist each normal provider-sized batch promptly instead
                    # of waiting for several internal calls before checkpointing.
                    batch_size=max(1,min(20,int(os.getenv('PROGRAM_EXAM_BATCH_SIZE','3'))))
                    current_counts=Counter(item['question'].get('difficulty') for item in selected if item['section']['subject']==section.subject)
                    desired=next(level for level in DIFFICULTIES if current_counts[level]<target_counts[level])
                    count = min(missing, batch_size,target_counts[desired]-current_counts[desired])
                    payload = GenerationRequest(exam_name=job['input']['program_name'], subject=section.subject,
                        level=settings.level, language=settings.language, count=count,
                        syllabus='See the frozen paper prompt below; section focus: '+section.topics,
                        difficulty=desired,
                        question_type='mcq_single', marks=str(section.marks),
                        extra_metadata={'program_id': job['program_id'], 'program_exam_scope': scope,'program_exam_job_id':jid},
                        generation_prompt=job['input']['effective_prompt'] + '\n\nCURRENT BATCH\n'
                        + f'Generate questions only for {section.subject}. Section topics: {section.topics}. '
                        + f'This batch fills section slots {section.count-missing+1}–{section.count-missing+count}. Use fresh scenarios and vary topic coverage. '
                        + "Use the current request's Question Count for this batch. The full paper quotas above are context; return only this batch.\nAvoid these existing stems:\n"
                        + '\n'.join(x['question']['statement'][:300] for x in selected[-20:])[-6000:])
                    batch=None
                    for transient_attempt in range(3):
                        try:
                            batch=generate_ai_questions_core(payload)
                            break
                        except HTTPException as exc:
                            if exc.status_code not in (422,429,500,502,503,504) or transient_attempt==2:raise
                            checkpoint(section.subject)
                            time.sleep(transient_attempt+1)
                    if batch is None:raise RuntimeError('Generation did not return a batch')
                    accepted = 0
                    for item in batch['questions']:
                        q = GeneratedQuestion.model_validate({k:v for k,v in item.items() if k not in {'review_index','fingerprint'}})
                        validate_question(q)
                        fp = fingerprint(q.statement)
                        if fp in seen or is_near_duplicate(q.statement,seen_statements) or len(q.options) != 4 or {o.label for o in q.options} != {'A','B','C','D'} or not q.solution.strip():
                            continue
                        if q.subject and q.subject.casefold() != section.subject.casefold():
                            continue
                        if q.qtype and q.qtype.casefold() != 'mcq_single':
                            continue
                        if q.difficulty and q.difficulty.casefold().replace(' ', '_') != desired:
                            continue
                        # Exam delivery renders canonical statement/options. Preserve
                        # the generated question figure there as well as in assets.
                        statement = q.statement
                        for asset in q.visual_assets:
                            if asset.get('type') != 'answer_figures' and asset.get('asset','').startswith('/uploads/') and asset['asset'] not in statement:
                                statement += '\n\n![Question figure](' + asset['asset'] + ')'
                        question = Question(subject=section.subject, chapter=q.chapter, topic=q.topic, subtopic=q.subtopic,
                            exam=job['input']['program_name'], qtype='mcq_single', difficulty=desired,
                            marks=str(section.marks), statement=statement, options=[o.text for o in sorted(q.options,key=lambda o:o.label)],
                            answer=q.answer, solution=q.solution, content_blocks=q.content_blocks, visual_assets=q.visual_assets,
                            verification_status='REVIEW_REQUIRED', source_type='AI_GENERATED', generation_run_id=batch['run_id'],
                            generation_provider='vertex-ai', generation_model=batch['model'], generation_prompt_version=SYSTEM_PROMPT_VERSION,
                            generation_prompt=payload.generation_prompt, generation_fingerprint=fp,
                            generation_metadata={'program_id': job['program_id'], 'program_exam_scope': scope,
                                'language':settings.language, 'level':settings.level, 'program_exam_job_id':jid, 'generated_metadata':q.metadata,
                                'precomputed_explanations':{'en':q.explanation_en,'te':q.explanation_te}})
                        pending.append(question)
                        selected.append({'question': {'id': None, **question.model_dump()}, 'section':section.model_dump(), 'origin':'GENERATED','review_status':'REVIEW_REQUIRED', 'pending_index':len(pending)-1,'fingerprint':fp})
                        seen.add(fp); missing -= 1; accepted += 1
                        seen_statements.append(q.statement)
                        if not missing:
                            break
                    checkpoint(section.subject)
                    stalled=stalled+1 if accepted==0 else 0
                    if stalled>=3:raise ValueError('No new valid questions after three batches')
                    if accepted < count:
                        break
            if missing:
                raise ValueError('The generator did not produce enough valid, distinct questions')
        with closing(db()) as conn:
            if not conn.execute("UPDATE program_exam_jobs SET status=status WHERE id=? AND status='RUNNING' AND updated_at=?", (jid, lease)).rowcount:
                return
            program_row(conn, job['program_id'], True)
            conn.execute('UPDATE programs SET revision=revision WHERE id=?',(job['program_id'],))
            run_counts = {}
            for item in selected:
                if item['origin'] == 'GENERATED':
                    q = pending[item.pop('pending_index')]
                    # Fingerprints are intentionally not globally unique: the same
                    # stem may exist under another program/prompt scope. Select a
                    # compatible saved copy instead of failing on whichever row the
                    # database happens to return first. If a compatible copy was
                    # corrected while generation ran, its current snapshot is the
                    # version the administrator reviews and approves.
                    candidates=[row_to_dict(row) for row in conn.execute('SELECT * FROM questions WHERE generation_fingerprint=? ORDER BY id DESC',(q.generation_fingerprint,)).fetchall()]
                    existing=next((candidate for candidate in candidates
                        if question_scope(candidate)==q.generation_metadata['program_exam_scope']
                        and candidate['verification_status'] in ('APPROVED','VERIFIED','REVIEW_REQUIRED')),None)
                    if existing:
                        item['question']=snapshot(existing)
                        continue
                    qid = conn.execute(f'INSERT INTO questions ({", ".join(FIELDS)}, created_at, updated_at) VALUES ({", ".join(["?"] * len(FIELDS))}, ?, ?)', values_of(q)+[time.time(),time.time()]).lastrowid
                    from app import cache_generated_explanations
                    prepared=q.generation_metadata.get('precomputed_explanations',{})
                    generated=GeneratedQuestion(statement=q.statement,answer=q.answer,solution=q.solution,explanation_en=prepared.get('en',''),explanation_te=prepared.get('te',''))
                    cache_generated_explanations(conn,qid,generated)
                    item['question'] = snapshot({'id':qid, **q.model_dump()})
                    run_counts[q.generation_run_id] = run_counts.get(q.generation_run_id,0)+1
            for run_id, count in run_counts.items():
                conn.execute("UPDATE ai_generation_runs SET accepted_count=accepted_count+?,status='SAVED_FOR_REVIEW' WHERE id=?",(count,run_id))
            result = {'questions':selected, 'reused':len(selected)-len(pending), 'generated':len(pending)}
            conn.execute("UPDATE program_exam_jobs SET status='REVIEW_REQUIRED',result_json=?,updated_at=? WHERE id=?", (canonical(result),time.time(),jid))
            audit(conn, {'id':job['created_by']}, job['program_id'], 'GUIDED_PAPER_READY', jid, {'generated':len(pending)})
            conn.commit()
    except Exception as exc:
        logging.getLogger(__name__).exception('Guided paper %s failed',jid)
        with closing(db()) as conn:
            complete=len(selected)==total
            message=(f'All {total} questions are preserved. Finalization for review was interrupted; retry finalization without regenerating questions. '
                     if complete else f'Generation paused with {len(selected)} of {total} questions preserved. Retry generation resumes the remaining questions. ')
            conn.execute("UPDATE program_exam_jobs SET status='FAILED',error=?,updated_at=? WHERE id=? AND status='RUNNING' AND updated_at=?",
                (message+f'No incomplete paper was published. ({type(exc).__name__})',time.time(),jid,lease))
            conn.commit()


class Approval(Contract):
    reviewed: Literal[True]
    publish: bool = False
    review_updated_at: float | None = None


class QuestionAction(Contract):
    action: Literal['APPROVE','PUBLISH','DELETE']


@router.post('/{pid}/exam-papers/{jid}/questions/{qid}')
def question_action(pid: int, jid: int, qid: int, data: QuestionAction, request: Request):
    user=require_admin(_auth(request,True))
    with closing(db()) as conn:
        program_row(conn,pid,True)
        conn.execute('UPDATE program_exam_jobs SET status=status WHERE id=? AND program_id=?',(jid,pid))
        row=conn.execute('SELECT * FROM program_exam_jobs WHERE id=? AND program_id=?',(jid,pid)).fetchone()
        if not row:raise HTTPException(404,'Paper not found')
        job=unpack(row)
        if job['status']!='REVIEW_REQUIRED' or job['exam_id']:
            raise HTTPException(409,'Question actions are available before the paper becomes an exam')
        item=next((entry for entry in job['result'].get('questions',[]) if int(entry['question'].get('id') or 0)==qid),None)
        if not item:raise HTTPException(404,'Question is not part of this paper')
        question=conn.execute('SELECT id,verification_status FROM questions WHERE id=?',(qid,)).fetchone()
        if not question:raise HTTPException(404,'Question not found')
        now=time.time()
        if data.action in {'APPROVE','PUBLISH'}:
            target='VERIFIED' if data.action=='PUBLISH' else 'APPROVED'
            conn.execute('UPDATE questions SET verification_status=?,updated_at=? WHERE id=?',(target,now,qid))
            item['review_status']=target
            job['result']['correction_review_required']=True
            conn.execute('UPDATE program_exam_jobs SET result_json=?,updated_at=? WHERE id=?',(canonical(job['result']),now,jid))
            audit(conn,user,pid,'GUIDED_QUESTION_'+data.action,jid,{'question_id':qid,'status':target})
            conn.commit();return {'question_id':qid,'status':target,'paper_status':'REVIEW_REQUIRED'}
        questions=job['result'].get('questions',[])
        job['result']['questions']=[entry for entry in questions if entry is not item]
        if item['origin']=='GENERATED':
            conn.execute("UPDATE questions SET verification_status='REJECTED',updated_at=? WHERE id=? AND verification_status IN ('REVIEW_REQUIRED','APPROVED','VERIFIED')",(now,qid))
        job['result']['progress']={'completed':len(job['result']['questions']),'total':sum(s['count'] for s in job['input']['settings']['sections']),'section':item['section']['subject']}
        message='Question removed from this paper. Retry generation to create a distinct replacement.'
        conn.execute("UPDATE program_exam_jobs SET status='FAILED',result_json=?,error=?,updated_at=? WHERE id=?",(canonical(job['result']),message,now,jid))
        audit(conn,user,pid,'GUIDED_QUESTION_DELETED',jid,{'question_id':qid,'origin':item['origin']})
        conn.commit();return {'question_id':qid,'status':'DELETED_FROM_PAPER','paper_status':'FAILED'}


@router.post('/{pid}/exam-papers/{jid}/approve')
def approve(pid: int, jid: int, data: Approval, request: Request):
    from app import row_to_dict
    from exam_conduct import publish_version, _snapshot
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        # Lock this row before reading its review state, on both database engines.
        conn.execute('UPDATE program_exam_jobs SET status=status WHERE id=? AND program_id=?', (jid,pid))
        row = conn.execute('SELECT * FROM program_exam_jobs WHERE id=? AND program_id=?', (jid,pid)).fetchone()
        if not row:
            raise HTTPException(404, 'Paper not found')
        job = unpack(row)
        if job['result'].get('correction_review_required') and data.review_updated_at != job['updated_at']:
            raise HTTPException(409, 'This paper was corrected. Reopen it and review the current questions before approving.')
        if job['exam_id']:
            if data.publish and job['status'] == 'DRAFT':
                current = conn.execute('SELECT * FROM exams WHERE id=?', (job['exam_id'],)).fetchone()
                if not current or current['status'] != 'DRAFT':
                    raise HTTPException(409, 'Exam was changed outside this paper; review it in Manage Exams')
                if content_hash({'exam':dict(current),'questions':_snapshot(conn,job['exam_id'])}) != job['result'].get('draft_hash'):
                    raise HTTPException(409, 'Draft changed after review; review and publish it in Manage Exams')
                if conn.execute("SELECT q.id FROM questions q JOIN exam_questions eq ON eq.question_id=q.id WHERE eq.exam_id=? AND q.verification_status NOT IN ('APPROVED','VERIFIED') LIMIT 1", (job['exam_id'],)).fetchone():
                    raise HTTPException(409, 'A question is no longer approved; review the paper again')
                conn.execute("UPDATE exams SET status='PUBLISHED',updated_at=? WHERE id=?", (time.time(),job['exam_id']))
                publish_version(conn,job['exam_id'],user['id'])
                conn.execute("UPDATE program_exam_jobs SET status='PUBLISHED' WHERE id=?", (jid,))
                audit(conn,user,pid,'GUIDED_PAPER_PUBLISHED',jid,{'exam_id':job['exam_id']})
                conn.commit()
                return {'exam_id':job['exam_id'], 'status':'PUBLISHED'}
            return {'exam_id':job['exam_id'], 'status':job['status']}
        if job['status'] != 'REVIEW_REQUIRED':
            raise HTTPException(409, 'A complete paper must be ready for review')
        settings = Settings.model_validate(job['input']['settings'])
        items = job['result']['questions']
        if len(items) != sum(s.count for s in settings.sections):
            raise HTTPException(409, 'Paper has incomplete sections')
        for item in items:
            q = conn.execute('SELECT * FROM questions WHERE id=?', (item['question']['id'],)).fetchone()
            allowed = {'APPROVED','VERIFIED'} if item['origin'] == 'BANK' else {'REVIEW_REQUIRED','APPROVED','VERIFIED'}
            if not q or snapshot(row_to_dict(q)) != item['question'] or q['verification_status'] not in allowed:
                raise HTTPException(409, 'A question changed after preview; generate a fresh paper before approval')
        status = 'PUBLISHED' if data.publish else 'DRAFT'
        name = meaningful_exam_name(job['input']['program_name'],settings,job['created_at'],jid)
        eid = conn.execute('INSERT INTO exams(name,description,exam_type,subject,level,instructions,duration_minutes,status,total_marks,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (name,settings.pattern,settings.mode,settings.sections[0].subject if settings.mode=='SUBJECT' else '',settings.level,settings.instructions,settings.duration_minutes,status,
             sum(s.count*s.marks for s in settings.sections),user['id'],time.time(),time.time())).lastrowid
        for order, item in enumerate(items,1):
            section, qid = item['section'], item['question']['id']
            conn.execute('INSERT INTO exam_questions(exam_id,question_id,display_order,section_name,marks,negative_marks,created_at) VALUES(?,?,?,?,?,?,?)',
                (eid,qid,order,section['subject'],section['marks'],section['negative_marks'],time.time()))
            if item['origin']=='GENERATED':
                conn.execute("UPDATE questions SET verification_status='APPROVED',updated_at=? WHERE id=? AND verification_status='REVIEW_REQUIRED'", (time.time(),qid))
                conn.execute("UPDATE ai_generation_runs SET status='SAVED' WHERE id=(SELECT generation_run_id FROM questions WHERE id=?) AND NOT EXISTS (SELECT 1 FROM questions WHERE generation_run_id=ai_generation_runs.id AND verification_status='REVIEW_REQUIRED')", (qid,))
        if data.publish:
            publish_version(conn,eid,user['id'])
        else:
            current = conn.execute('SELECT * FROM exams WHERE id=?', (eid,)).fetchone()
            job['result']['draft_hash'] = content_hash({'exam':dict(current),'questions':_snapshot(conn,eid)})
            conn.execute('UPDATE program_exam_jobs SET result_json=? WHERE id=?', (canonical(job['result']),jid))
        conn.execute('UPDATE program_exam_jobs SET status=?,exam_id=?,updated_at=? WHERE id=?', (status,eid,time.time(),jid))
        audit(conn,user,pid,'GUIDED_PAPER_'+status,jid,{'exam_id':eid})
        conn.commit()
        return {'exam_id':eid,'status':status}
