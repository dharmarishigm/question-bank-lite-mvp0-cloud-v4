(()=>{
const status=document.getElementById('status');
const api=async(path,body)=>{const csrf=document.cookie.split('; ').find(v=>v.startsWith('qb_csrf='))?.split('=')[1]||'';const r=await fetch('/api/auth/'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf)},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Verification failed');return data;};
async function init(){try{const me=await api('me');if(!me.mfa_required){location.replace('/app');return;}if(!me.mfa_enrolled){const setup=await api('mfa/setup',{});document.getElementById('secret').textContent=setup.secret;document.getElementById('enroll').hidden=false;}}catch(e){status.textContent=e.message;}}
document.getElementById('verify').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;status.textContent='Verifying…';try{await api('mfa/verify',{code:document.getElementById('code').value});location.replace('/app');}catch(e){status.textContent=e.message;}finally{button.disabled=false;}};
document.getElementById('logout').onclick=async()=>{try{await api('logout',{});location.replace('/');}catch(e){status.textContent=e.message;}};
init();
})();
