window.BlueprintWorkspace = (() => {
  async function render(host, pid, tab, request) {
    host.replaceChildren(); const schemas=await request('/contracts/all');
    const status=document.createElement('p');status.setAttribute('role','status');host.append(status);
    const text=(tag,value,parent=host)=>{const n=document.createElement(tag);n.textContent=value;parent.append(n);return n;};
    const action=(name,callback,parent=host)=>{const b=text('button',name,parent);b.type='button';b.onclick=async()=>{b.disabled=true;try{await callback();}catch(error){status.textContent=error.message;}finally{b.disabled=false;}};return b;};
    function form(name,contract,path,initial={},parent=host,onDone) {
      const detail=document.createElement('details');parent.append(detail);text('summary',name,detail);
      const f=document.createElement('form'), fields=document.createElement('div');f.append(fields);detail.append(f);
      const edit=BlueprintForms.editor(fields,schemas[contract],initial),submit=text('button','Save',f);
      submit.type='submit';f.onsubmit=async e=>{e.preventDefault();submit.disabled=true;status.textContent='Saving…';try{const result=await request(`/${pid}/${path}`,'POST',edit.read());if(onDone)await onDone(result);else await render(host,pid,tab,request);}catch(error){status.textContent=error.message;}finally{submit.disabled=false;}};
    }
    if(tab==='curriculum') {
      text('h4','Curriculum versions');form('Create curriculum','Curriculum','curricula');
      for(const c of await request(`/${pid}/curricula`)) {
        const box=document.createElement('article');box.className='panel';host.append(box);text('h4',`${c.name} · ID ${c.id} · ${c.status}`,box);
        for(const node of c.nodes)text('p',`#${node.id} ${node.kind}: ${node.name}${node.parent_id?' · parent #'+node.parent_id:''}`,box);
        if(c.status==='DRAFT'){form('Add curriculum node','Node',`curricula/${c.id}/nodes`,{},box);action('Publish curriculum',async()=>{if(confirm('Freeze and publish this curriculum version?')){await request(`/${pid}/curricula/${c.id}/publish`,'POST');await render(host,pid,tab,request);}},box);}
      }
    }
    if(tab==='evidence') {
      text('h4','Evidence and historical profiles');text('p','Register an authorized source link and its SHA-256 hash. A reviewer must verify the source and checksum before inclusion. Historical statistics use only approved paper classifications.');
      form('Register evidence','Evidence','sources');
      for(const source of await request(`/${pid}/sources`)) {
        const box=document.createElement('article');box.className='panel';host.append(box);text('h4',`#${source.id} ${source.payload.filename} · ${source.review_status}`,box);text('p',`${source.kind} · ${source.included?'Included':'Excluded'} · ${source.sha256}`,box);form('Review / include or exclude','EvidenceReview',`sources/${source.id}/review`,{},box);
      }
      form('Classify a historical paper question','HistoricalObservation','historical-observations');
      for(const row of await request(`/${pid}/historical-observations`)) {
        const box=document.createElement('article');box.className='panel';host.append(box);text('h4',`#${row.id} Paper ${row.source_id}, question ${row.source_question_ref} · ${row.review_status}`,box);text('p',`${row.payload.subject} / ${row.payload.topic} · ${row.payload.difficulty}`,box);form('Review classification','ClassificationReview',`historical-observations/${row.id}/review`,{},box);
      }
      form('Build immutable historical profile','Profile','historical-profiles',{reference_year:new Date().getFullYear(),half_life_years:5});
      for(const profile of await request(`/${pid}/historical-profiles`)){text('h4',`Profile #${profile.id} · ${profile.payload.sample_size} reviewed questions`);text('pre',JSON.stringify(profile.payload,null,2));}
    }
    if(tab==='papers') {
      text('h4','Reviewed inventory and paper generation');
      text('p','Imported question text must match its exact source version. Taxonomy mapping and academic approval are separate from source verification. Sample previews cannot become approved papers.');
      form('Add manual draft / link existing question version','Inventory','inventory');
      for(const q of await request(`/${pid}/inventory`)) {
        const box=document.createElement('article');box.className='panel';host.append(box);
        text('h4',`Snapshot #${q.id} · ${q.payload.subject} · ${q.payload.difficulty}`,box);
        text('p',`${q.origin} · Academic: ${q.academic_status} · Source: ${q.transcription_status} · Exposure: ${q.exposure}`,box);
        const details=document.createElement('details');box.append(details);text('summary','Question, answer and provenance',details);text('pre',JSON.stringify({question:q.payload,provenance:q.provenance},null,2),details);
        form('Review question','InventoryReview',`inventory/${q.id}/review`,{},box);
      }
      form('Check feasibility','Run','paper-feasibility',{},host,async result=>{let view=host.querySelector('[data-feasibility]');if(!view){view=document.createElement('div');view.dataset.feasibility='';host.append(view);}view.replaceChildren();text('h4',result.feasible?'Inventory is feasible':'Inventory gaps require review',view);const table=document.createElement('table');view.append(table);for(const values of [['Scope','Required','Available','Missing','Action'],...result.matrix.map(r=>[r.scope,r.required,r.approved_available,r.missing,r.action])]){const tr=document.createElement('tr');table.append(tr);values.forEach(v=>text('td',v,tr));}status.textContent='Feasibility checked.';});
      form('Freeze a paper run','Run','paper-runs');
      for(const run of await request(`/${pid}/paper-runs`)) {
        const box=document.createElement('article');box.className='panel';host.append(box);text('h4',`Run #${run.id} · ${run.status}${run.payload.sample_preview?' · SAMPLE ONLY':''}`,box);
        text('p',`${run.payload.selected.length} selected · ${run.payload.gaps.length} missing · Seed ${run.payload.seed}`,box);
        const detail=document.createElement('details');box.append(detail);text('summary','Frozen run and question snapshots',detail);text('pre',JSON.stringify(run.payload,null,2),detail);
        if(run.status==='DRAFT') {form('Review paper','ClassificationReview',`paper-runs/${run.id}/approve`,{},box);if(run.payload.gaps.length)form('Generate a missing question draft','GenerateGap',`paper-runs/${run.id}/generate-missing`,{},box);}
      }
      action('Refresh generation jobs',()=>render(host,pid,tab,request));
      for(const job of await request(`/${pid}/generation-jobs`)){text('h4',`Job #${job.id} · Run #${job.run_id} slot ${job.slot_position} · ${job.status}`);text('p',job.error||JSON.stringify(job.result));}
      text('p','After approving new inventory, create a new paper run. Earlier runs stay unchanged.');
    }
    if(tab==='gemini') {
      text('h4','Versioned prompts and Gemini refinement');text('p','Gemini proposes changes to soft authoring fields. Official exam facts stay fixed. Review each change before saving a new draft.');
      const registry=await request(`/${pid}/prompts`);schemas.Prompt.properties.purpose.enum=registry.purposes;
      form('Create prompt version','Prompt','prompts');
      for(const p of registry.items){const detail=document.createElement('details');host.append(detail);text('summary',`#${p.id} ${p.purpose} · v${p.version_number}`,detail);text('pre',p.template,detail);}
      form('Refine with Gemini','Refine','refinements');action('Refresh proposals',()=>render(host,pid,tab,request));
      for(const r of await request(`/${pid}/refinements`)) {
        const box=document.createElement('article');box.className='panel';host.append(box);text('h4',`Proposal #${r.id} · blueprint version #${r.blueprint_version_id} · ${r.status}`,box);
        if(r.error)text('p',r.error,box);for(const warning of r.proposal.warnings||[])text('p',warning,box);
        const selected=[];
        (r.proposal.patches||[]).forEach((patch,index)=>{const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.disabled=r.status!=='READY';label.append(check,document.createTextNode(patch.path));box.append(label);selected.push(check);text('pre',`${JSON.stringify(patch.old)} → ${JSON.stringify(patch.new)}`,box);text('p',`${patch.reason} · Confidence ${patch.confidence} · ${patch.impact} · Evidence ${patch.evidence_source_ids.join(', ')}`,box);});
        if(r.status==='READY')action('Save reviewed changes as new draft',async()=>{const blueprints=await request(`/${pid}/blueprints`);let bp;for(const b of blueprints){const versions=await request(`/${pid}/blueprints/${b.id}/versions`);if(versions.some(v=>v.id===r.blueprint_version_id)){bp=b;break;}}if(!bp)throw Error('Blueprint not found');const reason=prompt('Review reason (including rejected fields)');if(!reason)return;await request(`/${pid}/refinements/${r.id}/accept`,'POST',{accepted_indices:selected.flatMap((c,i)=>c.checked?[i]:[]),revision:bp.revision,reason,training_eligible:false});await render(host,pid,tab,request);},box);
      }
    }
  }
  return {render};
})();
