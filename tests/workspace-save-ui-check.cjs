/* Actual App + conversation controller save/exit integration. Synthetic bridge only; no model or USB. */
'use strict';
const assert=require('node:assert/strict');
const {harness,settle,clone}=require('./ui-check.cjs');

const settings={provider:'kimi-code',baseUrl:'https://api.kimi.com/coding/v1',model:'k3',hasKey:true,supportsImages:true};
const reference={name:'offline-reference.jpg',dataUrl:'data:image/jpeg;base64,/9j/'};
const saveCalls=h=>h.calls.filter(c=>c.action==='saveWorkspace');
const current=h=>h.app.state.conversations.find(c=>c.id===h.app.state.activeConversationId);
async function until(predicate,label){for(let i=0;i<30;i++){if(predicate())return;await settle();}assert.ok(predicate(),label);}
function observe(promise){const result={done:false,value:null,error:null};promise.then(value=>{result.done=true;result.value=value;},error=>{result.done=true;result.error=error;});return result;}
function make(platform,extra={}){
 let h,active=0,maximum=0,automatic=false;
 const queue=[],commits=[];
 h=harness({chat:true,platform,workspace:extra.workspace,handlers:{getAISettings:()=>clone(settings),importAIImages:()=>({images:[clone(reference)]}),...extra.handlers,
  saveWorkspace:payload=>{
   active++;maximum=Math.max(maximum,active);
   return new Promise((resolve,reject)=>{
    const item={payload:clone(payload),finish(result={saved:true}){assert.equal(item.finished,undefined,'a fixture commit completed twice');item.finished=true;active--;if(result.saved===true){h.control.workspace=clone(item.payload);commits.push(clone(item.payload));}resolve(result);},fail(error=Error('offline disk full')){assert.equal(item.finished,undefined);item.finished=true;active--;reject(error);}};
    queue.push(item);if(automatic)queueMicrotask(()=>item.finish());
   });
  }
 }});
 return {h,queue,commits,set automatic(value){automatic=value;},get active(){return active;},get maximum(){return maximum;},next(){const item=queue.find(item=>!item.finished);assert.ok(item,'expected a queued offline write');return item;}};
}
function input(h,text){
 h.el('creativeBrief').value=text;h.el('creativeBrief').oninput({target:h.el('creativeBrief')});
 // Draft edits are debounced. Advance the harness's mocked save timer;
 // settling promises alone never runs setTimeout callbacks in this harness.
 void h.flushSave();
}
async function finishWrites(store,predicate){
 for(let i=0;i<30&&!predicate();i++){await settle();const item=store.queue.find(item=>!item.finished);if(item)item.finish();}
 await until(predicate,'all save callers complete after committed writes');
}
function tinyDesign(h,id='offline-late-result'){
 const d=clone(h.window.STUDIO_DATA.designs[0]);d.id=id;d.name='离线生成结果';d.frames=d.frames.slice(0,2);d.frame_count=2;d.keyframes=d.keyframes.slice(0,2);d.stages=d.stages.slice(0,2);return d;
}

async function serialAndLatest(platform){
 const store=make(platform),h=store.h;await settle();
 assert.ok(h.app.chat,'production App binds its own conversation controller');
 assert.equal(h.el('generateAIBtn').onclick,h.app.chat.generate,'the real App replaces the legacy AI click handler');
 input(h,'先保存第一段描述');await until(()=>store.active===1,'draft input reaches the real save bridge');
 assert.equal(store.next().payload.conversations[0].draft.brief,'先保存第一段描述');
 assert.equal(h.control.workspace,null,'a scheduled bridge request is not a committed file');
 const first=observe(h.app.saveWorkspace({immediate:true})),second=observe(h.app.saveWorkspace({immediate:true}));
 await settle();assert.equal(first.done,false);assert.equal(second.done,false);assert.equal(store.active,1);
 h.el('brightness').value=73;h.el('brightness').oninput({target:h.el('brightness')});input(h,'旧写入等待时修改后的最新描述');
 await settle();assert.equal(store.maximum,1,'new edits cannot create overlapping file writes');
 const stale=store.next();assert.equal(stale.payload.brightness,100);assert.equal(stale.payload.conversations[0].draft.brief,'先保存第一段描述');
 stale.finish();await until(()=>store.active===1,'new revision starts only after old commit');
 const latest=store.next();assert.equal(latest.payload.brightness,73);assert.equal(latest.payload.conversations[0].draft.brief,'旧写入等待时修改后的最新描述');
 assert.equal(first.done,false,'an immediate caller waits for edits queued during the old save');
 assert.equal(second.done,false);
 latest.finish();await until(()=>first.done&&second.done,'concurrent immediate save callers complete');
 assert.equal(first.error,null);assert.equal(second.error,null);assert.equal(first.value.saved,true);assert.equal(second.value.saved,true);
 assert.equal(store.maximum,1);assert.equal(h.control.workspace.brightness,73);assert.equal(h.control.workspace.conversations[0].draft.brief,'旧写入等待时修改后的最新描述');
 console.log('PASS '+platform+' actual App binding, strict serial saves and latest edits while an older commit waits');
}

async function scheduledAndFlush(platform){
 const store=make(platform),h=store.h;await settle();
 h.app.state.brightness=64;const scheduled=await h.app.saveWorkspace();
 assert.equal(scheduled.scheduled,true);assert.equal(saveCalls(h).length,0,'debounced work is not falsely committed');
 const flushing=observe(h.app.flushWorkspace());await until(()=>store.active===1,'exit flush bypasses the debounce timer');
 assert.equal(h.app.state.closing,true);assert.equal(flushing.done,false);assert.equal(h.el('creativeBrief').disabled,true);
 assert.equal(h.el('newConversationBtn').disabled,true);
 const page=h.app.state.page;h.app.navigate('workbench');assert.equal(h.app.state.page,page,'navigation is held during exit saving');
 store.next().finish();await until(()=>flushing.done,'exit flush completes after disk acknowledgment');
 assert.equal(flushing.error,null);assert.equal(flushing.value.saved,true);assert.equal(h.control.workspace.brightness,64);
 const writes=saveCalls(h).length;await h.flushSave();assert.equal(saveCalls(h).length,writes,'flushed debounce cannot write again after exit approval');
 h.window.StudioBridge.event({event:'workspaceExit',phase:'failed'});
 assert.equal(h.app.state.closing,false);assert.equal(h.el('creativeBrief').disabled,false,'a native timeout/cancel releases the closing lock');
 console.log('PASS '+platform+' scheduled writes, immediate exit flush, debounce cancellation and native abort unlock');
}

async function failedCommit(platform){
 const baseline={designs:[],pending:[],brightness:52,speedMs:40,brief:'原文件保持',selectedId:null};
 const store=make(platform,{workspace:baseline}),h=store.h;await settle();
 const unchanged=JSON.stringify(h.control.workspace),slots=JSON.stringify([...h.app.state.pending]);
 input(h,'失败后保留的创作草稿');await until(()=>store.active===1,'failure fixture has a pending save');
 const flushing=observe(h.app.flushWorkspace());await settle();assert.equal(flushing.done,false);assert.equal(h.app.state.closing,true);
 store.next().fail();await until(()=>flushing.done,'flush reports disk failure');
 assert.match(flushing.error?.message||'',/offline disk full/);assert.equal(h.app.state.closing,false);
 assert.equal(JSON.stringify(h.control.workspace),unchanged,'failed saving does not overwrite the old file');
 assert.equal(current(h).draft.brief,'失败后保留的创作草稿');assert.equal(JSON.stringify([...h.app.state.pending]),slots);assert.equal(h.el('creativeBrief').disabled,false);
 const falseReply=observe(h.app.saveWorkspace({immediate:true}));await until(()=>store.active===1,'retry reaches save bridge');
 store.next().finish({saved:false});await until(()=>falseReply.done,'false saved flag fails instead of approving exit');
 assert.match(falseReply.error?.message||'',/尚未保存/);assert.equal(JSON.stringify(h.control.workspace),unchanged);
 const retry=observe(h.app.flushWorkspace());await until(()=>store.active===1,'a later exit retry can commit');store.next().finish();await until(()=>retry.done,'retried flush completed');
 assert.equal(retry.error,null);assert.equal(h.control.workspace.conversations[0].draft.brief,'失败后保留的创作草稿');assert.equal(store.maximum,1);
 console.log('PASS '+platform+' failed/rejected commits keep the prior file and draft; flush requires saved=true');
}

async function workbenchCloseLock(platform){
 const store=make(platform),h=store.h;await settle();h.app.navigate('workbench');
 await h.document.querySelectorAll('[data-target-slot]').find(b=>b.dataset.targetSlot==='3').click();await h.el('assignBtn').click();
 const draft=JSON.stringify([...h.app.state.pending]),brightness=h.app.state.brightness,speed=h.app.state.speedMs,target=h.app.state.targetSlot;
 const flushing=observe(h.app.flushWorkspace());await until(()=>store.active===1,'workbench exit is awaiting a file commit');
 assert.equal(h.document.querySelector('.app-shell').inert,true,'the whole shell is inert while saving for exit');
 assert.equal(h.el('assignBtn').disabled,true,'exit saving locks the workbench assign action');
 assert.equal(h.el('brightness').disabled,true,'exit saving locks workbench brightness');
 assert.equal(h.el('speedNumber').disabled,true,'exit saving locks workbench speed');
 assert.ok(h.document.querySelectorAll('[data-target-slot]').every(button=>button.disabled),'exit saving locks target slot controls');
 assert.ok(h.document.querySelectorAll('[data-discard-slot]').every(button=>button.disabled),'exit saving locks draft removal controls');
 await h.el('assignBtn').click();await h.document.querySelectorAll('[data-target-slot]').find(b=>b.dataset.targetSlot==='1').click();
 assert.equal(JSON.stringify([...h.app.state.pending]),draft);assert.equal(h.app.state.targetSlot,target);assert.equal(h.app.state.brightness,brightness);assert.equal(h.app.state.speedMs,speed);
 await finishWrites(store,()=>flushing.done);assert.equal(flushing.error,null);
 h.window.StudioBridge.event({event:'workspaceExit',phase:'failed'});
 assert.equal(h.document.querySelector('.app-shell').inert,false,'cancelled exit removes the shell lock');
 assert.equal(h.el('assignBtn').disabled,false);assert.equal(h.el('brightness').disabled,false);assert.equal(h.el('speedNumber').disabled,false);
 assert.equal(JSON.stringify([...h.app.state.pending]),draft,'cancelled exit preserves its original slot draft');
 console.log('PASS '+platform+' workbench exit locks local slot/parameter mutations and cancelled exit restores controls');
}

async function stopAndPreserve(platform){
 let resolveModel;
 const store=make(platform,{handlers:{generateAI:()=>new Promise(resolve=>{resolveModel=resolve;}),cancelAI:payload=>({cancelled:true,requestId:payload.requestId})}});
 store.automatic=true;const h=store.h;await settle();
 h.app.navigate('workbench');await h.document.querySelectorAll('[data-target-slot]').find(b=>b.dataset.targetSlot==='3').click();await h.el('assignBtn').click();
 h.app.navigate('create');await h.el('addAIImagesBtn').click();input(h,'原描述与参考图在退出时必须保留');await settle();
 const slotDraft=JSON.stringify([...h.app.state.pending]);const c=current(h),draft=clone(c.draft),library=JSON.stringify(h.app.state.designs);
 const making=h.el('generateAIBtn').click();await until(()=>h.calls.some(c=>c.action==='generateAI'),'bound App sends the synthetic request');
 const modelCall=h.calls.find(c=>c.action==='generateAI');assert.equal(modelCall.payload.brief,draft.brief);assert.deepEqual(modelCall.payload.images,draft.images);
 store.automatic=false;const flushing=observe(h.app.flushWorkspace());await until(()=>store.active===1,'exit has a saved draft awaiting acknowledgment');
 assert.equal(h.app.state.closing,true);assert.ok(h.calls.some(c=>c.action==='cancelAI'&&c.payload.requestId===modelCall.payload.requestId));
 assert.equal(h.el('creativeBrief').disabled,true);assert.equal(h.el('generateAIBtn').disabled,true);
 const conversations=h.app.state.conversations.length;h.app.chat.newConversation();assert.equal(h.app.state.conversations.length,conversations,'closing cannot replace the active conversation');
 await h.app.chat.generate();assert.equal(h.calls.filter(c=>c.action==='generateAI').length,1,'closing cannot submit another request');
 resolveModel({design:tinyDesign(h),provider:'kimi-code',model:'k3'});await until(()=>c.turns.at(-1).status==='cancelled','late model result is rejected after close cancellation');
 assert.equal(c.versions.length,0,'late output cannot become a deliverable version');assert.equal(JSON.stringify(h.app.state.designs),library);
 assert.deepEqual(clone(c.draft),draft);assert.equal(JSON.stringify([...h.app.state.pending]),slotDraft);
 const made=observe(making);await finishWrites(store,()=>made.done&&flushing.done);
 assert.equal(flushing.error,null);assert.equal(store.maximum,1);
 const stored=current(h),workspace=clone(h.control.workspace);
 assert.deepEqual(workspace.conversations.find(item=>item.id===stored.id).draft,draft);
 assert.equal(workspace.pending.length,1);assert.equal(workspace.pending[0].slot,3);
 const reload=harness({chat:true,platform,workspace,handlers:{getAISettings:()=>clone(settings)}});await settle();
 assert.deepEqual(clone(current(reload).draft),draft);assert.equal(current(reload).turns.at(-1).status,'cancelled');assert.equal(reload.app.state.pending.has(3),true);
 assert.ok(h.calls.every(c=>!['execute','plan','detect','setTime','initializePlan'].includes(c.action)));
 console.log('PASS '+platform+' closing stops reception, rejects late results and preserves descriptions, references and slot drafts across restart');
}

(async()=>{
 for(const platform of ['macos','windows']){
  await serialAndLatest(platform);await scheduledAndFlush(platform);await failedCommit(platform);await stopAndPreserve(platform);await workbenchCloseLock(platform);
 }
 console.log('Workspace save integration checks passed with the shipped App and bound chat controller. Only synthetic local-file/model replies; no API, system credential or USB calls.');
})().catch(error=>{console.error(error);process.exitCode=1;});
