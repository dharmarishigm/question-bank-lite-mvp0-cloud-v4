/* Search only navigation entries already exposed by the role-aware shell. */
(() => {
  const sidebar=document.querySelector('.sidebar');
  if(!sidebar)return;
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
  document.addEventListener('workspace:view-changed',()=>{input.value='';refresh();});
  window.addEventListener('mobile:login',refresh);
  // Navigation modules add links after login. Observe those modules, not results.
  const observer=new MutationObserver(refresh);
  sidebar.querySelectorAll('nav').forEach(nav=>observer.observe(nav,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden']}));
})();
