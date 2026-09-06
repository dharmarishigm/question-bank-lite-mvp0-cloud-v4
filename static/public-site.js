(() => {
  const site=document.getElementById('public-site');
  const login=document.getElementById('login-screen');
  const openLogin=()=>{login.hidden=false;document.body.classList.add('public-login-open');document.getElementById('login-close')?.focus();};
  const closeLogin=()=>{login.hidden=true;document.body.classList.remove('public-login-open');};
  document.querySelectorAll('[data-open-login]').forEach(button=>button.addEventListener('click',openLogin));
  document.addEventListener('click',event=>{const button=event.target.closest('[data-enroll-exam]');if(!button)return;sessionStorage.setItem('meritiqra_pending_exam',button.dataset.enrollExam);openLogin();});
  document.getElementById('login-close')?.addEventListener('click',closeLogin);
  document.getElementById('public-menu-toggle')?.addEventListener('click',event=>{const nav=document.getElementById('public-nav');const open=nav.classList.toggle('open');event.currentTarget.setAttribute('aria-expanded',String(open));});
  document.getElementById('public-nav')?.addEventListener('click',()=>document.getElementById('public-nav').classList.remove('open'));
  window.showPublicSite=()=>{site.hidden=false;closeLogin();};
  window.hidePublicSite=()=>{site.hidden=true;closeLogin();};
  fetch('/api/public/exams',{cache:'no-store'}).then(r=>r.ok?r.json():[]).then(rows=>{
    const target=document.getElementById('public-exam-list');if(!target)return;
    if(!rows.length){target.innerHTML='<div class="public-empty"><h3>New assessments are being prepared</h3><p>Sign in to check your registered exams or return soon for new practice opportunities.</p><button class="public-cta" data-open-login>Get Started</button></div>';target.querySelector('[data-open-login]').onclick=openLogin;return;}
    target.innerHTML=rows.map(e=>'<article class="public-exam-card"><span class="public-eyebrow">'+esc(e.exam_type||'ASSESSMENT')+'</span><h3>'+esc(e.name)+'</h3><p>'+esc(e.description||'A structured MeritIQra assessment.')+'</p><div class="exam-card-meta"><span>'+esc(e.subject||'General')+'</span><span>'+esc(e.level||'All levels')+'</span><span>'+Number(e.question_count||0)+' questions</span><span>'+Number(e.duration_minutes||0)+' min</span><span>'+(e.proctor_required?'Proctored':'Practice')+'</span></div>'+(e.allow_self_registration?'<button class="public-cta" data-enroll-exam="'+Number(e.id)+'">Register / Enroll</button>':'<button class="public-cta" data-open-login>Login to view</button>')+'</article>').join('');
    target.querySelectorAll('[data-open-login]').forEach(b=>b.onclick=openLogin);
  }).catch(()=>{const t=document.getElementById('public-exam-list');if(t)t.innerHTML='<div class="public-empty">Assessments are temporarily unavailable.</div>';});
  function esc(v){const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML;}
})();

// Keep friendly public routes useful while retaining one lightweight document.
(() => {
  const routeTargets={
    '/practice-exams':'assessments','/exams':'assessments','/features':'features',
    '/how-it-works':'how-it-works','/for-students':'for-students',
    '/for-schools':'for-schools','/for-organizations':'for-organizations','/about':'home',
    '/ai-question-bank':'features','/ai-question-generation':'features',
    '/online-exam-platform':'features','/assessment-platform':'features'
  };
  const id=routeTargets[location.pathname];
  if(id) requestAnimationFrame(()=>document.getElementById(id)?.scrollIntoView({block:'start'}));
})();
