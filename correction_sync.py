"""Propagate reviewed bank corrections while preserving attempt evidence."""
import json,time
from blueprint_domain import content_hash
from multimodal import statement_with_question_figures


def invalidate_generated_explanations(item):
    """Remove text derived from a previous question, including nested caches."""
    for field in ('explanation_en','explanation_te'):
        if field in item:item[field]=''
    def clear(value):
        if not isinstance(value,dict):return
        value.pop('precomputed_explanations',None)
        value.pop('explanation_en',None);value.pop('explanation_te',None)
        for child in value.values():
            if isinstance(child,dict):clear(child)
    clear(item.get('metadata'))
    clear(item.get('generation_metadata'))


def prepare(conn,qid):
    from exam_conduct import _snapshot
    plans=[]
    for row in conn.execute("SELECT * FROM program_exam_jobs WHERE status IN ('REVIEW_REQUIRED','DRAFT','PUBLISHED') ORDER BY id").fetchall():
        result=json.loads(row['result_json'] or '{}')
        if not any(i.get('question',{}).get('id')==qid for i in result.get('questions',[])):continue
        conn.execute('UPDATE program_exam_jobs SET updated_at=updated_at WHERE id=?',(row['id'],))
        row=conn.execute('SELECT * FROM program_exam_jobs WHERE id=?',(row['id'],)).fetchone();result=json.loads(row['result_json'] or '{}')
        draft=conn.execute('SELECT * FROM exams WHERE id=?',(row['exam_id'],)).fetchone() if row['exam_id'] else None
        valid=bool(draft and draft['status']=='DRAFT' and content_hash({'exam':dict(draft),'questions':_snapshot(conn,row['exam_id'])})==result.get('draft_hash'))
        plans.append((dict(row),result,dict(draft) if draft else None,valid))
    return plans


def propagate(conn,old,updated,user_id,plans):
    from program_exam import snapshot
    from exam_conduct import _snapshot,audit
    qid=updated['id'];now=time.time()
    content_changed=any(old.get(key)!=updated.get(key) for key in ('statement','options','answer','solution','visual_assets'))
    if not content_changed and all(old.get(k)==updated.get(k) for k in ('subject','chapter','topic','subtopic','difficulty','qtype','verification_status')):
        return
    if content_changed:
        invalidate_generated_explanations(updated)
        conn.execute('UPDATE questions SET generation_metadata=? WHERE id=?',(json.dumps(updated.get('generation_metadata',{}),ensure_ascii=False),qid))
    for job,result,draft,valid in plans:
        for item in result.get('questions',[]):
            if item.get('question',{}).get('id')==qid:item['question']=snapshot(updated)
        if job['status'] in {'REVIEW_REQUIRED','DRAFT'}:result['correction_review_required']=True
        if valid:result['draft_hash']=content_hash({'exam':draft,'questions':_snapshot(conn,job['exam_id'])})
        else:result.pop('draft_hash',None)
        conn.execute('UPDATE program_exam_jobs SET result_json=?,updated_at=? WHERE id=?',(json.dumps(result,ensure_ascii=False),now,job['id']))
    # Saved DigitalQBank entries are views of their bank question. Keep local
    # unsaved entries and source/page provenance, but update every saved copy.
    if updated.get('verification_status') in {'APPROVED','VERIFIED'}:
        from grand_tests import reviewed_payload_hash
        for row in conn.execute("SELECT id,questions_json FROM grand_tests WHERE questions_json LIKE '%saved_question_id%' ORDER BY id").fetchall():
            if not any(str(q.get('saved_question_id',''))==str(qid) for q in json.loads(row['questions_json'] or '[]')):continue
            conn.execute('UPDATE grand_tests SET revision=revision WHERE id=?',(row['id'],))
            refreshed=conn.execute('SELECT questions_json FROM grand_tests WHERE id=?',(row['id'],)).fetchone()
            if not refreshed:continue
            questions=json.loads(refreshed['questions_json'])
            changed=False
            for item in questions:
                if str(item.get('saved_question_id',''))!=str(qid):continue
                fields=('statement','options','answer','solution','visual_assets','content_blocks','subject','chapter','topic','subtopic','difficulty','qtype')
                if not any(item.get(k)!=updated.get(k) for k in fields):continue
                invalidate_generated_explanations(item)
                item.update({k:updated.get(k) for k in fields})
                item['reviewed']=True
                item['reviewed_payload_hash']=reviewed_payload_hash(item)
                changed=True
            if changed:
                conn.execute('UPDATE grand_tests SET questions_json=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=?',
                             (json.dumps(questions,ensure_ascii=False),user_id,now,row['id']))
    # Preserve run indices and provenance; saved previews must show current content.
    for row in conn.execute("SELECT id,output_json FROM ai_generation_runs WHERE id=? OR output_json LIKE ?",(old.get('generation_run_id',''),'%saved_question_id%')).fetchall():
        output=json.loads(row['output_json'] or '{}');changed=False
        for q in output.get('questions',[]):
            own=row['id']==old.get('generation_run_id') and q.get('statement')==old.get('statement')
            if q.get('saved_question_id')==qid or own:
                if content_changed:invalidate_generated_explanations(q)
                q.update(statement=updated['statement'],options=[{'label':chr(65+i),'text':text} for i,text in enumerate(updated['options'])],answer=updated['answer'],solution=updated['solution'],saved_question_id=qid,fingerprint=updated.get('generation_fingerprint',''));changed=True
        if changed:conn.execute('UPDATE ai_generation_runs SET output_json=? WHERE id=?',(json.dumps(output,ensure_ascii=False),row['id']))
    # Copy the currently published version, changing ONLY the reviewed question.
    # Unpublished edits to other bank questions or exam configuration stay out.
    if updated.get('verification_status') not in {'APPROVED','VERIFIED'}:return
    for row in conn.execute("SELECT id FROM exams WHERE current_version_id IS NOT NULL AND status IN ('PUBLISHED','OPEN','CLOSED') ORDER BY id").fetchall():
        eid=row['id'];conn.execute('UPDATE exams SET current_version_id=current_version_id WHERE id=?',(eid,))
        version=conn.execute('SELECT v.* FROM exam_versions v JOIN exams e ON e.current_version_id=v.id WHERE e.id=?',(eid,)).fetchone()
        if not version:continue
        questions=json.loads(version['question_snapshot_json']);changed=False
        for q in questions:
            if q['id']!=qid:continue
            value={k:updated[k] for k in ['statement','options','answer','solution','visual_assets']}
            value['statement']=statement_with_question_figures(updated['statement'],updated.get('visual_assets',[]))
            if any(q.get(k)!=v for k,v in value.items()):q.update(value);changed=True
        if not changed:continue
        number=conn.execute('SELECT COALESCE(MAX(version_number),0)+1 n FROM exam_versions WHERE exam_id=?',(eid,)).fetchone()['n']
        cur=conn.execute("INSERT INTO exam_versions(exam_id,version_number,status,configuration_json,question_snapshot_json,published_at,published_by,created_at) VALUES(?,?,'PUBLISHED',?,?,?,?,?)",(eid,number,version['configuration_json'],json.dumps(questions,ensure_ascii=False),now,user_id,now))
        conn.execute('UPDATE exams SET current_version_id=? WHERE id=?',(cur.lastrowid,eid))
        audit(conn,'QUESTION_CORRECTION_VERSION',exam_id=eid,user_id=user_id,metadata={'question_id':qid,'version_id':cur.lastrowid})


def current_corrections(conn,originals):
    """Approved current core content; caller retains exam timing/marks/evidence."""
    by_id={q['id']:q for q in originals};ids=list(by_id)
    if not ids:return {}
    rows=conn.execute("SELECT id,statement,options,answer,solution,visual_assets FROM questions WHERE verification_status IN ('APPROVED','VERIFIED') AND id IN ("+','.join('?' for _ in ids)+')',ids).fetchall()
    current={}
    for row in rows:
        q=dict(row);q['options']=json.loads(q['options'] or '[]');q['visual_assets']=json.loads(q['visual_assets'] or '[]')
        q['statement']=statement_with_question_figures(q['statement'],q['visual_assets'])
        previous=by_id[q['id']]
        if any(q.get(k)!=previous.get(k) for k in ['statement','options','answer','solution']) or q['visual_assets']!=previous.get('visual_assets',[]):
            current[q['id']]={k:v for k,v in q.items() if k!='id'}
    return current


def annotate(conn,questions,originals,include_answers=False):
    """Render corrected primary fields while retaining submitted grading evidence."""
    by_id={q['id']:q for q in originals}
    current=current_corrections(conn,originals)
    for q in questions:
        latest=current.get(q['id'])
        if not latest:continue
        visible=['statement','options','visual_assets']+(['answer','solution'] if include_answers else [])
        q['correction']={k:latest[k] for k in visible}
        if not include_answers:
            q['correction']['visual_assets']=[a for a in latest['visual_assets'] if a.get('type')!='answer_figures']
        if include_answers:
            old=by_id[q['id']]
            q['original_question']={k:old.get(k) for k in visible}
            q['original_answer']=old.get('answer','')
            q['historical_grading']=True
        q.update(q['correction'])
        q['content_corrected']=True
    return questions


def hydrate_workspace(conn,items):
    """Repair legacy saved workspace views without touching unsaved draft items."""
    from app import row_to_dict
    from grand_tests import reviewed_payload_hash
    ids={int(q['saved_question_id']) for q in items if str(q.get('saved_question_id','')).isdigit()}
    if not ids:return items
    rows=conn.execute("SELECT * FROM questions WHERE verification_status IN ('APPROVED','VERIFIED') AND id IN ("+','.join('?' for _ in ids)+')',list(ids)).fetchall()
    bank={str(row['id']):row_to_dict(row) for row in rows}
    fields=('statement','options','answer','solution','visual_assets','content_blocks','subject','chapter','topic','subtopic','difficulty','qtype')
    for item in items:
        latest=bank.get(str(item.get('saved_question_id')))
        if not latest:continue
        if any(item.get(k)!=latest.get(k) for k in fields):
            invalidate_generated_explanations(item)
            item.update({k:latest.get(k) for k in fields})
            item['reviewed']=True
            item['reviewed_payload_hash']=reviewed_payload_hash(item)
    return items


def hydrate_run(conn,run):
    """Resolve saved generation previews to the current bank, including older runs."""
    from app import row_to_dict
    items=run.get('output',{}).get('questions',[])
    ids={q.get('saved_question_id') for q in items if q.get('saved_question_id')}
    rows=conn.execute('SELECT * FROM questions WHERE generation_run_id=?'+(' OR id IN ('+','.join('?' for _ in ids)+')' if ids else ''),(run['id'],*ids)).fetchall()
    bank={r['id']:row_to_dict(r) for r in rows};statements={}
    for q in bank.values():
        if q.get('generation_run_id')==run['id']:statements.setdefault(q['statement'],set()).add(q['id'])
    for qid in bank:
        for version in conn.execute('SELECT payload_json FROM question_versions WHERE question_id=?',(qid,)).fetchall():
            old=json.loads(version['payload_json'] or '{}')
            if old.get('generation_run_id')==run['id']:statements.setdefault(old.get('statement',''),set()).add(qid)
    for item in items:
        matches=statements.get(item.get('statement'),set());qid=item.get('saved_question_id') or (next(iter(matches)) if len(matches)==1 else None)
        if qid in bank:
            q=bank[qid]
            # Legacy blobs may already contain corrected core fields but stale
            # explanations. The live cache is authoritative for saved questions.
            invalidate_generated_explanations(item)
            for cached in conn.execute("SELECT language,explanation FROM question_explanation_translations WHERE question_id=? AND language IN ('en','te')",(qid,)).fetchall():
                item['explanation_'+cached['language']]=cached['explanation']
            item.update(saved_question_id=qid,statement=q['statement'],options=[{'label':chr(65+i),'text':o} for i,o in enumerate(q['options'])],answer=q['answer'],solution=q['solution'])
