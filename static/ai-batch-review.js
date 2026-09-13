/* A selected batch is identified by run id; question indices remain local to it. */
window.AiBatchActions={mount(target){
  const toolbar=target.querySelector(':scope > .actions');if(!toolbar)return;
  toolbar.className='ai-bulk-toolbar';
  toolbar.innerHTML='<label><input type="checkbox" data-ai-select-page> Select page (up to 20)</label><span data-ai-selected-count>0 selected</span><select data-ai-bulk-menu aria-label="Actions for selected generation runs"><option value="">Selected actions…</option><option value="review">Review together</option><option value="pause">Pause / stop selected</option><option value="delete">Delete saved generations</option></select><button type="button" data-ai-clear-batches>Clear selection</button><button type="button" data-ai-review-selected-batches hidden>Review together</button><p role="status" data-ai-bulk-status></p>';
  updateAiSelection();
}};
function updateAiSelection(){
  const target=$('ai-run-list'),boxes=[...target.querySelectorAll('[data-ai-select-run]')],selected=boxes.filter(box=>box.checked);
  const count=target.querySelector('[data-ai-selected-count]');if(count)count.textContent=`${selected.length} selected`;
  const menu=target.querySelector('[data-ai-bulk-menu]');if(menu)menu.disabled=!selected.length;
  const page=target.querySelector('[data-ai-select-page]');if(page){page.checked=selected.length===Math.min(20,boxes.length)&&!!selected.length;page.indeterminate=!!selected.length&&!page.checked;}
}
$('ai-run-list')?.addEventListener('change',async event=>{
  const target=$('ai-run-list');
  if(event.target.matches('[data-ai-select-page]')){target.querySelectorAll('[data-ai-select-run]').forEach((box,i)=>box.checked=event.target.checked&&i<20);updateAiSelection();return;}
  if(event.target.matches('[data-ai-select-run]')){if(target.querySelectorAll('[data-ai-select-run]:checked').length>20){event.target.checked=false;notify('Select up to 20 runs at a time.');}updateAiSelection();return;}
  if(!event.target.matches('[data-ai-bulk-menu]'))return;
  const action=event.target.value;event.target.value='';if(!action)return;
  const selected=[...target.querySelectorAll('[data-ai-select-run]:checked')];
  if(!selected.length)return;
  if(action==='review'){target.querySelector('[data-ai-review-selected-batches]').click();return;}
  if(action==='delete'&&!confirm(`Remove ${selected.length} selected saved generations from the list? Bank questions and exam papers will remain unchanged. Running generations must be paused and finished first.`))return;
  const status=target.querySelector('[data-ai-bulk-status]');let done=0;const failures=[];
  const controls=[...target.querySelectorAll('input,select,button')];controls.forEach(control=>control.disabled=true);
  try{
    for(const box of selected){
      status.textContent=`${action==='delete'?'Deleting':'Requesting pause'} ${done+failures.length+1} of ${selected.length}…`;
      try{await api(`/api/ai/runs/${box.dataset.aiSelectRun}${action==='pause'?'/pause':''}`,{method:action==='delete'?'DELETE':'POST'});done++;}
      catch(error){failures.push(`Run ${box.dataset.aiSelectRun.slice(0,8)}: ${error.message}`);}
    }
    if(action==='delete'&&done){const results=$('ai-generation-results');results.hidden=true;results.innerHTML='';}
    await loadAiGenerationRuns();
    const summary=`${done} of ${selected.length} ${action==='delete'?'saved generations removed; bank questions unchanged':'pause requests completed; in-flight calls may finish'}.${failures.length?' '+failures.join(' '):''}`;
    const current=target.querySelector('[data-ai-bulk-status]');if(current)current.textContent=summary;notify(summary);
  }finally{controls.filter(control=>control.isConnected).forEach(control=>control.disabled=false);updateAiSelection();}
});
$('ai-run-list')?.addEventListener('click',async event=>{
  if(event.target.closest('[data-ai-select-all-batches]')){$('ai-run-list').querySelectorAll('[data-ai-select-run]:not(:disabled)').forEach((n,i)=>n.checked=i<20);return;}
  if(event.target.closest('[data-ai-clear-batches]')){$('ai-run-list').querySelectorAll('[data-ai-select-run]').forEach(n=>n.checked=false);updateAiSelection();return;}
  const button=event.target.closest('[data-ai-review-selected-batches]');if(!button)return;
  const ids=[...$('ai-run-list').querySelectorAll('[data-ai-select-run]:checked')].map(n=>n.dataset.aiSelectRun);
  if(!ids.length||ids.length>20){notify('Select between 1 and 20 completed batches.');return;}
  button.disabled=true;
  try{
    const runs=await Promise.all(ids.map(id=>api('/api/ai/runs/'+id)));
    if(runs.some(run=>!['REVIEW_REQUIRED','SAVED','PAUSED','CONTINUED'].includes(run.status)))throw new Error('Review together requires completed or paused runs. Deselect running and failed runs.');
    const questions=runs.flatMap(run=>(run.output?.questions||[]).map((q,index)=>({...q,_runId:run.id,_reviewIndex:index})));
    switchAiTab('new');renderAiGenerationResults({run_id:'multiple',exam:`${runs.length} selected batches`,subject:[...new Set(runs.map(r=>r.subject))].join(', '),requested:runs.reduce((n,r)=>n+r.requested_count,0),generated:questions.length,review_required:questions.filter(q=>!q.saved_question_id).length,model:[...new Set(runs.map(r=>r.model))].join(', '),questions});
    $('ai-prompt-preview').querySelector('pre').textContent=runs.map(r=>`Batch ${r.id} - ${r.exam_name} / ${r.subject}\n${r.request?.generation_prompt||''}\n\nSyllabus\n${r.request?.syllabus||''}`).join('\n\n---\n\n');
    $('ai-generation-results').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){notify(error.message);}finally{button.disabled=false;}
});
$('ai-generation-results')?.addEventListener('click',async event=>{
 const button=event.target.closest('[data-ai-edit-draft]');if(!button)return;
 const card=button.closest('[data-ai-review-index]'),target=$('ai-generation-results'),index=Number(card.dataset.aiReviewIndex),source=target._reviewQuestions[index];
 const original=Object.fromEntries(Object.entries(source).filter(([key])=>!['review_index','fingerprint','saved_question_id','_runId','_reviewIndex'].includes(key)));
 await QuestionCorrection.open(source,{save:async value=>{
   const question={...original,...value,options:value.options.map((text,i)=>({label:String.fromCharCode(65+i),text}))};
   const updated=await api(`/api/ai/review/runs/${card.dataset.aiRun}/questions/${card.dataset.aiSourceIndex}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,original_question:original})});
   target._reviewQuestions[index]={...updated,_runId:card.dataset.aiRun,_reviewIndex:Number(card.dataset.aiSourceIndex)};
   const body=card.querySelector('.ai-question-body');body.innerHTML=`<h3>Question ${index+1} — corrected</h3><div class="rendered">${toHtml(updated.statement)}</div>${visualAssetsHtml(updated)}<ol>${updated.options.map(o=>`<li class="rendered">${escapeHtml(o.label)}. ${toHtml(o.text)}</li>`).join('')}</ol><details class="ai-answer-details"><summary>Show answer and worked explanation</summary><div class="rendered"><strong>Answer:</strong> ${toHtml(updated.answer)}<br><strong>Solution:</strong> ${toHtml(updated.solution)}</div></details>`;body.querySelectorAll('.rendered').forEach(typeset);return updated;
 }});
});
