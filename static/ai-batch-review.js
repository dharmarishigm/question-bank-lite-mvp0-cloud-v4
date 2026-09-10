/* A selected batch is identified by run id; question indices remain local to it. */
$('ai-run-list')?.addEventListener('click',async event=>{
  if(event.target.closest('[data-ai-select-all-batches]')){$('ai-run-list').querySelectorAll('[data-ai-select-run]:not(:disabled)').forEach((n,i)=>n.checked=i<20);return;}
  if(event.target.closest('[data-ai-clear-batches]')){$('ai-run-list').querySelectorAll('[data-ai-select-run]').forEach(n=>n.checked=false);return;}
  const button=event.target.closest('[data-ai-review-selected-batches]');if(!button)return;
  const ids=[...$('ai-run-list').querySelectorAll('[data-ai-select-run]:checked')].map(n=>n.dataset.aiSelectRun);
  if(!ids.length||ids.length>20){notify('Select between 1 and 20 completed batches.');return;}
  button.disabled=true;
  try{
    const runs=await Promise.all(ids.map(id=>api('/api/ai/runs/'+id)));
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
   const body=card.querySelector('.ai-question-body');body.innerHTML=`<h3>Question ${index+1} — corrected</h3><div class="rendered">${toHtml(updated.statement)}</div>${visualAssetsHtml(updated)}<ol>${updated.options.map(o=>`<li class="rendered">${escapeHtml(o.label)}. ${toHtml(o.text)}</li>`).join('')}</ol><div class="rendered"><strong>Answer:</strong> ${toHtml(updated.answer)}<br><strong>Solution:</strong> ${toHtml(updated.solution)}</div>`;body.querySelectorAll('.rendered').forEach(typeset);return updated;
 }});
});
