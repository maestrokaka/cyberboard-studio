/* First configuration is checked through both native transports, without USB. */
const assert=require('assert/strict');
const {harness,settle,clone,syntheticConfig}=require('./ui-check.cjs');
let testPlatform;
const missing=()=>Object.assign(Error('这台键盘在本机没有完整配置记录。'),{code:'baseline_missing',details:{stage:'plan',synthetic:true}});
const transport=()=>Object.assign(Error('COM12 键位查询通信超时。'),{code:'serial_keymap_failed',details:{port:'COM12',kind:'timeout'}});
function plan(h,payload,initialization=true,token='first-config'){
 const applied=payload.assignments.map(a=>a.slot),config=h.window.StudioModel.merge(syntheticConfig(),payload.assignments);
 if(initialization)for(const page of config.page_data)if(page.page_index<5||!applied.includes(page.page_index-4)){page.valid=page.page_index<3?1:0;page.lightness=100;page.speed_ms=50;page.word_page={valid:0,word_len:0,unicode:[]};for(const [field,width] of [['frames',200],['keyframes',90]])page[field]={valid:1,frame_num:1,frame_data:[{frame_index:0,frame_RGB:Array(width).fill('#000000')}]};}
 const summary=(initialization?[1,2,3]:applied).map(slot=>{const assignment=payload.assignments.find(a=>a.slot===slot);return {slot,name:assignment?.design.name||'黑屏',enabled:!!assignment,wordEnabled:false,topFrames:assignment?.design.frames.length||1,keyFrames:assignment?.design.keyframes.length||1};});
 return {token,config,keymap:clone(config.key_layer),device:{productId:'AM01R4',connected:true},keyChangeCount:0,keymapPreservation:{source:'live',comparedKeycodes:1400,differentFromStored:0},summary,changedSlots:initialization?[1,2,3]:applied,appliedSlots:applied,totalFrames:270,estimatedSeconds:3,...(initialization?{initialization:true,backupScope:'live-keymap-only',ledSource:'unknown-before-initialization'}:{})};
}
function nativeHost(handlers={}){
 return harness({platform:testPlatform,emptyBaseline:true,handlers:{detect:()=>({connected:true,device:{productId:'AM01R4',port:'COM12'},keymap:syntheticConfig().key_layer,config:null}),plan:()=>{throw missing();},...handlers}});
}
async function draft(h,slot=1){await h.document.querySelectorAll('[data-target-slot]').find(b=>b.dataset.targetSlot===String(slot)).click();await h.el('assignBtn').click();}
async function firstPanel(h){await settle();await draft(h);await h.el('detectBtn').click();await h.el('syncSingleBtn').click();assert.ok(h.el('prepareInitializationBtn'));}
async function confirmed(h){await h.el('prepareInitializationBtn').click();assert.equal(h.el('executeBtn').disabled,true);await h.el('initializationAcknowledged').click();assert.equal(h.el('executeBtn').disabled,false);}
async function checkPlatform(platform){
 testPlatform=platform;
 let h;let established=false;
 h=nativeHost({plan:payload=>{if(!established)throw missing();return plan(h,payload,false,'ordinary-after-first');},initializePlan:payload=>plan(h,payload)});
 await firstPanel(h);
 if(platform==='windows')assert.equal(h.window.webkit,undefined);else{assert.ok(h.window.webkit?.messageHandlers?.studio);assert.equal(h.window.StudioNative,undefined);}assert.equal(h.calls.filter(c=>c.action==='execute').length,0);
 assert.match(h.el('syncContent').innerHTML,/这台键盘在本机没有完整配置记录/);assert.match(h.el('syncContent').innerHTML,/不要用另一把键盘的配置记录代替/);assert.match(h.el('syncContent').innerHTML,/这台键盘自己的完整配置记录/);
 assert.match(h.el('syncContent').innerHTML,/旧灯效、文字和其他灯光模式/);assert.match(h.el('syncContent').innerHTML,/独立宏、交换键和换键表无法保留/);assert.match(h.el('syncContent').innerHTML,/原样重写、读回校验/);assert.match(h.el('syncContent').innerHTML,/不能保证所有特殊功能/);
 assert.equal(h.el('executeBtn').disabled,true);assert.equal(h.app.state.plan,null);
 const requested=clone(h.calls.find(c=>c.action==='plan').payload.assignments);
 // The first-use CTA retains exactly the request that failed, even if draft state changes later.
 await draft(h,2);h.app.state.pending.get(1).brightness=23;
 const unrelated=JSON.stringify(h.app.state.pending.get(2));
 await h.el('prepareInitializationBtn').click();
 const prepared=h.calls.find(c=>c.action==='initializePlan');assert.deepEqual(prepared.payload,{assignments:requested,preserveCurrentKeymap:true});
 assert.equal(h.calls.filter(c=>c.action==='execute').length,0,'prepare only creates a reviewable plan');
 assert.deepEqual([...h.el('syncContent').innerHTML.matchAll(/槽位 0(\d)/g)].map(match=>match[1]),['1','2','3']);
 assert.match(h.el('syncContent').innerHTML,/槽位 02 · 黑屏 · 停用 \/ 黑屏/);assert.match(h.el('syncContent').innerHTML,/槽位 03 · 黑屏 · 停用 \/ 黑屏/);assert.match(h.el('syncContent').innerHTML,/电量、马赛克、时钟采用官网标准内置模式；文字和流光采用官网标准设置/);
 assert.match(h.el('syncContent').innerHTML,/键码快照已保存/);assert.match(h.el('syncContent').innerHTML,/不是旧灯效或原完整配置的备份/);assert.doesNotMatch(h.el('syncContent').innerHTML,/完整配置备份已创建|完整配置备份已保存/);
 assert.match(h.el('syncContent').innerHTML,/我理解旧灯效、文字、其他模式，以及独立宏、交换键和换键表无法保留/);assert.equal(h.el('initializationAcknowledged').checked,false);assert.equal(h.el('executeBtn').textContent,'建立配置并同步');await h.el('executeBtn').click();assert.equal(h.calls.filter(c=>c.action==='execute').length,0);
 // Both the visible control and handler gate the explicit confirmation; unchecked must never send.
 await h.el('initializationAcknowledged').click();assert.equal(h.el('executeBtn').disabled,false);await h.el('initializationAcknowledged').click();assert.equal(h.el('executeBtn').disabled,true);
 h.el('executeBtn').disabled=false;await h.el('executeBtn').onclick();assert.equal(h.calls.filter(c=>c.action==='execute').length,0);h.el('executeBtn').disabled=true;
 await h.el('initializationAcknowledged').click();const syncing=h.el('executeBtn').click();await settle();assert.deepEqual(h.calls.filter(c=>c.action==='execute').at(-1).payload,{token:'first-config',confirmInitialization:true});
 assert.equal(h.el('closeSyncBtn').disabled,true);h.window.StudioBridge.event({event:'progress',stage:'backup'});assert.equal(h.el('syncStage').textContent,'当前键码快照');
 h.replyExecute({success:true,deviceAck:true,keymapMatch:true,stateStored:true,reportStored:true,changedSlots:[1,2,3],appliedSlots:[1]});established=true;await syncing;await h.flushSave();
 assert.equal(h.app.state.pending.has(1),false);assert.equal(JSON.stringify(h.app.state.pending.get(2)),unrelated,'black initialization slots must not discard unrelated pending drafts');assert.deepEqual(h.control.workspace.pending.map(a=>a.slot),[2]);
 assert.match(h.el('syncContent').innerHTML,/新的完整配置记录已建立/);assert.doesNotMatch(h.el('syncContent').innerHTML,/完整配置备份已保存/);assert.equal(h.app.state.baselineMissing,false);
 await h.el('closeSyncBtn').click();await h.el('syncSingleBtn').click();assert.equal(h.app.state.plan.token,'ordinary-after-first');assert.equal(h.el('initializationAcknowledged'),null);assert.equal(h.el('executeBtn').textContent,'同步到键盘');assert.match(h.el('syncContent').innerHTML,/完整配置备份已创建/);
 const ordinary=h.el('executeBtn').click();await settle();assert.deepEqual(h.calls.filter(c=>c.action==='execute').at(-1).payload,{token:'ordinary-after-first'});h.replyExecute({success:true,deviceAck:true,keymapMatch:true,changedSlots:[2]});await ordinary;
 // Structured error metadata is preserved for programmatic decisions, while displayed text stays friendly.
 const bad=nativeHost({plan:()=>{throw transport();}});await settle();await assert.rejects(bad.app.api('plan'),error=>error.code==='serial_keymap_failed'&&error.details.port==='COM12');await draft(bad);await bad.el('detectBtn').click();await bad.el('syncSingleBtn').click();assert.equal(bad.el('prepareInitializationBtn'),null);assert.equal(bad.el('executeBtn').disabled,true);assert.match(bad.el('syncContent').innerHTML,/COM12 键位查询通信超时/);assert.doesNotMatch(bad.el('syncContent').innerHTML,/"kind"|"port"|准备首次配置/);
 const restore=nativeHost({restorePlan:()=>{throw missing();}});await settle();restore.app.navigate('history');await settle();await restore.document.querySelectorAll('[data-restore]')[0].click();assert.equal(restore.el('prepareInitializationBtn'),null,'history restore failures cannot offer initialization');assert.equal(restore.calls.filter(c=>c.action==='initializePlan').length,0);
 // Closing a first-use offer invalidates its CTA, and closing a preparing plan invalidates its reply.
 let delayed,finish;delayed=nativeHost({initializePlan:payload=>new Promise(resolve=>{finish=()=>resolve(plan(delayed,payload));})});await firstPanel(delayed);const oldCTA=delayed.el('prepareInitializationBtn');await delayed.el('closeSyncBtn').click();await delayed.el('syncSingleBtn').click();await oldCTA.click();assert.equal(delayed.calls.filter(c=>c.action==='initializePlan').length,0,'an old CTA cannot start initialization for a newer request');
 const before=JSON.stringify({device:delayed.app.state.device,keymap:delayed.app.state.keymap,pending:[...delayed.app.state.pending]});const preparing=delayed.el('prepareInitializationBtn').click();await settle();assert.equal(delayed.app.state.preparingSync,true);assert.equal(delayed.el('assignBtn').disabled,true);await delayed.el('cancelSyncBtn').click();assert.equal(delayed.el('syncModal').hidden,true);finish();await preparing;assert.equal(delayed.app.state.plan,null);assert.equal(delayed.el('executeBtn').disabled,true);assert.equal(delayed.app.state.preparingSync,false);assert.equal(JSON.stringify({device:delayed.app.state.device,keymap:delayed.app.state.keymap,pending:[...delayed.app.state.pending]}),before);await delayed.el('executeBtn').click();assert.equal(delayed.calls.filter(c=>c.action==='execute').length,0);
 // Every first-use slot must be reviewable before any confirmation becomes available.
 let incomplete;incomplete=nativeHost({initializePlan:payload=>({...plan(incomplete,payload),summary:[plan(incomplete,payload).summary[0]]})});await firstPanel(incomplete);await incomplete.el('prepareInitializationBtn').click();assert.equal(incomplete.el('initializationAcknowledged'),null);assert.equal(incomplete.el('executeBtn').disabled,true);
 let failed;failed=nativeHost({initializePlan:payload=>plan(failed,payload)});await firstPanel(failed);await confirmed(failed);const failedWrite=failed.el('executeBtn').click();await settle();failed.replyExecute({success:false,deviceAck:false,keymapMatch:false});await failedWrite;assert.match(failed.el('syncContent').innerHTML,/传输已开始或结果不确定时，不能直接再次初始化/);assert.match(failed.el('syncContent').innerHTML,/请保留键码快照与目标配置，并按错误提示处理/);assert.doesNotMatch(failed.el('syncContent').innerHTML,/完整配置备份已保留|通过历史记录重新准备恢复|检查设备连接并重新准备/);assert.equal(failed.app.state.pending.size,1);assert.equal(failed.app.state.baselineMissing,true);
 let notStored;notStored=nativeHost({initializePlan:payload=>plan(notStored,payload)});await firstPanel(notStored);await confirmed(notStored);const storing=notStored.el('executeBtn').click();await settle();notStored.replyExecute({success:true,deviceAck:true,keymapMatch:true,stateStored:false,reportStored:true,appliedSlots:[1],changedSlots:[1,2,3]});await storing;assert.match(notStored.el('syncContent').innerHTML,/新的完整配置记录尚未保存/);assert.match(notStored.el('syncContent').innerHTML,/本机记录或报告保存未完成/);assert.doesNotMatch(notStored.el('syncContent').innerHTML,/新的完整配置记录已建立|完整配置备份已保存/);assert.equal(notStored.app.state.config,null);assert.equal(notStored.app.state.baselineMissing,true);
 console.log('First setup '+platform+' UI checks passed: precise error selection, frozen preparation without execute, all-slot review, explicit acknowledgement, current-request and close guards, keymap-only snapshot labels, unrelated draft retention, failure/store warnings, and subsequent normal sync. No USB device or private records were accessed.');
}
(async()=>{for(const platform of ['windows','macos'])await checkPlatform(platform);})().catch(error=>{console.error(error);process.exitCode=1;});
