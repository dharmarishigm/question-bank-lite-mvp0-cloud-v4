/* Compact history filters and the shared program-paper publication workflow. */
(() => {
  const filters=$('ai-run-filters');
  filters?.addEventListener('submit',event=>{event.preventDefault();aiRunOffset=0;loadAiGenerationRuns();});
  filters?.addEventListener('reset',()=>{setTimeout(()=>{aiRunOffset=0;loadAiGenerationRuns();},0);});
  $('ai-runs-prev')?.addEventListener('click',()=>{aiRunOffset=Math.max(0,aiRunOffset-25);loadAiGenerationRuns();});
  $('ai-runs-next')?.addEventListener('click',()=>{aiRunOffset+=25;loadAiGenerationRuns();});
  let offset=0,version=0;
  async function refresh(){
    const host=$('admin-publishing');if(!host)return;const current=++version;
    host.innerHTML='<p role="status">Loading publication queue…</p>';
    try{
      const data=await api(`/api/programs/papers/review-queue?offset=${offset}&limit=12`);if(current!==version)return;
      if(!data.items.length&&offset){offset=0;return refresh();}
      host.innerHTML=`<div class="section-heading"><div><h3>Ready for review &amp; publish <span class="badge">${data.total}</span></h3><p>Completed program papers. Review questions and confirm before publishing.</p></div><button data-publishing-refresh>Refresh</button></div><div class="publishing-grid">${data.items.map(row=>`<article class="publishing-card"><div><span class="badge">${row.status==='DRAFT'?'Approved draft':'Needs review'}</span><h4>${esc(row.name)}</h4><small>${esc(row.program_name)} · Paper #${row.id}</small><p>${row.question_count} questions · ${row.duration_minutes} min · ${row.mode==='FULL'?'Full Exam':esc(row.subjects.join(', '))}</p></div><button class="primary" data-review-program="${row.program_id}" data-review-paper="${row.id}">Review &amp; publish</button></article>`).join('')||'<p class="empty-state">No program papers awaiting publication. Generate a paper in Programs; completed papers will appear here.</p>'}</div><nav class="pagination" aria-label="Publication queue pages"><span>${data.total?`${offset+1}–${offset+data.items.length} of ${data.total}`:'0 papers'}</span><div><button data-publishing-prev ${offset?'':'disabled'}>Previous</button><button data-publishing-next ${offset+data.items.length<data.total?'':'disabled'}>Next</button></div></nav>`;
    }catch(error){if(current===version)host.innerHTML=`<p role="alert">${esc(error.message)}</p><button data-publishing-refresh>Retry publication queue</button>`;}
  }
  window.AdminPublishing={refresh};
  $('admin-publishing')?.addEventListener('click',async event=>{
    if(event.target.closest('[data-publishing-refresh]')){refresh();return;}
    if(event.target.closest('[data-publishing-prev]')){offset=Math.max(0,offset-12);refresh();return;}
    if(event.target.closest('[data-publishing-next]')){offset+=12;refresh();return;}
    const button=event.target.closest('[data-review-paper]');if(!button)return;button.disabled=true;
    const panel=$('admin-paper-review'),host=$('admin-paper-review-content');
    try{
      const program=await api(`/api/programs/${button.dataset.reviewProgram}`);
      panel.hidden=false;host.textContent='Loading paper…';
      await ProgramExam.render(host,program,(path,method='GET',payload)=>api('/api/programs'+path,{method,...(payload?{headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{})}),{reviewOnly:true,paperId:Number(button.dataset.reviewPaper),onChange:()=>loadAdminExams()});
      panel.scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){notify(error.message);}finally{button.disabled=false;}
  });
  $('admin-review-close')?.addEventListener('click',()=>{$('admin-paper-review').hidden=true;$('admin-paper-review-content').replaceChildren();});
})();
