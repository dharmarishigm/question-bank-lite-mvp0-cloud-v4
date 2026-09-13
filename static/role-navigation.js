/* Search only navigation entries already exposed by the role-aware shell. */
(() => {
  const sidebar=document.querySelector('.sidebar');
  if(!sidebar)return;
  const quick=document.createElement('nav');quick.className='role-quick-navigation';quick.setAttribute('aria-label','Common tasks');
  const main=document.getElementById('main-content'),heading=main?.querySelector('.workspace-heading');if(heading)heading.after(quick);
  const roleLinks={
    ADMIN:[['dashboard','Overview'],['programs','Create program exam'],['grand-tests','DigitalQBank'],['admin-exams','Manage exams']],
    STUDENT:[['dashboard','Home'],['available-exams','Find exams'],['my-exams','Continue exams'],['my-results','Results']],
    PROCTOR:[['admin-exams','Assigned exams'],['admin-results','Exam dashboard']],
    OPERATOR:[['grand-tests','DigitalQBank workspaces']]
  };
  const renderQuick=()=>{quick.replaceChildren();const visible=document.querySelector('.tab-panel:not([hidden])')?.id.replace(/-panel$/,'');for(const [view,label] of roleLinks[signedInUser?.role]||[]){const b=document.createElement('button');b.type='button';b.dataset.view=view;b.textContent=label;if(view===visible){b.classList.add('active');b.setAttribute('aria-current','page');}quick.append(b);}quick.hidden=!quick.children.length;};
  const finder=document.createElement('div');finder.className='navigation-finder';
  const label=document.createElement('label');label.htmlFor='find-page';label.textContent='Find a page';
  const input=document.createElement('input');input.id='find-page';input.type='search';input.placeholder='Exams, questions, results…';input.autocomplete='off';
  const results=document.createElement('div');results.className='navigation-finder-results';results.hidden=true;results.setAttribute('aria-label','Matching pages');
  const status=document.createElement('p');status.setAttribute('role','status');status.hidden=true;
  finder.append(label,input,results,status);sidebar.prepend(finder);
  const refresh=()=>{
    results.replaceChildren();const query=input.value.trim().toLowerCase();results.hidden=!query;status.hidden=true;
    if(!query)return;
    const seen=new Set();
    sidebar.querySelectorAll('nav [data-view]').forEach(source=>{
      if(source.closest('[hidden]')||source.disabled||seen.has(source.dataset.view)||!source.textContent.toLowerCase().includes(query))return;
      seen.add(source.dataset.view);const button=document.createElement('button');button.type='button';button.textContent=source.textContent.trim();
      button.onclick=()=>{if(source.closest('[hidden]')){refresh();return;}input.value='';refresh();source.click();};results.append(button);
    });
    if(!results.children.length){status.hidden=false;status.textContent='No matching pages in this workspace.';}
  };
  input.addEventListener('input',refresh);
  input.addEventListener('keydown',e=>{if(e.key==='Escape'){input.value='';refresh();}if(e.key==='ArrowDown'){results.querySelector('button')?.focus();e.preventDefault();}});
  document.addEventListener('workspace:view-changed',event=>{input.value='';refresh();quick.querySelectorAll('[data-view]').forEach(b=>{const active=b.dataset.view===event.detail.name;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});});
  window.addEventListener('mobile:login',()=>{renderQuick();refresh();});
  if(typeof signedInUser!=='undefined'&&signedInUser)renderQuick();
  // Navigation modules add links after login. Observe those modules, not results.
  const observer=new MutationObserver(refresh);
  sidebar.querySelectorAll('nav').forEach(nav=>observer.observe(nav,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden']}));
})();
