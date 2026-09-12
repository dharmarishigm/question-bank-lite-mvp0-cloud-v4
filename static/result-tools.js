/* Exam rankings, concern review and individual PDF exports. */
window.ResultTools=(()=>{
  const esc=value=>escapeHtml(String(value??''));
  function dialog(title){
    document.getElementById('result-tools-dialog')?.remove();
    const node=document.createElement('dialog');node.id='result-tools-dialog';node.className='result-tools-dialog';
    node.innerHTML=`<div class="section-heading"><h3>${esc(title)}</h3><button type="button" data-close-result-dialog aria-label="Close">Close</button></div><div data-result-dialog-body></div>`;
    document.body.append(node);node.querySelector('[data-close-result-dialog]').onclick=()=>node.close();node.showModal();return node.querySelector('[data-result-dialog-body]');
  }
  function actions(s){if(signedInUser?.role!=='ADMIN')return `<div class="actions result-tools"><span data-result-rank="${s.id}"></span><button data-exam-leaderboard="${s.exam_id}">Exam leaderboard</button><span class="muted">Protected report · downloads and sharing are disabled</span></div>`;return `<div class="actions result-tools"><span data-result-rank="${s.id}"></span><button data-exam-leaderboard="${s.exam_id}">Exam leaderboard</button><button data-result-pdf="${s.id}">Export report PDF</button><button data-result-share="${s.id}">Share report</button><button data-result-revoke="${s.id}">Revoke report links</button></div>`;}
  async function rank(s,target){
    const block=document.createElement('section');block.className='panel result-subject-breakdown';block.setAttribute('aria-label','Subject and section marks');block.textContent='Loading subject marks…';target.querySelector('.result-hero')?.insertAdjacentElement('afterend',block);
    try{
      const r=await api(`/api/results/${s.id}/report`),node=target.querySelector('[data-result-rank]');if(node)node.textContent=`Best-attempt rank: ${r.rank??'—'} of ${r.participants} · Attempt ${r.rank_attempt_number??'—'}`;
      const number=n=>Number(n||0).toLocaleString(undefined,{maximumFractionDigits:2});
      const table=(title,rows)=>`<h3>${title}</h3><div class="table-wrap" role="region" aria-label="${title}" tabindex="0"><table><thead><tr><th scope="col">${title.startsWith('Subject')?'Subject':'Section'}</th><th scope="col">Marks</th><th scope="col">Percentage</th><th scope="col">Questions</th><th scope="col">Correct</th><th scope="col">Incorrect</th><th scope="col">Unanswered</th></tr></thead><tbody>${rows.map(row=>`<tr><th scope="row">${esc(row.subject)}</th><td>${number(row.score)} / ${number(row.max_score)}</td><td>${number(row.percentage)}%</td><td>${row.questions}</td><td>${row.correct}</td><td>${row.incorrect}</td><td>${row.unanswered}</td></tr>`).join('')}</tbody></table></div>`;
      block.innerHTML=table('Subject-wise marks',r.subjects||[])+(r.sections?.length&&JSON.stringify(r.sections)!==JSON.stringify(r.subjects)?table('Section-wise marks',r.sections):'')+`<p class="muted">Marks include negative marking where applicable. Calculated from the questions and marking scheme used in this attempt.</p>`;
    }catch(error){block.textContent='Unable to load subject marks. ';const retry=document.createElement('button');retry.textContent='Retry';retry.onclick=()=>{block.remove();rank(s,target);};block.append(retry);}
  }
  async function leaderboard(eid){
    const body=dialog('Exam leaderboard');body.textContent='Loading rankings…';
    try{const data=await api(`/api/exams/${eid}/leaderboard`);body.innerHTML=`<h4>${esc(data.exam_name)}</h4><p>${esc(data.ranking_rule)}</p>${!data.released?'<p>Admin preview: results are not released to students.</p>':''}<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Student</th><th>Marks</th><th>Percentage</th><th>Attempt</th></tr></thead><tbody>${data.entries.map(r=>`<tr ${r.is_you?'class="leaderboard-you"':''}><td>${r.rank}</td><td>${esc(r.student_name)}${r.is_you?' (You)':''}</td><td>${r.score} / ${r.max_score}</td><td>${Number(r.percentage).toFixed(1)}%</td><td>${r.attempt_number}</td></tr>`).join('')}</tbody></table></div>${data.entries.length?'':'<p>No completed attempts yet.</p>'}`;}catch(error){body.textContent=error.message;}
  }
  function reportConcern(qid,sid){
    const body=dialog(`Report a concern - question #${qid}`);
    body.innerHTML='<form data-concern-form><label>Concern about<select name="category"><option value="ANSWER">Correct answer</option><option value="OPTIONS">Answer options</option><option value="QUESTION">Question wording / equation / digitisation</option><option value="SOLUTION">Solution / explanation</option><option value="OTHER">Other</option></select></label><label>Describe the issue<textarea name="description" rows="5" minlength="10" maxlength="3000" required placeholder="Explain what seems incorrect and suggest a correction, if possible."></textarea></label><button class="primary">Submit concern</button><p role="status"></p></form>';
    const form=body.querySelector('form');form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;try{const values=Object.fromEntries(new FormData(form));await api('/api/question-concerns',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...values,question_id:Number(qid),session_id:sid?Number(sid):null})});form.querySelector('[role=status]').textContent='Concern submitted for admin review. You can close this dialog and continue your exam; the timer keeps running.';if(sid&&$('exam-current-question')?.dataset.session===String(sid)){window.ExamQuestionFlags??=new Set();window.ExamQuestionFlags.add(Number(qid));renderExamCurrentQuestion();renderExamNav();}}catch(error){form.querySelector('[role=status]').textContent=error.message;button.disabled=false;}};
  }
  async function concerns(){
    const body=dialog('Question concerns');body.innerHTML='<label>Status<select data-concern-filter><option>OPEN</option><option>RESOLVED</option><option>DISMISSED</option><option>ALL</option></select></label><div data-concern-list></div>';
    const filter=body.querySelector('select'),list=body.querySelector('[data-concern-list]');
    async function load(){
      try{const rows=await api('/api/question-concerns?status='+filter.value);list.innerHTML=rows.map(r=>`<article class="panel concern-card"><h4>Question #${r.question_id} · ${esc(r.category)} · ${esc(r.status)}</h4><p>${esc(r.exam_name||'Question bank')} · ${esc(r.reporter_name||'Student')}</p><div class="rendered" data-concern-statement="${r.id}"></div><p>${esc(r.description)}</p>${r.resolution?`<p><strong>Resolution:</strong> ${esc(r.resolution)}</p>`:''}<div class="actions"><button data-concern-edit="${r.question_id}">Edit question / options</button></div><p class="muted">Corrections update the question bank, exam previews and displayed questions. Active students review changed questions; submitted responses and scores remain recorded with their original grading context.</p><form data-resolve-concern="${r.id}" data-revision="${r.revision}"><label>Resolution<textarea name="resolution" minlength="5" maxlength="3000" required>${esc(r.resolution)}</textarea></label><label>Status<select name="status"><option value="RESOLVED">Resolved</option><option value="DISMISSED">Dismissed</option><option value="OPEN">Reopen</option></select></label><button>Save resolution</button></form></article>`).join('')||'<p>No concerns in this status.</p>';rows.forEach(r=>renderInto(list.querySelector(`[data-concern-statement="${r.id}"]`),r.statement));}catch(error){list.textContent=error.message;}
    }
    filter.onchange=load;
    body.addEventListener('click',async e=>{const button=e.target.closest('[data-concern-edit]');if(!button)return;try{const q=await api('/api/questions/'+button.dataset.concernEdit);body.closest('dialog').close();await QuestionCorrection.open(q);}catch(error){notify(error.message);}});
    body.addEventListener('submit',async e=>{const form=e.target.closest('[data-resolve-concern]');if(!form)return;e.preventDefault();try{await api('/api/question-concerns/'+form.dataset.resolveConcern,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...Object.fromEntries(new FormData(form)),revision:Number(form.dataset.revision)})});await load();}catch(error){notify(error.message);}});await load();
  }
  document.addEventListener('click',async e=>{
    const button=e.target.closest('[data-exam-leaderboard],[data-result-pdf],[data-result-share],[data-result-revoke],[data-report-concern],[data-manage-concerns]');if(!button)return;
    try{
      if(button.hasAttribute('data-exam-leaderboard'))return await leaderboard(button.dataset.examLeaderboard);
      if(button.hasAttribute('data-manage-concerns'))return await concerns();
      if(button.hasAttribute('data-report-concern'))return reportConcern(button.dataset.reportConcern,button.dataset.concernSession);
      if(button.hasAttribute('data-result-pdf')){window.open(`/api/results/${button.dataset.resultPdf}/report.pdf`,'_blank','noopener');return;}
      if(button.hasAttribute('data-result-revoke')){await api(`/api/results/${button.dataset.resultRevoke}/share`,{method:'DELETE'});notify('All share links for this report have been revoked.');return;}
      if(button.hasAttribute('data-result-share')){
        const body=dialog('Share result report');body.innerHTML='<p>Anyone with the link can download the student name and result summary for 7 days. Questions, answers and email addresses are excluded.</p><button class="primary" data-create-report-link>Create share link</button><div data-report-link></div>';
        body.querySelector('button').onclick=async event=>{event.target.disabled=true;try{const result=await api(`/api/results/${button.dataset.resultShare}/share`,{method:'POST'}),target=body.querySelector('[data-report-link]');target.innerHTML=`<label>Report link<input readonly value="${esc(result.url)}"></label><p>Expires ${new Date(result.expires_at*1000).toLocaleString()}</p><button data-copy-report-link>Copy link</button>`;target.querySelector('button').onclick=async()=>{try{await navigator.clipboard.writeText(result.url);notify('Report link copied.');}catch{target.querySelector('input').select();}};}catch(error){body.querySelector('[data-report-link]').textContent=error.message;event.target.disabled=false;}};
      }
    }catch(error){notify(error.message);}
  });
  return {actions,rank,reportConcern};
})();
