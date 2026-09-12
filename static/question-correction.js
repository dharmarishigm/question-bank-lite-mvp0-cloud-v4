/* Shared admin editor for bank questions and unsaved review drafts. */
window.QuestionCorrection=(()=>{
  const pick=q=>({statement:q.statement||'',options:(q.options||[]).map(o=>typeof o==='string'?o:o.text),answer:q.answer||'',solution:q.solution||''});
  const admin=()=>typeof signedInUser!=='undefined'&&signedInUser?.role==='ADMIN';
  async function open(q,{save,onSaved,programPaperId}={}){
    if(!admin())return;
    if(q.id&&!save)q=await api('/api/questions/'+q.id);
    const original=pick(q);let proposal=null;
    const modal=document.createElement('dialog');modal.className='result-tools-dialog correction-dialog';
    modal.innerHTML=`<h3>${q.id?'Correct question #'+Number(q.id):'Correct review question'}</h3><p>Edit wording, equations, options, answer and solution. AI suggestions require your review.</p><form><label>Question<textarea name="statement" rows="5" required></textarea></label><div data-options></div><div class="actions"><button type="button" data-add-option>Add option</button><button type="button" data-remove-option>Remove last option</button></div><label>Correct answer (option letter or value)<input name="answer" /></label><label>Solution<textarea name="solution" rows="5"></textarea></label><label>Instructions for AI<textarea name="instructions" rows="2" placeholder="Describe the transcription, equation or answer issue; or specify how to regenerate."></textarea></label><div class="actions"><button type="button" data-ai="correct">Correct with AI</button><button type="button" data-ai="regenerate">Regenerate with AI</button>${programPaperId?'<button type="button" data-ai="replace_from_paper">Replace from paper syllabus</button>':''}<button type="button" data-preview-correction>Preview changes</button></div><div data-proposal hidden><h4>AI suggestion — review before applying</h4><div data-ai-notes></div><div class="rendered" data-ai-preview></div><button type="button" data-apply-proposal>Use suggestion in editor</button><button type="button" data-dismiss-proposal>Discard suggestion</button></div><div class="rendered" data-correction-preview></div><label class="inline"><input type="checkbox" name="reviewed" required />I reviewed the rendered question, options, answer and solution.</label><p class="muted">${save?'Updates this review draft. Save/publish it through its normal review workflow.':'Updates the question bank, linked paper previews and published versions for future attempts. Existing attempts retain their recorded answers and scores and show a correction notice.'}</p><div class="actions"><button class="primary" type="submit">${save?'Update review question':'Update question'}</button><button type="button" data-close-correction>Cancel</button></div><p role="status"></p></form>`;
    const source=safeUrl(q.source_image||q.image||q.source_segments?.[0]?.image||'');if(source){const evidence=document.createElement('details');evidence.innerHTML=`<summary>Compare original source</summary><img src="${escapeHtml(source)}" alt="Original question crop" style="max-width:100%;height:auto" />`;modal.querySelector('form').prepend(evidence);}
    document.body.append(modal);modal.showModal();modal.addEventListener('close',()=>modal.remove());
    const form=modal.querySelector('form'),status=form.querySelector('[role=status]'),options=form.querySelector('[data-options]');
    const paint=(node,v)=>renderInto(node,`${v.statement}\n\n${v.options.map((o,i)=>`${String.fromCharCode(65+i)}. ${o}`).join('\n\n')}\n\n**Answer:** ${v.answer}\n\n**Solution:** ${v.solution}`);
    function fill(v){form.elements.statement.value=v.statement;form.elements.answer.value=v.answer;form.elements.solution.value=v.solution;options.innerHTML=v.options.map((o,i)=>`<label>Option ${String.fromCharCode(65+i)}<textarea data-option rows="2">${escapeHtml(o)}</textarea></label>`).join('');form.elements.reviewed.checked=false;paint(form.querySelector('[data-correction-preview]'),v);}
    const read=()=>({statement:form.elements.statement.value,options:[...options.querySelectorAll('[data-option]')].map(n=>n.value),answer:form.elements.answer.value,solution:form.elements.solution.value});
    fill(original);
    form.oninput=e=>{if(e.target!==form.elements.reviewed)form.elements.reviewed.checked=false;else if(form.elements.reviewed.checked)paint(form.querySelector('[data-correction-preview]'),read());};
    form.querySelector('[data-add-option]').onclick=()=>{const v=read();if(v.options.length<26){v.options.push('');fill(v);}};
    form.querySelector('[data-remove-option]').onclick=()=>{const v=read();v.options.pop();fill(v);};
    form.querySelector('[data-close-correction]').onclick=()=>modal.close();
    form.querySelector('[data-preview-correction]').onclick=()=>paint(form.querySelector('[data-correction-preview]'),read());
    form.querySelector('[data-dismiss-proposal]').onclick=()=>{proposal=null;form.querySelector('[data-proposal]').hidden=true;};
    form.querySelector('[data-apply-proposal]').onclick=()=>{if(proposal)fill(proposal.question);form.querySelector('[data-proposal]').hidden=true;status.textContent='Suggestion applied to the editor. Check the preview and review before updating.';};
    form.querySelectorAll('[data-ai]').forEach(button=>button.onclick=async()=>{
      const snapshot=JSON.stringify(read());form.querySelectorAll('[data-ai]').forEach(b=>b.disabled=true);status.textContent='AI is preparing a suggestion…';
      try{proposal=await api('/api/admin/question-corrections/suggest',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:read(),instructions:form.elements.instructions.value,mode:button.dataset.ai,source_image:q.source_image||q.image||q.source_segments?.[0]?.image||q.visual_assets?.[0]?.asset||'',program_paper_id:programPaperId||null,question_id:q.id||null})});if(!modal.isConnected)return;
        form.querySelector('[data-ai-notes]').textContent=[...proposal.changes,...proposal.uncertainties].join('\n');paint(form.querySelector('[data-ai-preview]'),proposal.question);form.querySelector('[data-proposal]').hidden=false;status.textContent=snapshot!==JSON.stringify(read())?'Your edits changed while AI was working. Compare carefully before applying.':'Suggestion ready. Nothing has been saved.';
      }catch(error){status.textContent=error.message;}finally{form.querySelectorAll('[data-ai]').forEach(b=>b.disabled=false);}
    });
    form.onsubmit=async e=>{e.preventDefault();if(!form.elements.reviewed.checked)return;const button=form.querySelector('[type=submit]');button.disabled=true;
      try{const value=read();const updated=save?await save(value):await api('/api/admin/question-corrections/'+q.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:value,original,reviewed:true,program_paper_id:programPaperId||null})});modal.close();await onSaved?.(updated||value);document.dispatchEvent(new CustomEvent('question:corrected',{detail:updated||value}));notify('Question updated.');}
      catch(error){status.textContent=error.message;button.disabled=false;}
    };
  }
  document.addEventListener('click',async e=>{const b=e.target.closest('[data-correct-question]');if(!b||!admin())return;try{await open({id:Number(b.dataset.correctQuestion)},{onSaved:()=>{if(typeof loadQuestions==='function')loadQuestions();}});}catch(error){notify(error.message);}});
  function button(q){return admin()&&Number(q.id)>0?`<button type="button" data-correct-question="${Number(q.id)}">Edit / AI correct / Regenerate</button>`:'';}
  const editorButton=document.createElement('button');editorButton.type='button';editorButton.textContent='Edit / AI correct / Regenerate';editorButton.id='editor-ai-correct';
  $('btn-preview')?.insertAdjacentElement('beforebegin',editorButton);
  editorButton.onclick=()=>open(formValue(),{save:async value=>{fillForm({...formValue(),...value});return value;}});
  document.addEventListener('question:corrected',event=>{
    const q=event.detail;if(!q.id)return;
    document.querySelectorAll(`[data-paper-question="${Number(q.id)}"]`).forEach(node=>{node.querySelector('.rendered').innerHTML=toHtml(q.statement);node.querySelector('.exam-option-list').innerHTML=q.options.map((o,i)=>`<li><span class="option-label">${String.fromCharCode(65+i)}.</span><span class="rendered">${toHtml(o)}</span></li>`).join('');typeset(node);});
    if(typeof blueprintPreview!=='undefined'&&blueprintPreview){const item=blueprintPreview.questions.find(i=>i.id===q.id);if(item){Object.assign(item,q);const node=document.querySelector(`[data-blueprint-item="${Number(q.id)}"] .rendered`);if(node)renderInto(node,q.statement);}}
  });
  return {open,button,pick};
})();
