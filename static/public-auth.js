(() => {
  const byId=id=>document.getElementById(id);
  let authConfig={};
  const showStudentGoogleState=()=>{byId('login-title').textContent='Student login';byId('student-google-prompt').hidden=false;byId('google-signin').hidden=false;byId('login-message').textContent=authConfig.client_id?'Register or login securely with the Google button above. Your Gmail identity will be verified before enrollment.':'Google sign-in is loading. Please wait a moment and try again.';};
  const json=async(url,options={})=>{const response=await fetch(url,options);const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||'Sign in failed');return body;};
  const role=document.createElement('select');role.id='login-role';role.innerHTML='<option value="STUDENT">Student</option><option value="ADMIN">Administrator</option><option value="OPERATOR">Operator</option><option value="FLAG">FLAG user</option>';const label=document.createElement('label');label.textContent='Sign in as';label.append(role);byId('google-signin').before(label);
  const complete=()=>location.assign('/app');
  json('/api/auth/config',{cache:'no-store'}).then(config=>{authConfig=config;
    byId('bootstrap-admin-toggle').hidden=!config.bootstrap_available;
    byId('admin-login-toggle').disabled=!config.local_admin;
    byId('admin-login-email').value='';
    if(config.client_id){
      const script=document.createElement('script');script.src='https://accounts.google.com/gsi/client';
      script.onload=()=>{byId('google-signin').textContent='';google.accounts.id.initialize({client_id:config.client_id,callback:async result=>{try{await json('/api/auth/google',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({credential:result.credential,login_role:role.value})});complete();}catch(error){byId('login-message').textContent=error.message;}}});google.accounts.id.renderButton(byId('google-signin'),{theme:'outline',size:'large',width:280,text:'continue_with'});if(!byId('login-screen').hidden)showStudentGoogleState();};
      document.head.append(script);
    }else if(config.mock){byId('mock-signin-email-wrap').hidden=false;byId('mock-signin').hidden=false;}
    else if(config.bootstrap_available)byId('login-message').textContent='Create the first administrator to complete initial setup.';
    else if(config.local_admin)byId('login-message').textContent='Google sign-in is not configured. Use Login below.';
    else byId('login-message').textContent='Google sign-in is not configured. Set GOOGLE_CLIENT_ID and restart the app.';
  });
  document.addEventListener('meritiqra:login-mode',event=>{
    const admin=event.detail.mode==='admin';role.value=admin?'ADMIN':'STUDENT';
    byId('login-title').textContent='Login to MeritIQra';byId('admin-login-toggle').textContent='Login';
    byId('login-options').hidden=false;byId('admin-login-form').hidden=true;
    byId('student-google-prompt').hidden=admin;byId('google-signin').hidden=admin;byId('mock-signin-email-wrap').hidden=admin||!authConfig.mock;byId('mock-signin').hidden=admin||!authConfig.mock;
    byId('admin-login-toggle').hidden=true;byId('admin-login-form').hidden=!admin;
    byId('bootstrap-admin-toggle').hidden=true;byId('bootstrap-admin-form').hidden=true;
    if(admin)byId('login-message').textContent=authConfig.local_admin?'Enter the administrator credentials configured for MeritIQra.':'Administrator credentials are not configured.';else showStudentGoogleState();
    if(admin){byId('admin-login-email').value='';byId('admin-login-password').value='';byId('admin-login-email').focus();}
  });
  byId('password-login-toggle').onclick=()=>{role.value='ADMIN';byId('student-google-prompt').hidden=true;byId('google-signin').hidden=true;byId('login-options').hidden=true;byId('admin-login-form').hidden=false;byId('admin-login-email').focus();byId('login-message').textContent='Enter your username and password.';};
  byId('exam-registration-toggle').onclick=()=>window.openPublicRegistration?.();
  byId('bootstrap-admin-toggle').onclick=()=>{byId('bootstrap-admin-toggle').hidden=true;byId('bootstrap-admin-form').hidden=false;byId('bootstrap-admin-name').focus();};
  byId('bootstrap-admin-cancel').onclick=()=>{byId('bootstrap-admin-form').hidden=true;byId('bootstrap-admin-toggle').hidden=false;};
  byId('bootstrap-admin-form').onsubmit=async event=>{event.preventDefault();try{await json('/api/auth/bootstrap-admin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:byId('bootstrap-admin-name').value,email:byId('bootstrap-admin-email').value})});complete();}catch(error){byId('login-message').textContent=error.message;}};
  byId('admin-login-toggle').onclick=()=>{byId('admin-login-toggle').hidden=true;byId('admin-login-form').hidden=false;byId('admin-login-email').focus();};
  byId('admin-login-cancel').onclick=()=>{byId('admin-login-form').hidden=true;byId('admin-login-toggle').hidden=false;};
  byId('admin-login-form').onsubmit=async event=>{event.preventDefault();try{await json('/api/auth/admin-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:byId('admin-login-email').value,password:byId('admin-login-password').value})});complete();}catch(error){byId('login-message').textContent=error.message;}};
  byId('mock-signin').onclick=async()=>{try{const email=byId('mock-signin-email')?.value||'student@example.test';await json('/api/auth/mock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email})});complete();}catch(error){byId('login-message').textContent=error.message;}};
})();
