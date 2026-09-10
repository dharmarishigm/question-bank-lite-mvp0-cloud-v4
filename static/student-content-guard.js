/* Browser deterrents cannot prevent operating-system screenshots or cameras. */
(()=>{
 let protectedView=false;
 const watermark=document.createElement('div');watermark.id='student-content-watermark';watermark.setAttribute('aria-hidden','true');watermark.hidden=true;document.body.append(watermark);
 function set(view){
  protectedView=typeof signedInUser!=='undefined'&&signedInUser?.role==='STUDENT'&&['exam','my-results','student-analytics'].includes(view);
  document.body.classList.toggle('student-protected-content',protectedView);watermark.hidden=!protectedView;
  if(protectedView){const text=`${signedInUser.display_name||'Student'} · ID ${signedInUser.id} · ${new Date().toLocaleDateString()} · MeritIqra`;watermark.replaceChildren(...Array.from({length:12},()=>{const node=document.createElement('span');node.textContent=text;return node;}));}
  window.MeritIQraNative?.Native.protectedWindow({enabled:protectedView||!!secureExamActive});
 }
 document.addEventListener('workspace:view-changed',e=>set(e.detail.name));
 const editing=e=>e.target instanceof Element&&!!e.target.closest('input,textarea,[contenteditable=true]');
 for(const type of ['copy','cut','contextmenu','dragstart','selectstart'])document.addEventListener(type,e=>{if(protectedView&&!editing(e)){e.preventDefault();if(type==='copy'||type==='contextmenu')notify('Copying exam and report content is disabled.');}},true);
 document.addEventListener('keydown',e=>{if(!protectedView)return;const key=e.key.toLowerCase();if((e.ctrlKey||e.metaKey)&&(['p','s'].includes(key)||!editing(e)&&['c','x','a'].includes(key))){e.preventDefault();notify('Copying, saving and printing protected exam content is disabled.');}},true);
 // Print styles also cover the browser menu, which bypasses keyboard handlers.
 set(document.querySelector('.sidebar button[aria-current=page]')?.dataset.view||'');
 new MutationObserver(()=>{if($('app-shell')?.hidden&&protectedView)set('');}).observe($('app-shell'),{attributes:true,attributeFilter:['hidden']});
})();
