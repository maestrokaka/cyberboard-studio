/* Actual shipped controller + synthetic bridge. No microphone, USB or network. */
const assert=require('assert/strict');
const {harness,settle}=require('./ui-check.cjs');
const device={productId:'AM01R6',firmware:'offline-r6',port:'/dev/synthetic-board'};
const status=()=>({connected:true,device:{...device},supportsAudio:true,canReadSettings:false,settings:{speaker:null,mic_direction:null,noise_reduction:null,mic_tone:null},lastConfirmed:{mic_direction:{value:32}},verification:'unknown'});
const devices=()=>({inputs:[{id:'keyboard',name:'AIROHAChat',isDefault:true},{id:'other',name:'Other microphone',isDefault:false}],outputs:[{id:'out',name:'AIROHAChat',isDefault:true}],defaultInputId:'keyboard',defaultOutputId:'out'});
const actions=h=>h.calls.map(call=>call.action);
const choice=(h,setting,value)=>h.document.querySelectorAll('[data-r6-setting]').find(el=>el.dataset.r6Setting===setting&&el.dataset.r6Value===String(value));
(async()=>{
 let setResolve,setFail=false,calibrations=0,recordResolve,stops=0,cancels=0,recordStartFail=false;
 const h=harness({handlers:{
  r6AudioStatus:async()=>status(),audioTestDevices:async()=>devices(),
  r6AudioSet:async payload=>{if(setFail)throw Error('设备断开');return new Promise(resolve=>setResolve=()=>resolve({setting:payload.setting,value:payload.value,state:'acknowledged',verification:'set_echo',acousticVerified:false}));},
  r6AudioCalibrate:async payload=>{assert.equal(payload.confirmCalibration,true);calibrations++;return{phase:'complete',passed:true,leftOhms:5.5,rightOhms:5.75};},
  audioTestStart:async payload=>{if(recordStartFail)throw Error('麦克风许可未开启');return new Promise(resolve=>recordResolve=()=>resolve({requestId:payload.requestId,recording:true}));},
  audioTestStop:async payload=>{stops++;return{requestId:payload.requestId,audio:{dataUrl:'data:audio/wav;base64,UklGRg=='}};},
  audioTestCancel:async()=>{cancels++;return{cancelled:true};}
 }});
 const intervals=new Map();let intervalId=0,playCount=0,pauseCount=0;
 h.window.setInterval=fn=>{intervals.set(++intervalId,fn);return intervalId;};h.window.clearInterval=id=>intervals.delete(id);
 h.window.Audio=class{constructor(src){this.src=src;this.paused=true;}async play(){this.paused=false;playCount++;}pause(){this.paused=true;pauseCount++;}};
 await settle();const ui=h.app.r6audio;assert(ui);
 assert.equal(actions(h).some(action=>/r6Audio|audioTest/.test(action)),false,'startup cannot configure or record');
 assert.equal(h.el('r6AudioDeviceBadge').textContent,'尚未检查');
 assert.equal(h.document.querySelectorAll('[data-r6-setting]').filter(button=>button.getAttribute('aria-pressed')==='true').length,0,'no default is passed off as hardware value');
 const pendingBefore=JSON.stringify([...h.app.state.pending]);const designBefore=h.app.state.selected.id;
 h.app.navigate('r6audio');await settle();await settle();
 assert.equal(h.app.state.page,'r6audio');assert.equal(h.el('pageTitle').textContent,'R6 声音');
 assert.equal(actions(h).filter(action=>action==='r6AudioStatus').length,1);assert.equal(actions(h).filter(action=>action==='audioTestDevices').length,1);
 assert.equal(actions(h).filter(action=>['r6AudioSet','r6AudioCalibrate','audioTestStart'].includes(action)).length,0,'entering page only checks connections');
 assert.equal(h.el('r6Audio-mic_direction-state').textContent,'实际值未知','lastConfirmed history must not preselect a hardware mode');
 assert.equal(h.el('r6AudioInput').querySelectorAll('option').find(el=>el.value==='other').disabled,true,'unsupported device selection must not pretend to work');
 assert.equal(h.el('r6AudioInput').value,'keyboard');
 const setting=choice(h,'mic_direction',21).click();await settle();
 assert.equal(choice(h,'mic_direction',32).disabled,true);await choice(h,'mic_direction',32).click();
 assert.equal(actions(h).filter(action=>action==='r6AudioSet').length,1,'one request at a time');
 assert.deepEqual(h.calls.find(call=>call.action==='r6AudioSet').payload,{setting:'mic_direction',value:21,expectedDevice:device});
 setResolve();await setting;assert.match(h.el('r6Audio-mic_direction-state').textContent,/本次回执：前向/);assert.match(h.el('r6AudioStatus').textContent,/设备回执已确认/);
 setFail=true;await choice(h,'mic_direction',32).click();assert.match(h.el('r6AudioStatus').textContent,/实际值未知/);assert.equal(h.el('r6Audio-mic_direction-state').textContent,'实际值未知');setFail=false;
 await ui.applySetting('mic_direction',0x21);assert.equal(actions(h).filter(action=>action==='r6AudioSet').length,2,'unsupported direction byte cannot be sent');
 await h.el('r6AudioCalibrationOpen').click();assert.equal(calibrations,0);assert.equal(h.el('r6AudioCalibrationRun').disabled,true);
 await h.el('r6AudioCalibrationAccepted').click();assert.equal(h.el('r6AudioCalibrationRun').disabled,false);await h.el('r6AudioCalibrationRun').click();
 assert.equal(calibrations,1);assert.match(h.el('r6AudioCalibrationStatus').textContent,/5\.50 Ω \/ 右 5\.75 Ω/);assert.match(h.el('r6AudioCalibrationStatus').textContent,/未自动恢复/);await h.el('r6AudioCalibrationClose').click();
 const start=h.el('r6AudioRecord').click();await settle();assert.equal(h.app.state.voiceBusy,true);assert.equal(h.el('r6AudioStop').disabled,true);recordResolve();await start;
 assert.equal(h.el('r6AudioTestPanel').dataset.phase,'recording');assert.equal(intervals.size,1);assert.equal(actions(h).filter(action=>action==='audioTestStart').length,1);
 h.app.navigate('create');assert.equal(h.app.state.page,'r6audio','recording must be explicitly ended or cancelled before navigation');
 await h.el('r6AudioStop').click();assert.equal(stops,1);assert(cancels>=1);assert.equal(intervals.size,0);assert.equal(h.app.state.voiceBusy,false);assert.equal(ui.snapshot.hasRecording,true);
 await h.el('r6AudioPlay').click();assert.equal(playCount,1);await h.el('r6AudioPlay').click();assert.equal(pauseCount,1);
 h.app.navigate('create');await settle();assert.equal(ui.snapshot.hasRecording,false);assert.equal(h.el('r6AudioPlay').disabled,true);
 h.app.navigate('r6audio');await settle();await settle();recordStartFail=true;await h.el('r6AudioRecord').click();assert.match(h.el('r6AudioTestStatus').textContent,/许可未开启/);assert.equal(h.app.state.voiceBusy,false);assert(cancels>=2,'failed start also releases native recorder');
 assert.equal(actions(h).some(action=>/transcribe|VoiceRecording|execute|plan$/.test(action)),false,'local test cannot call ASR or a full configuration write');
 assert.equal(JSON.stringify([...h.app.state.pending]),pendingBefore);assert.equal(h.app.state.selected.id,designBefore,'sound controls must not change lighting');
 const browser=harness({native:false});await settle();browser.app.navigate('r6audio');assert.equal(browser.el('r6AudioRefresh').disabled,true);assert.equal(browser.el('r6AudioRecord').disabled,true);assert.match(browser.el('r6AudioStatus').textContent,/桌面 App/);
 console.log('PASS R6 audio unknown initial values, read-only entry, explicit setting + identity, ACK distinction, failure recovery, enum guard, calibration confirmation, default-device guard, local recording/playback/cleanup, navigation and browser boundaries');
})().catch(error=>{console.error(error);process.exitCode=1;});
