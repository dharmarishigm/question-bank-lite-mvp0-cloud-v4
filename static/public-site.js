(() => {
  const site=document.getElementById('public-site'),login=document.getElementById('login-screen'),registration=document.getElementById('student-registration-modal');
  let exams=[];
  const closeOverlays=()=>{login.hidden=true;registration.hidden=true;document.body.classList.remove('public-login-open');};
  const openLogin=mode=>{closeOverlays();login.hidden=false;document.body.classList.add('public-login-open');document.dispatchEvent(new CustomEvent('meritiqra:login-mode',{detail:{mode}}));document.getElementById('login-close')?.focus();};
  const openRegistration=examId=>{if(examId){sessionStorage.setItem('meritiqra_pending_exam',String(examId));location.assign('/app');return;}closeOverlays();registration.hidden=false;document.body.classList.add('public-login-open');document.getElementById('public-registration-exam')?.focus();};
  document.addEventListener('click',event=>{
    const enroll=event.target.closest('[data-enroll-exam]');if(enroll){openRegistration(enroll.dataset.enrollExam);return;}
    if(event.target.closest('[data-open-registration]')){openRegistration();return;}
    if(event.target.closest('[data-admin-login]')){openLogin('admin');return;}
    if(event.target.closest('[data-student-login]')){location.assign('/app');}
  });
  document.getElementById('login-close')?.addEventListener('click',closeOverlays);
  document.getElementById('student-registration-close')?.addEventListener('click',closeOverlays);
  document.getElementById('student-registration-form')?.addEventListener('submit',event=>{
    event.preventDefault();const examId=Number(new FormData(event.currentTarget).get('exam_id'));const status=document.getElementById('student-registration-message');
    if(!examId){status.textContent='Select an open exam first.';return;}
    sessionStorage.setItem('meritiqra_pending_exam',String(examId));location.assign('/app');
  });
  document.getElementById('public-menu-toggle')?.addEventListener('click',event=>{const nav=document.getElementById('public-nav');const open=nav.classList.toggle('open');event.currentTarget.setAttribute('aria-expanded',String(open));});
  document.getElementById('public-nav')?.addEventListener('click',()=>document.getElementById('public-nav').classList.remove('open'));
  window.showPublicSite=()=>{site.hidden=false;closeOverlays();};window.hidePublicSite=()=>{site.hidden=true;closeOverlays();};
  fetch('/api/public/exams',{cache:'no-store'}).then(r=>r.ok?r.json():[]).then(rows=>{
    exams=rows;const select=document.getElementById('public-registration-exam');rows.filter(e=>e.allow_self_registration).forEach(e=>select?.add(new Option(e.name,e.id)));
    const target=document.getElementById('public-exam-list');if(!target)return;
    if(!rows.length){target.innerHTML='<div class="public-empty"><h3>New assessments are being prepared</h3><p>Register your interest or return soon for new practice opportunities.</p><button class="public-cta" data-open-registration>Register</button></div>';return;}
    target.innerHTML=rows.map(e=>'<article class="public-exam-card"><span class="public-eyebrow">'+esc(e.exam_type||'ASSESSMENT')+'</span><h3>'+esc(e.name)+'</h3><div class="public-exam-description">'+window.renderPublicMarkdown(e.description||'A structured MeritIQra assessment.')+'</div>'+(e.program_code?ProgramParticipation.html({code:e.program_code,name:e.program_name}):'')+'<div class="exam-card-meta"><span>'+esc(e.subject||'General')+'</span><span>'+esc(e.level||'All levels')+'</span><span>'+Number(e.question_count||0)+' questions</span><span>'+Number(e.duration_minutes||0)+' min</span><span>'+(e.proctor_required?'Proctored':'Practice')+'</span></div>'+(e.allow_self_registration?'<button class="public-cta" data-enroll-exam="'+Number(e.id)+'">Register or Login</button>':'<button class="public-cta" data-student-login>Student Login</button>')+'</article>').join('');
  }).catch(()=>{const t=document.getElementById('public-exam-list');if(t)t.innerHTML='<div class="public-empty">Assessments are temporarily unavailable.</div>';});
  fetch('/api/public/programs',{cache:'no-store'}).then(r=>r.json()).then(rows=>{const t=document.getElementById('public-program-list');if(t)t.innerHTML=rows.map(p=>`<article class="program-product-card"><span class="program-badge">PROGRAM</span><h3>${esc(p.name)}</h3><button class="public-cta" data-subscribe="${esc(p.name)} · Complete Program">Enquire to Subscribe</button><button class="public-secondary" data-subscribe="${esc(p.name)} · Grand Test Package">Grand Test Package</button></article>`).join('')||'<div class="public-empty">New programs are coming soon.</div>';});
  document.addEventListener('click',event=>{const b=event.target.closest('[data-subscribe]');if(b)location.assign('/enquiry?interest=EXAMS&product='+encodeURIComponent(b.dataset.subscribe));});
  function esc(v){const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML;}
  const routeTargets={'/practice-exams':'assessments','/exams':'assessments','/features':'features','/how-it-works':'how-it-works','/for-students':'for-students','/for-schools':'for-schools','/for-organizations':'for-organizations','/about':'home','/ai-question-bank':'features','/ai-question-generation':'features','/online-exam-platform':'features','/assessment-platform':'features'};
  const id=routeTargets[location.pathname];if(id)requestAnimationFrame(()=>document.getElementById(id)?.scrollIntoView({block:'start'}));
})();
