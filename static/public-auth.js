(() => {
  const byId=id=>document.getElementById(id);
  let authConfig={};
  const showStudentGoogleState=()=>{byId('login-title').textContent='Student login';byId('student-google-prompt').hidden=false;byId('google-signin').hidden=false;byId('login-message').textContent=authConfig.client_id?'Register or login securely with the Google button above. Your Gmail identity will be verified before enrollment.':'Google sign-in is loading. Please wait a moment and try again.';};
  const json=async(url,options={})=>{const response=await fetch(url,options);const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||'Sign in failed');return body;};
  const complete=()=>location.assign('/app');
  fetch('/api/auth/config',{cache:'no-store'}).then(config=>{authConfig=config;
    byId('bootstrap-admin-toggle').hidden=!config.bootstrap_available;
    byId('admin-login-toggle').disabled=!config.local_admin;
    byId('admin-login-email').value='';
    if(config.client_id){
      const script=document.createElement('script');script.src='https://accounts.google.com/gsi/client';
      script.onload=()=>{byId('google-signin').textContent='';google.accounts.id.initialize({client_id:config.client_id,callback:async result=>{try{await json('/api/auth/google',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({credential:result.credential})});complete();}catch(error){byId('login-message').textContent=error.message;}}});google.accounts.id.renderButton(byId('google-signin'),{theme:'outline',size:'large',width:280,text:'continue_with'});if(!byId('login-screen').hidden)showStudentGoogleState();};
      document.head.append(script);
    }else if(config.mock){byId('mock-signin').hidden=false;}
    else if(config.bootstrap_available)byId('login-message').textContent='Create the first administrator to complete initial setup.';
    else if(config.local_admin)byId('login-message').textContent='Google sign-in is not configured. Use administrator login below.';
    else byId('login-message').textContent='Google sign-in is not configured. Set GOOGLE_CLIENT_ID and restart the app.';
  });
  document.addEventListener('meritiqra:login-mode',event=>{
    const admin=event.detail.mode==='admin';
    byId('login-title').textContent=admin?'Administrator login':'Student login';
    byId('student-google-prompt').hidden=admin;byId('google-signin').hidden=admin;byId('mock-signin').hidden=admin||!authConfig.mock;
    byId('admin-login-toggle').hidden=true;byId('admin-login-form').hidden=!admin;
    byId('bootstrap-admin-toggle').hidden=true;byId('bootstrap-admin-form').hidden=true;
    if(admin)byId('login-message').textContent=authConfig.local_admin?'Enter the administrator credentials configured for MeritIQra.':'Administrator credentials are not configured.';else showStudentGoogleState();
    if(admin){byId('admin-login-email').value='';byId('admin-login-password').value='';byId('admin-login-email').focus();}
  });
  byId('bootstrap-admin-toggle').onclick=()=>{byId('bootstrap-admin-toggle').hidden=true;byId('bootstrap-admin-form').hidden=false;byId('bootstrap-admin-name').focus();};
  byId('bootstrap-admin-cancel').onclick=()=>{byId('bootstrap-admin-form').hidden=true;byId('bootstrap-admin-toggle').hidden=false;};
  byId('bootstrap-admin-form').onsubmit=async event=>{event.preventDefault();try{await json('/api/auth/bootstrap-admin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:byId('bootstrap-admin-name').value,email:byId('bootstrap-admin-email').value})});complete();}catch(error){byId('login-message').textContent=error.message;}};
  byId('admin-login-toggle').onclick=()=>{byId('admin-login-toggle').hidden=true;byId('admin-login-form').hidden=false;byId('admin-login-email').focus();};
  byId('admin-login-cancel').onclick=()=>{byId('admin-login-form').hidden=true;byId('admin-login-toggle').hidden=false;};
  byId('admin-login-form').onsubmit=async event=>{event.preventDefault();try{await json('/api/auth/admin-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:byId('admin-login-email').value,password:byId('admin-login-password').value})});complete();}catch(error){byId('login-message').textContent=error.message;}};
  byId('mock-signin').onclick=async()=>{try{await json('/api/auth/mock',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});complete();}catch(error){byId('login-message').textContent=error.message;}};
})();
