/* R6 scoped keys/macros/tap-hold with synthetic replies only. */
const assert=require('assert/strict'),crypto=require('crypto');
const {harness,settle,clone,syntheticConfig,syntheticDevice}=require('./ui-check.cjs');
const hash=matrix=>crypto.createHash('sha256').update(Buffer.from(matrix.layer_data.flatMap(row=>row.layer).map(code=>code.slice(1)).join(''),'hex')).digest('hex');
const view=matrix=>({...clone(matrix),source:'live',keymapHash:hash(matrix)});
const catalog={schemaVersion:1,layerCount:7,physicalKeyCount:81,r6DirectKeymapSupported:true,modifiers:[],entries:[
 {code:'#00070004',name:'字母 A',short:'A',token:'A',category:'keyboard'},
 {code:'#00070005',name:'字母 B',short:'B',token:'B',category:'keyboard'},
 {code:'#00070029',name:'退出',short:'Esc',token:'Esc',category:'keyboard'},
 {code:'#000700E1',name:'左 Shift',short:'Shift',token:'Shift',category:'modifier'}
]};
const button=(h,name,value)=>h.document.querySelectorAll('[data-'+name+']').find(el=>el.getAttribute('data-'+name)===String(value));
function setup(options={}){
 const config=syntheticConfig(),device={...syntheticDevice,connected:true};
 const control={matrix:clone(config.key_layer),advanced:{macros:[],pressHolds:[]},plans:new Map(),nextRead:null,nextPlan:null};
 const advanced=()=>({...clone(control.advanced),available:true,snapshotHash:'a'.repeat(64),source:'live',verification:'readback-verified'});
 const h=harness({emptyBaseline:options.emptyBaseline,handlers:{
  bootstrap:()=>({device:{...device,connected:false},config:options.emptyBaseline?null:clone(config),keymap:view(control.matrix)}),
  keymapCatalog:()=>clone(catalog),
  r6KeymapRead:()=>control.nextRead||{device,keymap:view(control.matrix),advanced:advanced(),directKeymapSupported:true},
  r6KeymapPlan:payload=>{
   if(control.nextPlan)return control.nextPlan(payload);
   const target=clone(control.matrix),before=clone(control.advanced),after=clone(before);
   for(const change of payload.keyChanges||[])target.layer_data[change.layer].layer[change.matrixIndex]=change.code;
   if(payload.edit){const e=payload.edit,old=target.layer_data[e.layer].layer[e.matrixIndex],macro=e.type.includes('macro'),table=macro?'macros':'pressHolds';
    if(e.type.startsWith('remove-')){after[table]=after[table].filter(item=>item.trigger!==old);target.layer_data[e.layer].layer[e.matrixIndex]=e.replacementCode;}
    else{const trigger=old.startsWith(macro?'#009515':'#009514')?old:(macro?'#00951500':'#00951400');after[table]=after[table].filter(item=>item.trigger!==trigger);after[table].push(macro?{trigger,events:clone(e.events)}:{trigger,tapCode:e.tapCode,holdCode:e.holdCode,intervalMs:e.intervalMs});target.layer_data[e.layer].layer[e.matrixIndex]=trigger;}
   }
   const changes=[];for(let layer=0;layer<7;layer++)for(let matrixIndex=0;matrixIndex<200;matrixIndex++)if(target.layer_data[layer].layer[matrixIndex]!==control.matrix.layer_data[layer].layer[matrixIndex])changes.push({layer,matrixIndex,before:{code:control.matrix.layer_data[layer].layer[matrixIndex]},after:{code:target.layer_data[layer].layer[matrixIndex]}});
   const plan={kind:'keymap',mode:'r6-direct',token:'token-'+control.plans.size,expectedKeymapHash:payload.expectedKeymapHash,device,targetKeymap:view(target),keyChanges:changes,keyChangeCount:changes.length,changedSlots:[],summary:[],advancedEdit:payload.edit?clone(payload.edit):null,advancedBefore:before,advancedTarget:after,totalFrames:2,ledTransmitted:false,requiresDeviceAck:false};control.plans.set(plan.token,plan);return clone(plan);
  },
  r6KeymapExecute:payload=>{const p=control.plans.get(payload.token);control.matrix=clone(p.targetKeymap);control.advanced=clone(p.advancedTarget);return{success:true,deviceAck:null,keymapMatch:true,keymap:view(control.matrix),device,advanced:advanced(),stateStored:true,reportStored:true,verification:{keymap:'readback-verified',advanced:'readback-verified',led:'not-transmitted'}};},
  ...options.handlers
 }});
 return Object.assign(h,{r6:control,fixture:config});
}
async function ready(h){await settle();h.app.navigate('keymap');await settle();}
async function read(h){await h.el('r6AdvancedReadBtn').click();await button(h,'key','esc').click();}
(async()=>{
 const ordinary=setup({emptyBaseline:true});await ready(ordinary);assert.equal(ordinary.el('r6AdvancedKeymap').hidden,false);assert.equal(ordinary.calls.filter(c=>/^r6Keymap/.test(c.action)).length,0,'opening a page never opens USB');await read(ordinary);await button(ordinary,'function-code','#00070005').click();assert.equal(ordinary.el('prepareKeymapBtn').disabled,false,'scoped keys do not require unknown LED content');assert.equal(ordinary.el('keymapBaselineNote').hidden,true);await ordinary.el('prepareKeymapBtn').click();assert.match(ordinary.el('keymapReviewContent').innerHTML,/独立改键指令/);assert.equal(ordinary.calls.filter(c=>c.action==='r6KeymapExecute').length,0);await ordinary.el('keymapWriteAcknowledged').click();await ordinary.el('keymapExecuteBtn').click();assert.equal(ordinary.app.keymap.serialize(),null);assert.equal(ordinary.app.state.keymap.layer_data[0].layer[0],'#00070005');assert.equal(ordinary.app.state.config,null);assert.match(ordinary.el('keymapReviewContent').innerHTML,/1400/);assert.equal(ordinary.calls.filter(c=>['execute','keymapPlan'].includes(c.action)).length,0);
 console.log('PASS R6 scoped key path without an LED baseline, reviewed command-only plan and readback success without invented ACK');
 const hold=setup();await ready(hold);await read(hold);assert.equal(hold.el('r6AdvancedPrepareBtn').disabled,false);hold.el('r6HoldInterval').value='250';await hold.el('r6AdvancedPrepareBtn').click();const hp=hold.calls.filter(c=>c.action==='r6KeymapPlan').at(-1).payload;assert.equal(hp.edit.type,'press-hold');assert.equal(hp.edit.intervalMs,250);assert.equal(hp.edit.tapCode,'#11070004');assert.equal(hp.edit.holdCode,'#110700E1');assert.equal(hold.el('keymapExecuteBtn').disabled,true);await hold.el('keymapWriteAcknowledged').click();await hold.el('keymapExecuteBtn').click();assert.equal(hold.app.state.keymap.layer_data[0].layer[0],'#00951400');assert.match(hold.el('keymapReviewContent').innerHTML,/高级功能表也已读回验证/);assert.equal(hold.el('r6AdvancedDeleteFields').hidden,false);hold.el('r6ReplacementCode').value='#00070005';await hold.el('r6AdvancedDeleteBtn').click();assert.equal(hold.calls.filter(c=>c.action==='r6KeymapPlan').at(-1).payload.edit.replacementCode,'#00070005');await hold.el('keymapWriteAcknowledged').click();await hold.el('keymapExecuteBtn').click();assert.equal(hold.r6.advanced.pressHolds.length,0);assert.equal(hold.app.state.keymap.layer_data[0].layer[0],'#00070005');
 console.log('PASS tap/hold exact parameters, advanced-table verification, explicit deletion and selected replacement binding');
 const macro=setup();await ready(macro);await read(macro);macro.el('r6AdvancedMode').value='macro';macro.el('r6AdvancedMode').onchange();await macro.el('r6AddMacroTap').click();assert.equal(macro.document.querySelectorAll('[data-r6-event-delay]').length,2);assert.equal(macro.calls.filter(c=>c.action==='r6KeymapExecute').length,0);await macro.el('r6AdvancedPrepareBtn').click();const mp=macro.calls.filter(c=>c.action==='r6KeymapPlan').at(-1).payload;assert.deepEqual(clone(mp.edit.events),[{code:'#11070004',delayMs:100},{code:'#10070004',delayMs:100}]);await macro.el('keymapWriteAcknowledged').click();await macro.el('keymapExecuteBtn').click();assert.equal(macro.r6.advanced.macros.length,1);assert.equal(macro.app.state.keymap.layer_data[0].layer[0],'#00951500');assert.equal(macro.el('r6AdvancedMode').value,'macro');assert.match(macro.el('keymapBindingName').textContent,/宏/);
 console.log('PASS macro click expands to balanced down/up events and only executes after review confirmation');
 const missing=setup();await ready(missing);missing.r6.nextRead={device:{...syntheticDevice,connected:true},keymap:view(missing.r6.matrix),advanced:{available:false,reason:'incomplete device table'}};await read(missing);assert.equal(missing.el('r6AdvancedPrepareBtn').disabled,true);assert.match(missing.el('r6AdvancedState').textContent,/未读取完整/);assert.equal(missing.calls.filter(c=>c.action==='r6KeymapPlan').length,0);
 const busy=setup();await ready(busy);await read(busy);busy.app.state.voiceBusy=true;busy.app.keymap.refresh();assert.equal(busy.el('r6AdvancedPrepareBtn').disabled,true);assert.equal(busy.el('r6AdvancedReadBtn').disabled,true);assert.equal(busy.el('r6AddMacroTap').disabled,true);
 const tampered=setup();await ready(tampered);await read(tampered);tampered.r6.nextPlan=()=>({kind:'keymap',mode:'r6-direct',token:'bad',ledTransmitted:true});await tampered.el('r6AdvancedPrepareBtn').click();assert.match(tampered.el('keymapReviewContent').innerHTML,/未通过检查/);assert.equal(tampered.el('keymapExecuteBtn').hidden,true);assert.equal(tampered.calls.filter(c=>c.action==='r6KeymapExecute').length,0);
 console.log('PASS incomplete tables remain unknown, recording locks edits, malformed scope refuses execution. No USB or private data accessed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
