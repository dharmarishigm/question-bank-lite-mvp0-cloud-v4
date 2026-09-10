// Keep Performance Lab useful before a learner has a released attempt.
document.addEventListener('workspace:view-changed',event=>{
  if(event.detail.name!=='student-analytics')return;
  const status=$('analytics-status'),content=$('analytics-content');
  setTimeout(()=>{
    if(!status||!content||!content.hidden||!/first assessment|No completed attempts/i.test(status.textContent))return;
    $('analytics-kpis').innerHTML=[['Average score','—'],['Accuracy','—'],['Correct answers','0'],['Incorrect answers','0'],['Unanswered','0'],['Completion','—']].map(([k,v])=>`<article class="exam-analytics-card"><h4>${esc(k)}</h4><strong>${v}</strong></article>`).join('');
    $('analytics-trend').innerHTML='<div class="empty-state"><strong>Your score trend will appear after your first released exam.</strong><p>Choose an available exam to establish your baseline.</p><button class="primary" id="analytics-empty-explore">Explore Exams</button></div>';
    $('analytics-empty-explore').onclick=()=>showView('available-exams');
    $('analytics-topics').innerHTML='<p class="empty-state">Topic mastery appears after you answer questions in a released exam.</p>';
    $('analytics-recommendations').innerHTML='<article class="recommendation-card"><span>START HERE</span><h4>Build your assessment baseline</h4><p>Complete an available exam, then return here for score tracking, learning gaps and a focused study plan.</p><button class="primary" id="analytics-empty-plan">Explore Exams</button></article>';
    $('analytics-empty-plan').onclick=()=>showView('available-exams');
    status.hidden=true;content.hidden=false;
  },700);
});
