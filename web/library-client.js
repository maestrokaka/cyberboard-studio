(function(global){
 'use strict';
 function create(options){
  const {$,state,M,builtInIds,esc,thumbnail,selectDesign,renderSlots,renderDesignSelect,saveWorkspace,navigate,toast}=options;
  let confirmation=null,sequence=0;
  const isCustom=design=>!!design&&!builtInIds.has(design.id)&&state.designs.some(d=>d.id===design.id);
  const customCount=()=>state.designs.filter(d=>!builtInIds.has(d.id)).length;
  function blocked(){if(state.aiBusy||state.executing||state.preparingSync||!$('syncModal').hidden){toast('请先完成或关闭当前操作，再整理作品。');return true;}return false;}
  function refreshSelection(){const editable=isCustom(state.selected),busy=state.aiBusy||state.executing||state.preparingSync;$('designNameInput').value=options.isEmptyDesign(state.selected)?'':state.selected.name||'';$('designNameInput').disabled=!editable||busy;$('saveDesignNameBtn').disabled=!editable||busy;$('designNameHint').textContent=editable?'名称会用于作品库和导出文件；不改变灯效内容。':options.isEmptyDesign(state.selected)?'导入、制作或恢复一套作品后，可在这里命名。':'内置作品保留原名；生成模板变体后可另行命名。';}
  function rename(){
   if(blocked()||!isCustom(state.selected))return;
   const name=$('designNameInput').value.trim();if(!name||name.length>60||/[\u0000-\u001F\u007F]/.test(name)){toast('请输入 1–60 个字符的作品名称。');return;}
   state.selected.name=name;for(const pending of state.pending.values())if(pending.design.id===state.selected.id)pending.design.name=name;
   $('designTitle').textContent=name;renderDesignSelect();renderSlots();refreshSelection();render();saveWorkspace();toast('作品名称已保存。');
  }
  function softDelete(id){
   if(blocked())return;const index=state.designs.findIndex(d=>d.id===id);if(index<0)return;
   if(state.trash.length>=30){toast('回收站已满 30 套，请先恢复或明确清理其中的作品。');state.libraryView='trash';render();return;}
   const design=state.designs[index],builtin=builtInIds.has(design.id),archived=M.copy(design);
   if(builtin&&!state.removedBuiltinIds.has(id)&&state.removedBuiltinIds.size>=255){toast('内置作品删除记录已达 255 项，请先恢复部分作品。');return;}
   if(state.trash.some(item=>item.design.id===archived.id)){if(builtin){toast('回收站已有这套内置作品，请先处理旧记录。');return;}archived.id=archived.id.slice(0,215)+'-deleted-'+Date.now().toString(36)+'-'+(++sequence);}
   if(builtin)state.removedBuiltinIds.add(id);state.trash.push({design:archived,deletedAt:new Date().toISOString()});state.designs.splice(index,1);
   for(const [slot,pending]of state.pending)if(pending.design.id===id)state.pending.delete(slot);
   if(state.selected.id===id)selectDesign(options.fallbackDesign());else refreshSelection();
   renderDesignSelect();renderSlots();render();saveWorkspace();toast('已移入回收站，并取消引用此作品的槽位草稿；键盘灯效保留。');
  }
  function restore(id){
   if(blocked())return;const index=state.trash.findIndex(item=>item.design.id===id);if(index<0)return;
   const design=M.copy(state.trash[index].design),removed=state.removedBuiltinIds.has(design.id),builtin=removed&&options.builtInDesign(design.id),unknown=removed&&!builtin;
   if(!builtin&&customCount()>=30){toast('作品库已满 30 套自定义作品，请先移出部分作品。');return;}
   M.validate(design);
   if(builtin&&state.designs.some(d=>d.id===design.id)){toast('已有同编号作品，请先整理后再恢复，原记录保留。');return;}
   if(unknown||state.designs.some(d=>d.id===design.id)){const base=design.id.slice(0,215);do{design.id=base+'-restored-'+Date.now().toString(36)+'-'+(++sequence);}while(state.designs.some(d=>d.id===design.id)||state.removedBuiltinIds.has(design.id)||options.builtInDesign(design.id));}
   state.trash.splice(index,1);if(builtin)state.removedBuiltinIds.delete(design.id);
   if(builtin&&!builtInIds.has(design.id))selectDesign(builtin);else{state.designs.push(design);if(builtin){const order=new Map(Array.from(builtInIds,(id,index)=>[id,index]));state.designs.sort((a,b)=>{const left=order.get(a.id),right=order.get(b.id);return left===undefined?right===undefined?0:1:right===undefined?-1:left-right;});}if(options.isEmptyDesign(state.selected))selectDesign(design);}
   renderDesignSelect();renderSlots();refreshSelection();render();saveWorkspace();toast(unknown?'该旧内置作品已作为自定义作品恢复；原删除记录保留。':'作品已恢复，槽位草稿不会自动恢复。');
  }
  function closeConfirmation(){confirmation=null;$('libraryConfirmModal').hidden=true;}
  function requestPermanent(id){
   if(blocked())return;const item=id?state.trash.find(x=>x.design.id===id):null;if(id&&!item||!id&&!state.trash.length)return;
   confirmation={id:id||null};$('libraryConfirmTitle').textContent=id?'永久删除这套作品？':'清空回收站？';
   $('libraryConfirmMessage').textContent=id?'「'+item.design.name+'」将从本机回收站永久删除，无法恢复。已有键盘灯效不会改变。':'回收站内 '+state.trash.length+' 套作品将永久删除，无法恢复。已有键盘灯效不会改变。';
   $('libraryConfirmDeleteBtn').textContent=id?'永久删除':'永久清空';$('libraryConfirmModal').hidden=false;
  }
  function confirmPermanent(){if(!confirmation||blocked())return;const id=confirmation.id;if(id)state.trash=state.trash.filter(item=>item.design.id!==id);else state.trash=[];closeConfirmation();render();saveWorkspace();toast(id?'已从回收站永久删除。':'回收站已清空。');}
  function render(){
   const trash=state.libraryView==='trash',q=$('librarySearch').value.trim().toLowerCase(),records=(trash?state.trash:state.designs.map(design=>({design}))).filter(item=>(item.design.name+' '+(item.design.description||'')).toLowerCase().includes(q));
   $('libraryWorksTab').classList.toggle('selected',!trash);$('libraryTrashTab').classList.toggle('selected',trash);$('libraryTrashTab').textContent='回收站'+(state.trash.length?' ('+state.trash.length+')':'');$('clearTrashBtn').hidden=!trash;$('clearTrashBtn').disabled=!state.trash.length||state.aiBusy||state.executing;
   $('libraryCount').textContent=records.length+(trash?' 套已删除作品':' 套作品');$('libraryNote').textContent=trash?'恢复只找回作品；永久删除前会再次确认。回收站最多 30 套。':'内置和自定义作品都可移入回收站；本机删除状态会保留。删除不影响已经同步的键盘灯效。';
   $('libraryGrid').innerHTML=records.map(({design:d,deletedAt})=>`<article class="library-card"><div class="library-art"><canvas class="led-thumbnail" data-library-thumb="${esc(d.id)}"></canvas></div><div class="library-info"><div class="label-row"><h3>${esc(d.name)}</h3><span class="badge">${trash?'回收站':builtInIds.has(d.id)?'内置':window.StudioAI?.isAIWork(d)?esc(window.StudioAI.providerName(d.ai?.provider||(d.origin==='kimi-ai'?'kimi-open':d.origin.replace(/-ai$/,'')))+' 创作'):d.origin==='template-variant'?'模板变体':'作品'}</span></div><p>${esc(d.description||'顶部与轴灯同步编排。')}</p><div class="palette">${(d.palette||[]).slice(0,5).map(c=>`<span class="color-chip" style="background:${esc(c)}" title="${esc(c)}"></span>`).join('')}</div>${trash?`<div class="library-deleted-date">移入时间 ${esc(new Date(deletedAt).toLocaleString('zh-CN',{hour12:false}))}</div>`:''}<div class="library-footer"><span>${d.frames.length} 帧 · ${(d.frames.length*d.speed_ms/1000).toFixed(2)} 秒</span>${trash?`<button class="button" data-restore-design="${esc(d.id)}">恢复作品</button>`:`<button class="button" data-preview-design="${esc(d.id)}">预览作品</button>`}</div>${trash?`<div class="library-manage"><button class="text-button danger-text" data-permanent-design="${esc(d.id)}">永久删除</button></div>`:`<div class="library-manage">${!builtInIds.has(d.id)?`<button class="text-button" data-rename-design="${esc(d.id)}">重命名</button>`:'<span class="muted">内置作品</span>'}<button class="text-button" data-delete-design="${esc(d.id)}">移入回收站</button></div>`}</div></article>`).join('')||'<div class="empty-state">'+(trash?'回收站没有匹配的作品':'没有匹配的灯效作品')+'</div>';
   document.querySelectorAll('[data-library-thumb]').forEach(c=>thumbnail(c,records.find(item=>item.design.id===c.dataset.libraryThumb)?.design));
   document.querySelectorAll('[data-preview-design]').forEach(b=>b.onclick=()=>{selectDesign(state.designs.find(d=>d.id===b.dataset.previewDesign));navigate('workbench');});
   document.querySelectorAll('[data-rename-design]').forEach(b=>b.onclick=()=>{selectDesign(state.designs.find(d=>d.id===b.dataset.renameDesign));navigate('workbench');$('designNameInput').focus?.();$('designNameInput').select?.();});
   document.querySelectorAll('[data-delete-design]').forEach(b=>{b.disabled=state.aiBusy||state.executing;b.onclick=()=>softDelete(b.dataset.deleteDesign);});
   document.querySelectorAll('[data-restore-design]').forEach(b=>{b.disabled=state.aiBusy||state.executing;b.onclick=()=>restore(b.dataset.restoreDesign);});
   document.querySelectorAll('[data-permanent-design]').forEach(b=>{b.disabled=state.aiBusy||state.executing;b.onclick=()=>requestPermanent(b.dataset.permanentDesign);});
  }
  $('saveDesignNameBtn').onclick=rename;$('designNameInput').onkeydown=event=>{if(event.key==='Enter')rename();};
  $('libraryWorksTab').onclick=()=>{state.libraryView='works';render();};$('libraryTrashTab').onclick=()=>{state.libraryView='trash';render();};$('clearTrashBtn').onclick=()=>requestPermanent();
  $('libraryConfirmCancelBtn').onclick=closeConfirmation;$('libraryConfirmCloseBtn').onclick=closeConfirmation;$('libraryConfirmDeleteBtn').onclick=confirmPermanent;
  refreshSelection();return{render,refreshSelection,closeConfirmation};
 }
 function fileName(name){let safe=String(name||'灯效作品').replace(/[<>:"/\\|?*\u0000-\u001F\u007F]/g,'-').replace(/^[ .]+|[ .]+$/g,'').slice(0,80).replace(/[ .]+$/g,'');if(!safe)safe='灯效作品';if(/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(safe))safe='_'+safe;return safe+'.design.json';}
 global.StudioLibrary={create,fileName};
})(typeof window!=='undefined'?window:globalThis);
