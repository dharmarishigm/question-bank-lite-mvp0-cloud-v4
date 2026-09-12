/* Canonical question content stays current; submitted grading remains auditable. */
window.QuestionUpdates=(()=>{
  function notice(q){
    if(!q.correction&&!q.content_corrected&&!q.historical_grading)return '';
    if(q.historical_grading){const original=q.original_question;return `<details class="question-correction-notice"><summary>Updated question · original grading retained</summary><p>The question, options and solution above show the current approved correction. Your recorded response and marks remain from the submitted attempt.</p>${original?`<h4>Question used for the recorded score</h4><div class="rendered">${toHtml(original.statement||'')}</div><ol>${(original.options||[]).map(o=>`<li class="rendered">${toHtml(o)}</li>`).join('')}</ol>${original.answer?`<p class="rendered"><strong>Answer used for grading:</strong> ${toHtml(original.answer)}</p>`:''}`:''}</details>`;}
    return `<p class="question-correction-notice" role="status">${q.response_review_required?'This question was updated. Review the corrected options and choose your answer again.':'This question shows the latest approved correction.'}</p>`;
  }
  function paintCurrent(body,q){body.innerHTML=`<div class="rendered">${toHtml(q.statement)}</div>${visualAssetsHtml(q)}<ol>${q.options.map(o=>`<li class="rendered">${toHtml(typeof o==='string'?o:o.text)}</li>`).join('')}</ol><p class="rendered"><strong>Answer:</strong> ${toHtml(q.answer)}</p><div class="rendered">${toHtml(q.solution)}</div>`;body.querySelectorAll('.rendered').forEach(typeset);}
  function invalidateExplanation(qid){
    const modal=$('explain-modal');if(!modal||Number(modal.dataset.questionId)!==Number(qid))return;
    modal.dataset.requestVersion=String(Number(modal.dataset.requestVersion||0)+1);
    const content=$('explain-content');delete content.dataset.rawExplanation;delete content.dataset.structured;
    $('explain-like').disabled=true;$('explain-like').hidden=true;
    if(modal.hidden)return;
    content.textContent='This question was corrected. Open the explanation for the updated question.';
    const again=document.createElement('button');again.type='button';again.textContent='Open updated explanation';again.onclick=()=>modal.dataset.studentReview==='1'?openAttemptExplanation(qid):openExplainModal(qid);content.append(again);
  }
  function refreshEditor(q){
    if(typeof editingId==='undefined'||Number(editingId)!==Number(q.id)||$('editor-modal')?.hidden)return;
    const sameContent=JSON.stringify(QuestionCorrection.pick(formValue()))===JSON.stringify(QuestionCorrection.pick(q));
    if(JSON.stringify(formValue())===editingBaseline||sameContent){fillForm(q);$('save-status').textContent='Updated to the current question.';return;}
    editingStale=true;syncSaveState();const status=$('save-status');status.textContent='This question was corrected. Your unsaved draft is still here; load the updated question before saving. ';
    const reload=document.createElement('button');reload.type='button';reload.textContent='Load corrected question';reload.onclick=()=>{fillForm(q);status.textContent='Current question loaded. Review your changes before saving.';};status.append(reload);
  }
  async function refreshResults(){
    const tasks=[];
    for(const [id,admin] of [['my-results-list',false],['admin-results-list',true]]){const target=$(id);if(target?.dataset.attempt&&target.querySelector('[data-attempt-question]')&&!target.closest('.tab-panel')?.hidden)tasks.push(loadAttemptResult(target.dataset.attempt,admin,{refresh:true}));}
    await Promise.allSettled(tasks);
  }
  const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('meritiqra-question-updates'):null;
  document.addEventListener('question:corrected',event=>{
    const q=event.detail;if(!Number(q?.id))return;
    const current={statement:q.statement,options:q.options,answer:q.answer,solution:q.solution};
    if(typeof questions!=='undefined'){const bank=questions.find(item=>item.id===q.id);if(bank){Object.assign(bank,q);renderList();}}
    invalidateExplanation(q.id);refreshEditor(q);
    if(!$('image-viewer-modal')?.hidden&&Number($('image-viewer-modal').dataset.questionId)===Number(q.id)){closeImageViewer();notify('Question updated. Reopen the current figure or source preview.');}
    if(typeof parsed!=='undefined')parsed.forEach((item,index)=>{if(Number(item.saved_question_id)!==Number(q.id))return;Object.assign(item,current,{visual_assets:q.visual_assets||[],explanation_en:'',explanation_te:''});const row=$('pdf-list').querySelector(`[data-item="${index}"]`);if(row){row.outerHTML=pdfItemHtml(item,index);renderPdfPreview(index);togglePreview(index,true);}if(!$('compare-modal').hidden&&Number($('compare-modal').dataset.reviewIndex)===index)openCompareModal(index);});
    if(typeof examState!=='undefined'){
      const inAttempt=!!$('exam-current-question')?.dataset.session;
      if(inAttempt)refreshAttempt(true);else{for(const item of examState.questions||[]){if(item.id===q.id)Object.assign(item,current);}if(examState.started)renderExamCurrentQuestion();}
    }
    refreshResults();
    const target=$('ai-generation-results');
    (target?._reviewQuestions||[]).forEach((item,index)=>{if(item.saved_question_id===q.id){Object.assign(item,current,{options:q.options.map((text,i)=>({label:String.fromCharCode(65+i),text})),visual_assets:q.visual_assets||[],explanation_en:'',explanation_te:''});const body=target.querySelector(`[data-ai-review-index="${index}"] .ai-question-body`);if(body)paintCurrent(body,q);}});
    document.querySelectorAll('[data-program-correction-host]').forEach(host=>Promise.resolve(host._refreshCorrections?.()).catch(error=>notify(error.message)));
    if(!event.fromPeer)channel?.postMessage({id:Number(q.id)});
  });
  if(channel)channel.onmessage=async event=>{
    const id=Number(event.data?.id);if(!Number.isSafeInteger(id)||id<1)return;
    invalidateExplanation(id);refreshAttempt(true);refreshResults();document.dispatchEvent(new CustomEvent('question:invalidated',{detail:{id}}));
    if(signedInUser?.role==='ADMIN'){try{const q=await api('/api/questions/'+id);const update=new CustomEvent('question:corrected',{detail:q});update.fromPeer=true;document.dispatchEvent(update);}catch{}}
  };
  let polling=false,refreshAgain=false;
  async function refreshAttempt(force=false){
    const host=$('exam-current-question'),sid=host?.dataset.session;
    if(polling){refreshAgain=refreshAgain||force;return;}
    if(!sid||!examState.started||examState.submitted||(!force&&(document.hidden||$('exam-panel').hidden)))return;
    polling=true;
    const responseVersions=new Map(examState.questions.map(q=>[q.id,{serial:q._responseSerial||0,saving:q._answerSaving||0}]));
    try{const data=await api(`/api/sessions/${sid}`);if(host.dataset.session!==sid)return;
      let changed=false;
      for(const q of data.questions){const existing=examState.questions.find(x=>x.id===q.id);if(!existing)continue;
        const revisionChanged=existing.content_revision!==q.content_revision;
        const prior=responseVersions.get(q.id);
        const localResponseChanged=(existing._responseSerial||0)!==prior?.serial||existing._answerSaving||prior?.saving;
        for(const key of ['statement','options','subject','chapter','section_name','visual_assets','content_revision','content_corrected','correction']){if(JSON.stringify(existing[key])!==JSON.stringify(q[key])){existing[key]=q[key];changed=true;}}
        if(revisionChanged||!localResponseChanged){if(existing.response_review_required!==q.response_review_required)changed=true;existing.response_review_required=q.response_review_required;
          if(q.response_review_required){const index=examState.questions.indexOf(existing);delete examState.answers[getExamQuestionKey(index)];existing.selected_answer='';if(typeof examAnswers!=='undefined')examAnswers[existing.number]='';changed=true;}
        }
      }
      if(typeof examQuestions!=='undefined')examQuestions=examState.questions;
      if(changed){renderExamNav();renderExamCurrentQuestion();}
    }catch(error){if(force)notify('Could not refresh the corrected question. '+error.message);}finally{polling=false;if(refreshAgain){refreshAgain=false;refreshAttempt(true);}}
  }
  setInterval(()=>refreshAttempt(),30000);
  setInterval(()=>{if(!document.hidden)refreshResults();},60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){refreshAttempt();refreshResults();}});
  window.addEventListener('focus',()=>{refreshAttempt();refreshResults();});
  document.addEventListener('click',event=>{
    const b=event.target.closest('[data-admin-take-exam]');if(!b)return;showView('available-exams');
  });
  document.addEventListener('click',event=>{
    if(signedInUser?.role!=='ADMIN')return;
    const image=event.target.closest('[data-view-image]');if(!image)return;
    const context=image.closest('.question-card,[data-paper-question],[data-ai-review-index],[data-item],.guided-review-question,[data-attempt-question],#exam-current-question');
    const original=context&&[...context.querySelectorAll('button')].find(b=>b.textContent.includes('Edit / AI correct'));
    $('image-viewer-modal').querySelector('[data-image-correct]')?.remove();
    if(original){const edit=document.createElement('button');edit.dataset.imageCorrect='1';edit.textContent='Edit / AI correct / Regenerate';edit.onclick=()=>{closeImageViewer();original.click();};$('image-viewer-modal').querySelector('.modal-head').append(edit);}
  });
  // Explain dialogs also identify the bank question; the same editor is available.
  const explain=$('explain-modal');
  if(explain)new MutationObserver(()=>{
    explain.querySelector('[data-correct-question]')?.remove();
    if(!explain.hidden&&Number(explain.dataset.questionId)){
      const box=explain.querySelector('.modal-content')||explain.firstElementChild;
      box?.insertAdjacentHTML('afterbegin',window.QuestionCorrection?.button({id:Number(explain.dataset.questionId)})||'');
    }
  }).observe(explain,{attributes:true,attributeFilter:['hidden','data-question-id']});
  return {notice,refreshAttempt,refreshResults,invalidateExplanation};
})();
