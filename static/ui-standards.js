/* Navigation state and keyboard conventions shared across roles. */
(() => {
  const toggle=document.getElementById('sidebar-toggle'),shell=document.getElementById('app-shell');
  toggle.setAttribute('aria-controls','sidebar');
  const syncNavigation=()=>{
    const mobile=matchMedia('(max-width:800px)').matches;
    const expanded=mobile?shell.classList.contains('nav-open'):!shell.classList.contains('nav-collapsed');
    toggle.setAttribute('aria-expanded',String(expanded));
    toggle.setAttribute('aria-label',expanded?'Collapse navigation':'Expand navigation');
    document.getElementById('sidebar').inert=!expanded;
  };
  new MutationObserver(syncNavigation).observe(shell,{attributes:true,attributeFilter:['class']});
  matchMedia('(max-width:800px)').addEventListener('change',syncNavigation);syncNavigation();
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&shell.classList.contains('nav-open')){shell.classList.remove('nav-open');toggle.focus();}
  });
  function labelTables(){
    document.querySelectorAll('.guided-prompt-markdown table,.rich-description table').forEach(table=>{table.tabIndex=0;table.setAttribute('aria-label','Formatted content table; scroll horizontally for more columns');});
    document.querySelectorAll('#main-content .table-wrap').forEach(wrap=>{
      if(!wrap.querySelector('table'))return;
      wrap.tabIndex=0;wrap.setAttribute('role','region');
      if(!wrap.hasAttribute('aria-label'))wrap.setAttribute('aria-label',(wrap.closest('.tab-panel')?.querySelector('h2')?.textContent||'Results')+' table; scroll horizontally for more columns');
    });
  }
  new MutationObserver(labelTables).observe(document.getElementById('main-content'),{childList:true,subtree:true});labelTables();
  const aiTabs=[...document.querySelectorAll('[data-ai-tab]')];
  function syncTabs(){
    aiTabs.forEach(button=>{
      const name=button.dataset.aiTab,pane=document.getElementById('ai-'+name+'-pane'),selected=!pane.hidden;
      button.id='ai-tab-'+name;button.setAttribute('role','tab');button.setAttribute('aria-controls',pane.id);button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;
      pane.setAttribute('role','tabpanel');pane.setAttribute('aria-labelledby',button.id);
    });
  }
  aiTabs.forEach((button,index)=>{
    button.addEventListener('keydown',event=>{
      const next=event.key==='Home'?0:event.key==='End'?aiTabs.length-1:event.key==='ArrowRight'?(index+1)%aiTabs.length:event.key==='ArrowLeft'?(index+aiTabs.length-1)%aiTabs.length:null;
      if(next!==null){event.preventDefault();aiTabs[next].click();aiTabs[next].focus();}
    });
    new MutationObserver(syncTabs).observe(document.getElementById('ai-'+button.dataset.aiTab+'-pane'),{attributes:true,attributeFilter:['hidden']});
  });syncTabs();
  for(const id of ['notification','ai-generation-status','program-setup-status']){
    const node=document.getElementById(id);if(node){node.setAttribute('role','status');node.setAttribute('aria-live','polite');}
  }
})();
