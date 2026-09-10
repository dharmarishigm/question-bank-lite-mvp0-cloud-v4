/* Separate Grand Test workflow. Uses the authenticated shell and shared API helper. */
(()=>{
  const panel=document.createElement('section');panel.id='grand-tests-panel';panel.className='tab-panel';panel.hidden=true;
  $('main-content').append(panel);
  const nav=document.createElement('nav');nav.hidden=true;nav.setAttribute('aria-label','Grand Tests');
  nav.innerHTML='<button data-view="grand-tests">Grand Tests</button>';
  $('admin-nav').parentElement.append(nav);
  nav.querySelector('button').onclick=()=>showView('grand-tests');
  let current=null,programs=[],selections=[],page=1,poll=null;
  const call=(path='',method='GET',body)=>api('/api/grand-tests'+path,{method,...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  const run=async task=>{try{await task();}catch(e){notify(e.message);const status=panel.querySelector('[data-status]');if(status)status.textContent=e.message;}};
  const options=id=>programs.map(p=>`<option value="${p.id}" ${p.id===Number(id)?'selected':''}>${esc(p.name)}</option>`).join('');
  const permitted=()=>['ADMIN','OPERATOR'].includes(signedInUser?.role);
  const syncAccess=()=>{nav.hidden=!permitted();if(signedInUser?.role==='OPERATOR')showView('grand-tests');};
  window.addEventListener('mobile:login',syncAccess);
  window.addEventListener('load',syncAccess);
  if(signedInUser)queueMicrotask(syncAccess);
  document.addEventListener('workspace:view-changed',e=>{clearTimeout(poll);if(e.detail.name==='grand-tests'&&permitted())run(load);});
  async function load(){
    programs=(await api('/api/programs?limit=100')).items||[];
    const rows=await call();current=null;selections=[];
    panel.innerHTML=`<div class="page-header"><div><h2>Grand Tests</h2><p>Digitize a paper, review the questions, then schedule a proctored exam.</p></div></div><p data-status role="status"></p>
      <form id="gt-create" class="panel"><h3>Create Grand Test</h3><div class="gt-fields"><label>Program<select name="program_id" required>${options()}</select></label><label>Grand Test name<input name="name" required maxlength="200"></label><label>Paper name<input name="paper_name" maxlength="200"></label><label>Academic year / batch<input name="academic_year" maxlength="100"></label><label>Description<textarea name="description"></textarea></label></div><button class="primary">Create workspace</button></form>
      ${signedInUser.role==='ADMIN'?'<details class="panel"><summary>Manage Operator access</summary><p>Assign Operator access to an existing user account.</p><div id="gt-users"></div></details>':''}
      <div class="gt-list">${rows.map(r=>`<article class="panel"><h3>${esc(r.name)}</h3><p>${esc(r.status.replaceAll('_',' '))} · ${r.questions.length} questions</p><p>Last updated by ${esc(r.operator_email)}</p><button data-open="${r.id}">Open workspace</button></article>`).join('')||'<p>No Grand Tests yet.</p>'}</div>`;
    $('gt-create').onsubmit=e=>{e.preventDefault();run(async()=>{const body=Object.fromEntries(new FormData(e.target));body.program_id=Number(body.program_id);const row=await call('','POST',body);await open(row.id);});};
    panel.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>run(()=>open(Number(b.dataset.open))));
    if($('gt-users')){
      const users=await api('/api/admin/users');
      $('gt-users').innerHTML=users.filter(u=>u.id!==signedInUser.id).map(u=>`<label>${esc(u.email)}<select data-role="${u.id}">${['STUDENT','OPERATOR','PROCTOR','ADMIN'].map(r=>`<option ${u.role===r?'selected':''}>${r}</option>`).join('')}</select></label>`).join('');
      $('gt-users').querySelectorAll('select').forEach(s=>s.onchange=()=>run(async()=>{await api(`/api/admin/users/${s.dataset.role}/role`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({role:s.value})});notify('Role updated');}));
    }
  }
  async function open(id){current=await call('/'+id);render();}
  function render(){
    const g=current,locked=!!g.exam_id||g.status==='DIGITIZING',admin=signedInUser.role==='ADMIN';
    panel.innerHTML=`<button id="gt-back">← Grand Tests</button><div class="page-header"><div><h2>${esc(g.name)}</h2><p>${esc(g.paper_name)} · ${esc(g.status.replaceAll('_',' '))} · ${g.questions.length} questions</p></div></div><p data-status role="status">${esc(g.error||'')}</p>
      ${!locked?'<form id="gt-upload" class="panel"><label>Source PDF<input name="file" type="file" accept="application/pdf" required></label><button>Upload PDF</button></form>':''}
      ${g.source.id?`<div class="panel"><h3>${esc(g.source.filename)}</h3><div class="actions"><label>Page <input id="gt-page" type="number" min="1" max="${g.source.page_count}" value="${page}"></label><span>of ${g.source.page_count}</span><label>Zoom <select id="gt-zoom"><option value="100">100%</option><option value="150">150%</option><option value="200">200%</option></select></label></div><p>Drag on the page to add regions. Navigate to another page to keep selecting.</p><div class="gt-page-scroll"><div id="gt-page-wrap"><img id="gt-page-image" draggable="false" alt="Source PDF page"><div id="gt-boxes"></div></div></div><div id="gt-selections"></div>${!locked?'<div class="actions"><button id="gt-whole">Digitize Whole PDF</button><button id="gt-selected">Digitize Selected Portions</button></div>':''}</div>`:''}
      ${g.status==='DIGITIZING'?'<p role="status">Digitizing and classifying… You can return to this workspace later.</p>':''}
      <form id="gt-review"><h3>Review questions</h3><p>Check the source, correct metadata and answers, then mark each question reviewed. Advanced content preserves source images, tables and equations.</p><div id="gt-questions">${g.questions.map((q,i)=>question(q,i,locked)).join('')}</div>${!locked&&g.questions.length?'<div class="actions"><button class="primary">Save review</button><button type="button" id="gt-finalize">Save & finalize questions</button></div>':''}</form>
      ${admin&&g.status==='FINALIZED'?'<button id="gt-generate" class="primary">Generate Exam</button>':''}
      ${admin&&g.exam?examForm(g.exam):''}`;
    $('gt-back').onclick=()=>run(load);
    if($('gt-upload'))$('gt-upload').onsubmit=e=>{e.preventDefault();run(async()=>{current=await api(`/api/grand-tests/${g.id}/pdf?revision=${g.revision}`,{method:'POST',body:new FormData(e.target)});page=1;selections=[];render();});};
    if(g.source.id){page=Math.min(page,g.source.page_count);$('gt-page').value=page;showPage();$('gt-page').onchange=()=>{page=Math.max(1,Math.min(g.source.page_count,Number($('gt-page').value)||1));showPage();};$('gt-zoom').onchange=()=>{$('gt-page-wrap').style.width=$('gt-zoom').value+'%';};setupSelection(!locked);}
    if($('gt-whole'))$('gt-whole').onclick=()=>run(()=>digitize([]));
    if($('gt-selected'))$('gt-selected').onclick=()=>run(async()=>{if(!selections.length)throw Error('Select at least one region');await digitize(selections);});
    $('gt-review').onsubmit=e=>{e.preventDefault();run(save);};
    if($('gt-finalize'))$('gt-finalize').onclick=()=>run(async()=>{await save();current=await call(`/${g.id}/finalize`,'POST',{revision:current.revision});render();});
    if($('gt-generate'))$('gt-generate').onclick=()=>run(async()=>{await call(`/${g.id}/generate`,'POST',{revision:g.revision});await open(g.id);});
    panel.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>b.closest('[data-question]').remove());
    panel.querySelectorAll('[data-move]').forEach(b=>b.onclick=()=>{const row=b.closest('[data-question]');if(b.dataset.move==='up'&&row.previousElementSibling)row.before(row.previousElementSibling);else if(b.dataset.move==='down'&&row.nextElementSibling)row.after(row.nextElementSibling);});
    if($('gt-schedule'))$('gt-schedule').onsubmit=e=>{e.preventDefault();run(async()=>{await saveSchedule(e.target);notify('Draft schedule saved');});};
    if($('gt-publish'))$('gt-publish').onclick=()=>run(async()=>{await saveSchedule($('gt-schedule'));const result=await call(`/${g.id}/publish`,'POST',{revision:current.revision});await open(g.id);const notice=document.createElement('p');notice.setAttribute('role','status');notice.textContent=`Published. Proctor code: ${result.proctor_code}. Save this code securely and share it with the proctor. It is shown only once.`;panel.prepend(notice);});
    if($('gt-exam-admin'))$('gt-exam-admin').onclick=()=>showView('admin-exams');
    if(g.status==='DIGITIZING'){clearTimeout(poll);poll=setTimeout(()=>{if(!panel.hidden)run(()=>open(g.id));},5000);}
  }
  function question(q,i,locked){return `<article class="panel" data-question="${esc(q.id)}"><h4>Question ${esc(q.number??i+1)}</h4><p>${q.reviewed?'Reviewed':'Review required'} · Extraction confidence ${Math.round((q.confidence||0)*100)}% · Classification confidence ${Math.round((q.classification_confidence||0)*100)}%</p><fieldset ${locked?'disabled':''}><label>Question number<input name="number" value="${esc(q.number??i+1)}"></label><label>Question text<textarea name="statement" rows="4">${esc(q.statement)}</textarea></label><label>Options — one per line<textarea name="options" rows="4">${esc((q.options||[]).join('\n'))}</textarea></label><label>Correct answer<input name="answer" value="${esc(q.answer)}"></label><label>Explanation<textarea name="solution">${esc(q.solution)}</textarea></label><div class="gt-fields"><label>Program<select name="program_id">${options(q.program_id)}</select></label>${['subject','chapter','topic','subtopic','difficulty','qtype'].map(k=>`<label>${esc(k)}<input name="${k}" value="${esc(q[k])}" required></label>`).join('')}</div>${q.source_image&&/^\/uploads\//.test(q.source_image)?`<img class="gt-evidence" src="${esc(q.source_image)}" alt="Question source evidence">`:''}<details><summary>Advanced content: images, tables and equations</summary><textarea name="advanced" rows="8">${esc(JSON.stringify({source_image:q.source_image,visual_assets:q.visual_assets,content_blocks:q.content_blocks,math_evidence:q.math_evidence},null,2))}</textarea></details><label><input name="reviewed" type="checkbox" ${q.reviewed?'checked':''}> I reviewed the question, answer and classification</label><div class="actions"><button type="button" data-move="up">Move up</button><button type="button" data-move="down">Move down</button><button type="button" data-remove>Remove question</button></div></fieldset></article>`;}
  function collect(){return [...panel.querySelectorAll('[data-question]')].map(row=>{const q={...current.questions.find(q=>q.id===row.dataset.question)};row.querySelectorAll('[name]').forEach(el=>{if(el.name==='advanced')Object.assign(q,JSON.parse(el.value));else q[el.name]=el.type==='checkbox'?el.checked:el.name==='options'?el.value.split('\n').filter(x=>x.trim()):el.name==='program_id'?Number(el.value):el.value;});return q;});}
  async function save(){current=await call(`/${current.id}/questions`,'PUT',{revision:current.revision,questions:collect()});render();notify('Review saved');}
  async function digitize(regions){await call(`/${current.id}/digitize`,'POST',{revision:current.revision,selections:regions});selections=[];await open(current.id);}
  function showPage(){$('gt-page-image').src=`/api/grand-tests/${current.id}/pages/${page}`;drawSelections();}
  function drawSelections(){
    $('gt-boxes').innerHTML=selections.filter(s=>s.page===page).map(s=>`<span style="left:${s.bbox[0]*100}%;top:${s.bbox[1]*100}%;width:${(s.bbox[2]-s.bbox[0])*100}%;height:${(s.bbox[3]-s.bbox[1])*100}%"></span>`).join('');
    $('gt-selections').innerHTML=selections.map((s,i)=>`<button type="button" data-selection="${i}">Page ${s.page} · Region ${i+1} ×</button>`).join('');
    $('gt-selections').querySelectorAll('button').forEach(b=>b.onclick=()=>{selections.splice(Number(b.dataset.selection),1);drawSelections();});
  }
  function setupSelection(enabled){if(!enabled)return;const img=$('gt-page-image');let start;
    const point=e=>{const r=img.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
    img.onpointerdown=e=>{e.preventDefault();start=point(e);img.setPointerCapture(e.pointerId);};
    img.onpointerup=e=>{if(!start)return;const end=point(e),bbox=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];start=null;if(bbox[2]-bbox[0]>.01&&bbox[3]-bbox[1]>.01){selections.push({page,bbox});drawSelections();}};
  }
  const localDate=t=>{if(!t)return '';const d=new Date(t*1000);return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};
  function examForm(e){return e.status==='DRAFT'?`<form id="gt-schedule" class="panel"><h3>Schedule & publish</h3><p>Times use your device time zone (${esc(Intl.DateTimeFormat().resolvedOptions().timeZone)}). A proctor code is required for every student.</p><label>Exam name<input name="name" value="${esc(e.name)}" required></label><label>Start date & time<input name="start" type="datetime-local" required value="${localDate(e.exam_start_at)}"></label><label>End date & time<input name="end" type="datetime-local" required value="${localDate(e.exam_end_at)}"></label><label>Duration (minutes)<input name="duration" type="number" min="1" max="1440" value="${e.duration_minutes}" required></label><label><input name="self" type="checkbox" ${e.allow_self_registration?'checked':''}> Allow students to enroll themselves</label><p>Use Exam Admin to assign students or create invitation links.</p><div class="actions"><button>Save draft schedule</button><button type="button" id="gt-publish" class="primary">Publish Grand Test</button><button type="button" id="gt-exam-admin">Exam Admin / student assignments</button></div></form>`:`<div class="panel"><h3>Published exam #${e.id}</h3><p>${esc(new Date(e.exam_start_at*1000).toLocaleString())} – ${esc(new Date(e.exam_end_at*1000).toLocaleString())}</p><button id="gt-exam-admin">Exam Admin / registrations & proctor codes</button></div>`;}
  async function saveSchedule(form){if(!form.reportValidity())throw Error('Complete all scheduling fields');const f=new FormData(form);current=await call(`/${current.id}/schedule`,'PUT',{revision:current.revision,name:f.get('name'),start_at:new Date(f.get('start')).getTime()/1000,end_at:new Date(f.get('end')).getTime()/1000,duration_minutes:Number(f.get('duration')),allow_self_registration:f.has('self')});render();}
})();
