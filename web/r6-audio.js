(function(global){
 'use strict';
 const SETTINGS={
  speaker:{label:'扬声器输出',options:[[0,'关闭'],[1,'仅左声道'],[2,'仅右声道'],[3,'左右声道']]},
  mic_direction:{label:'麦克风方向',options:[[21,'前向'],[32,'后向'],[48,'全向']]},
  noise_reduction:{label:'降噪',options:[[0,'最高'],[1,'稍弱'],[2,'关闭']]},
  mic_tone:{label:'麦克风音色',options:[[1,'常规'],[2,'高亮'],[3,'低频饱满']]}
 };
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const identity=device=>device?JSON.stringify([device.port||'',device.productId||'',device.productInfo||device.firmware||'']):'';
 const publicDevice=device=>({port:device.port,productId:device.productId,firmware:device.firmware||device.productInfo});
 function create({$,api,native,state,toast,onBusy,onDevice}){
  if(!$('page-r6audio'))return null;
  let connection=null,confirmed={},loadId=0,pending='',testDevices=null,recording=null,audio=null,audioData=null,timer=null,elapsed=0,sequence=0,calibrationPending=false;
  const settingBusy=()=>!!(state.aiBusy||state.voiceBusy||state.miaoCallBusy||state.executing||state.preparingSync||state.closing||state.hardwareBusy);
  function note(text,error=false){$('r6AudioStatus').textContent=text;$('r6AudioStatus').classList.toggle('error',error);}
  function testNote(text,error=false){$('r6AudioTestStatus').textContent=text;$('r6AudioTestStatus').classList.toggle('error',error);}
  function supported(){return !!(native&&connection?.connected&&connection?.supportsAudio);}
  function setPending(value){pending=value;state.r6AudioBusy=!!value;state.hardwareBusy=!!value;refresh();onBusy?.();}
  function recordingNote(){testNote('正在录音 · '+Math.min(elapsed,30)+' / 30 秒。点击结束后可本地回放。');}
  function stopPlayer(){if(audio){audio.pause?.();audio.src='';audio=null;}$('r6AudioPlay').textContent='播放录音';}
  function clearRecording(){stopPlayer();audioData=null;elapsed=0;$('r6AudioPlay').disabled=true;$('r6AudioClear').disabled=true;}
  function clearTimer(){if(timer!==null){global.clearInterval(timer);timer=null;}}
  function renderChoices(){
   for(const [setting,definition] of Object.entries(SETTINGS)){
    const field=$('r6Audio-'+setting),last=confirmed[setting];
    field.innerHTML=definition.options.map(([value,label])=>'<button type="button" class="button r6-audio-choice" data-r6-setting="'+setting+'" data-r6-value="'+value+'" aria-pressed="'+(last?.value===value)+'">'+esc(label)+'</button>').join('');
    field.querySelectorAll('[data-r6-setting]').forEach(button=>button.onclick=()=>applySetting(setting,Number(button.dataset.r6Value)));
    $('r6Audio-'+setting+'-state').textContent=last?'本次回执：'+(definition.options.find(([v])=>v===last.value)?.[1]||'已确认')+' · 实际效果待实测':'实际值未知';
    $('r6Audio-'+setting+'-state').dataset.state=last?'acknowledged':'unknown';
   }
  }
  function refresh(){
   const busy=settingBusy(),ready=supported();
   $('r6AudioRefresh').disabled=!native||busy;
   $('r6AudioDeviceBadge').textContent=!native?'桌面 App 中使用':pending==='status'?'正在检查':!connection?'尚未检查':connection.connected?connection.supportsAudio?'R6 USB 已连接':'当前设备不支持':'未连接';
   $('r6AudioDeviceName').textContent=connection?.device?.productId||'CYBERBOARD R6';
   $('r6AudioDeviceMeta').textContent=connection?.connected?(connection.device?.productInfo||connection.device?.firmware||'固件版本未返回'):'通过 USB 连接键盘后，点击「检查声音连接」。';
   document.querySelectorAll('[data-r6-setting]').forEach(button=>button.disabled=!ready||busy);
   $('r6AudioTestRefresh').disabled=!native||busy||!!recording;
   const input=testDevices?.inputs?.find(item=>item.id===testDevices.defaultInputId||item.isDefault===true);
   $('r6AudioInput').disabled=!native||busy||!!recording;
   $('r6AudioRecord').disabled=!native||busy||!input||!!recording;
   $('r6AudioStop').hidden=!recording;$('r6AudioRecord').hidden=!!recording;
   $('r6AudioStop').disabled=!recording||recording.phase!=='recording'||pending==='record-stop';
   $('r6AudioCancel').hidden=!recording;$('r6AudioCancel').disabled=!!state.closing;
   $('r6AudioPlay').disabled=busy||!!recording||!audioData;
   $('r6AudioClear').disabled=busy||!!recording||!audioData;
   $('r6AudioCalibrationOpen').disabled=!ready||busy||!!recording;
   $('r6AudioCalibrationRun').disabled=!ready||busy||!!recording||!$('r6AudioCalibrationAccepted').checked;
   $('r6AudioCalibrationClose').disabled=calibrationPending;$('r6AudioCalibrationCancel').disabled=calibrationPending;
   $('r6AudioTestPanel').dataset.phase=recording?.phase||(audioData?'recorded':'idle');
  }
  async function load(){
   if(!native){note('声音配置与麦克风测试需要在桌面 App 中使用。');refresh();return;}
   if(settingBusy()||recording)return;
   const id=++loadId;confirmed={};renderChoices();setPending('status');note('正在检查键盘型号和声音控制能力…');
   try{const result=await api('r6AudioStatus');if(id!==loadId)return;connection=result;onDevice?.(result);note(result.connected&&result.supportsAudio?'连接已确认。设备没有可用的声音参数查询接口，选项不会自动当作当前值。':result.connected?'当前设备没有启用 R6 声音控制能力。':'未发现 R6，请检查 USB 连接后重试。');}
   catch(error){if(id===loadId){connection=null;note(error.message||'声音连接检查失败。',true);}}
   finally{if(id===loadId)setPending('');}
   if(id===loadId&&state.page==='r6audio')await loadTestDevices();
  }
  async function applySetting(setting,value){
   if(settingBusy()||recording||!supported()||!SETTINGS[setting]?.options.some(([option])=>option===value))return;
   const expected=publicDevice(connection.device),fingerprint=identity(connection.device);setPending('setting');note('正在设置'+SETTINGS[setting].label+'，等待设备回执…');
   try{
    const result=await api('r6AudioSet',{setting,value,expectedDevice:expected});
    if(result.setting!==setting||result.value!==value||result.state!=='acknowledged'||result.verification!=='set_echo')throw Error('设备未返回完整的参数确认，实际状态未知。');
    if(identity(connection?.device)!==fingerprint)throw Error('连接设备已改变，实际状态未知，请重新检查。');
    confirmed[setting]={value};renderChoices();note(SETTINGS[setting].label+'：设备回执已确认。拾音方向与音色请通过录音试听。');
   }catch(error){delete confirmed[setting];renderChoices();note((error.message||'参数设置未完成。')+' 请检查连接；实际值未知。',true);}
   finally{setPending('');}
  }
  async function loadTestDevices(){
   if(!native||settingBusy()||recording)return;
   setPending('devices');testNote('正在读取系统音频设备…');
   try{const result=await api('audioTestDevices');testDevices=result;const inputs=Array.isArray(result.inputs)?result.inputs:[];const current=inputs.find(item=>item.id===result.defaultInputId||item.isDefault===true);
    $('r6AudioInput').innerHTML=inputs.length?inputs.map(item=>'<option value="'+esc(item.id)+'" '+(item.id===current?.id?'selected':'disabled')+'>'+esc(item.name)+(item.id===current?.id?' · 系统当前输入':' · 请先在系统中切换')+'</option>').join(''):'<option value="">没有可用输入设备</option>';
    $('r6AudioInput').value=current?.id||'';
    const output=(result.outputs||[]).find(item=>item.id===result.defaultOutputId||item.isDefault===true);
    $('r6AudioOutput').textContent=output?.name||'未检测到默认输出';
    testNote(!current?'没有可用麦克风。连接或启用 AIROHAChat 后刷新。':/airoha/i.test(current.name)?'当前输入已选中 '+current.name+'。点击录音，比较前后两侧的拾音效果。':'当前输入是 '+current.name+'。测试键盘前，请在系统声音设置中切换为 AIROHAChat，再刷新。');
   }catch(error){testDevices=null;$('r6AudioInput').innerHTML='<option value="">无法读取输入设备</option>';testNote(error.message||'音频设备读取失败。',true);}
   finally{setPending('');}
  }
  async function startRecording(){
   if(!native||settingBusy()||recording)return;
   const current=testDevices?.inputs?.find(item=>item.id===testDevices.defaultInputId||item.isDefault===true);
   if(!current||$('r6AudioInput').value!==current.id){testNote('请先在系统声音设置中选择输入，再刷新设备。',true);return;}
   clearRecording();const request={id:'r6-audio-'+Date.now().toString(36)+'-'+(++sequence),phase:'starting',inputId:current.id};recording=request;state.r6AudioBusy=true;state.voiceBusy=true;onBusy?.();refresh();testNote('正在打开 '+current.name+'，首次使用需要麦克风许可。');
   try{const result=await api('audioTestStart',{requestId:request.id,inputId:current.id});if(recording!==request||state.page!=='r6audio'){await api('audioTestCancel',{requestId:request.id}).catch(()=>{});return;}
    if(result.requestId!==request.id||result.recording!==true)throw Error('麦克风没有开始录音。');request.phase='recording';elapsed=0;recordingNote();refresh();timer=global.setInterval(()=>{if(recording!==request)return;elapsed++;recordingNote();if(elapsed>=30)stopRecording();},1000);
   }catch(error){await api('audioTestCancel',{requestId:request.id}).catch(()=>{});if(recording===request){recording=null;state.r6AudioBusy=false;state.voiceBusy=false;testNote(error.message||'无法开始录音。',true);refresh();onBusy?.();}}
  }
  async function stopRecording(){
   const request=recording;if(!request||request.phase!=='recording')return;clearTimer();request.phase='stopping';pending='record-stop';refresh();testNote('正在结束录音…');
   try{const result=await api('audioTestStop',{requestId:request.id});if(recording!==request)return;
    if(result.requestId!==request.id||typeof result.audio?.dataUrl!=='string'||!/^data:audio\/[a-z0-9.+-]+;base64,/i.test(result.audio.dataUrl)||result.audio.dataUrl.length>12000000)throw Error('录音没有完整返回，请重试。');
    audioData=result.audio.dataUrl;testNote('录音已就绪，点击播放试听。音频只用于本地测试，不会发送给语音模型。');
   }catch(error){if(recording===request){clearRecording();testNote(error.message||'录音未完成。',true);}}
   finally{await api('audioTestCancel',{requestId:request.id}).catch(()=>{});if(recording===request){recording=null;pending='';state.r6AudioBusy=false;state.voiceBusy=false;refresh();onBusy?.();}}
  }
  async function cancelRecording(){const request=recording;clearTimer();recording=null;if(request){pending='';state.r6AudioBusy=false;state.voiceBusy=false;}clearRecording();refresh();onBusy?.();if(request)await api('audioTestCancel',{requestId:request.id}).catch(error=>testNote(error.message||'录音清理未完成，请重试。',true));}
  async function playRecording(){
   if(settingBusy()||recording||!audioData)return;
   if(audio&&!audio.paused){audio.pause();$('r6AudioPlay').textContent='继续播放';return;}
   try{if(!audio){if(typeof global.Audio!=='function')throw Error('当前环境不支持本地音频回放。');audio=new global.Audio(audioData);audio.onended=()=>{$('r6AudioPlay').textContent='重新播放';};audio.onerror=()=>testNote('录音播放失败，请重新录制。',true);}await audio.play();$('r6AudioPlay').textContent='暂停播放';}
   catch(error){testNote(error.message||'录音无法播放。',true);}
  }
  function closeCalibration(){if(calibrationPending)return;$('r6AudioCalibrationModal').hidden=true;$('r6AudioCalibrationAccepted').checked=false;refresh();}
  async function calibrate(){
   if(!supported()||settingBusy()||recording||!$('r6AudioCalibrationAccepted').checked||$('r6AudioCalibrationModal').hidden)return;
   stopPlayer();calibrationPending=true;setPending('calibration');$('r6AudioCalibrationRun').textContent='正在校准…';$('r6AudioCalibrationStatus').textContent='正在检查默认输出并启动校准，请保持连接。';
   try{const result=await api('r6AudioCalibrate',{expectedDevice:publicDevice(connection.device),confirmCalibration:true});
    if(result.phase!=='complete'||typeof result.passed!=='boolean')throw Error('校准结果未完整返回。');
    const left=Number(result.leftOhms??result.left_ohms),right=Number(result.rightOhms??result.right_ohms);
    $('r6AudioCalibrationStatus').textContent=(result.passed?'校准通过':'校准未通过')+(Number.isFinite(left)&&Number.isFinite(right)?' · 左 '+left.toFixed(2)+' Ω / 右 '+right.toFixed(2)+' Ω':'')+'。原声道未自动恢复，请按需要重新设置。';
    confirmed={};renderChoices();note('校准流程已结束。声音设置实际值未知，请重新设置需要的声道。',!result.passed);
   }catch(error){confirmed={};renderChoices();$('r6AudioCalibrationStatus').textContent=error.message||'校准未完成。';note('校准未完成，设备声音状态未知，请检查连接。',true);}
   finally{calibrationPending=false;setPending('');$('r6AudioCalibrationRun').textContent='确认并开始校准';$('r6AudioCalibrationAccepted').checked=false;refresh();}
  }
  for(const setting of Object.keys(SETTINGS))$('r6Audio-'+setting)?.setAttribute('role','group');
  $('r6AudioRefresh').onclick=load;$('r6AudioTestRefresh').onclick=loadTestDevices;$('r6AudioRecord').onclick=startRecording;$('r6AudioStop').onclick=stopRecording;$('r6AudioCancel').onclick=()=>cancelRecording().then(()=>testNote('录音已取消。'));$('r6AudioPlay').onclick=playRecording;$('r6AudioClear').onclick=()=>{clearRecording();testNote('本地测试录音已清除。');refresh();};
  $('r6AudioCalibrationOpen').onclick=()=>{if(!supported()||settingBusy()||recording)return;$('r6AudioCalibrationModal').hidden=false;$('r6AudioCalibrationStatus').textContent='开始前，请将系统默认输出切换为 AIROHAChat。';$('r6AudioCalibrationAccepted').checked=false;refresh();};
  $('r6AudioCalibrationAccepted').onchange=refresh;$('r6AudioCalibrationRun').onclick=calibrate;$('r6AudioCalibrationClose').onclick=$('r6AudioCalibrationCancel').onclick=closeCalibration;
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){closeCalibration();if(recording)cancelRecording().then(()=>testNote('录音已取消。'));}});
  renderChoices();refresh();
  return{load,refresh,applySetting,loadTestDevices,startRecording,stopRecording,cancelRecording,playRecording,calibrate,closeCalibration,
   pageChanged(page){if(page==='r6audio'){if(!pending&&!recording)load();}else{closeCalibration();if(recording)cancelRecording();else clearRecording();}},
   event(value){if(value.event==='audioTestRecording'&&value.requestId===recording?.id){if(value.reason==='limit')stopRecording();else if(value.reason==='error')cancelRecording().then(()=>testNote(value.message||'录音意外中止。',true));}},
   async prepareClose(){if(calibrationPending||pending&&pending!=='record-stop')throw Error('请等待声音设备操作完成，再退出。');await cancelRecording();closeCalibration();},
   get snapshot(){return{connection,confirmed,pending,recording:recording?.phase||null,hasRecording:!!audioData};}};
 }
 global.StudioR6Audio={create,SETTINGS};
})(window);
