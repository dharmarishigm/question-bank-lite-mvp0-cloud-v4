/* Live canonical previews; scored attempts keep their original question evidence. */
window.QuestionUpdates=(()=>{
  function notice(q){
    const c=q.correction;if(!c)return '';
    return `<details class="question-correction-notice"><summary>Correction available — view current question</summary><p>This attempt retains its original question, recorded answers and score. The current correction below applies to new attempts.</p><div class="rendered">${toHtml(c.statement)}</div><ol>${c.options.map(o=>`<li class="rendered">${toHtml(o)}</li>`).join('')}</ol>${'answer' in c?`<p class="rendered"><strong>Current answer:</strong> ${toHtml(c.answer)}</p><div class="rendered">${toHtml(c.solution)}</div>`:'<p>Correct answers and solutions remain hidden during the exam.</p>'}</details>`;
  }
  function paintCurrent(body,q){body.innerHTML=`<div class="rendered">${toHtml(q.statement)}</div><ol>${q.options.map(o=>`<li class="rendered">${toHtml(typeof o==='string'?o:o.text)}</li>`).join('')}</ol><p class="rendered"><strong>Answer:</strong> ${toHtml(q.answer)}</p><div class="rendered">${toHtml(q.solution)}</div>`;body.querySelectorAll('.rendered').forEach(typeset);}
  document.addEventListener('question:corrected',event=>{
    const q=event.detail;if(!q.id)return;
    const current={statement:q.statement,options:q.options,answer:q.answer,solution:q.solution};
    if(typeof questions!=='undefined'){const bank=questions.find(item=>item.id===q.id);if(bank){Object.assign(bank,q);renderList();}}
    const explainModal=$('explain-modal');
    if(explainModal&&!explainModal.hidden&&Number(explainModal.dataset.questionId)===q.id){
      $('explain-content').textContent='The question was corrected. Generate a fresh explanation for the current version.';
      const again=document.createElement('button');again.textContent='Explain corrected question';again.onclick=()=>openExplainModal(q.id);$('explain-content').append(again);
    }
    if(typeof examState!=='undefined'){
      const inAttempt=!!$('exam-current-question')?.dataset.session;
      for(const item of examState.questions||[]){if(item.id===q.id){if(inAttempt)item.correction={statement:q.statement,options:q.options};else Object.assign(item,current);}}
      if(examState.started)renderExamCurrentQuestion();
    }
    document.querySelectorAll(`[data-attempt-question="${q.id}"]`).forEach(card=>{
      card.querySelector('.question-correction-notice')?.remove();card.insertAdjacentHTML('beforeend',notice({correction:current}));card.querySelectorAll('.rendered').forEach(typeset);
    });
    const target=$('ai-generation-results');
    (target?._reviewQuestions||[]).forEach((item,index)=>{if(item.saved_question_id===q.id){Object.assign(item,current,{options:q.options.map((text,i)=>({label:String.fromCharCode(65+i),text}))});const body=target.querySelector(`[data-ai-review-index="${index}"] .ai-question-body`);if(body)paintCurrent(body,q);}});
    document.querySelectorAll('[data-program-correction-host]').forEach(host=>Promise.resolve(host._refreshCorrections?.()).catch(error=>notify(error.message)));
  });
  let polling=false;
  async function refreshAttempt(){
    const host=$('exam-current-question'),sid=host?.dataset.session;
    if(polling||!sid||!examState.started||examState.submitted||document.hidden||$('exam-panel').hidden)return;
    polling=true;
    try{const data=await api(`/api/sessions/${sid}`);if(host.dataset.session!==sid)return;
      let changed=false;
      for(const q of data.questions){const existing=examState.questions.find(x=>x.id===q.id);if(existing&&JSON.stringify(existing.correction)!==JSON.stringify(q.correction)){existing.correction=q.correction;changed=true;}}
      if(changed)renderExamCurrentQuestion();
    }catch{}finally{polling=false;}
  }
  setInterval(refreshAttempt,30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshAttempt();});
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
  return {notice,refreshAttempt};
})();
