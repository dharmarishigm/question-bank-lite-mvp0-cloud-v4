/* Compact native menus preserve the original buttons, handlers and permissions. */
(()=>{
  function refresh(){
    document.querySelectorAll('#main-content table').forEach(table=>{
      if(table.closest('.rendered,.prompt-readable,.guided-prompt-markdown'))return;
      const headers=[...table.querySelectorAll('thead tr:first-child th')];
      const columns=headers.map((th,index)=>/^actions?$/i.test(th.textContent.trim())?index:-1).filter(index=>index>=0);
      // Tables with their own selection workflow keep it. Other data tables
      // get selection + export only, never invented bulk write permissions.
      if(headers.length&&!table.querySelector('input[type=checkbox]:not(.table-row-select)')){
        let toolbar=table.previousElementSibling;
        if(!toolbar?.classList.contains('table-selection-toolbar')){
          toolbar=document.createElement('div');toolbar.className='table-selection-toolbar';
          toolbar.innerHTML='<label><input type="checkbox" data-table-select-page> Select page</label><span data-table-selection-count>0 selected</span><select aria-label="Selected row actions" data-table-selected-actions><option value="">Selected actions…</option><option value="export">Export selected rows (CSV)</option><option value="clear">Clear selection</option></select>';
          table.before(toolbar);
          toolbar.querySelector('[data-table-select-page]').addEventListener('change',event=>{table.querySelectorAll('.table-row-select').forEach(box=>box.checked=event.target.checked);refresh();});
          toolbar.querySelector('select').addEventListener('change',event=>{
            const action=event.target.value;event.target.value='';
            if(action==='clear'){table.querySelectorAll('.table-row-select').forEach(box=>box.checked=false);refresh();return;}
            const rows=[...table.querySelectorAll('tbody tr')].filter(row=>row.querySelector('.table-row-select')?.checked);
            if(action!=='export'||!rows.length)return;
            const quote=value=>'"'+String(value).replace(/^[\s]*[=+@-]/,"'$&").replaceAll('"','""')+'"';
            const data=[headers.map(th=>th.textContent.trim()).filter((_,i)=>!columns.includes(i)),...rows.map(row=>[...row.cells].filter((_,i)=>!columns.includes(i)).map(cell=>cell.textContent.trim()))];
            const url=URL.createObjectURL(new Blob(['\ufeff'+data.map(row=>row.map(quote).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
            const link=document.createElement('a');link.href=url;link.download='selected-rows.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
          });
        }
        table.querySelectorAll('tbody tr').forEach(row=>{
          if(row.cells.length!==headers.length||!row.cells[0]||row.querySelector('.table-row-select'))return;
          const box=document.createElement('input');box.type='checkbox';box.className='table-row-select';box.setAttribute('aria-label','Select '+row.cells[0].textContent.trim());box.addEventListener('click',event=>event.stopPropagation());box.addEventListener('change',refresh);row.cells[0].prepend(box);
        });
        const boxes=[...table.querySelectorAll('.table-row-select')],selected=boxes.filter(box=>box.checked);
        const count=toolbar.querySelector('[data-table-selection-count]'),text=`${selected.length} selected`;if(count.textContent!==text)count.textContent=text;
        const page=toolbar.querySelector('[data-table-select-page]');page.checked=!!boxes.length&&selected.length===boxes.length;page.indeterminate=!!selected.length&&!page.checked;
        const select=toolbar.querySelector('select');if(select.disabled!==!selected.length)select.disabled=!selected.length;
      }
      table.querySelectorAll('tbody tr').forEach(row=>columns.forEach(index=>{
        const cell=row.cells[index];if(!cell)return;
        const buttons=[...cell.querySelectorAll('button')].filter(button=>!button.hidden&&!button.closest('[hidden]'));
        if(!buttons.length)return;
        let menu=cell.querySelector(':scope > select.table-action-menu');
        const signature=JSON.stringify(buttons.map(button=>[button.textContent.trim(),button.disabled]));
        if(!menu){
          menu=document.createElement('select');menu.className='table-action-menu';menu.setAttribute('aria-label','Actions for '+(row.cells[0]?.textContent.trim()||'this row'));cell.prepend(menu);
          menu.addEventListener('change',()=>{const button=menu._buttons?.[Number(menu.value)];menu.value='';if(button?.isConnected&&!button.disabled&&!button.hidden)button.click();});
        }
        menu._buttons=buttons;
        if(menu.dataset.signature!==signature){
          menu.replaceChildren(new Option('Actions…',''));
          buttons.forEach((button,i)=>{const option=new Option(button.textContent.trim(),String(i));option.disabled=button.disabled;menu.add(option);});
          menu.disabled=buttons.every(button=>button.disabled);menu.dataset.signature=signature;
        }
        buttons.forEach(button=>button.classList.add('table-action-source'));
      }));
    });
  }
  let queued=false;
  const schedule=()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;refresh();});};
  new MutationObserver(schedule).observe(document.querySelector('#main-content')||document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['disabled','hidden']});
  window.TableActions={refresh};refresh();
})();
