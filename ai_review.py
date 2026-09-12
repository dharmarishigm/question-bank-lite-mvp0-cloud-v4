"""Review multiple generated batches and save their selected questions atomically."""
from contextlib import closing
import json
import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from blueprint_domain import Contract
from platform_api import _auth, require_admin
from llm_generate import GenerationRequest, GeneratedQuestion, validate_question, fingerprint, SYSTEM_PROMPT_VERSION

router=APIRouter(prefix='/api/ai/review')
INTERNAL={'review_index','fingerprint','saved_question_id'}

class BatchSelection(Contract):
    run_id:str=Field(min_length=1,max_length=100)
    indices:list[int]=Field(min_length=1,max_length=200)

class SaveSelection(Contract):
    batches:list[BatchSelection]=Field(min_length=1,max_length=20)
    reviewed:bool
    @model_validator(mode='after')
    def valid(self):
        if not self.reviewed:raise ValueError('Review the selected questions before saving')
        if len({b.run_id for b in self.batches})!=len(self.batches):raise ValueError('Select each batch once')
        if sum(len(b.indices) for b in self.batches)>500:raise ValueError('Save up to 500 questions at a time')
        if any(len(set(b.indices))!=len(b.indices) or any(i<0 for i in b.indices) for b in self.batches):raise ValueError('Invalid question selection')
        return self


def question_payload(row,item):
    from app import Question
    req=GenerationRequest.model_validate_json(row['request_json'])
    generated=GeneratedQuestion.model_validate({k:v for k,v in item.items() if k not in INTERNAL});validate_question(generated)
    metadata=json.loads(row['metadata_json'] or '{}')
    return Question(subject=generated.subject or req.subject,chapter=generated.chapter or req.chapter,topic=generated.topic or req.topic,subtopic=generated.subtopic or req.subtopic,exam=generated.exam or req.exam_name,qtype=generated.qtype or req.question_type,difficulty=generated.difficulty or req.difficulty,marks=generated.marks or req.marks,statement=generated.statement,options=[o.text for o in generated.options],answer=generated.answer,solution=generated.solution,tags=', '.join(generated.tags or req.tags),content_blocks=generated.content_blocks,visual_assets=generated.visual_assets,verification_status='APPROVED',source_type='AI_GENERATED',generation_run_id=row['id'],generation_provider='vertex-ai',generation_model=row['model'],generation_prompt_version=row['system_prompt_version'] or SYSTEM_PROMPT_VERSION,generation_prompt=req.generation_prompt,generation_metadata={**metadata,'generated_metadata':generated.metadata,'approved_during_admin_review':True},generation_fingerprint=fingerprint(generated.statement))


def save_batches(data):
    from app import connect,FIELDS,values_of,cache_generated_explanations
    results=[];saved=0
    with closing(connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        pending=[]
        # Lock runs in stable order; retries of the same selections are idempotent.
        for batch in sorted(data.batches,key=lambda b:b.run_id):
            conn.execute('UPDATE ai_generation_runs SET accepted_count=accepted_count WHERE id=?',(batch.run_id,))
            row=conn.execute('SELECT * FROM ai_generation_runs WHERE id=?',(batch.run_id,)).fetchone()
            if not row:raise HTTPException(404,'Generation batch not found')
            if row['status'] not in {'REVIEW_REQUIRED','SAVED'}:raise HTTPException(409,'Only completed batches can be reviewed')
            output=json.loads(row['output_json'] or '{}');items=output.get('questions',[])
            if any(i>=len(items) for i in batch.indices):raise HTTPException(422,'A selected question no longer exists')
            for i in batch.indices:
                try:question=question_payload(row,items[i])
                except Exception as exc:raise HTTPException(422,f'Batch {batch.run_id}, question {i+1} needs correction before saving') from exc
                pending.append((row,output,i,question))
        outputs={};counts={}
        for row,output,index,q in pending:
            saved_id=output['questions'][index].get('saved_question_id')
            duplicate=conn.execute('SELECT id FROM questions WHERE id=?',(saved_id,)).fetchone() if saved_id else None
            if not duplicate:
                duplicate=conn.execute('SELECT id FROM questions WHERE generation_fingerprint=? OR lower(trim(statement))=lower(trim(?)) LIMIT 1',(q.generation_fingerprint,q.statement)).fetchone()
            if duplicate:qid=duplicate['id'];status='ALREADY_SAVED'
            else:
                now=time.time();columns=', '.join(FIELDS);placeholders=', '.join('?' for _ in FIELDS)
                qid=conn.execute(f'INSERT INTO questions ({columns},created_at,updated_at) VALUES ({placeholders},?,?)',values_of(q)+[now,now]).lastrowid
                generated=GeneratedQuestion.model_validate({k:v for k,v in output['questions'][index].items() if k not in INTERNAL})
                cache_generated_explanations(conn,qid,generated)
                status='SAVED';saved+=1;counts[row['id']]=counts.get(row['id'],0)+1
            output['questions'][index]['saved_question_id']=qid;outputs[row['id']]=output
            results.append({'run_id':row['id'],'index':index,'question_id':qid,'status':status})
        for rid,output in outputs.items():
            complete=all(q.get('saved_question_id') for q in output['questions'])
            conn.execute('UPDATE ai_generation_runs SET output_json=?,accepted_count=accepted_count+?,status=? WHERE id=?',(json.dumps(output,ensure_ascii=False),counts.get(rid,0),'SAVED' if complete else 'REVIEW_REQUIRED',rid))
        conn.commit()
    return {'saved_count':saved,'already_saved_count':len(results)-saved,'items':results}


@router.post('/save')
def bulk_save(data:SaveSelection,request:Request):
    require_admin(_auth(request,True));return save_batches(data)


class DraftEdit(Contract):
    question:GeneratedQuestion
    original_question:GeneratedQuestion

@router.put('/runs/{rid}/questions/{index}')
def edit_draft(rid:str,index:int,data:DraftEdit,request:Request):
    require_admin(_auth(request,True))
    from app import connect
    try:validate_question(data.question)
    except Exception as exc:raise HTTPException(422,str(exc)) from exc
    with closing(connect()) as conn:
        conn.execute('UPDATE ai_generation_runs SET accepted_count=accepted_count WHERE id=?',(rid,))
        row=conn.execute('SELECT * FROM ai_generation_runs WHERE id=?',(rid,)).fetchone()
        if not row:raise HTTPException(404,'Batch not found')
        if row['status'] not in {'REVIEW_REQUIRED','SAVED'}:raise HTTPException(409,'Batch is not ready for review')
        output=json.loads(row['output_json'] or '{}');items=output.get('questions',[])
        if index<0 or index>=len(items):raise HTTPException(404,'Question not found')
        old=items[index]
        if old.get('saved_question_id') or conn.execute('SELECT 1 FROM questions WHERE generation_fingerprint=?',(fingerprint(old['statement']),)).fetchone():raise HTTPException(409,'This question is already saved. Edit it in the question bank.')
        if GeneratedQuestion.model_validate({k:v for k,v in old.items() if k not in INTERNAL}).model_dump()!=data.original_question.model_dump():raise HTTPException(409,'Question changed. Reopen the batch before editing.')
        from multimodal import build_content_blocks
        if any(getattr(data.question,key)!=getattr(data.original_question,key) for key in ('statement','options','answer','solution')):
            from correction_sync import invalidate_generated_explanations
            edited=data.question.model_dump()
            invalidate_generated_explanations(edited)
            data.question=GeneratedQuestion.model_validate(edited)
        data.question.content_blocks=build_content_blocks(data.question.statement,data.question.visual_assets)
        items[index]={**data.question.model_dump(),'review_index':index,'fingerprint':fingerprint(data.question.statement)}
        conn.execute('UPDATE ai_generation_runs SET output_json=? WHERE id=?',(json.dumps(output,ensure_ascii=False),rid));conn.commit()
    return items[index]
