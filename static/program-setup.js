/* Minimal-input program setup. Model output is always rendered as text. */
window.ProgramSetup = (() => {
  async function render(host, program, request) {
    host.replaceChildren();
    const add = (tag, text, parent = host) => {const el=document.createElement(tag);el.textContent=text;parent.append(el);return el;};
    add('h4','Generate program setup with Gemini');
    add('p',`Start with ${program.name}. Add an exam or class if you want a specific variant. Review one proposal to populate the program workspace.`);
    const form=add('form','');form.className='compact-form';
    function input(label,name,value,placeholder) {const wrapper=add('label',label,form),el=add('input','',wrapper);el.name=name;el.value=value;el.placeholder=placeholder;return el;}
    const exam=input('Exam / class (optional)','exam_class','','For example: JNVST Class VI');exam.maxLength=200;
    const language=input('Language','language',program.payload.languages?.[0]||'English','English');language.required=true;language.maxLength=100;
    const notes=input('Additional guidance (optional)','notes','','Subjects or learning goals');notes.maxLength=1500;
    const submit=add('button','Generate setup',form);submit.className='primary';submit.type='submit';
    const status=add('p','');status.setAttribute('role','status');
    const jobs=add('div','');jobs.className='program-setup-results';
    let timer;
    async function refresh() {
      clearTimeout(timer);
      const rows=await request(`/${program.id}/setup`);
      if(!jobs.isConnected)return;
      jobs.replaceChildren();
      for(const row of rows) {
        const card=add('article','',jobs);card.className='panel program-setup-card';
        add('h4',`Setup #${row.id} · ${row.status.replaceAll('_',' ')}`,card);
        if(row.status==='QUEUED'||row.status==='RUNNING')add('p','Gemini is preparing the workspace. You can leave this tab and return later.',card);
        if(row.error)add('p',row.error,card);
        if(row.status==='FAILED'||(['RUNNING','QUEUED'].includes(row.status)&&Date.now()/1000-row.updated_at>600)) {
          const retry=add('button','Retry setup',card);retry.onclick=async()=>{retry.disabled=true;try{await request(`/${program.id}/setup/${row.id}/retry`,'POST');await refresh();}catch(error){status.textContent=error.message;retry.disabled=false;}};
        }
        if(['READY','APPLIED'].includes(row.status)) {
          const p=row.proposal;
          const description=add('div','',card);description.className='rich-description rendered';renderInto(description,p.description||'');
          add('p',`${p.variant} · ${p.level} · ${row.input.language}`,card);
          const summary=add('div','',card);summary.className='data-grid';
          add('p',`${p.subjects.length} subjects · ${p.subjects.reduce((n,s)=>n+s.chapters.length,0)} chapters`,summary);
          add('p','Five difficulty profiles · Ten prompt templates',summary);
          add('p',`${p.sections.reduce((n,s)=>n+s.question_count,0)} practice questions · Draft paper preview`,summary);
          add('strong','Practice sample only: question counts, marks and timing are not verified official exam rules.',card);
          const details=add('details','',card);add('summary','Review suggested curriculum and difficulty profiles',details);
          for(const subject of p.subjects) {
            add('h5',subject.name,details);
            for(const chapter of subject.chapters)add('p',`${chapter.name}: ${chapter.topics.join(', ')}`,details);
          }
          for(const profile of p.profiles)add('p',`${profile.difficulty.replaceAll('_',' ')}: ${profile.reasoning_steps} reasoning steps; ${profile.distractor_strategy}`,details);
          add('h5','Assumptions to review',card);const assumptions=add('ul','',card);p.assumptions.forEach(v=>add('li',v,assumptions));
          add('h5','Evidence still needed',card);const evidence=add('ul','',card);p.evidence_needed.forEach(v=>add('li',v,evidence));
          add('p','Real source documents and reviewed paper questions are needed to calculate historical analytics.',card);
          if(row.status==='READY') {
            const apply=add('button','Apply setup as drafts',card);apply.className='primary';
            apply.onclick=async()=>{
              if(!confirm('Apply this reviewed setup? This updates program details and adds draft curriculum, blueprints, prompts and a practice preview. Existing blueprint versions are retained.'))return;
              apply.disabled=true;status.textContent='Saving program setup…';
              try {await request(`/${program.id}/setup/${row.id}/apply`,'POST');status.textContent='Setup applied. Open the tabs below to review or edit the drafts.';await refresh();}
              catch(error){status.textContent=error.message;apply.disabled=false;}
            };
          } else {
            add('p',`Drafts saved · ${row.result.question_version_ids.length} question blueprints · Paper preview #${row.result.paper_run_id}`,card);
            const actions=add('div','',card);actions.className='actions';
            for(const [tab,label] of [['overview','Program details'],['EXAM_PATTERN','Patterns'],['EXAM_GENERATOR','Exam blueprints'],['QUESTION_GENERATOR','Question blueprints'],['curriculum','Curriculum'],['evidence','Evidence'],['gemini','Prompts'],['papers','Paper preview'],['audit','Audit']]) {
              const b=add('button',label,actions);b.dataset.programTab=tab;
            }
          }
        }
      }
      if(rows.some(r=>['QUEUED','RUNNING'].includes(r.status)))timer=setTimeout(()=>{if(jobs.isConnected)refresh().catch(e=>{status.textContent=e.message;});},3000);
    }
    form.onsubmit=async event=>{
      event.preventDefault();submit.disabled=true;status.textContent='Requesting program setup…';
      try{await request(`/${program.id}/setup`,'POST',{exam_class:exam.value,language:language.value,notes:notes.value,request_key:crypto.randomUUID()});status.textContent='';await refresh();}
      catch(error){status.textContent=error.message;}finally{submit.disabled=false;}
    };
    await refresh();
  }
  async function evidence(host,pid,request) {
    const rows=await request(`/${pid}/setup`);const latest=rows.find(r=>r.status==='APPLIED');if(!latest)return;
    const box=document.createElement('aside');box.className='panel';
    const title=document.createElement('h4');title.textContent='Evidence checklist from program setup';box.append(title);
    for(const value of latest.result.evidence_needed){const p=document.createElement('p');p.textContent=value;box.append(p);}
    host.append(box);
  }
  return {render,evidence};
})();
