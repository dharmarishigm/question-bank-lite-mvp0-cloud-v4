/* Guided authoring: server-owned prompts, persistent generation and explicit review. */
window.ProgramExam = (() => {
  const difficultyOptions = [['very_easy','Very Easy'],['easy','Easy'],['medium','Medium'],['hard','Hard'],['very_hard','Very Hard']];
  async function render(host, program, request, options={}) {
    host.replaceChildren();
    const el = (tag, text, parent=host) => {const node=document.createElement(tag);node.textContent=text;parent.append(node);return node;};
    el('h4', `${options.reviewOnly?'Review paper':'Create an exam'} for ${program.name}`);
    if(program.status==='ARCHIVED'){
      el('p','This program is archived. Restore it to create or edit exams.');
      const restore=el('button','Restore program and create exam');restore.type='button';restore.className='primary';
      const message=el('p','');message.setAttribute('role','status');
      restore.onclick=async()=>{
        restore.disabled=true;
        try{
          const latest=await request(`/${program.id}`);
          if(latest.status==='ARCHIVED')await request(`/${program.id}/restore?revision=${latest.revision}`,'POST');
          const restored=await request(`/${program.id}`);
          host.dispatchEvent(new CustomEvent('program-restored',{bubbles:true}));
          await render(host,restored,request);
        }catch(error){message.textContent=error.message;restore.disabled=false;}
      };
      return;
    }

    if(!options.reviewOnly)el('p', 'The latest available official exam information populates the pattern. Edit the setup and AI prompt, then review your practice paper.');
    const officialPanel=el('section','');officialPanel.className='official-pattern-panel';
    const form=el('form','');form.className='guided-exam-form';
    function field(label,name,value,tag='input',parent=form) {
      const wrapper=el('label',label,parent), node=el(tag,'',wrapper);node.name=name;node.value=value??'';
      if(tag==='textarea'){node.rows=5;wrapper.className='wide';}
      return node;
    }
    function select(label,name,options,value,parent=form){const node=field(label,name,'','select',parent);for(const [key,text] of options){const option=el('option',text,node);option.value=key;}node.value=value;return node;}
    function button(label,parent,action){const node=el('button',label,parent);node.type='button';node.onclick=action;return node;}
    const mode=select('Paper type','mode',[['FULL','Full Exam'],['SUBJECT','Subject-wise']],'FULL');
    const name=field('Exam title (optional)','name','');name.maxLength=200;
    const level=field('Class / level','level',program.payload.levels?.[0]||'');level.placeholder='For example: Class VI';
    const language=field('Language','language',program.payload.languages?.[0]||'English');language.required=true;
    const difficulty=select('Difficulty','difficulty',difficultyOptions,'medium');
    const duration=field('Duration (minutes)','duration_minutes',60);duration.type='number';duration.min=1;duration.max=1440;duration.required=true;
    const allButton=button('Refresh official pattern',form,()=>loadOfficial(true));allButton.className='primary wide';
    const subjectArea=el('section','',form);subjectArea.className='wide';el('h5','Subjects and question counts',subjectArea);
    el('p','Full Exam includes every section below. Subject-wise uses one selected subject. Questions are single-correct MCQs with four options.',subjectArea);
    const subjects=el('div','',subjectArea);let sections=[];
    function addSection(value={subject:'',count:10,marks:1,negative_marks:0,topics:''}){
      const row=el('fieldset','',subjects);row.className='guided-section';
      const subject=field('Subject','subject',value.subject,'input',row);subject.required=true;
      const count=field('Questions','count',value.count,'input',row);count.type='number';count.min=1;count.max=200;count.required=true;
      const marks=field('Marks each','marks',value.marks,'input',row);marks.type='number';marks.min=.01;marks.max=100;marks.step='any';marks.required=true;
      const negative=field('Wrong-answer penalty','negative_marks',value.negative_marks,'input',row);negative.type='number';negative.min=0;negative.max=100;negative.step='any';negative.required=true;
      const timing=field('Section time (minutes, if specified)','section_minutes',value.duration_minutes??'','input',row);timing.type='number';timing.min=1;timing.max=1440;
      const topics=field('Topics / exclusions (optional)','topics',value.topics,'textarea',row);topics.rows=2;
      const entry={row,subject,count,marks,negative,topics,timing};sections.push(entry);
      button('Remove subject',row,()=>{sections=sections.filter(s=>s!==entry);row.remove();invalidate();});
    }
    const addSubject=button('Add subject',subjectArea,()=>{if(mode.value==='SUBJECT'&&sections.length){status.textContent='Subject-wise papers use one subject. Edit the subject below.';return;}addSection();invalidate();});
    const subjectChoice=select('Choose subject','chosen_subject',[],'',subjectArea);subjectChoice.parentElement.hidden=true;
    let fullSections=[],fullDuration=null;
    function readSections(){return sections.map(s=>({subject:s.subject.value.trim(),count:Number(s.count.value),marks:Number(s.marks.value),negative_marks:Number(s.negative.value),topics:s.topics.value.trim(),duration_minutes:s.timing.value?Number(s.timing.value):null}));}
    function setSections(values){sections=[];subjects.replaceChildren();values.forEach(addSection);}
    function setChoices(values){subjectChoice.replaceChildren();for(const s of values){const option=el('option',s.subject||'Untitled subject',subjectChoice);option.value=s.subject;}}
    mode.onchange=()=>{
      if(mode.value==='SUBJECT'){
        fullDuration=duration.value;fullSections=readSections();setChoices(fullSections);setSections(fullSections.slice(0,1));if(fullSections[0]?.duration_minutes)duration.value=fullSections[0].duration_minutes;
      }else{if(fullDuration!==null)duration.value=fullDuration;const current=readSections()[0];setSections(fullSections.length?fullSections.map(s=>s.subject===current?.subject?current:s):current?[current]:[]);}
      subjectChoice.parentElement.hidden=mode.value!=='SUBJECT'||fullSections.length<2;addSubject.hidden=mode.value==='SUBJECT';invalidate();
    };
    subjectChoice.onchange=()=>{const chosen=fullSections.find(s=>s.subject===subjectChoice.value);if(chosen){setSections([chosen]);if(chosen.duration_minutes)duration.value=chosen.duration_minutes;}invalidate();};
    const curriculum=field('Curriculum / syllabus','curriculum','','textarea');curriculum.maxLength=20000;
    const curriculumButton=button('Suggest curriculum with AI',form,()=>suggest('curriculum'));
    const pattern=field('Exam pattern','pattern','','textarea');pattern.maxLength=10000;
    const patternButton=button('Load official pattern with AI',form,()=>loadOfficial(true));
    const instructions=field('Student instructions','instructions','','textarea');instructions.maxLength=5000;
    const prompt=field('Editable generation prompt','generation_prompt','','textarea');prompt.rows=8;prompt.maxLength=20000;
    const additionalConditions=field('Additional conditions for final prompt (optional)','additional_conditions','','textarea');additionalConditions.rows=4;additionalConditions.maxLength=10000;additionalConditions.placeholder='For example: balance numerical and conceptual questions; avoid calculator-dependent arithmetic; include two assertion-reason questions.';
    const promptActions=el('div','',form);promptActions.className='actions wide';
    button('Build prompt from my inputs',promptActions,()=>{
      prompt.value=`Prepare an original ${mode.value==='FULL'?'full':'subject-wise'} ${program.name} paper for ${level.value||'the chosen level'} in ${language.value}. Use ${difficulty.selectedOptions[0].textContent} difficulty. Follow the curriculum, section counts, marking scheme and pattern supplied with this prompt. Cover the listed topics, construct plausible distractors, use clear age-appropriate language, provide one unambiguous correct answer and a worked solution for every question. Include visual reasoning where the curriculum requires it using the supported visual format. Avoid repeated questions and disclose no claims of official approval.`;invalidate();
    });
    const promptButton=button('Improve prompt with AI',promptActions,()=>suggest('prompt'));
    const reuse=field('Reuse approved questions matching these inputs','reuse_questions','','input');reuse.type='checkbox';reuse.checked=true;
    const actions=el('div','',form);actions.className='actions wide';
    let setupRevision=0;
    button('Save exam setup',actions,async()=>{
      try{
        const saved=await request(`/${program.id}/exam-setup`,'PUT',{settings:settings(),revision:setupRevision});
        setupRevision=saved.revision;status.textContent='Exam setup saved. It will be loaded when you reopen this program.';
      }catch(error){status.textContent=error.message;}
    });
    button('Preview final prompt',actions,async()=>{try{await preview();}catch(error){status.textContent=error.message;}});
    const generate=el('button','Generate paper for review',actions);generate.type='submit';generate.className='primary';
    const status=el('p','');status.setAttribute('role','status');
    const proposals=el('section','');
    const previewBox=el('details','');previewBox.open=true;el('summary','Final prompt — Markdown preview',previewBox);const finalPrompt=el('div','',previewBox);finalPrompt.className='guided-prompt-markdown';
    const rawBox=el('details','',previewBox);el('summary','View / copy Markdown source',rawBox);const rawPrompt=el('textarea','',rawBox);rawPrompt.readOnly=true;rawPrompt.rows=8;rawPrompt.setAttribute('aria-label','Final prompt Markdown source');
    button('Copy final prompt',previewBox,async()=>{try{await navigator.clipboard.writeText(rawPrompt.value);status.textContent='Final prompt copied.';}catch{rawPrompt.select();status.textContent='Select and copy the Markdown source.';}});
    const results=el('section','');
    if(options.reviewOnly){form.hidden=true;officialPanel.hidden=true;previewBox.hidden=true;}
    function settings(){return {name:name.value.trim(),mode:mode.value,level:level.value.trim(),language:language.value.trim(),duration_minutes:Number(duration.value),difficulty:difficulty.value,curriculum:curriculum.value.trim(),pattern:pattern.value.trim(),instructions:instructions.value.trim(),generation_prompt:prompt.value.trim(),additional_conditions:additionalConditions.value.trim(),sections:readSections(),reuse_questions:reuse.checked,official_lookup_id:officialLookupId};}
    let requestKey=null,lastRequest='',timer,previewTimer,previewVersion=0,officialTimer,officialLookupId=null,officialRow=null;
    const totals=el('div','',subjectArea);totals.className='guided-totals';const totalQuestions=field('Total questions','total_questions',0,'input',totals),totalMarks=field('Total marks','total_marks',0,'input',totals);totalQuestions.readOnly=true;totalMarks.readOnly=true;
    function updateTotals(){const values=readSections();totalQuestions.value=values.reduce((n,s)=>n+s.count,0);totalMarks.value=Number(values.reduce((n,s)=>n+s.count*s.marks,0).toFixed(4));}
    function invalidate(){requestKey=null;previewVersion++;updateTotals();showOfficial();clearTimeout(previewTimer);previewTimer=setTimeout(()=>{if(host.isConnected)preview().catch(error=>{finalPrompt.textContent=error.message;});},450);}
    form.addEventListener('input',invalidate);
    async function preview(){const version=++previewVersion,input=settings();input.sections=input.sections.filter(s=>s.subject);const data=await request(`/${program.id}/exam-prompt`,'POST',input);if(version===previewVersion&&host.isConnected){renderInto(finalPrompt,data.effective_prompt);rawPrompt.value=data.effective_prompt;}return data;}
    async function suggest(kind){
      const buttons=[allButton,curriculumButton,patternButton,promptButton];buttons.forEach(b=>b.disabled=true);status.textContent='Preparing an editable suggestion…';
      try{
        const input=settings(),baseline=JSON.stringify(input);
        // Empty placeholder rows are not substantive scope for an AI suggestion.
        input.sections=input.sections.filter(s=>s.subject);
        const data=await request(`/${program.id}/exam-assist`,'POST',{field:kind,settings:input});
        if(!host.isConnected)return;
        proposals.replaceChildren();const card=el('article','',proposals);card.className='panel program-setup-card';
        el('h5',`Review suggested ${kind==='all'?'exam setup':kind}`,card);
        el('p',kind==='prompt'?'Apply this suggestion, then edit it as needed.':'AI suggestions are unverified. Review the curriculum, counts and timing before using them.',card);
        el('pre',kind==='curriculum'?data.curriculum:kind==='prompt'?data.generation_prompt:data.pattern+'\n'+data.sections.map(s=>`${s.subject}: ${s.count} questions · ${s.marks} marks each · penalty ${s.negative_marks}`).join('\n')+`\nDuration: ${data.duration_minutes} minutes\n${data.instructions}`,card);
        if(kind==='all'){el('pre',`Class / level: ${data.level}\n\n${data.curriculum}\n\n${data.generation_prompt}`,card);}
        (data.assumptions||[]).forEach(value=>el('p',value,card));
        const applySuggestion=()=>{
          if(JSON.stringify(settings())!==baseline){status.textContent='Inputs changed while this suggestion was being prepared. Request a fresh suggestion to preserve your edits.';return;}
          if(kind==='curriculum'){
            curriculum.value=data.curriculum;
            if(!level.value.trim())level.value=data.level||'';
            if(!readSections().some(s=>s.subject))setSections(data.subjects.slice(0,mode.value==='SUBJECT'?1:20).map(subject=>({subject,count:10,marks:1,negative_marks:0,topics:''})));
          }else if(kind==='pattern'||kind==='all'){
            if(mode.value!==input.mode){status.textContent='Paper type changed. Request a fresh pattern suggestion.';return;}
            pattern.value=data.pattern;duration.value=data.duration_minutes;instructions.value=data.instructions;setSections(data.sections);
            if(kind==='all'){curriculum.value=data.curriculum;prompt.value=data.generation_prompt;level.value=data.level||level.value;}
          }else prompt.value=data.generation_prompt;
          invalidate();status.textContent='AI guidance populated in the editable fields.';
        };
        applySuggestion();
      }catch(error){status.textContent=error.message;}finally{buttons.forEach(b=>b.disabled=false);}
    }
    function populate(value){
      if(value.mode==='FULL')fullDuration=value.duration_minutes;
      mode.value=value.mode;name.value=value.name;level.value=value.level;language.value=value.language;difficulty.value=value.difficulty;duration.value=value.duration_minutes;
      curriculum.value=value.curriculum;pattern.value=value.pattern;instructions.value=value.instructions;prompt.value=value.generation_prompt;additionalConditions.value=value.additional_conditions||'';reuse.checked=value.reuse_questions;officialLookupId=value.official_lookup_id||null;setSections(value.sections);addSubject.hidden=value.mode==='SUBJECT';updateTotals();
    }
    function showOfficial(){
      officialPanel.replaceChildren();const busy=['QUEUED','RUNNING'].includes(officialRow?.status);allButton.disabled=busy;patternButton.disabled=busy;if(!officialRow)return;
      if(['QUEUED','RUNNING'].includes(officialRow.status)){el('p','Looking up the latest official exam information and preparing your editable inputs…',officialPanel);return;}
      if(officialRow.status==='FAILED'){el('p',officialRow.error,officialPanel);return;}
      const result=officialRow.result;if(!result?.official)return;
      const ref=result.official;
      el('h5',`${ref.exam_name} · ${ref.exam_cycle}`,officialPanel);
      el('p',`${ref.total_questions} questions · ${ref.total_marks} marks · ${ref.duration_minutes} minutes`,officialPanel);
      const current=readSections();
      const unchanged=mode.value==='FULL'&&Number(duration.value)===ref.duration_minutes&&current.length===ref.sections.length&&current.every((s,i)=>s.subject===ref.sections[i].subject&&s.count===ref.sections[i].count&&Math.abs(s.marks*s.count-ref.sections[i].total_marks)<.00001&&s.negative_marks===ref.negative_marks&&s.duration_minutes===ref.sections[i].duration_minutes);
      el('p',unchanged?'Official-source pattern populated. Review the AI extraction before use.':'Custom practice inputs — the official reference above remains available for comparison.',officialPanel);
      el('p',result.status_label||`Source checked ${new Date(result.checked_at).toLocaleString()}. Curriculum guidance and authoring prompts are AI suggestions.`,officialPanel);
      for(const source of result.sources||[]){const link=el('a',source.title||'Open official source',officialPanel);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';}
      for(const assumption of result.assumptions||[])el('p',assumption,officialPanel);
      if(result.search_html){const frame=el('iframe','',officialPanel);frame.title='Google Search suggestions';frame.setAttribute('sandbox','allow-popups allow-popups-to-escape-sandbox');frame.srcdoc=result.search_html;frame.className='official-search-suggestions';}
    }
    async function loadOfficial(force=false,autoFill=false){
      clearTimeout(officialTimer);
      try{
        officialRow=await request(`/${program.id}/official-pattern`);
        if(!host.isConnected)return;
        const startNew=force||(!officialRow&&autoFill);
        const baseline=JSON.stringify(settings());
        if(startNew){
          const input=settings();input.sections=input.sections.filter(s=>s.subject);
          officialRow=await request(`/${program.id}/official-pattern`,'POST',{request_key:crypto.randomUUID(),settings:input});
        }
        showOfficial();
        const canApply=force||autoFill;
        async function settle(){
          if(!host.isConnected)return;
          showOfficial();
          if(['QUEUED','RUNNING'].includes(officialRow.status)){
            officialTimer=setTimeout(async()=>{try{officialRow=await request(`/${program.id}/official-pattern`);await settle();}catch(error){status.textContent=error.message;}},3000);return;
          }
          if(officialRow.status==='READY'&&canApply){
            if(JSON.stringify(settings())!==baseline){status.textContent='Official pattern is ready. Your edits were kept; use Refresh official pattern to populate it.';return;}
            const chosen=mode.value==='SUBJECT'?readSections()[0]?.subject:null;
            const value={...officialRow.result.settings,difficulty:difficulty.value,language:language.value,reuse_questions:reuse.checked};
            fullDuration=value.duration_minutes;fullSections=value.sections;setChoices(fullSections);
            if(chosen){const section=fullSections.find(s=>s.subject.toLowerCase()===chosen.toLowerCase());if(section){value.mode='SUBJECT';value.sections=[section];value.duration_minutes=section.duration_minutes||value.duration_minutes;subjectChoice.value=section.subject;}else{status.textContent='The chosen subject was not in the official pattern. Select a subject from the retrieved full pattern.';}}
            populate(value);subjectChoice.parentElement.hidden=value.mode!=='SUBJECT'||fullSections.length<2;
            invalidate();status.textContent='Official pattern and AI guidance populated. All inputs remain editable.';await preview();
          }
        }
        if(officialRow)await settle();
      }catch(error){status.textContent=error.message;}
    }
    async function refresh(initial=false){
      clearTimeout(timer);const rows=options.paperId?[await request(`/${program.id}/exam-papers/${options.paperId}`)]:await request(`/${program.id}/exam-papers`);if(!results.isConnected)return;
      let savedSetup=null;
      if(initial&&!options.reviewOnly){savedSetup=await request(`/${program.id}/exam-setup`);setupRevision=savedSetup?.revision||0;
        if(savedSetup){populate(savedSetup.settings);fullSections=savedSetup.settings.sections;setChoices(fullSections);}
        else if(rows.length)populate(rows[0].input.settings);
      }
      results.replaceChildren();el('h4','Papers and review',results);
      if(!rows.length)el('p','Generated papers will appear here. You can leave and return while generation runs.',results);
      for(const row of rows){
        const card=el('article','',results);card.className='panel program-setup-card';
        const setup=row.input.settings;
        el('h5',`${setup.name||program.name} · #${row.id} · ${row.status.replaceAll('_',' ')}`,card);
        el('p',`${setup.mode==='FULL'?'Full Exam':setup.sections[0].subject} · ${difficultyOptions.find(([key])=>key===setup.difficulty)?.[1]||setup.difficulty} · ${setup.sections.reduce((n,s)=>n+s.count,0)} questions · ${setup.duration_minutes} minutes`,card);
        if(row.error)el('p',row.error,card);
        if(['RUNNING','QUEUED','FAILED'].includes(row.status)){
          const progress=row.result.progress,total=setup.sections.reduce((n,s)=>n+s.count,0),completed=progress?.completed||0;
          el('p',`${completed} of ${total} questions ready${progress?.section?' · '+progress.section:''}. Completed work is saved; retries continue from this point.`,card);
          const meter=el('progress','',card);meter.max=total;meter.value=completed;meter.setAttribute('aria-label','Paper generation progress');
        }
        const requestedTotal=setup.sections.reduce((n,s)=>n+s.count,0),completeFailure=row.status==='FAILED'&&(row.result.questions?.length||0)===requestedTotal;
        if(row.status==='FAILED'||(['RUNNING','QUEUED'].includes(row.status)&&Date.now()/1000-row.updated_at>1800))button(completeFailure?'Finalize for review':'Retry generation',card,async event=>{const retryButton=event.currentTarget;retryButton.disabled=true;status.textContent=completeFailure?'Finalizing the preserved paper for review…':'Resuming paper generation…';try{await request(`/${program.id}/exam-papers/${row.id}/retry`,'POST');await refresh();}catch(error){status.textContent=error.message;retryButton.disabled=false;}});
        if(row.result.questions&&(['REVIEW_REQUIRED','DRAFT','PUBLISHED'].includes(row.status)||completeFailure)){
          el('p',`${row.result.reused} reused from the bank · ${row.result.generated} generated`,card);
          const paper=el('details','',card);el('summary','Review question paper, answers and solutions',paper);
          row.result.questions.forEach((item,index)=>{
            const q=item.question;const block=el('section','',paper);block.className='guided-review-question';
            el('strong',`${index+1}. ${item.section.subject} · ${item.section.marks} marks · ${item.origin==='BANK'?'Question bank':'New question'}`,block);
            renderInto(el('div','',block),q.statement);
            q.options.forEach((text,i)=>renderInto(el('div','',block),`${String.fromCharCode(65+i)}. ${text}`));
            el('p',`Answer: ${q.answer}`,block);renderInto(el('div','',block),q.solution);
            if(q.id)button('Edit / AI correct / Regenerate',block,()=>QuestionCorrection.open(q,{programPaperId:row.id,onSaved:()=>refresh()}));
            if(q.id)button('Report a concern',block,()=>window.ResultTools?.reportConcern(q.id,null));
          });
          if(completeFailure)el('p','All questions are available to inspect. Finalize the preserved paper to enable approval and publication; no new AI generation is required.',card);
          const frozen=el('details','',card);el('summary','Inputs and prompt used for this paper',frozen);const frozenPrompt=el('div','',frozen);frozenPrompt.className='guided-prompt-markdown';renderInto(frozenPrompt,row.input.effective_prompt);
          if(row.status==='REVIEW_REQUIRED'||row.status==='DRAFT'){
            const reviewed=field('I reviewed the questions, answers and marking scheme','reviewed','','input',card);reviewed.type='checkbox';
            const actionArea=el('div','',card);actionArea.className='actions';
            const approve=async publish=>{
              if(!reviewed.checked){status.textContent='Review the paper and select the review checkbox first.';return;}
              actionArea.querySelectorAll('button').forEach(b=>b.disabled=true);
              try{const saved=await request(`/${program.id}/exam-papers/${row.id}/approve`,'POST',{reviewed:true,publish,review_updated_at:row.updated_at});status.textContent=`Exam #${saved.exam_id} ${publish?'published':'saved as a draft'}. It is available in Manage Exams.`;await refresh();await options.onChange?.();}
              catch(error){status.textContent=error.message;actionArea.querySelectorAll('button').forEach(b=>b.disabled=false);}
            };
            if(row.status==='REVIEW_REQUIRED')button('Approve and save draft exam',actionArea,()=>approve(false));
            button('Approve and publish exam',actionArea,()=>approve(true)).className='primary';
          }
        }
        if(row.exam_id){el('p',`Exam #${row.exam_id} · ${row.status==='PUBLISHED'?'Published':'Draft'}`,card);button('Open Manage Exams',card,()=>document.querySelector('#admin-nav [data-view="admin-exams"]')?.click());}
      }
      if(initial&&!options.reviewOnly){await loadOfficial(false,!savedSetup&&rows.length===0);invalidate();}
      if(rows.some(r=>['QUEUED','RUNNING'].includes(r.status)))timer=setTimeout(()=>{if(results.isConnected)refresh().catch(error=>{status.textContent=error.message;});},4000);
    }
    form.onsubmit=async event=>{
      event.preventDefault();if(!form.reportValidity())return;generate.disabled=true;status.textContent='Starting paper generation…';
      try{const value=settings(),serialized=JSON.stringify(value);if(!requestKey||lastRequest!==serialized){requestKey=crypto.randomUUID();lastRequest=serialized;}
        await preview();await request(`/${program.id}/exam-papers`,'POST',{request_key:requestKey,settings:value});requestKey=null;status.textContent='Paper generation started. Review and publication remain separate steps.';await refresh();
      }catch(error){status.textContent=error.message;}finally{generate.disabled=false;}
    };
    host.dataset.programCorrectionHost='1';host._refreshCorrections=()=>refresh();
    addSection();await refresh(true);
  }
  return {render,difficultyOptions};
})();
