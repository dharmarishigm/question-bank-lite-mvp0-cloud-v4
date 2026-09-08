/* Public HTML stays cacheable; identity is fetched privately after page load. */
(() => {
 const actions=document.querySelector('.public-actions');if(!actions)return;
 const guest=[...actions.children];const account=document.createElement('details');account.className='public-account';account.hidden=true;
 account.innerHTML='<summary><span class="public-account-name"></span><span class="public-account-role"></span></summary><div class="public-account-menu"><span class="public-account-email"></span><a href="/app">Open dashboard</a><button type="button">Sign out</button></div>';actions.append(account);
 async function refresh(){try{const r=await fetch('/api/auth/me',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw new Error();const u=await r.json();account.querySelector('.public-account-name').textContent=u.display_name||u.email;account.querySelector('.public-account-role').textContent=u.role==='ADMIN'?'Admin':u.role==='PROCTOR'?'Proctor':'Student';account.querySelector('.public-account-email').textContent=u.email;guest.forEach(x=>x.hidden=true);account.hidden=false;}catch{guest.forEach(x=>x.hidden=false);account.hidden=true;}}
 account.querySelector('button').onclick=async()=>{const token=document.cookie.split('; ').find(x=>x.startsWith('qb_csrf='))?.slice(8)||'';const r=await fetch('/api/auth/logout',{method:'POST',headers:{'X-CSRF-Token':decodeURIComponent(token)}});if(r.ok)location.reload();};
 window.addEventListener('pageshow',refresh);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});refresh();
})();
