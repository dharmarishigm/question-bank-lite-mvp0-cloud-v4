/* Additive Programs workspace. Existing exam-generation routes remain unchanged. */
(() => {
  const nav = document.getElementById('admin-nav');
  if (!nav) return;
  const button = document.createElement('button');
  button.dataset.view = 'programs'; button.textContent = 'Create program exam';
  nav.insertBefore(button,nav.querySelector('[data-view=exam]'));
  const panel = document.createElement('section');
  panel.id = 'programs-panel'; panel.className = 'tab-panel'; panel.hidden = true;
  panel.innerHTML = `<div class="page-header"><div><p class="eyebrow">PROGRAMS &amp; EXAMS</p><h2>Programs</h2><p>Add a program, generate questions, review and publish an exam.</p></div><button class="primary" data-program-add>Add program</button></div>
    <form data-program-search class="actions"><label>Search programs<input name="q" maxlength="200" placeholder="Name or code"></label><label>Status<select name="status"><option value="ACTIVE">Active programs</option><option value="INACTIVE">Inactive programs</option><option value="ARCHIVED">Archived programs</option><option value="">All statuses</option></select></label><label>Sort<select name="sort"><option value="name">Name</option><option value="code">Code</option><option value="updated_at">Updated</option></select></label><label>Order<select name="direction"><option value="asc">Ascending</option><option value="desc">Descending</option></select></label><button>Search</button></form>
    <p data-program-status role="status"></p><div data-program-list class="data-grid"></div><div class="actions"><button data-program-prev>Previous</button><span data-program-page></span><button data-program-next>Next</button></div>
    <section data-program-workspace hidden class="panel"><nav class="program-breadcrumbs" aria-label="Breadcrumb"><button data-program-back>Programs</button><span aria-hidden="true">/</span><strong data-program-crumb></strong><span data-program-section-crumb-wrap><span aria-hidden="true">/</span> <span data-program-section-crumb></span></span></nav><div class="section-heading"><div><p class="eyebrow">PROGRAM WORKSPACE</p><h3 data-program-title></h3></div><button data-program-close>Back to Programs</button></div><nav class="actions program-primary-nav" aria-label="Program sections"><button data-program-tab="overview">Overview</button><button data-program-tab="create-exam">Create exam</button><button data-program-tab="papers">Papers</button><button data-program-tab="setup">Program setup</button></nav><details class="program-advanced"><summary>Advanced program workspace</summary><p class="muted">Curriculum, versioned blueprints, evidence, prompts and audit history.</p><nav class="actions" aria-label="Advanced program sections"><button data-program-tab="EXAM_PATTERN">Patterns</button><button data-program-tab="EXAM_GENERATOR">Exam blueprints</button><button data-program-tab="QUESTION_GENERATOR">Question blueprints</button><button data-program-tab="curriculum">Curriculum</button><button data-program-tab="evidence">Historical evidence</button><button data-program-tab="blueprint-papers">Blueprint paper runs</button><button data-program-tab="gemini">Gemini &amp; prompts</button><button data-program-tab="audit">Audit</button></nav></details><div data-program-content></div></section>
    <dialog data-program-editor><form method="dialog"><button aria-label="Close editor">×</button></form><h3 data-editor-title></h3><form data-program-form class="compact-form"><label>Stable code<input name="code" pattern="[A-Z][A-Z0-9_]{1,63}" required></label><label>Name<input name="name" maxlength="200" required></label><label class="wide">Description<textarea name="description" maxlength="4000"></textarea></label><label>Conducting authority<input name="authority"></label><label>Region<input name="region"></label><label>Category<input name="category"></label><label>Levels (comma separated)<input name="levels"></label><label>Languages (comma separated)<input name="languages"></label><label>Tags (comma separated)<input name="tags"></label><label>Status<select name="status"><option>ACTIVE</option><option>INACTIVE</option></select></label><button class="primary">Save program</button><p data-editor-status role="status"></p></form></dialog>`;
  const main=document.getElementById('main-content'); main.insertBefore(panel,main.querySelector('footer'));
  matchMedia('(max-width:800px)').addEventListener('change', event => {if(event.matches && !panel.hidden){document.getElementById('app-shell').classList.remove('nav-open');document.getElementById('sidebar-toggle').setAttribute('aria-expanded','false');}});
  const find = selector => panel.querySelector(selector);
  const programNav=find('[aria-label="Program sections"]');programNav.classList.add('workspace-tabs');
  const escape = value => { const node = document.createElement('span'); node.textContent = String(value ?? ''); return node.innerHTML.replaceAll('"', '&quot;').replaceAll("'", '&#39;'); };
  let offset = 0, items = [], current = null, editing = null, listScroll = 0, restoring = false;
  const sectionLabels={overview:'Overview','create-exam':'Create exam',papers:'Papers',setup:'Program setup',EXAM_PATTERN:'Patterns',EXAM_GENERATOR:'Exam blueprints',QUESTION_GENERATOR:'Question blueprints',curriculum:'Curriculum',evidence:'Historical evidence','blueprint-papers':'Blueprint paper runs',gemini:'Gemini & prompts',audit:'Audit'};
  function setRoute(tab,mode='push',paperId){
    if(restoring||location.pathname!=='/app'||!current)return;
    const url=new URL(location.href);url.searchParams.set('view','programs');url.searchParams.set('program',current.id);url.searchParams.set('section',tab);
    if(paperId)url.searchParams.set('paper',paperId);else url.searchParams.delete('paper');
    const next=url.pathname+url.search+url.hash;if(next!==location.pathname+location.search+location.hash)history[mode==='replace'?'replaceState':'pushState']({view:'programs',program:current.id,section:tab},'',next);
  }
  function clearProgramRoute(mode='push'){
    const url=new URL(location.href);url.searchParams.set('view','programs');for(const key of ['program','section','paper'])url.searchParams.delete(key);
    const next=url.pathname+url.search+url.hash;if(next!==location.pathname+location.search+location.hash)history[mode==='replace'?'replaceState':'pushState']({view:'programs'},'',next);
  }
  async function request(path, method = 'GET', payload) {
    return api('/api/programs' + path, {method, ...(payload ? {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)} : {})});
  }
  async function load() {
    const status = find('[data-program-status]'); status.textContent = 'Loading programs…';
    try {
      const query = new URLSearchParams(new FormData(find('[data-program-search]'))); query.set('offset', offset);
      const data = await request('?' + query); items = data.items;
      find('[data-program-list]').innerHTML = items.map(p => `<article class="exam-tile"><span class="badge">${escape(p.status)}</span><h3>${escape(p.name)}</h3><div class="rich-description rendered">${toHtml(p.payload.description || 'No description provided.')}</div>${ProgramParticipation.html(p,{fallback:true})}<p>Full exam or subject-wise · Five difficulty levels</p><div class="actions"><button class="primary" data-program-open="${p.id}">${p.status === 'ARCHIVED' ? 'View archived program' : 'Open program'}</button>${p.status === 'ARCHIVED' ? '' : `<button data-program-edit="${p.id}">Edit</button>`}<button data-program-state="${p.id}">${p.status === 'ARCHIVED' ? 'Restore' : 'Delete / archive'}</button></div></article>`).join('') || '<p class="empty-state">No programs match this search. Try another name or status.</p>';
      find('[data-program-page]').textContent = `${data.total ? offset + 1 : 0}–${offset + items.length} of ${data.total}`;
      find('[data-program-prev]').disabled = offset === 0; find('[data-program-next]').disabled = offset + items.length >= data.total;
      find('[data-program-list]').querySelectorAll('.rich-description').forEach(typeset);
      status.textContent = '';
    } catch (error) { status.textContent = error.message; }
  }
  function edit(program) {
    editing = program; const form = find('[data-program-form]'); form.reset();
    find('[data-editor-title]').textContent = program ? 'Edit program' : 'Add program';
    const payload = program?.payload || {};
    for (const name of ['code','name','description','authority','region','category','levels','languages','tags','status']) {
      form.elements[name].value = Array.isArray(payload[name]) ? payload[name].join(', ') : (payload[name] || (name === 'status' ? 'ACTIVE' : ''));
    }
    form.elements.code.readOnly = !!program;
    find('[data-editor-status]').textContent = ''; find('[data-program-editor]').showModal();
  }
  async function workspace(tab = 'overview', options={}) {
    const content = find('[data-program-content]'); content.textContent = 'Loading…';
    try {
      if(!options.restore)setRoute(tab,options.history||'push',options.paperId);
      find('[data-program-workspace]').dataset.activeSection=tab;
      panel.querySelectorAll('[data-program-tab]').forEach(b=>b.setAttribute('aria-current',String(b.dataset.programTab===tab)));
      current = await request('/' + current.id); find('[data-program-title]').textContent = current.name;
      find('[data-program-crumb]').textContent=current.name;find('[data-program-section-crumb]').textContent=sectionLabels[tab]||tab;
      find('[data-program-workspace]').hidden = false;
      find('[data-program-search]').hidden=true;find('[data-program-list]').hidden=true;find('[data-program-prev]').parentElement.hidden=true;
      if (tab === 'create-exam') {await ProgramExam.render(content,current,request,{onPaperChange:id=>setRoute('create-exam','replace',id),onManageExams:openManageExams});return;}
      if (tab === 'papers') {const paperId=options.paperId||Number(new URL(location.href).searchParams.get('paper'))||null;await ProgramExam.render(content,current,request,{reviewOnly:true,paperId,onPaperChange:id=>setRoute('papers','replace',id),onManageExams:openManageExams});if(paperId){const all=document.createElement('button');all.type='button';all.textContent='View all papers';all.onclick=()=>workspace('papers',{history:'replace',paperId:null});content.prepend(all);}return;}
      if (tab === 'overview') {
        const [papers,setups]=await Promise.all([request('/'+current.id+'/exam-papers'),request('/'+current.id+'/setup')]);
        const active=papers.filter(p=>['QUEUED','RUNNING'].includes(p.status)),review=papers.filter(p=>['REVIEW_REQUIRED','DRAFT'].includes(p.status)),published=papers.filter(p=>p.status==='PUBLISHED');
        content.innerHTML = `<section class="program-overview-hero"><div class="rich-description rendered">${toHtml(current.payload.description || 'No description provided.')}</div>${ProgramParticipation.html(current,{fallback:true})}</section><div class="metric-strip program-readiness"><div><span>In progress</span><strong>${active.length}</strong></div><div><span>Needs review</span><strong>${review.length}</strong></div><div><span>Published</span><strong>${published.length}</strong></div><div><span>Program setup</span><strong>${setups.some(s=>s.status==='APPLIED')?'Ready':'Not applied'}</strong></div></div><div class="program-next-actions"><button class="primary" data-program-tab="create-exam">Create a program exam</button>${active.length||review.length?'<button data-program-tab="papers">Continue papers</button>':''}${setups.some(s=>s.status==='APPLIED')?'':'<button data-program-tab="setup">Generate program setup</button>'}<button data-program-manage-exams>Manage published exams</button></div><dl><dt>Authority</dt><dd>${escape(current.payload.authority || 'Not specified')}</dd><dt>Revision</dt><dd>${current.revision}</dd><dt>Status</dt><dd>${escape(current.status)}</dd></dl>`;
        content.querySelector('[data-program-manage-exams]').onclick=openManageExams;return;
      }
      if (tab === 'setup') {await ProgramSetup.render(content,current,request);return;}
      if (tab === 'audit') {
        const rows = await request('/' + current.id + '/audit');
        content.innerHTML = '<ol>' + rows.map(r => `<li><strong>${escape(r.action)}</strong> · ${escape(new Date(r.created_at * 1000).toLocaleString())}</li>`).join('') + '</ol>'; return;
      }
      if (['curriculum','evidence','gemini','blueprint-papers'].includes(tab)) {const target=tab==='blueprint-papers'?'papers':tab;await BlueprintWorkspace.render(content, current.id, target, request); if(tab==='evidence')await ProgramSetup.evidence(content,current.id,request); return;}
      const rows = (await request('/' + current.id + '/blueprints')).filter(r => r.kind === tab);
      content.innerHTML = `<p>Each save creates a new immutable payload. Publication is a separate reviewed action.</p><button data-blueprint-new="${tab}">Create blueprint</button><div class="data-grid">${rows.map(b => `<article class="exam-tile"><h4>${escape(b.name)}</h4><span>${b.revision} versions</span><button data-blueprint-open="${b.id}">Edit / versions</button></article>`).join('')}</div><div data-blueprint-detail></div>`;
      content.querySelector('[data-blueprint-new]').onclick = () => blueprintEditor({kind:tab, name:'', revision:0});
      content.querySelectorAll('[data-blueprint-open]').forEach(b => b.onclick = () => blueprintEditor(rows.find(r => r.id === Number(b.dataset.blueprintOpen))));
    } catch (error) { content.textContent = error.message; }
  }
  function openManageExams(){
    sessionStorage.setItem('meritiqra_program_origin',JSON.stringify({id:current.id,name:current.name,section:'papers'}));
    const url=new URL(location.href);url.searchParams.set('view','admin-exams');url.searchParams.set('program',current.id);url.searchParams.set('section','papers');url.searchParams.delete('paper');history.pushState({view:'admin-exams'},'',url.pathname+url.search);showView('admin-exams',{history:'none'});renderReturnToProgram();
  }
  async function restoreRoute(){
    const url=new URL(location.href),pid=Number(url.searchParams.get('program')),section=url.searchParams.get('section')||'overview';
    if(find('[data-program-workspace]').hidden===false&&current&&String(current.id)===String(pid)&&find('[data-program-workspace]').dataset.activeSection===section)return;
    await load();if(!pid){find('[data-program-workspace]').hidden=true;find('[data-program-search]').hidden=false;find('[data-program-list]').hidden=false;find('[data-program-prev]').parentElement.hidden=false;return;}
    try{current=await request('/'+pid);restoring=true;await workspace(section,{restore:true,paperId:Number(url.searchParams.get('paper'))||null});}
    catch(error){find('[data-program-status]').textContent='That program location is no longer available. '+error.message;clearProgramRoute('replace');}
    finally{restoring=false;}
  }
  async function blueprintEditor(bp) {
    const target = find('[data-blueprint-detail]'); target.textContent = 'Loading versions…';
    try {
      const versions = bp.id ? await request(`/${current.id}/blueprints/${bp.id}/versions`) : [];
      const sample = bp.kind === 'QUESTION_GENERATOR' ? {schema_version:1,scope:'PROGRAM',overrides:{}} : {};
      target.innerHTML = `<h4>${escape(bp.name || 'New ' + bp.kind.toLowerCase().replaceAll('_',' '))}</h4><form data-blueprint-form><label>Name<input name="name" value="${escape(bp.name)}" required maxlength="200" ${bp.id?'readonly':''}></label><div data-structured-editor></div><details><summary>Advanced JSON import / export</summary><label>Version payload<textarea name="payload" rows="16" spellcheck="false"></textarea></label><button type="button" data-json-import>Load JSON into editor</button><button type="button" data-json-export>Export editor to JSON</button></details><label>Change summary<input name="summary" required maxlength="2000"></label><button class="primary">Save new draft version</button><p role="status" data-blueprint-status></p></form><div data-version-list>${versions.map(v => `<article class="panel"><strong>Version ${v.version_number} · ${escape(v.status)}</strong><p>${escape(v.summary)}</p><span> · ID ${v.id}</span><button type="button" data-version-clone="${v.id}">Clone</button><button data-version-view="${v.id}">View payload</button>${bp.kind==='QUESTION_GENERATOR'?`<button type="button" data-version-effective="${v.id}">Effective profiles</button>`:''}${v.status==='DRAFT'?`<button data-version-transition="${v.id}" data-old="DRAFT" data-next="IN_REVIEW">Submit for review</button>`:v.status==='IN_REVIEW'?`<button data-version-transition="${v.id}" data-old="IN_REVIEW" data-next="PUBLISHED">Publish</button>`:v.status==='PUBLISHED'?`<button data-version-transition="${v.id}" data-old="PUBLISHED" data-next="RETIRED">Retire</button>`:''}</article>`).join('')}</div>`;
      const form = target.querySelector('form'); const schemas = await request('/contracts/all');
      let structured = BlueprintForms.editor(target.querySelector('[data-structured-editor]'), schemas[bp.kind], versions[0]?.payload || sample);
      form.elements.payload.value = JSON.stringify(versions[0]?.payload || sample, null, 2);
      target.querySelector('[data-json-import]').onclick = () => {try {structured = BlueprintForms.editor(target.querySelector('[data-structured-editor]'), schemas[bp.kind], JSON.parse(form.elements.payload.value));} catch(error) {target.querySelector('[data-blueprint-status]').textContent=error.message;}};
      target.querySelector('[data-json-export]').onclick = () => {form.elements.payload.value=JSON.stringify(structured.read(),null,2);};
      form.onsubmit = async event => { event.preventDefault(); const status=target.querySelector('[data-blueprint-status]'); try {
        const payload = structured.read(), summary = form.elements.summary.value;
        await request(`/${current.id}/blueprints${bp.id ? '/' + bp.id + '/versions' : ''}`, 'POST', bp.id ? {revision:bp.revision,payload,summary} : {kind:bp.kind,name:form.elements.name.value,payload,summary});
        await workspace(bp.kind);
      } catch(error) {status.textContent=error.message;} };
      target.querySelectorAll('[data-version-view]').forEach(b => b.onclick = () => { const payload=versions.find(v=>v.id===Number(b.dataset.versionView)).payload; form.elements.payload.value=JSON.stringify(payload,null,2); structured=BlueprintForms.editor(target.querySelector('[data-structured-editor]'),schemas[bp.kind],payload); });
      if(versions.length>1){const button=document.createElement('button');button.type='button';button.textContent='Compare latest two versions';target.append(button);button.onclick=async()=>{try{const diff=await request(`/${current.id}/blueprints/${bp.id}/compare?left=${versions[1].id}&right=${versions[0].id}`);const view=document.createElement('pre');view.textContent=JSON.stringify(diff.changes,null,2);target.append(view);}catch(error){target.querySelector('[data-blueprint-status]').textContent=error.message;}};}
      target.querySelectorAll('[data-version-clone]').forEach(b=>b.onclick=async()=>{const name=prompt('Name for the cloned blueprint',bp.name+' copy');if(!name)return;try{await request(`/${current.id}/blueprints/${bp.id}/clone?version_id=${b.dataset.versionClone}&name=${encodeURIComponent(name)}`,'POST');await workspace(bp.kind);}catch(error){target.querySelector('[data-blueprint-status]').textContent=error.message;}});
      target.querySelectorAll('[data-version-effective]').forEach(b => b.onclick = async () => {try {const data=await request(`/${current.id}/blueprints/${bp.id}/effective/${b.dataset.versionEffective}`); let view=target.querySelector('[data-effective-view]'); if(!view){view=document.createElement('pre');view.dataset.effectiveView='';target.append(view);} view.textContent=JSON.stringify(data,null,2);}catch(error){target.querySelector('[data-blueprint-status]').textContent=error.message;}});
      target.querySelectorAll('[data-version-transition]').forEach(b => b.onclick = async () => { if (!confirm(`${b.dataset.next} this blueprint version?`)) return; try {
        await request(`/${current.id}/blueprints/${bp.id}/versions/${b.dataset.versionTransition}/transition`,'POST',{status:b.dataset.next,expected_status:b.dataset.old,reason:'Reviewed in Programs workspace'}); await blueprintEditor(bp);
      } catch(error) {target.querySelector('[data-blueprint-status]').textContent=error.message;} });
    } catch(error) {target.textContent=error.message;}
  }
  const programForm=find('[data-program-form]');const extra=document.createElement('details');extra.className='wide';const extraTitle=document.createElement('summary');extraTitle.textContent='Optional program details';extra.append(extraTitle);const nameLabel=programForm.elements.name.parentElement;programForm.prepend(nameLabel);for(const input of [...programForm.querySelectorAll('label')])if(input!==nameLabel)extra.append(input);nameLabel.after(extra);programForm.elements.code.required=false;programForm.elements.name.required=true;programForm.elements.name.placeholder='For example: Navodaya';
  find('[data-program-form]').onsubmit = async event => { event.preventDefault(); const payload = Object.fromEntries(new FormData(event.target));
    if(!payload.code)payload.code='PROGRAM_'+crypto.randomUUID().replaceAll('-','').slice(0,12).toUpperCase();
    for (const field of ['levels','languages','tags']) payload[field] = payload[field].split(',').map(s=>s.trim()).filter(Boolean);
    try { const saved=await request(editing ? `/${editing.id}?revision=${editing.revision}` : '', editing ? 'PUT':'POST', payload); find('[data-program-editor]').close(); await load(); if(!editing){current=saved;await workspace('overview');} }
    catch(error) { find('[data-editor-status]').textContent=error.message; }
  };
  find('[data-program-search]').onsubmit = event => { event.preventDefault(); offset=0; load(); };
  find('[data-program-prev]').onclick = () => {offset=Math.max(0,offset-25);load();};
  find('[data-program-next]').onclick = () => {offset+=25;load();};
  panel.addEventListener('click', async event => { const b=event.target.closest('button'); if(!b)return;
    if(b.hasAttribute('data-program-add')) edit(null);
    if(b.dataset.programEdit) edit(items.find(p=>p.id===Number(b.dataset.programEdit)));
    if(b.dataset.programOpen) {listScroll=window.scrollY;current=items.find(p=>p.id===Number(b.dataset.programOpen));workspace('overview');}
    if(b.hasAttribute('data-program-close')||b.hasAttribute('data-program-back')) {find('[data-program-workspace]').hidden=true;find('[data-program-search]').hidden=false;find('[data-program-list]').hidden=false;find('[data-program-prev]').parentElement.hidden=false;clearProgramRoute();requestAnimationFrame(()=>window.scrollTo({top:listScroll,behavior:'instant'}));}
    if(b.dataset.programTab) workspace(b.dataset.programTab);
    if(b.dataset.programState) {const p=items.find(p=>p.id===Number(b.dataset.programState));if(!confirm(`${p.status==='ARCHIVED'?'Restore':'Delete / archive'} ${p.name}? Blueprint history is retained.`))return;
      try {await request(`/${p.id}${p.status==='ARCHIVED'?'/restore':''}?revision=${p.revision}`,p.status==='ARCHIVED'?'POST':'DELETE');await load();if(current?.id===p.id)await workspace();} catch(error){find('[data-program-status]').textContent=error.message;}}
  });
  panel.addEventListener('program-restored',load);
  document.addEventListener('workspace:view-changed',event=>{if(event.detail.name==='programs')restoreRoute();else if(event.detail.name==='admin-exams')renderReturnToProgram();});
  function renderReturnToProgram(){
    const host=document.getElementById('admin-exams-panel');if(!host)return;host.querySelector('[data-return-program]')?.remove();
    const url=new URL(location.href),pid=Number(url.searchParams.get('program'));let origin=null;try{origin=JSON.parse(sessionStorage.getItem('meritiqra_program_origin')||'null');}catch{}
    if(!pid||!origin||Number(origin.id)!==pid)return;
    const bar=document.createElement('nav');bar.dataset.returnProgram='';bar.className='program-return-banner';bar.setAttribute('aria-label','Return to program');bar.innerHTML=`<button type="button">← Back to ${escape(origin.name)}</button><span>Manage exams opened from this program.</span>`;
    bar.querySelector('button').onclick=()=>{const target=new URL('/app',location.origin);target.searchParams.set('view','programs');target.searchParams.set('program',pid);target.searchParams.set('section',origin.section||'papers');history.pushState({view:'programs'},'',target.pathname+target.search);showView('programs',{history:'none'});};host.prepend(bar);
  }
  if(!panel.hidden)restoreRoute();
})();
