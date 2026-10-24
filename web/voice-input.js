(function(global){
 'use strict';
 const LABELS={'qwen-asr':'千问语音识别','openai-asr':'OpenAI 语音识别','minimax-asr':'MiniMax 语音识别'};
 const MODELS={'minimax-asr':['asr-1.0'],'qwen-asr':['qwen3-asr-flash'],'openai-asr':['gpt-transcribe','gpt-4o-mini-transcribe','gpt-4o-transcribe','whisper-1']};
 function insertion(value,text,start,end){
  if(typeof value!=='string'||typeof text!=='string'||!text.trim())throw Error('没有识别到文字，请重新录制。');
  start=Math.max(0,Math.min(value.length,Number.isInteger(start)?start:value.length));end=Math.max(start,Math.min(value.length,Number.isInteger(end)?end:start));
  const result=value.slice(0,start)+text.trim()+value.slice(end);
  if(result.length>4000)throw Error('输入框将超过 4000 字。识别结果已保留，可复制后整理文字。');
  return {value:result,cursor:start+text.trim().length};
 }
 function create(options){
  const {$,api,native,state,navigate,toast,onBusy,getContext,insertTranscript}=options;
  let settings=null,settingsBusy=false,loadPromise=null,active=null,sequence=0,timer=null,revealed=null,revealSequence=0;
  const input=$('creativeBrief'),controls=['voiceProvider','voiceRegion','voiceModel','voiceApiKey','saveVoiceSettingsBtn','deleteVoiceKeyBtn','toggleVoiceKeyBtn'];
  function elsewhereBusy(){return !!(state.miaoCallBusy||state.aiBusy||state.executing||state.hardwareBusy||state.preparingSync||state.closing);}
  function note(text,error=false){$('voiceInputStatus').hidden=!text;$('voiceInputStatus').textContent=text||'';$('voiceInputStatus').classList.toggle('error',error);}
  function settingsNote(text,error=false){$('voiceSettingsStatus').textContent=text;$('voiceSettingsStatus').classList.toggle('error',error);}
  function selectedProfile(){return settings?.profiles?.[$('voiceProvider').value];}
  function form(){return {provider:$('voiceProvider').value,region:$('voiceRegion').value,model:$('voiceModel').value};}
  function hideKey(){revealSequence++;if(revealed&&$('voiceApiKey').value===revealed.value)$('voiceApiKey').value='';revealed=null;$('voiceApiKey').type='password';}
  function showProfile(provider){
   hideKey();$('voiceApiKey').value='';$('voiceProvider').value=provider;const saved=settings?.profiles?.[provider];
   $('voiceRegion').innerHTML=provider==='openai-asr'?'<option value="global">国际区</option>':'<option value="china">中国区</option><option value="global">'+(provider==='minimax-asr'?'国际区':'国际区（新加坡）')+'</option>';
   $('voiceModel').innerHTML=MODELS[provider].map(model=>'<option value="'+model+'">'+model+'</option>').join('');
   $('voiceModel').value=saved?.model||MODELS[provider][0];$('voiceRegion').value=saved?.region||(provider==='openai-asr'?'global':'china');refresh();
  }
  function refresh(){
   const busy=elsewhereBusy(),inUse=!!active,configured=settings?.hasKey===true&&settings?.supportsTranscription===true;
   $('voiceInputBtn').disabled=busy||settingsBusy||!!loadPromise||inUse&&active.phase!=='recording';
   $('voiceInputBtn').textContent=active?.phase==='recording'?'结束录音':active?.phase==='starting'?'打开麦克风…':active?.phase==='transcribing'?'识别中…':'语音输入';
   $('voiceInputBtn').title=configured?LABELS[settings.provider]+' · '+settings.model:'先配置支持语音转文字的模型';
   $('voiceInputBtn').setAttribute('aria-pressed',String(active?.phase==='recording'));
   $('cancelVoiceInputBtn').hidden=!inUse;$('cancelVoiceInputBtn').disabled=!!state.closing;
   controls.forEach(id=>$(id).disabled=busy||inUse||settingsBusy||!native);
   const profile=selectedProfile(),visible=$('voiceApiKey').type==='text';$('toggleVoiceKeyBtn').textContent=visible?'隐藏':'显示';$('toggleVoiceKeyBtn').setAttribute('aria-pressed',String(visible));
   $('toggleVoiceKeyBtn').disabled=busy||inUse||settingsBusy||!native||!$('voiceApiKey').value&&!profile?.hasKey;
   $('deleteVoiceKeyBtn').disabled=busy||inUse||settingsBusy||!native||!profile?.hasKey;
   $('voiceApiKey').placeholder=profile?.hasKey?'已保存；输入新 Key 可替换':'输入语音识别服务的 API Key';
   $('voiceSettingsBadge').textContent=!native?'桌面 App 中使用':configured?'可语音输入':'尚未配置';
   $('voiceConnectionSummary').textContent=configured?'语音输入：'+LABELS[settings.provider]+' · '+settings.model+'。识别后可交给任意创作模型。':'可连接 MiniMax、千问或 OpenAI 的语音模型；转成文字后交给你选择的创作模型。';
  }
  function setActive(value){active=value;state.voiceBusy=!!value;refresh();onBusy?.();}
  async function loadSettings(){
   if(!native){refresh();return null;}if(loadPromise)return loadPromise;
   loadPromise=(async()=>{try{settings=await api('voiceSettings');showProfile(settings.provider);return settings;}catch(error){settingsNote(error.message||'语音连接未读取，请重新保存。',true);return null;}finally{loadPromise=null;refresh();}})();refresh();return loadPromise;
  }
  function contextMatches(request){return active===request&&!request.cancelled&&!state.closing&&state.page==='create'&&getContext()?.id===request.context.id;}
  function retainText(text,message){$('voiceRecoveredText').value=text;$('voiceRecovery').hidden=false;note(message,true);}
  async function start(){
   if(active?.phase==='recording')return stop();if(active||elsewhereBusy()||settingsBusy||state.page!=='create')return;
   if(!native){toast('语音输入需要在桌面 App 中使用。');return;}
   if(!settings)await loadSettings();if(active||elsewhereBusy()||state.page!=='create')return;
   if(!settings?.hasKey||!settings.supportsTranscription){navigate('models');$('voiceSettingsCard').scrollIntoView?.({block:'nearest'});settingsNote('先保存一个支持语音转文字的模型连接。',true);return;}
   const context=getContext();if(!context)return;
   const request={id:'voice-'+Date.now().toString(36)+'-'+(++sequence),phase:'starting',context:{...context},
    base:input.value,start:input.selectionStart,end:input.selectionEnd,provider:settings.provider,model:settings.model,region:settings.region,cancelled:false};
   setActive(request);note('正在打开麦克风。首次使用需要系统麦克风许可。');
   try{const result=await api('startVoiceRecording',{requestId:request.id});if(!contextMatches(request)){await api('cancelVoiceRecording',{requestId:request.id}).catch(()=>{});return;}
    if(result.requestId!==request.id||result.recording!==true)throw Error('麦克风没有开始录音，请重试。');request.phase='recording';request.started=Date.now();refresh();note('正在聆听 · 点击「结束录音」转成文字，最多 60 秒。');
    timer=global.setInterval(()=>{if(!contextMatches(request))return;const seconds=Math.floor((Date.now()-request.started)/1000);note('正在聆听 · '+Math.min(seconds,60)+' / 60 秒 · 点击结束录音');if(seconds>=60)stop();},1000);
   }catch(error){if(active===request&&!request.cancelled){note(error.message||'无法打开麦克风，请检查系统麦克风权限。',true);setActive(null);}}
  }
  async function stop(){
   const request=active;if(!request||request.phase!=='recording')return;global.clearInterval(timer);timer=null;request.phase='transcribing';refresh();note('正在把语音转成文字…');
   try{const recorded=await api('stopVoiceRecording',{requestId:request.id});if(!contextMatches(request))return;
    if(recorded.requestId!==request.id||!recorded.audio?.dataUrl)throw Error('录音未完整返回，请重新录制。');
    const result=await api('transcribeVoice',{requestId:request.id,audio:recorded.audio,expectedProvider:request.provider,expectedModel:request.model,expectedRegion:request.region});
    if(!contextMatches(request))return;if(result.requestId!==request.id||typeof result.text!=='string')throw Error('语音结果无法识别，请重试。');
    if(input.value!==request.base||getContext()?.brief!==request.context.brief){retainText(result.text,'输入内容已改变，识别结果保留在下方，请自行复制。');return;}
    let inserted;try{inserted=insertion(request.base,result.text,request.start,request.end);}catch(error){retainText(result.text,error.message);return;}
    insertTranscript(request.context.id,inserted.value);input.value=inserted.value;input.setSelectionRange?.(inserted.cursor,inserted.cursor);note('已转成文字 · 可继续编辑，点击「发送并制作」才会提交。');
   }catch(error){if(active===request&&!request.cancelled)note(error.message||'语音识别未完成，原输入已保留。',true);}
   finally{await api('cancelVoiceRecording',{requestId:request.id}).catch(()=>{});if(active===request){setActive(null);input.focus?.();}}
  }
  async function cancel(){const request=active;if(!request)return;request.cancelled=true;global.clearInterval(timer);timer=null;setActive(null);note('语音输入已取消，原文字保留。');await Promise.allSettled([api('cancelVoiceRecording',{requestId:request.id}),request.phase==='transcribing'?api('cancelVoiceTranscription',{requestId:request.id}):Promise.resolve()]);}
  function event(value){if(value.event!=='voiceRecording'||value.requestId!==active?.id)return;if(value.reason==='limit')stop();else if(value.reason==='error'){const request=active;cancel().then(()=>note(value.message||'录音未完成，请重新录制。',true));request.cancelled=true;}}
  async function saveSettings(){if(elsewhereBusy()||active||settingsBusy||!native)return;settingsBusy=true;refresh();const payload=form(),key=$('voiceApiKey').value.trim();if(key&&(!revealed||key!==revealed.value))payload.apiKey=key;try{settings=await api('saveVoiceSettings',payload);showProfile(settings.provider);settingsNote('语音连接已保存。回到 AI 创作，点击「语音输入」即可。');}catch(error){settingsNote(error.message||'语音连接保存失败。',true);}finally{settingsBusy=false;refresh();}}
  async function toggleKey(){if($('voiceApiKey').type==='text'){hideKey();refresh();return;}if(elsewhereBusy()||active||settingsBusy||!native)return;if($('voiceApiKey').value){$('voiceApiKey').type='text';refresh();return;}const sequence=++revealSequence,provider=$('voiceProvider').value;settingsBusy=true;refresh();try{const result=await api('revealVoiceKey',{provider});if(sequence!==revealSequence||state.page!=='models'||provider!==$('voiceProvider').value)return;revealed={provider,value:result.apiKey};$('voiceApiKey').value=result.apiKey;$('voiceApiKey').type='text';}catch(error){settingsNote(error.message||'语音 Key 读取失败。',true);}finally{settingsBusy=false;refresh();}}
  async function deleteKey(){if(elsewhereBusy()||active||settingsBusy||!native)return;settingsBusy=true;refresh();try{settings=await api('deleteVoiceKey',{provider:$('voiceProvider').value});hideKey();settingsNote('此服务的语音 Key 已移除。');}catch(error){settingsNote(error.message||'语音 Key 未移除。',true);}finally{settingsBusy=false;refresh();}}
  $('voiceInputBtn').onclick=start;$('cancelVoiceInputBtn').onclick=cancel;$('saveVoiceSettingsBtn').onclick=saveSettings;$('toggleVoiceKeyBtn').onclick=toggleKey;$('deleteVoiceKeyBtn').onclick=deleteKey;
  $('voiceProvider').onchange=()=>{showProfile($('voiceProvider').value);settingsNote('保存后生效；创作模型不会改变。');};$('voiceRegion').onchange=$('voiceModel').onchange=()=>settingsNote('修改尚未保存。');
  $('voiceApiKey').oninput=()=>{revealed=null;refresh();};$('closeVoiceRecoveryBtn').onclick=()=>{$('voiceRecovery').hidden=true;$('voiceRecoveredText').value='';};
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&active){event.preventDefault?.();cancel();}});
  showProfile('qwen-asr');refresh();
  return {loadSettings,refresh,start,stop,cancel,event,pageChanged(page){if(page!=='models')hideKey();if(page!=='create'&&active)cancel();if(page==='models'&&!active)loadSettings();refresh();},async prepareClose(){await cancel();hideKey();},get settings(){return settings;},get active(){return active;}};
 }
 global.StudioVoiceInput={create,insertion};
})(window);
