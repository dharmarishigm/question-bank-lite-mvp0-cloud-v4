/* One private learner assistant, shared by public and authenticated surfaces. */
(() => {
  let user=null,sessionId=null,context={},busy=false,lastFocus=null;
  const launcher=document.createElement('button');launcher.className='mentor-launcher';launcher.textContent='✦ IQraMentor';launcher.setAttribute('aria-expanded','false');launcher.setAttribute('aria-controls','mentor-drawer');
  const drawer=document.createElement('section');drawer.id='mentor-drawer';drawer.className='mentor-drawer';drawer.hidden=true;drawer.setAttribute('role','dialog');drawer.setAttribute('aria-label','IQraMentor — Your Personal Performance & Learning Tutor');
  drawer.innerHTML='<header><div><strong>✦ IQraMentor</strong><small>Your Personal Performance &amp; Learning Tutor</small></div><button type="button" aria-label="Close IQraMentor">×</button></header><div class="mentor-prompts"><button data-prompt="What should I practice next?">Practice next</button><button data-prompt="Did I improve?">Explain my trend</button><button data-prompt="Generate my performance report and a 7-day study plan.">My report</button><button data-history>History</button><button data-new>New chat</button></div><div class="mentor-conversation" role="log" aria-live="polite"></div><form><textarea aria-label="Ask IQraMentor" placeholder="Ask IQraMentor…" maxlength="2000" required></textarea><button type="submit">Send</button></form>';
  document.body.append(launcher,drawer);
  const log=drawer.querySelector('.mentor-conversation'),form=drawer.querySelector('form'),input=drawer.querySelector('textarea');
  async function request(path,options={}) { const token=document.cookie.split('; ').find(v=>v.startsWith('qb_csrf='))?.slice(8)||''; const r=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(token),...options.headers}}); const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Unable to complete this request.');return data; }
  function message(text,role='assistant'){const el=document.createElement('p');el.className='mentor-message '+role;el.textContent=text;log.append(el);log.scrollTop=log.scrollHeight;}
  function report(data){const el=document.createElement('details');el.className='mentor-report';const summary=document.createElement('summary');summary.textContent='Performance report · '+data.data_period;el.append(summary);function section(title,text){const h=document.createElement('h4');h.textContent=title;const p=document.createElement('p');p.textContent=text;el.append(h,p);}
    section('Recent performance',`${data.attempt_count} released attempts · Average score ${data.average_score??'—'}% · Accuracy ${data.accuracy??'—'}%`);
    section('Strengths',data.strengths.map(x=>`${x.label}: ${x.accuracy}%`).join(' · ')||'More topic evidence is needed.');
    section('Learning gaps',data.learning_gaps.map(x=>`${x.label}: ${x.accuracy}% (${x.confidence.toLowerCase()} confidence)`).join(' · ')||'No established gap.');
    section('Difficulty analysis',data.dimensions.difficulty.map(x=>`${x.label}: ${x.accuracy??'—'}% across ${x.count} questions`).join(' · ')||'No released evidence.');
    section('Speed & accuracy',`${data.average_seconds_per_question??'—'} seconds per question. ${data.time_note}`);
    section('Attempt trend',data.recent_attempts.map(x=>`${x.exam_name}: ${x.percentage}%`).join(' → ')||'No released attempts.');
    section('Benchmark',data.benchmark.message);section('Readiness',data.readiness.message);
    section('Recommended practice',data.recommendations.map(x=>`${x.title}. ${x.reason} ${x.action}`).join('\n'));
    section('Next 7 days',(data.seven_day_plan||[]).map(x=>`Day ${x.day}: ${x.action}`).join('\n'));
    log.append(el);log.scrollTop=log.scrollHeight;
  }
  async function open(options={}) {lastFocus=document.activeElement;drawer.hidden=false;launcher.setAttribute('aria-expanded','true');context=options;const previousUser=user?.id;try {user=await request('/api/auth/me');}catch{user=null;}if(previousUser!==user?.id){sessionId=null;log.replaceChildren();}form.hidden=!user||user.role!=='STUDENT';drawer.querySelector('.mentor-prompts').hidden=form.hidden;
    if(!user){log.replaceChildren();message('Sign in to MeritIQra to get personalized guidance from IQraMentor.');const a=document.createElement('a');a.href='/student';a.textContent='Sign In';log.append(a);return;}
    if(user.role!=='STUDENT'){message('IQraMentor is a private learner workspace. Administrator accounts cannot browse learner conversations.');return;}
    if(!log.children.length)message('Ask. Understand. Improve. Ask about your released results, learning gaps, or a concept you want to understand.');input.focus();if(options.prompt){input.value=options.prompt;}
  }
  function close(){drawer.hidden=true;launcher.setAttribute('aria-expanded','false');lastFocus?.focus();}
  launcher.onclick=()=>drawer.hidden?open():close();drawer.querySelector('header button').onclick=close;
  drawer.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
  form.onsubmit=async e=>{e.preventDefault();if(busy||!input.value.trim())return;busy=true;form.querySelector('button').disabled=true;const text=input.value.trim();message(text,'user');input.value='';try{const {prompt,...safeContext}=context;const data=await request('/api/tutor/chat',{method:'POST',body:JSON.stringify({message:text,session_id:sessionId,...safeContext})});sessionId=data.session_id;message(data.message);report(data.report);}catch(error){message(error.message);}finally{busy=false;form.querySelector('button').disabled=false;input.focus();}};
  drawer.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{input.value=b.dataset.prompt;input.focus();});
  drawer.querySelector('[data-new]').onclick=()=>{if(busy)return;sessionId=null;context={};log.replaceChildren();message('New conversation. What would you like to understand?');input.focus();};
  drawer.querySelector('[data-history]').onclick=async()=>{try{const rows=await request('/api/tutor/sessions');message(rows.length?'Choose a recent conversation:':'No conversations yet.');for(const row of rows){const b=document.createElement('button');b.textContent=new Date(row.updated_at*1000).toLocaleString();b.onclick=async()=>{if(busy)return;try{const messages=await request('/api/tutor/sessions/'+row.id);sessionId=row.id;context={};log.replaceChildren();messages.forEach(m=>message(m.content,m.role));}catch(e){message(e.message);}};log.append(b);}}catch(e){message(e.message);}};
  window.openIQraMentor=open;
  document.addEventListener('click',e=>{const b=e.target.closest('[data-mentor]');if(b){const options={prompt:b.dataset.mentor};if(b.dataset.attempt)options.attempt_id=Number(b.dataset.attempt);if(b.dataset.question)options.question_id=Number(b.dataset.question);if(!options.attempt_id && typeof signedInUser!=='undefined' && signedInUser?.role==='STUDENT' && !document.getElementById('student-analytics-panel')?.hidden)Object.assign(options,window.performanceFilters?.()||{});open(options);}});
})();
