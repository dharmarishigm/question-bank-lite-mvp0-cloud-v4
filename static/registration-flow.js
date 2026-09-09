/* Shared-link enrollment reuses verified Google identity and preserves the intended exam. */
window.setupSharedGoogleEnrollment=async(token,exam)=>{
  const config=await fetch('/api/auth/config',{cache:'no-store'}).then(r=>r.json());let current=null;try{current=await api('/api/auth/me');}catch{}
  if(!config.client_id&&!window.MeritIQraNative&&!current)return false;
  const block=$('public-google-block'),fallback=$('public-fallback'),form=$('public-registration-form'),message=$('public-registration-message');
  block.hidden=false;fallback.hidden=true;$('public-fallback-toggle').hidden=true;$('public-fallback-toggle').textContent='Option 2 · Login without Gmail';
  async function signedIn(user){
    if(user.role!=='STUDENT'||!user.email_verified){message.textContent='This link is for student enrollment. Sign in with your student Google account.';return;}
    current=user;block.hidden=true;fallback.hidden=false;fallback.querySelector('.registration-choice').hidden=true;$('public-student-login-form').hidden=true;form.hidden=false;
    form.innerHTML='<label>Google account<input name="email" type="email" readonly></label><label>Mobile number<input name="phone_number" type="tel" autocomplete="tel" placeholder="+91 98765 43210" required minlength="10" maxlength="20"></label><p class="registration-hint">Use your own mobile number. A number can belong to only one account.</p><button class="primary" type="submit">Enroll in this exam</button>';
    form.elements.email.value=user.email;
    try{const profile=await api('/api/student/profile');form.elements.phone_number.value=profile.phone_number||'';}catch{}
    message.textContent='Your Google email is verified. Add your mobile number to continue.';
    form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;message.textContent='Enrolling…';try{await api(`/api/register/exam/${encodeURIComponent(token)}/enroll`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone_number:form.elements.phone_number.value})});$('public-registration').hidden=true;history.replaceState({},'','/app');window.sharedRegistrationSignedIn=null;await finishLogin(current);showView('available-exams');$('available-exams-panel')?.scrollIntoView({behavior:'smooth',block:'start'});notify('You are enrolled. Available Exams now shows Enter proctor and Start exam.');}catch(error){message.textContent=error.message;}finally{button.disabled=false;}};
  }
  window.sharedRegistrationSignedIn=signedIn;
  if(current&&current.role==='STUDENT'&&current.email_verified){await signedIn(current);return true;}
  if(window.MeritIQraNative){const button=document.createElement('button');button.className='primary';button.textContent='Continue with Google';button.onclick=()=>window.MeritIQraNative.Native.signIn();$('public-google-signin').replaceChildren(button);}
  else if(config.client_id)renderGoogleSignIn(config.client_id,$('public-google-signin'),signedIn,error=>message.textContent=error.message);
  return true;
};
