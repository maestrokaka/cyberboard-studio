(function(){
 'use strict';
 const copy=value=>JSON.parse(JSON.stringify(value));
 const validCode=code=>typeof code==='string'&&/^#[0-9a-f]{8}$/i.test(code);
 const layerName=layer=>layer===0?'基础层':layer===1?'Fn 层':'层 '+(layer+1);
 const equalCode=(a,b)=>String(a).toUpperCase()===String(b).toUpperCase();
 const pair=(layer,index)=>layer+':'+index;
 window.StudioKeymap={create(options){
  const {$,api,native,state,D,esc,toast,status,saveWorkspace,onBusy,onApplied,onRead}=options;
  const physical=new Map(D.keyLayout.map(key=>[key.matrix_index,key]));
  const known=new Map();D.keyLayout.forEach(key=>(key.bindings||[]).forEach(binding=>known.set(binding.code.toUpperCase(),binding)));
  let catalog=null,catalogRequest=null,draft=null,undo=[],request=0,review=null,reviewRevision=0,revision=0,modalMode='',reread=null,category='common',query='';
  const busy=()=>state.aiBusy||(state.voiceBusy||state.miaoCallBusy)||state.executing||state.hardwareBusy||state.preparingSync||state.closing;
  const changes=()=>draft?.changes||[];
  const hasDraft=()=>changes().length>0;
  const sourceMatrix=()=>state.keymap?.layer_data||state.config?.keymap?.layer_data||state.config?.key_layer?.layer_data;
  function matrix(layers){return Array.isArray(layers)&&layers.length===7&&layers.every(item=>Array.isArray(item.layer)&&item.layer.length===200&&item.layer.every(validCode))?layers.map(item=>item.layer.slice()):null;}
  function current(){const base=matrix(sourceMatrix()),hash=state.keymap?.keymapHash;return{base,baseHash:typeof hash==='string'&&/^[0-9a-f]{64}$/i.test(hash)?hash:null,device:{productId:state.device.productId||'',firmware:state.device.firmware||''}};}
  const live=()=>state.keymap?.source==='live'&&state.device.connected;
  function sameDevice(a,b){return a?.productId===b?.productId&&a?.firmware===b?.firmware;}
  function stale(){const source=current();return hasDraft()&&(!source.baseHash||source.baseHash!==draft.baseHash||!sameDevice(source.device,draft.device));}
  function describe(code){
   if(!validCode(code))return{code:code||'—',short:'未读取',name:'尚未读取'};
   const binding=known.get(code.toUpperCase());if(binding)return{...binding,code};
   const mask=parseInt(code.slice(1,3),16),base='#00'+code.slice(3),baseBinding=known.get(base.toUpperCase());
   if(mask&&baseBinding&&base.toUpperCase()!=='#00000000'&&catalog){const mods=catalog.modifiers.filter(item=>(mask&item.mask)===item.mask);if(mods.reduce((value,item)=>value|item.mask,0)===mask)return{code,short:mods.map(item=>item.short).join('+')+'+'+baseBinding.short,name:mods.map(item=>item.name).join(' + ')+' + '+baseBinding.name};}
   return{code,short:'未知功能',name:'未知功能 · 原始键码保留'};
  }
  function codeAt(layer,index){const changed=changes().find(item=>item.layer===layer&&item.matrixIndex===index);return changed?.code||(hasDraft()?draft.base[layer]?.[index]:sourceMatrix()?.[layer]?.layer?.[index])||null;}
  function baselineCode(layer,index){return hasDraft()?draft.base[layer]?.[index]:sourceMatrix()?.[layer]?.layer?.[index];}
  function editable(){const source=current();return native&&!busy()&&!!(hasDraft()?draft.baseHash:source.baseHash)&&!!(hasDraft()?draft.base:source.base)&&!stale();}
  function save(){revision++;review=null;saveWorkspace({preserveStatus:true});render();}
  function startDraft(){const source=current();if(!source.base||!source.baseHash||!source.device.productId||!source.device.firmware)return false;draft={schemaVersion:1,baseHash:source.baseHash,device:copy(source.device),base:copy(source.base),changes:[],updatedAt:new Date().toISOString()};return true;}
  function setCode(layer,index,code,record=true){
   if(!editable()||!validCode(code)||!physical.has(index))return false;
   if(!hasDraft()&&!startDraft()){toast('请先读取设备键位，再编辑。');return false;}
   const before=codeAt(layer,index);if(equalCode(before,code))return false;
   if(record)undo.push({layer,matrixIndex:index,code:before});
   draft.changes=draft.changes.filter(item=>pair(item.layer,item.matrixIndex)!==pair(layer,index));
   if(!equalCode(draft.base[layer][index],code))draft.changes.push({layer,matrixIndex:index,code});
   draft.changes.sort((a,b)=>a.layer-b.layer||a.matrixIndex-b.matrixIndex);draft.updatedAt=new Date().toISOString();save();return true;
  }
  async function loadCatalog(){
   if(catalog||catalogRequest||!native)return catalog;
   catalogRequest=(async()=>{try{const result=await api('keymapCatalog');if(result.schemaVersion!==1||result.layerCount!==7||result.physicalKeyCount!==81||!Array.isArray(result.entries)||!Array.isArray(result.modifiers))throw Error('功能目录格式不完整。');catalog=copy(result);catalog.entries.forEach(entry=>{if(validCode(entry.code))known.set(entry.code.toUpperCase(),entry);});render();return catalog;}catch(error){toast('键位功能目录未载入：'+error.message);return null;}finally{catalogRequest=null;}})();return catalogRequest;
  }
  function rows(){return D.keyLayout.map(key=>({...key,bindings:Array.from({length:7},(_,layer)=>describe(codeAt(layer,key.matrix_index)))}));}
  function render(){
   if(!$('keyGrid'))return;
   const focused=document.activeElement,focusAttribute=['data-key','data-layer','data-binding-layer','data-function-code'].find(attribute=>focused?.getAttribute?.(attribute)!==null&&focused?.getAttribute?.(attribute)!==undefined),focusValue=focusAttribute&&focused.getAttribute(focusAttribute);
   for(const key of state.keymap?.keys||[])for(const binding of key.bindings||[])if(validCode(binding.code)&&!known.has(binding.code.toUpperCase()))known.set(binding.code.toUpperCase(),binding);
   const data=rows(),locked=busy(),editableNow=editable(),source=current();
   $('keymapSource').textContent=hasDraft()?'显示本机键位草稿 · '+(stale()?'编辑基底需要重新确认。':live()?'以设备实时读取为基底。':'以本机缓存为基底。'):live()?'来自设备实时读取，81 个实体键 × 7 层。':source.base?'当前显示上次同步记录；连接后可以读取设备。':'缺少本机键位记录，请连接设备读取。';
   $('keymapReadState').textContent=hasDraft()?changes().length+' 项键位草稿':live()?'实时键位':source.base?'本机缓存':'尚未读取';$('keymapReadState').classList.toggle('pending',hasDraft());
   $('keymapDraftNote').textContent=stale()?'当前读回键位或设备已变化。草稿完整保留，请重新读取并确认如何处理。':hasDraft()?'本机键位草稿尚未同步；审核并确认后才会写入 USB。':source.base&&!source.baseHash?'缓存可以查看；连接并读取后才可编辑。':'点击实体按键，选择功能。各层分别编辑，灯效槽位草稿独立保留。';
   $('readKeysBtn').disabled=locked||!native;$('undoKeymapBtn').disabled=locked||!undo.length||stale();$('resetKeymapBtn').disabled=locked||!hasDraft();
   $('prepareKeymapBtn').disabled=locked||!hasDraft()||!state.device.connected||stale()||state.baselineMissing||!state.config;$('keymapDiffCount').textContent=changes().length+' 项修改';
   $('keymapBaselineNote').hidden=!hasDraft()||(!state.baselineMissing&&!!state.config);$('keymapBaselineNote').textContent='缺少这台键盘的完整配置记录，键位草稿可保留；无法安全同步，未知灯效不能从 USB 读回。';
   $('layerSwitch').innerHTML=Array.from({length:7},(_,layer)=>`<button type="button" data-layer="${layer}" class="${state.layer===layer?'selected':''}" aria-pressed="${state.layer===layer}" ${locked?'disabled':''}>${layerName(layer)}${changes().some(item=>item.layer===layer)?'<i aria-label="本层有修改"></i>':''}</button>`).join('');
   $('layerSwitch').querySelectorAll('[data-layer]').forEach(button=>button.onclick=()=>{if(busy())return;state.layer=Number(button.dataset.layer);render();});
   let column=1,previous=-1;
   $('keyGrid').innerHTML=data.map(key=>{if(previous!==key.row){previous=key.row;column=1;}const start=column,span=key.span||2;column+=span;const binding=key.bindings[state.layer],changed=changes().some(item=>item.layer===state.layer&&item.matrixIndex===key.matrix_index);return`<button type="button" class="key-button ${state.selectedKey===key.physical?'selected':''} ${changed?'key-changed':''}" data-key="${esc(key.physical)}" style="grid-row:${key.row+1};grid-column:${start}/span ${span}" title="${esc(key.physical_name)} → ${esc(binding.name)}${changed?' · 本机草稿':''}" aria-label="${esc(key.physical_name)}，${layerName(state.layer)}，${esc(binding.name)}${changed?'，已修改':''}" aria-pressed="${state.selectedKey===key.physical}" ${locked?'disabled':''}><span class="key-function">${esc(binding.code==='—'?key.physical_name:binding.short)}</span>${state.layer!==0?`<small>${esc(key.physical_name)}</small>`:''}</button>`;}).join('');
   $('keyGrid').querySelectorAll('[data-key]').forEach(button=>button.onclick=()=>{if(busy())return;state.selectedKey=button.dataset.key;query='';$('keymapFunctionSearch').value='';render();});
   const selected=data.find(key=>key.physical===state.selectedKey);
   $('keymapEditorEmpty').hidden=!!selected;$('keymapEditor').hidden=!selected;
   if(selected){const binding=selected.bindings[state.layer],base=describe(baselineCode(state.layer,selected.matrix_index));$('keymapSelectedName').textContent=selected.physical_name;$('keymapSelectedLayer').textContent=layerName(state.layer);$('keymapBindingName').textContent=binding.name;$('keymapRawCode').textContent=binding.code;$('keymapBeforeCode').textContent=equalCode(base.code,binding.code)?'原始键码逐字保留':'基底 '+base.code+' → 草稿 '+binding.code;$('resetKeyBindingBtn').disabled=!editableNow||equalCode(base.code,binding.code);$('bindingPanel').innerHTML=`<div class="binding-head"><h3>各层绑定</h3><span class="badge">矩阵 ${selected.matrix_index}</span></div><div class="binding-grid">${selected.bindings.map((item,layer)=>`<button type="button" class="binding-cell ${layer===state.layer?'selected':''}" data-binding-layer="${layer}" ${locked?'disabled':''}><small>${layerName(layer)}</small><b>${esc(item.short)}</b><code>${esc(item.code)}</code></button>`).join('')}</div>`;$('bindingPanel').querySelectorAll('[data-binding-layer]').forEach(button=>button.onclick=()=>{if(busy())return;state.layer=Number(button.dataset.bindingLayer);render();});}
   else $('bindingPanel').innerHTML='<p>选择一个按键，查看各层绑定与原始键码。</p>';
   $('keymapFunctionSearch').disabled=!selected||locked;$('keymapFunctionCategories').querySelectorAll('[data-key-category]').forEach(button=>{button.classList.toggle('selected',button.dataset.keyCategory===category);button.disabled=locked;});renderFunctions(selected,editableNow);renderDiff();
   if(focusAttribute&&!locked){const replacement=[...$('page-keymap').querySelectorAll('['+focusAttribute+']')].find(element=>element.getAttribute(focusAttribute)===focusValue);if(replacement&&!replacement.disabled)replacement.focus?.({preventScroll:true});}
  }
  function renderFunctions(selected,canEdit){
   if(!selected){$('keymapFunctionList').innerHTML='';return;}
   if(!catalog){$('keymapFunctionList').innerHTML='<p class="keymap-muted">'+(native?'打开键位页后载入 CLI 功能目录。':'功能选择需要桌面 App。')+'</p>';return;}
   $('keymapComboControls').hidden=category!=='combo';
   const categories=category==='common'?['keyboard','modifier','unassigned']:category==='combo'?['keyboard']:category==='media'?['media']:['layer','display','backlight','wireless','system'];
   const text=query.trim().toLowerCase(),entries=catalog.entries.filter(entry=>categories.includes(entry.category)&&(!text||[entry.short,entry.name,entry.token,entry.code].some(value=>String(value).toLowerCase().includes(text))));
   $('keymapFunctionList').innerHTML=entries.length?entries.map(entry=>`<button type="button" class="keymap-function-option" data-function-code="${esc(entry.code)}" ${!canEdit?'disabled':''}><b>${esc(entry.short)}</b><span>${esc(entry.name)}</span></button>`).join(''):'<p class="keymap-muted">没有匹配功能。</p>';
   $('keymapFunctionList').querySelectorAll('[data-function-code]').forEach(button=>button.onclick=()=>{if(!editable())return;let code=button.dataset.functionCode;if(category==='combo'){const mask=[...$('keymapComboControls').querySelectorAll('[data-modifier-mask]')].filter(box=>box.checked).reduce((value,box)=>value|Number(box.dataset.modifierMask),0);if(!mask){toast('先选择组合键修饰键，再选择普通按键。');return;}code='#'+mask.toString(16).padStart(2,'0').toUpperCase()+code.slice(3);}setCode(state.layer,selected.matrix_index,code);});
   if(!$('keymapComboControls').querySelectorAll('[data-modifier-mask]').length){$('keymapComboControls').innerHTML=catalog.modifiers.map(item=>`<label><input type="checkbox" data-modifier-mask="${item.mask}" ${!canEdit?'disabled':''}>${esc(item.name)}</label>`).join('');}
   $('keymapComboControls').querySelectorAll('[data-modifier-mask]').forEach(box=>box.disabled=!canEdit);
  }
  function renderDiff(){
   $('keymapDiffList').innerHTML=hasDraft()?changes().map(item=>{const key=physical.get(item.matrixIndex),before=describe(draft.base[item.layer][item.matrixIndex]),after=describe(item.code);return`<div class="keymap-diff-row"><span>${layerName(item.layer)} · ${esc(key.physical_name)}</span><span>${esc(before.short)} <i>→</i> <b>${esc(after.short)}</b></span><code>${esc(before.code)} → ${esc(after.code)}</code></div>`;}).join(''):'<p class="keymap-muted">暂无键位修改。</p>';
  }
  function openModal(mode,title,html){modalMode=mode;$('keymapReviewTitle').textContent=title;$('keymapReviewContent').innerHTML=html;$('keymapReviewModal').hidden=false;$('keymapExecuteBtn').hidden=true;$('keymapResolveBtn').hidden=true;$('keymapDiscardBtn').hidden=true;$('keymapCancelBtn').disabled=false;$('keymapReviewCloseBtn').disabled=false;$('keymapReviewCloseBtn').focus?.();}
  function closeModal(){if(state.executing||state.closing)return;request++;review=null;reread=null;modalMode='';$('keymapReviewModal').hidden=true;$('keymapExecuteBtn').disabled=true;}
  function requestRead(){
   if(busy())return;
   if(hasDraft()){openModal('read','读取前保留键位草稿',`<p>当前有 ${changes().length} 项本机修改。读取会保留草稿，并比较新的设备键位；基底变化时需要你确认。</p>`);$('keymapResolveBtn').hidden=false;$('keymapResolveBtn').textContent='保留草稿并读取';$('keymapResolveBtn').onclick=()=>read();return;}
   return read();
  }
  async function read(){
   if(busy()||!native)return;const token=++request;review=null;state.hardwareBusy=true;onBusy?.();render();status('正在读取设备键位…');
   try{const result=await api('keymap');if(token!==request||state.page!=='keymap'||state.closing)return;if(result.connected===false)throw Error('未发现 Cyberboard USB 设备，本机草稿保留。');const view=result.keymap||result,device=result.device||state.device,base=matrix(view.layer_data);if(!base||typeof view.keymapHash!=='string'||!/^([a-f0-9]{64})$/i.test(view.keymapHash))throw Error('设备键位读回不完整。');state.keymap={...copy(view),source:'live'};state.device={...state.device,...device,connected:true};if(Object.prototype.hasOwnProperty.call(result,'config')){state.config=result.config?copy(result.config):null;state.baselineMissing=!state.config;onRead?.();}if(hasDraft()&&(draft.baseHash!==view.keymapHash||!sameDevice(draft.device,state.device))){reread={base,baseHash:view.keymapHash,device:{productId:state.device.productId,firmware:state.device.firmware}};openRebase();}else{closeModal();status('设备键位实时读取完成');}}
   catch(error){if(token===request&&state.page==='keymap'&&!state.closing){state.device.connected=false;if(state.keymap)state.keymap.source='cached';toast(error.message);status('设备键位未读取完成 · 本机草稿保留');}}
   finally{state.hardwareBusy=false;onBusy?.();render();}
  }
  function openRebase(){const canRebase=sameDevice(draft.device,reread.device),conflicts=changes().filter(item=>!equalCode(draft.base[item.layer][item.matrixIndex],reread.base[item.layer][item.matrixIndex]));openModal('rebase','读回基底已变化',`<p>${canRebase?'新读回键位与编辑基底不同。':'当前设备身份与草稿不同。'}${changes().length} 项草稿完整保留。</p>${canRebase?`<p>${conflicts.length} 个编辑位置的设备键码也发生了变化。重新应用会使用草稿中的目标功能，其他全部键码采用本次读回。</p>`:'<p>不能把这份草稿自动应用到另一设备。取消可保留原草稿，或明确放弃后编辑当前设备。</p>'}<div class="keymap-rebase-list">${conflicts.map(item=>`<p>${layerName(item.layer)} · ${esc(physical.get(item.matrixIndex).physical_name)}：基底 ${esc(draft.base[item.layer][item.matrixIndex])} · 设备 ${esc(reread.base[item.layer][item.matrixIndex])} · 草稿 ${esc(item.code)}</p>`).join('')}</div>`);$('keymapResolveBtn').hidden=!canRebase;$('keymapResolveBtn').textContent='将草稿应用到新基底';$('keymapResolveBtn').onclick=()=>{if(busy()||!reread||!sameDevice(draft.device,reread.device))return;draft={...draft,...copy(reread),changes:changes().filter(item=>!equalCode(item.code,reread.base[item.layer][item.matrixIndex])),updatedAt:new Date().toISOString()};undo=[];closeModal();save();};$('keymapDiscardBtn').hidden=false;$('keymapDiscardBtn').textContent='放弃草稿，使用读回键位';$('keymapDiscardBtn').onclick=discard;}
  function discard(){if(busy())return;draft=null;undo=[];closeModal();save();status('键位草稿已撤销 · 键盘未改变');}
  function reset(){if(busy()||!hasDraft())return;openModal('reset','撤销全部键位草稿？',`<p>将撤销 ${changes().length} 项本机修改。设备上的键位不受影响，灯效槽位草稿继续保留。</p>`);$('keymapDiscardBtn').hidden=false;$('keymapDiscardBtn').textContent='撤销全部键位草稿';$('keymapDiscardBtn').onclick=discard;}
  function validatePlan(plan,submitted){
   if(plan?.kind!=='keymap'||typeof plan.token!=='string'||!plan.token||plan.initialization===true||!plan.config||!Array.isArray(plan.keyChanges)||plan.keyChangeCount!==submitted.length||!submitted.length||(plan.changedSlots||[]).length||(plan.summary||[]).length)throw Error('键位计划的修改范围未通过检查；尚未写入键盘。');
   if(!sameDevice(plan.device,draft.device)||plan.expectedKeymapHash!==draft.baseHash)throw Error('键位计划的设备或编辑基底未通过检查。');
   const target=matrix(plan.config.key_layer?.layer_data||plan.config.keymap?.layer_data);
   if(!target||JSON.stringify(plan.config.page_data)!==JSON.stringify(state.config?.page_data))throw Error('键位计划未完整保留灯效基线。');
   for(let layer=0;layer<7;layer++)for(let index=0;index<200;index++){const expected=submitted.find(item=>item.layer===layer&&item.matrixIndex===index)?.code||draft.base[layer][index];if(!equalCode(target[layer][index],expected))throw Error('键位计划包含未审核的键码修改。');}
   if(plan.keyChanges.length!==submitted.length||new Set(plan.keyChanges.map(item=>pair(item.layer,item.matrixIndex))).size!==submitted.length)throw Error('键位计划包含重复或缺失的修改。');
   for(const item of plan.keyChanges){const expected=submitted.find(change=>change.layer===item.layer&&change.matrixIndex===item.matrixIndex);if(!expected||!equalCode(item.before?.code,draft.base[item.layer]?.[item.matrixIndex])||!equalCode(item.after?.code,expected.code))throw Error('键位计划与当前草稿不同，请重新读取并审核。');}
   return true;
  }
  async function prepare(){
   if(busy()||!hasDraft()||stale()||!state.device.connected||state.baselineMissing||!state.config)return;
   const token=++request,submitted=copy(changes()),draftRevision=revision;review=null;state.preparingSync=true;onBusy?.();render();openModal('plan','审核键位修改','<p class="keymap-muted">正在检查当前设备与完整灯效基线，创建完整配置备份…</p>');
   try{const plan=await api('keymapPlan',{expectedKeymapHash:draft.baseHash,expectedProductId:draft.device.productId,expectedFirmware:draft.device.firmware,keyChanges:submitted});if(token!==request||$('keymapReviewModal').hidden||state.page!=='keymap'||state.closing||draftRevision!==revision)return;validatePlan(plan,submitted);review=copy(plan);reviewRevision=revision;$('keymapReviewContent').innerHTML=`<p>${submitted.length} 项实体键绑定将改变。完整灯效基线、未编辑键码和灯效槽位草稿保持各自状态。</p><div class="keymap-review-diff">${plan.keyChanges.map(item=>`<div class="keymap-diff-row"><span>${layerName(item.layer)} · ${esc(item.physicalName||physical.get(item.matrixIndex).physical_name)}</span><span>${esc(item.before.name||describe(item.before.code).name)} <i>→</i> <b>${esc(item.after.name||describe(item.after.code).name)}</b></span><code>${esc(item.before.code)} → ${esc(item.after.code)}</code></div>`).join('')}</div><p class="sync-note">完整配置备份已创建；USB 将传输完整配置并读回 1400 个键码校验。灯效使用本机完整记录保留，不能从设备完整读回。预计 ${Math.ceil(plan.estimatedSeconds||0)} 秒。</p><label class="keymap-confirm"><input type="checkbox" id="keymapWriteAcknowledged">我已逐项检查，同意只修改上方键位。</label>`;$('keymapExecuteBtn').hidden=false;$('keymapExecuteBtn').disabled=true;$('keymapWriteAcknowledged').onchange=()=>{$('keymapExecuteBtn').disabled=!$('keymapWriteAcknowledged').checked||busy()||reviewRevision!==revision;};status('键位计划已准备 · 等待明确确认');}
   catch(error){if(token===request&&!$('keymapReviewModal').hidden&&!state.closing){review=null;$('keymapReviewContent').innerHTML='<div class="sync-error">'+esc(error.message)+'</div><p class="sync-note">草稿完整保留。请重新读取设备键位后再审核；尚未写入键盘。</p>';status('键位计划未通过检查');}}
   finally{state.preparingSync=false;onBusy?.();render();}
  }
  async function execute(){
   if(!review||busy()||reviewRevision!==revision||$('keymapReviewModal').hidden||!$('keymapWriteAcknowledged')?.checked||$('keymapExecuteBtn').disabled)return;
   const plan=review;try{validatePlan(plan,changes());}catch(error){toast(error.message);closeModal();return;}state.executing=true;onBusy?.();render();$('keymapCancelBtn').disabled=$('keymapReviewCloseBtn').disabled=$('keymapExecuteBtn').disabled=true;$('keymapReviewTitle').textContent='正在同步键位';$('keymapReviewContent').innerHTML='<p>请保持 USB 连接，等待设备提交与键码读回。</p><div class="progress-track"><div id="keymapProgressFill" class="progress-fill"></div></div><p id="keymapProgressText">开始传输</p>';
   let saved=false;
   try{const result=await api('execute',{token:plan.token});if(!result.success||!result.deviceAck||!result.keymapMatch)throw Error('设备确认或键码读回校验未完成。');state.config=result.stateStored===false?state.config:copy(plan.config);state.baselineMissing=!state.config;state.device={...state.device,...result.device,connected:true};if(result.keymap)state.keymap={...copy(result.keymap),source:'live'};else if(plan.targetKeymap)state.keymap={...copy(plan.targetKeymap),source:'live'};else state.keymap=null;draft=null;undo=[];revision++;review=null;onApplied?.();saved=true;$('keymapReviewTitle').textContent='键位同步完成';$('keymapReviewContent').innerHTML='<p class="success-line">设备已确认，1400 个键码读回一致。</p><p class="sync-note">键位草稿已完成，灯效槽位草稿保留。</p>'+(result.warning||result.stateStored===false||result.reportStored===false?'<div class="sync-error">设备已同步，本机记录或报告未完整保存：'+esc(result.warning||'请保留备份并重新检查本机记录。')+'</div>':'');status(result.warning||result.stateStored===false||result.reportStored===false?'键位已同步 · 本机记录或报告保存未完成':'键位同步成功 · 读回校验通过');}
   catch(error){$('keymapReviewTitle').textContent='键位同步未完成';$('keymapReviewContent').innerHTML='<div class="sync-error">'+esc(error.message)+'</div><p class="sync-note">草稿与完整备份保留。设备结果可能需要重新读取确认；不要直接重复写入。</p>';review=null;state.device.connected=false;if(state.keymap)state.keymap.source='cached';status('键位同步未完成 · 请重新读取设备');}
   finally{state.executing=false;onBusy?.();render();$('keymapExecuteBtn').hidden=true;$('keymapCancelBtn').disabled=$('keymapReviewCloseBtn').disabled=false;if(saved)saveWorkspace({preserveStatus:true});}
  }
  function restore(value){if(value===undefined||value===null)return;try{if(value.schemaVersion!==1||!Array.isArray(value.base)||value.base.length!==7||value.base.some(row=>!Array.isArray(row)||row.length!==200||row.some(code=>!validCode(code)))||!/^[0-9a-f]{64}$/i.test(value.baseHash)||!value.device?.productId||!value.device?.firmware||!Array.isArray(value.changes)||value.changes.length>567||value.changes.some(item=>!Number.isInteger(item.layer)||item.layer<0||item.layer>6||!physical.has(item.matrixIndex)||!validCode(item.code))||new Set(value.changes.map(item=>pair(item.layer,item.matrixIndex))).size!==value.changes.length)throw Error('键位草稿格式不完整。');draft=copy(value);undo=[];revision++;render();}catch(error){toast('本机键位草稿未载入：'+error.message);}}
  $('keymapFunctionCategories').innerHTML=[['common','常用'],['combo','组合键'],['media','媒体'],['device','键盘功能']].map(([id,name])=>`<button type="button" data-key-category="${id}" class="${category===id?'selected':''}">${name}</button>`).join('');
  $('keymapFunctionCategories').querySelectorAll('[data-key-category]').forEach(button=>button.onclick=()=>{if(busy())return;category=button.dataset.keyCategory;query='';$('keymapFunctionSearch').value='';render();});
  $('keymapFunctionSearch').oninput=()=>{if(busy())return;query=$('keymapFunctionSearch').value;renderFunctions(rows().find(key=>key.physical===state.selectedKey),editable());};
  $('readKeysBtn').onclick=requestRead;$('undoKeymapBtn').onclick=()=>{if(busy()||stale()||!undo.length)return;const item=undo.pop();setCode(item.layer,item.matrixIndex,item.code,false);};$('resetKeymapBtn').onclick=reset;$('resetKeyBindingBtn').onclick=()=>{const key=D.keyLayout.find(item=>item.physical===state.selectedKey);if(key)setCode(state.layer,key.matrix_index,baselineCode(state.layer,key.matrix_index));};$('prepareKeymapBtn').onclick=prepare;$('keymapExecuteBtn').onclick=execute;$('keymapCancelBtn').onclick=closeModal;$('keymapReviewCloseBtn').onclick=closeModal;
  return{render,refresh:render,restore,serialize:()=>hasDraft()?copy(draft):null,hasDraft,describe,loadCatalog,requestRead,prepare,closeConfirmation:closeModal,pageChanged(page){if(page!=='keymap'){request++;if(!state.executing)closeModal();}else{render();loadCatalog();}},progress(message){if(!state.executing||modalMode!=='plan')return;const label=$('keymapProgressText');if(label)label.textContent=({committing:'等待设备提交',verifying:'读取键码并验证',completed:'同步完成'}[message.stage]||'传输完整配置')+(message.total>0?' · '+message.transferred+' / '+message.total+' 包':'');if($('keymapProgressFill')&&message.total>0)$('keymapProgressFill').style.width=Math.min(100,message.transferred/message.total*100)+'%';},prepareClose(){if(state.hardwareBusy||state.preparingSync||state.executing)throw Error('请等待设备操作完成，再退出。');}};
 }};
})();
