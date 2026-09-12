/* Separate Grand Test workflow. Uses the authenticated shell and shared API helper. */
(()=>{
  const panel=document.createElement('section');panel.id='grand-tests-panel';panel.className='tab-panel';panel.hidden=true;
  $('main-content').append(panel);
  const nav=document.createElement('nav');nav.hidden=true;nav.setAttribute('aria-label','DigitalQBank');
  nav.innerHTML='<button data-view="grand-tests">DigitalQBank</button>';
  $('admin-nav').parentElement.append(nav);
  nav.querySelector('button').onclick=()=>showView('grand-tests');
  let current=null,programs=[],poll=null,pdfWorkspace=null;
  const call=(path='',method='GET',body)=>api('/api/grand-tests'+path,{method,...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  const progress=(text,tone='info')=>{const el=panel.querySelector('[data-status]');if(el){el.textContent=text;el.dataset.tone=tone;}};
  const run=async task=>{try{await task();}catch(e){notify(e.message);const status=panel.querySelector('[data-status]');if(status)progress(e.message,'error');}};
  const options=id=>programs.map(p=>`<option value="${p.id}" ${p.id===Number(id)?'selected':''}>${esc(p.name)}</option>`).join('');
  const permitted=()=>['ADMIN','OPERATOR'].includes(signedInUser?.role);
  const syncAccess=()=>{nav.hidden=!permitted();if(signedInUser?.role==='OPERATOR')showView('grand-tests');};
  window.addEventListener('mobile:login',syncAccess);
  window.addEventListener('load',syncAccess);
  if(signedInUser)queueMicrotask(syncAccess);
  document.addEventListener('workspace:view-changed',e=>{clearTimeout(poll);if(e.detail.name==='grand-tests'&&permitted())run(load);});
  async function load(){
    pdfWorkspace?.destroy();
    programs=(await api('/api/programs?limit=100')).items||[];const docs=await call(signedInUser.role==='ADMIN'?'/admin/document-library':'/documents');
    const rows=await call();current=null;
    panel.innerHTML=`<div class="page-header"><div><h2>DigitalQBank</h2><p>Digitise a paper, review the questions, then schedule a proctored exam.</p></div></div><p class="gt-status" data-status role="status" aria-live="polite"></p>
      <form id="gt-create" class="panel"><h3>Create DigitalQBank workspace</h3><div class="gt-fields"><label>Program<select name="program_id" required>${options()}</select></label><label>Workspace name<input name="name" required maxlength="200"></label><label>Paper name<input name="paper_name" maxlength="200"></label><label>Academic year / batch<input name="academic_year" maxlength="100"></label><label>Description<textarea name="description"></textarea></label></div><button class="primary">Create workspace</button></form>
      ${signedInUser.role==='ADMIN'?'<details class="panel"><summary>Manage Operator access</summary><p>Only Admins can approve verified Operator emails. Removing an email revokes existing sessions.</p><form id="gt-allowlist"><label>Approved Operator email<input type="email" name="email" required></label><button>Add email</button></form><div id="gt-allowlist-rows"></div><p>Assign Operator access only after the email is approved.</p><div id="gt-users"></div></details>':''}
      <div class="gt-list">${rows.map(r=>`<article class="panel"><h3>${esc(r.name)}</h3><p>${esc(r.status.replaceAll('_',' '))} · ${r.questions.length} questions</p><p>Last updated by ${esc(r.operator_email)}</p><div class="actions"><button data-open="${r.id}">Open workspace</button>${!r.exam_id?`<button class="danger" data-delete-workspace="${r.id}" data-workspace-name="${esc(r.name)}">Delete workspace</button>`:''}</div></article>`).join('')||'<p>No DigitalQBank workspaces yet.</p>'}</div>`;
    const adminLibrary=signedInUser.role==='ADMIN';
    const libraryAccess=permitted();
    const when=value=>value?new Date(value*1000).toLocaleString():'—';
    const docRows=docs.map(d=>`<tr><td>${esc(d.filename)}</td><td>${esc(d.program_name)}</td><td>${esc(d.subject||'—')}</td><td>${d.page_count}</td><td>${d.available_for_digitisation?'Available':'Hidden'}</td>${adminLibrary?`<td>${esc(d.chapter||'—')}</td><td>${esc(when(d.created_at))}</td><td>${esc(d.uploaded_by||'—')}</td><td>${esc(d.overall_status)}<br>${d.completed}/${d.page_count} completed · ${d.percentage_complete}% resolved</td><td>${d.progress.Pending} pending · ${d.progress.InProgress} in progress · ${d.progress['Not Applicable']} N/A</td><td>${esc(d.last_digitalised_by||'—')}<br>${esc(when(d.last_status_update||d.updated_at))}</td><td>${d.workspaces.map(w=>`<button type="button" data-open="${w.id}">${esc(w.name)} · ${esc(w.status)}</button>`).join(' ')||'No workspace'}</td>`:''}<td>${adminLibrary?`<button type="button" data-doc-availability="${d.id}" data-available="${d.available_for_digitisation?'0':'1'}">${d.available_for_digitisation?'Hide':'Make available'}</button>`:''}</td></tr>`).join('');
    const library=document.createElement('section');library.className='panel';library.innerHTML='<h3>PDF Library</h3><p>Upload documents and control which PDFs Operators may digitise.</p><form id="gt-doc-upload"><label>Program<select name="program_id" required>'+options()+'</select></label><label>Subject<input name="subject" required maxlength="120" placeholder="e.g. Mathematics"></label><label>PDF<input name="file" type="file" accept="application/pdf" multiple required></label><button>Store documents</button><p id="gt-upload-status" role="status"></p></form><div class="gt-table-wrap"><table><thead><tr><th>Filename</th><th>Program</th><th>Subject</th><th>Pages</th><th>Operator access</th><th>Action</th></tr></thead><tbody>'+docRows+'</tbody></table></div>';if(libraryAccess)panel.querySelector('#gt-create').after(library);
    WorkspaceTabs.mount(panel,[['Workspaces',[panel.querySelector('.gt-list')]],['Create workspace',[$('gt-create')]],['PDF library',[libraryAccess?library:null]],['Operator access',[panel.querySelector('details.panel')]]],'catalog');
    if($('gt-doc-upload'))$('gt-doc-upload').onsubmit=e=>{e.preventDefault();run(async()=>{const form=e.target, f=new FormData(form),files=[...form.file.files],button=form.querySelector('button'),status=form.querySelector('#gt-upload-status');button.disabled=true;status.textContent=`Uploading 0 of ${files.length}…`;try{for(let i=0;i<files.length;i++){status.textContent=`Uploading ${i+1} of ${files.length}: ${files[i].name}`;progress(status.textContent,'busy');const one=new FormData();one.append('file',files[i]);await api('/api/grand-tests/documents?program_id='+f.get('program_id')+'&subject='+encodeURIComponent(f.get('subject')),{method:'POST',body:one});}status.textContent=`Upload complete — ${files.length} document${files.length===1?'':'s'} ready for digitisation.`;await load();progress('Upload complete. PDFs stored in the Program library.','success');notify(`${files.length} document${files.length>1?'s':''} stored in the Program library`);}catch(error){status.textContent=`Upload failed: ${error.message}. Retry when ready.`;throw error;}finally{button.disabled=false;}});};
    panel.querySelectorAll('[data-doc-availability]').forEach(b=>b.onclick=()=>run(async()=>{b.disabled=true;try{await call(`/admin/documents/${b.dataset.docAvailability}/availability`,'PUT',{available:b.dataset.available==='1'});await load();notify('PDF availability updated');}finally{b.disabled=false;}}));
    if(adminLibrary){const actionHeader=library.querySelector('thead th:last-child');for(const title of ['Chapter','Uploaded at','Uploaded by','Digitisation progress','Page statuses','Last updated by / at','Workspaces']){const th=document.createElement('th');th.scope='col';th.textContent=title;actionHeader.before(th);}}
    if(!docs.length)library.querySelector('tbody').innerHTML=`<tr><td colspan="${adminLibrary?13:6}">No PDFs available.</td></tr>`;
    const documentField=document.createElement('label');documentField.innerHTML='Stored document<select name="document_id" required></select><span role="status" data-document-status></span><button type="button" data-document-retry hidden>Retry loading PDFs</button>';document.querySelector('#gt-create .gt-fields')?.prepend(documentField);
    const docSelect=documentField.querySelector('select'),programSelect=document.querySelector('#gt-create select[name="program_id"]'),docStatus=documentField.querySelector('[data-document-status]'),retry=documentField.querySelector('[data-document-retry]');let documentRequest=0;
    programSelect.onchange=async()=>{const request=++documentRequest,previous=docSelect.value;docSelect.disabled=true;docSelect.replaceChildren();docStatus.textContent='Loading PDFs…';retry.hidden=true;
      try{const available=await call('/documents/available?program_id='+encodeURIComponent(programSelect.value));if(request!==documentRequest)return;docSelect.innerHTML='<option value="">Choose a stored document</option>'+available.map(d=>`<option value="${d.id}">${esc(d.filename)} · ${esc(d.subject||'')} · ${d.page_count} pages</option>`).join('');if(available.some(d=>String(d.id)===previous))docSelect.value=previous;docStatus.textContent=available.length?`${available.length} PDFs available`:'No PDFs are currently available for digitalisation in this Program.';}
      catch(error){if(request===documentRequest){docStatus.textContent=error.message;retry.hidden=false;}}
      finally{if(request===documentRequest)docSelect.disabled=false;}};retry.onclick=()=>programSelect.onchange();programSelect.onchange();
    $('gt-create').onsubmit=e=>{e.preventDefault();run(async()=>{const body=Object.fromEntries(new FormData(e.target));body.program_id=Number(body.program_id);if(!body.document_id)delete body.document_id;else body.document_id=Number(body.document_id);if(!body.document_id)throw Error('Choose a stored PDF for this Program');progress('Creating workspace…');const row=await call('','POST',body);await open(row.id);});};
    panel.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>run(()=>open(Number(b.dataset.open))));
    panel.querySelectorAll('[data-delete-workspace]').forEach(b=>b.onclick=()=>run(async()=>{if(!confirm(`Delete workspace "${b.dataset.workspaceName}" permanently?`))return;await call('/'+b.dataset.deleteWorkspace,'DELETE');notify('Workspace deleted');await load();}));
    if($('gt-users')){
      const allowed=await api('/api/admin/operator-allowlist');
      $('gt-allowlist-rows').innerHTML=allowed.map(x=>`<div class="actions"><span>${esc(x.email)}${x.active?'':' (inactive)'}</span><button type="button" data-remove-operator="${esc(x.email)}">Remove</button></div>`).join('')||'<p>No approved Operator emails.</p>';
      $('gt-allowlist').onsubmit=e=>{e.preventDefault();run(async()=>{await api('/api/admin/operator-allowlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:new FormData(e.target).get('email')})});await load();notify('Operator email approved');});};
      $('gt-allowlist-rows').querySelectorAll('[data-remove-operator]').forEach(b=>b.onclick=()=>run(async()=>{await api('/api/admin/operator-allowlist/'+encodeURIComponent(b.dataset.removeOperator),{method:'DELETE'});await load();notify('Operator access revoked');}));
      const users=await api('/api/admin/users');
      $('gt-users').innerHTML=users.filter(u=>u.id!==signedInUser.id).map(u=>`<label>${esc(u.email)}<select data-role="${u.id}">${['STUDENT','OPERATOR','PROCTOR','ADMIN'].map(r=>`<option ${u.role===r?'selected':''}>${r}</option>`).join('')}</select></label>`).join('');
      $('gt-users').querySelectorAll('select').forEach(s=>s.onchange=()=>run(async()=>{await api(`/api/admin/users/${s.dataset.role}/role`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({role:s.value})});notify('Role updated');}));
    }
  }
  async function open(id){const wasDigitising=current?.id===id&&current.status==='DIGITIZING';current=await call('/'+id);if(wasDigitising&&current.status==='REVIEW_REQUIRED')panel.dataset.workspaceSection='Review & save';render();}
  let correctionRefresh=false,correctionAgain=false;
  async function refreshSavedQuestions(id){
    if(!current||!permitted()||(id&&!current.questions.some(q=>Number(q.saved_question_id)===Number(id))))return;
    if(correctionRefresh){correctionAgain=true;return;}
    correctionRefresh=true;const workspace=current;
    try{const fresh=await call('/'+workspace.id);if(current!==workspace)return;
      // Only saved rows are locked. Never rebuild the form over an unsaved review or schedule.
      const unsaved=questions=>questions.filter(q=>!q.saved_question_id);
      const sameDraft=JSON.stringify(unsaved(workspace.questions))===JSON.stringify(unsaved(fresh.questions))&&workspace.status===fresh.status&&workspace.exam_id===fresh.exam_id&&JSON.stringify(workspace.exam)===JSON.stringify(fresh.exam);
      for(const q of fresh.questions.filter(q=>q.saved_question_id)){
        const index=workspace.questions.findIndex(old=>old.id===q.id&&old.saved_question_id===q.saved_question_id);if(index<0)continue;
        const row=[...panel.querySelectorAll('[data-question]')].find(node=>node.dataset.question===String(q.id));workspace.questions[index]=q;if(!row)continue;
        row.querySelectorAll('[name]').forEach(field=>{if(field.name==='advanced')field.value=JSON.stringify({source_image:q.source_image,visual_assets:q.visual_assets,content_blocks:q.content_blocks,math_evidence:q.math_evidence},null,2);else if(field.type==='checkbox')field.checked=!!q[field.name];else field.value=field.name==='options'?(q.options||[]).join('\n'):q[field.name]??'';});
        QuestionSourceReview.refresh(row,q);
      }
      if(sameDraft){workspace.revision=fresh.revision;progress('Saved question content updated. Your unsaved review and schedule entries are preserved.','success');}
      else progress('Saved question content updated. Other workspace changes were found; reopen the workspace before saving. Your unsaved entries are still here.','error');
    }catch(error){progress('Could not refresh corrected questions. '+error.message,'error');}
    finally{correctionRefresh=false;if(correctionAgain){correctionAgain=false;refreshSavedQuestions();}}
  }
  document.addEventListener('question:corrected',event=>refreshSavedQuestions(event.detail?.id));
  document.addEventListener('question:invalidated',event=>refreshSavedQuestions(event.detail?.id));
  function render(){
    const g=current,locked=!!g.exam_id||g.status==='DIGITIZING',admin=signedInUser.role==='ADMIN',saved=g.questions.filter(q=>q.saved_question_id);
    panel.innerHTML=`<button id="gt-back">← DigitalQBank</button><a class="gt-home" href="/app">Home</a><div class="page-header"><div><h2>${esc(g.name)}</h2><p>${esc(g.paper_name)} · ${esc(g.status.replaceAll('_',' '))} · ${g.questions.length} questions</p></div>${!g.exam_id?`<button class="danger" id="gt-delete-workspace">Delete workspace</button>`:''}</div><p class="gt-status" data-status role="status" aria-live="polite">${esc(g.error||(g.status==='DIGITIZING'?'Digitising and classifying… Please wait.':g.questions.length?'Questions ready for review. Select reviewed questions to save to the question bank.':'PDF ready. Select a portion or digitise the whole PDF.'))}</p>
      ${!g.source.id?'<p>Choose a stored PDF when creating a workspace.</p>':''}
      ${g.source.id?'<div id="gt-pdf-workspace"></div>':''}

      <form id="gt-review"><h3>Review questions</h3><p>Check the source, correct metadata and answers, then mark each question reviewed. Advanced content preserves source images, tables and equations.</p><div id="gt-questions">${g.questions.map((q,i)=>question(q,i,locked)).join('')}</div>${!locked&&g.questions.length?'<div class="actions"><button>Save review</button><button type="button" id="gt-save-all" class="primary">Save all questions</button><button type="button" id="gt-save-selected">Save selected questions</button><button type="button" id="gt-finalize">Save & finalize questions</button></div>':''}</form>
      ${admin&&!g.exam_id&&saved.length?`<form id="gt-create-exam" class="panel"><h3>Create exam with selected questions</h3><p>Select saved Question Bank items above. The new exam remains a draft for review, scheduling and publication.</p><div class="gt-fields"><label>Exam name<input name="name" value="${esc(g.name)}" required maxlength="200"></label><label>Duration (minutes)<input name="duration" type="number" min="1" max="1440" value="30" required></label></div><button class="primary">Create draft exam</button></form>`:''}
      ${admin&&g.exam?examForm(g.exam):''}`;
    $('gt-back').onclick=()=>run(load);
    $('gt-delete-workspace')?.addEventListener('click',()=>run(async()=>{if(!confirm(`Delete workspace "${g.name}" permanently?`))return;await call('/'+g.id,'DELETE');notify('Workspace deleted');await load();}));
    pdfWorkspace?.destroy();
    if(g.source.id){
      pdfWorkspace=mountPdfDigitisationWorkspace($('gt-pdf-workspace'),{
        locked, isBusy:()=>locked,
        load:async()=>({...g.source,pages:Array.from({length:g.source.page_count},(_,i)=>({number:i+1,url:`/api/grand-tests/${g.id}/pages/${i+1}`}))}),
        digitise:regions=>digitize(regions),
      });
      run(()=>pdfWorkspace.open({name:g.source.filename}));
      const host=$('gt-pdf-workspace'), navBar=document.createElement('div'); navBar.className='gt-page-nav';
      navBar.innerHTML='<button type="button" data-page-prev>Previous page</button><span data-page-label>Page 1 of '+g.source.page_count+'</span><button type="button" data-page-next>Next page</button><label>Status <select data-page-status><option>Pending</option><option>InProgress</option><option>Completed</option><option>Not Applicable</option></select></label><span data-progress></span>';
      host.before(navBar);
      const pages=()=>host.querySelectorAll('.pdf-viewer-page'), viewer=host.querySelector('.pdf-viewer-pages');
      let activePage=1, statuses={};
      const refresh=()=>{navBar.querySelector('[data-page-label]').textContent=`Page ${activePage} of ${g.source.page_count}`;navBar.querySelector('[data-page-prev]').disabled=activePage===1;navBar.querySelector('[data-page-next]').disabled=activePage===g.source.page_count;navBar.querySelector('[data-page-status]').value=statuses[activePage]||'Pending';};
      const progress=async()=>{const data=await call(`/${g.id}/page-status`);statuses=Object.fromEntries(data.pages.map(x=>[x.page_number,x.status]));navBar.querySelector('[data-progress]').textContent=`${data.completed} of ${data.total} pages completed`;refresh();};
      navBar.querySelector('[data-page-prev]').onclick=()=>{activePage=Math.max(1,activePage-1);pages()[activePage-1]?.scrollIntoView({behavior:'smooth',block:'start'});refresh();};
      navBar.querySelector('[data-page-next]').onclick=()=>{activePage=Math.min(g.source.page_count,activePage+1);pages()[activePage-1]?.scrollIntoView({behavior:'smooth',block:'start'});refresh();};
      viewer.addEventListener('scroll',()=>{const top=viewer.getBoundingClientRect().top;const visible=[...pages()].findIndex(p=>p.getBoundingClientRect().bottom>top+32);if(visible>=0){activePage=visible+1;refresh();}},{passive:true});
      navBar.querySelector('[data-page-status]').disabled=locked;
      navBar.querySelector('[data-page-status]').onchange=e=>run(async()=>{const select=e.target;select.disabled=true;try{const data=await call(`/${g.id}/page-status`,'PUT',{revision:current.revision,page:activePage,status:select.value});current.revision=data.revision;statuses=Object.fromEntries(data.pages.map(x=>[x.page_number,x.status]));navBar.querySelector('[data-progress]').textContent=`${data.completed} of ${data.total} pages completed`;refresh();}finally{select.disabled=locked;}});
      run(progress);
    }
    if($('gt-save-all'))$('gt-save-all').onclick=()=>run(()=>saveBank(false));
    if($('gt-save-selected'))$('gt-save-selected').onclick=()=>run(()=>saveBank(true));
    $('gt-review').onsubmit=e=>{e.preventDefault();run(save);};
    if($('gt-finalize'))$('gt-finalize').onclick=()=>run(async()=>{await save();current=await call(`/${g.id}/finalize`,'POST',{revision:current.revision});render();});
    QuestionSourceReview.bindAll(panel,g.questions);
    if($('gt-create-exam'))$('gt-create-exam').onsubmit=e=>{e.preventDefault();run(async()=>{const ids=[...panel.querySelectorAll('[data-exam-question]:checked')].map(x=>Number(x.value));if(!ids.length)throw Error('Select at least one saved question for the exam');const form=e.target;const result=await call(`/${g.id}/exams`,'POST',{revision:current.revision,question_ids:ids,name:form.name.value,duration_minutes:Number(form.duration.value),request_key:`workspace-${g.id}-${Date.now()}`});await open(g.id);notify(`Draft exam #${result.exam_id} created with ${ids.length} question(s)`);});};
    panel.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>b.closest('[data-question]').remove());
    panel.querySelectorAll('[data-move]').forEach(b=>b.onclick=()=>{const row=b.closest('[data-question]');if(b.dataset.move==='up'&&row.previousElementSibling)row.before(row.previousElementSibling);else if(b.dataset.move==='down'&&row.nextElementSibling)row.after(row.nextElementSibling);});
    if($('gt-schedule'))$('gt-schedule').onsubmit=e=>{e.preventDefault();run(async()=>{await saveSchedule(e.target);notify('Draft schedule saved');});};
    if($('gt-publish'))$('gt-publish').onclick=()=>run(async()=>{await saveSchedule($('gt-schedule'));const result=await call(`/${g.id}/publish`,'POST',{revision:current.revision});await open(g.id);const notice=document.createElement('p');notice.setAttribute('role','status');notice.textContent=`Published. Proctor code: ${result.proctor_code}. Save this code securely and share it with the proctor. It is shown only once.`;panel.prepend(notice);});
    if($('gt-exam-admin'))$('gt-exam-admin').onclick=()=>showView('admin-exams');
    WorkspaceTabs.mount(panel,[['Digitise',[$('gt-pdf-workspace'),panel.querySelector('.gt-page-nav')]],['Review & save',[$('gt-review')]],['Create exam / schedule',[$('gt-create-exam'),$('gt-schedule'),$('gt-exam-admin')?.closest('.panel')]]],String(g.id));
    if(g.status==='DIGITIZING'){clearTimeout(poll);poll=setTimeout(()=>{if(!panel.hidden)run(()=>open(g.id));},5000);}
  }
  function question(q,i,locked){const saved=!!q.saved_question_id;locked=locked||saved;return `<article class="panel" data-question="${esc(q.id)}"><h4>Question ${esc(q.number??i+1)}</h4><label class="gt-pick"><input type="checkbox" data-pick-question ${locked?'disabled':'checked'}> ${saved?'Saved to question bank':'Select question to save'}</label>${saved?`<label class="gt-pick"><input type="checkbox" data-exam-question value="${q.saved_question_id}" checked> Include Question Bank #${q.saved_question_id} in exam</label>`:''}<p class="gt-review-label">${q.reviewed?'Reviewed':'Review required'} · Extraction confidence ${Math.round((q.confidence||0)*100)}% · Classification confidence ${Math.round((q.classification_confidence||0)*100)}%</p><div class="question-source-review"><section data-review-source aria-label="Original source"></section><section data-review-editor><fieldset ${locked?'disabled':''}><label>Question number<input name="number" value="${esc(q.number??i+1)}"></label><label>Question text<textarea name="statement" rows="4">${esc(q.statement)}</textarea></label><label>Options — one per line<textarea name="options" rows="4">${esc((q.options||[]).join('\n'))}</textarea></label><label>Correct answer<input name="answer" value="${esc(q.answer)}"></label><label>Explanation<textarea name="solution">${esc(q.solution)}</textarea></label><div class="gt-live-preview" data-review-preview aria-live="polite"></div><div class="gt-fields"><label>Program<select name="program_id">${options(q.program_id)}</select></label>${['subject','chapter','topic','subtopic','difficulty','qtype'].map(k=>`<label>${esc(k)}<input name="${k}" value="${esc(q[k])}" required></label>`).join('')}</div><details><summary>Advanced content: images, tables and equations</summary><textarea name="advanced" rows="8">${esc(JSON.stringify({source_image:q.source_image,visual_assets:q.visual_assets,content_blocks:q.content_blocks,math_evidence:q.math_evidence},null,2))}</textarea></details><label><input name="reviewed" type="checkbox" ${q.reviewed?'checked':''}> I reviewed the source, rendered question, answer and classification</label><div class="actions"><button type="button" data-move="up">Move up</button><button type="button" data-move="down">Move down</button><button type="button" data-remove>Remove question</button></div></fieldset></section></div></article>`;}
  function collect(){return [...panel.querySelectorAll('[data-question]')].map(row=>{const q={...current.questions.find(q=>q.id===row.dataset.question)};row.querySelectorAll('[name]').forEach(el=>{if(el.name==='advanced')Object.assign(q,JSON.parse(el.value));else q[el.name]=el.type==='checkbox'?el.checked:el.name==='options'?el.value.split('\n').filter(x=>x.trim()):el.name==='program_id'?Number(el.value):el.value;});return q;});}
  async function save(){current=await call(`/${current.id}/questions`,'PUT',{revision:current.revision,questions:collect()});render();notify('Review saved');}
  async function saveBank(selectedOnly){
    const ids=[...panel.querySelectorAll('[data-question]')].filter(row=>{const pick=row.querySelector('[data-pick-question]');return !pick.disabled&&(!selectedOnly||pick.checked);}).map(row=>row.dataset.question);
    if(!ids.length)throw Error('Select at least one unsaved question');
    const questions=collect();if(questions.some(q=>ids.includes(q.id)&&!q.reviewed))throw Error('Review each selected question before saving');
    const buttons=[...panel.querySelectorAll('#gt-review button')];buttons.forEach(b=>b.disabled=true);progress('Saving reviewed questions…','busy');
    try{current=await call(`/${current.id}/questions`,'PUT',{revision:current.revision,questions});current=await call(`/${current.id}/save-questions`,'POST',{revision:current.revision,question_ids:ids});render();progress(`${ids.length} question(s) saved to the question bank.`,'success');}
    finally{buttons.forEach(b=>b.disabled=false);}
  }
  async function digitize(regions){progress('Digitisation starting…','busy');await call(`/${current.id}/digitize`,'POST',{revision:current.revision,selections:regions});await open(current.id);}
  const localDate=t=>{if(!t)return '';const d=new Date(t*1000);return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};
  function examForm(e){return e.status==='DRAFT'?`<form id="gt-schedule" class="panel"><h3>Schedule & publish</h3><p>Times use your device time zone (${esc(Intl.DateTimeFormat().resolvedOptions().timeZone)}). A proctor code is required for every student.</p><label>Exam name<input name="name" value="${esc(e.name)}" required></label><label>Start date & time<input name="start" type="datetime-local" required value="${localDate(e.exam_start_at)}"></label><label>End date & time<input name="end" type="datetime-local" required value="${localDate(e.exam_end_at)}"></label><label>Duration (minutes)<input name="duration" type="number" min="1" max="1440" value="${e.duration_minutes}" required></label><label><input name="self" type="checkbox" ${e.allow_self_registration?'checked':''}> Allow students to enroll themselves</label><p>Use Exam Admin to assign students or create invitation links.</p><div class="actions"><button>Save draft schedule</button><button type="button" id="gt-publish" class="primary">Publish Grand Test</button><button type="button" id="gt-exam-admin">Exam Admin / student assignments</button></div></form>`:`<div class="panel"><h3>Published exam #${e.id}</h3><p>${esc(new Date(e.exam_start_at*1000).toLocaleString())} – ${esc(new Date(e.exam_end_at*1000).toLocaleString())}</p><button id="gt-exam-admin">Exam Admin / registrations & proctor codes</button></div>`;}
  async function saveSchedule(form){if(!form.reportValidity())throw Error('Complete all scheduling fields');const f=new FormData(form);current=await call(`/${current.id}/schedule`,'PUT',{revision:current.revision,name:f.get('name'),start_at:new Date(f.get('start')).getTime()/1000,end_at:new Date(f.get('end')).getTime()/1000,duration_minutes:Number(f.get('duration')),allow_self_registration:f.has('self')});render();}
})();
