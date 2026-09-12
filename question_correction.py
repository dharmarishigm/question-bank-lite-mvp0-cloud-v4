"""Admin-reviewed question corrections; suggestions never persist themselves."""
from contextlib import closing
import json,logging,secrets,time
from typing import Literal
from fastapi import APIRouter,HTTPException,Request
from pydantic import Field,model_validator
from blueprint_domain import Contract
from blueprint_gemini import structured_call
from platform_api import _auth,require_admin
router=APIRouter(prefix='/api/admin/question-corrections')
class Content(Contract):
    statement:str=Field(min_length=1,max_length=30000)
    options:list[str]=Field(default_factory=list,max_length=26)
    answer:str=Field(default='',max_length=1000)
    solution:str=Field(default='',max_length=30000)
    @model_validator(mode='before')
    @classmethod
    def normalize_provider_content(cls,value):
        if not isinstance(value,dict):return value
        result=dict(value)
        for alias,target in (('question','statement'),('question_text','statement'),('correct_answer','answer'),('explanation','solution')):
            if target not in result and alias in result:result[target]=result[alias]
        options=[]
        raw=result.get('options') or []
        if isinstance(raw,dict):raw=list(raw.values())
        for option in raw:
            if isinstance(option,dict):option=option.get('text') or option.get('value') or option.get('content') or ''
            options.append(str(option))
        result['options']=options
        for key in ('statement','answer','solution'):
            if isinstance(result.get(key),dict):result[key]=str(result[key].get('text') or result[key].get('value') or result[key].get('content') or '')
            elif isinstance(result.get(key),list):result[key]='\n\n'.join(str(item) for item in result[key])
        return {key:result.get(key,'' if key!='options' else []) for key in cls.model_fields}
    @model_validator(mode='after')
    def valid(self):
        if not self.statement.strip():raise ValueError('Question text is required')
        if any(not o.strip() or len(o)>15000 for o in self.options):raise ValueError('Options must contain text and fit within 15000 characters')
        return self
class Suggestion(Contract):
    question:Content
    changes:list[str]=Field(default_factory=list,max_length=30)
    uncertainties:list[str]=Field(default_factory=list,max_length=30)
    @model_validator(mode='before')
    @classmethod
    def normalize_provider_shape(cls,value):
        if not isinstance(value,dict):return value
        result=dict(value)
        # Some valid Gemini responses flatten the question despite the response
        # schema, or omit optional review notes. Normalize only those safe shape
        # differences; Content still validates the actual replacement strictly.
        if 'question' not in result and 'statement' in result:
            result['question']={key:value for key,value in result.items() if key not in {'changes','uncertainties'}}
            result={key:value for key,value in result.items() if key in {'question','changes','uncertainties'}}
        for key in ('changes','uncertainties'):
            note=result.get(key,[])
            note=[note] if isinstance(note,(str,dict)) else (note or [])
            result[key]=[str(item.get('text') or item.get('change') or item.get('reason') or item.get('description') or '') if isinstance(item,dict) else str(item) for item in note]
        return result
class SuggestInput(Contract):
    mode:Literal['correct','regenerate','replace_from_paper']='correct'
    source_image:str=Field(default='',max_length=1000)
    question:Content
    instructions:str=Field(default='',max_length=3000)
    program_paper_id:int|None=None
    question_id:int|None=None
class SaveInput(Contract):
    question:Content
    original:Content
    reviewed:bool
    program_paper_id:int|None=None

def content(q):return Content.model_validate({k:q.get(k,'' if k!='options' else []) for k in Content.model_fields})

def paper_replacement_context(data):
    if not data.program_paper_id or not data.question_id:
        raise HTTPException(422,'Paper and question are required for a syllabus-based replacement')
    from app import connect
    with closing(connect()) as conn:
        job=conn.execute('SELECT id,status,input_json,result_json FROM program_exam_jobs WHERE id=?',(data.program_paper_id,)).fetchone()
    if not job:raise HTTPException(404,'Program paper not found')
    if job['status'] not in {'REVIEW_REQUIRED','DRAFT','PUBLISHED'}:raise HTTPException(409,'Paper is not ready for question replacement')
    frozen=json.loads(job['input_json'] or '{}');result=json.loads(job['result_json'] or '{}')
    item=next((i for i in result.get('questions',[]) if i.get('question',{}).get('id')==data.question_id),None)
    if not item:raise HTTPException(409,'Question is not part of this paper')
    settings=frozen.get('settings',{})
    return {
        'paper_id':job['id'],
        'effective_prompt':frozen.get('effective_prompt',''),
        'paper_settings':settings,
        'question_slot':item.get('section',{}),
        'other_question_stems':[i.get('question',{}).get('statement','')[:500] for i in result.get('questions',[]) if i is not item][:30],
    }

@router.post('/suggest')
def suggest(data:SuggestInput,request:Request):
    require_admin(_auth(request,True))
    replacement_context=paper_replacement_context(data) if data.mode=='replace_from_paper' else None
    parts=[]
    if data.source_image and data.mode!='replace_from_paper':
        from pathlib import Path
        from urllib.parse import urlsplit,unquote
        from app import UPLOAD_DIR
        from google.genai import types
        url=urlsplit(data.source_image);root=Path(UPLOAD_DIR).resolve()
        if not url.scheme and not url.netloc and url.path.startswith('/uploads/'):
            path=(root/unquote(url.path[len('/uploads/'):])).resolve()
            if path.is_relative_to(root) and path.is_file() and path.stat().st_size<=4*1024*1024:
                mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}.get(path.suffix.lower())
                if mime:parts=[types.Part.from_bytes(data=path.read_bytes(),mime_type=mime)]
    if data.mode=='replace_from_paper':
        prompt='Create a completely new, original replacement for this exact question-paper slot. Use the server-provided frozen paper prompt, syllabus, subject, topics, difficulty, language, exam pattern and section constraints as authoritative. Replace the stem, every option/distractor, answer and worked solution; do not merely paraphrase the old question. Preserve the option count and avoid duplicating other paper questions. Solve independently. Return the replacement, a concise change list and uncertainties for administrator review. Never assert guaranteed correctness.'
    else:
        prompt=(('Regenerate an original replacement question testing the same concept, subject, difficulty and language. Preserve the number and ordering of options. Supply a correct answer and worked solution. Do not reuse image references as evidence for newly invented visual details. ' if data.mode=='regenerate' else 'Review this existing question, not a new question. ')+ 'Correct transcription, Markdown/LaTeX, equations, wording, options, answer and worked solution only where justified. Preserve intent, difficulty, language, option ordering and image references. Do not invent missing visual evidence: use attached source pixels when present; otherwise only the transcribed text is available. Explicitly list uncertainties about unreadable or missing source information. Solve independently to check the answer. Return the corrected question, a concise change list and uncertainties for an administrator to review. Never assert guaranteed correctness.')
    request_payload={'mode':data.mode,'question':data.question.model_dump(),'instructions':data.instructions}
    if replacement_context:request_payload['paper_context']=replacement_context
    elif data.source_image:request_payload['source_image']=data.source_image
    reference=secrets.token_hex(6)
    try:
        proposal,meta=structured_call('QUESTION_CORRECTION',prompt,request_payload,Suggestion,image_parts=parts)
    except Exception as first:
        # Image parsing and strict structured responses can fail transiently even
        # when the text is usable. Make one bounded text-only recovery attempt;
        # suggestions still require explicit administrator review before saving.
        logging.getLogger(__name__).warning('AI correction first attempt failed reference=%s type=%s image=%s',reference,type(first).__name__,bool(parts))
        fallback={**request_payload,
                  "source_context":"Source pixels were unavailable in the recovery attempt; list any visual dependency as uncertain."}
        try:
            proposal,meta=structured_call('QUESTION_CORRECTION',prompt,fallback,Suggestion,image_parts=[])
            meta={**meta,'recovered_without_image':True,'reference':reference}
        except Exception as exc:
            logging.getLogger(__name__).exception('AI correction failed reference=%s type=%s',reference,type(exc).__name__)
            raise HTTPException(502,f'AI correction could not be completed. Your question has not changed; retry or edit manually. Reference: {reference}') from exc
    return {**proposal.model_dump(),'model':meta['model'],'saved':False}

@router.put('/{qid}')
def save(qid:int,data:SaveInput,request:Request):
    user=_auth(request,True);require_admin(user)
    if not data.reviewed:raise HTTPException(422,'Review the correction before updating')
    from app import connect,row_to_dict,Question,FIELDS,values_of,_snapshot
    from multimodal import build_content_blocks
    from llm_generate import fingerprint
    from program_exam import snapshot
    with closing(connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE questions SET updated_at=updated_at WHERE id=?',(qid,))
        row=conn.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone()
        if not row:raise HTTPException(404,'Question not found')
        old=row_to_dict(row)
        if content(old)!=data.original:raise HTTPException(409,'Question changed since you opened it. Reopen the editor before saving.')
        job=None;refresh_draft_hash=False
        if data.program_paper_id:
            conn.execute('UPDATE program_exam_jobs SET updated_at=updated_at WHERE id=?',(data.program_paper_id,))
            job=conn.execute('SELECT * FROM program_exam_jobs WHERE id=?',(data.program_paper_id,)).fetchone()
            if not job:raise HTTPException(404,'Program paper not found')
            result=json.loads(job['result_json'] or '{}')
            if not any(i['question']['id']==qid for i in result.get('questions',[])):raise HTTPException(409,'Question is not part of this paper')
            if job['status'] not in {'REVIEW_REQUIRED','DRAFT','PUBLISHED'}:raise HTTPException(409,'Paper is not ready for correction')
        from correction_sync import prepare,propagate
        plans=prepare(conn,qid)
        q=Question.model_validate({**old,**data.question.model_dump()})
        if q.qtype=='mcq_single' and (len(q.options)<2 or q.answer.strip().upper() not in list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'[:len(q.options)])):raise HTTPException(422,'Choose a valid correct option for this multiple-choice question')
        q.content_blocks=build_content_blocks(q.statement,q.visual_assets)
        if q.source_type=='AI_GENERATED':q.generation_fingerprint=fingerprint(q.statement)
        q.verification_status='APPROVED'
        _snapshot(conn,qid,'admin reviewed correction')
        conn.execute('UPDATE questions SET '+', '.join(f'{f}=?' for f in FIELDS)+', updated_at=? WHERE id=?',values_of(q)+[time.time(),qid])
        for table in ['question_explanations','question_explanation_translations']:conn.execute(f'DELETE FROM {table} WHERE question_id=?',(qid,))
        updated=row_to_dict(conn.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone())
        propagate(conn,old,updated,user['id'],plans)
        from exam_conduct import audit
        audit(conn,'QUESTION_CORRECTED',user_id=user['id'],metadata={'question_id':qid,'program_paper_id':data.program_paper_id})
        conn.commit()
    return updated
