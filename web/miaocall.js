(function(global){
 'use strict';
 const ACTIVE=new Set(['configuring','preparing','listening','transcribing','connecting','thinking','acting','awaitingApproval','awaitingInput','cancelling']);
 const LABELS={configuring:'正在配置连接',preparing:'正在准备语音',idle:'等待你的下一句话',listening:'正在听你说',transcribing:'正在识别语音',awaitingConfirmation:'确认一下，再交给 Codex',connecting:'正在连接 Codex',thinking:'Codex 正在思考',acting:'Codex 正在执行任务',awaitingApproval:'等待你的授权',awaitingInput:'等待补充信息',cancelling:'正在停止任务',completed:'Codex 已返回结果',cancelled:'已取消',error:'需要处理一下'};
 const EXAMPLE={uri:'spotify:track:5pIcwtJYNJx93l420oR2Vm',title:'晴天',artist:'周杰倫',aliases:['周杰伦的晴天','周杰倫的晴天','Jay Chou 晴天']};
 function track(value,title,artist){
  const match=String(value||'').trim().match(/^(?:spotify:track:|https:\/\/open\.spotify\.com\/track\/)([A-Za-z0-9]{22})(?:\?[^\s]*)?$/);
  if(!match||!String(title||'').trim()||!String(artist||'').trim())throw Error('填写歌曲名称、歌手和 Spotify 歌曲链接。');
  return {uri:'spotify:track:'+match[1],title:String(title).trim().slice(0,100),artist:String(artist).trim().slice(0,100)};
 }
 function create({$,api,native,state,navigate,toast,onBusy}){
  let companionUI=null,taskUI=null,setupUI=null;
  if(global.StudioNative?.platform==='windows'&&global.StudioNative?.capabilities?.miaoCall===true){
   const note=document.querySelector('.miaocall-privacy');
   if(note)note.textContent='桌面陪伴无需开启麦克风或按键监听。语音需要在 Windows 隐私设置中允许桌面应用使用麦克风；只有主动录音时才采集声音。全局按键由你主动开启，退出即关闭。录音和指令不进入灯效作品库。';
  }
  let current={enabled:false,state:'idle',transcript:'',message:''},pending=false,held=false,operation=0,revision=0,dirty=false;
  const controls=['miaoCallToggle','miaoConfirm','miaoTrackTitle','miaoTrackArtist','miaoTrackLink','miaoUseSpotify'];
  function options(){return {confirmBeforeSend:$('miaoConfirm').checked,tracks:$('miaoUseSpotify')?.checked?[track($('miaoTrackLink').value,$('miaoTrackTitle').value,$('miaoTrackArtist').value)]:[]};}
  function render(){
   const busy=ACTIVE.has(current.state),confirm=current.state==='awaitingConfirmation';
   $('miaoCallToggle').checked=!!current.enabled;
   $('miaoTrackSummary').textContent=($('miaoTrackTitle').value||'选择歌曲')+' · '+($('miaoTrackArtist').value||'歌手');
   $('miaoApplySettings').disabled=!native||pending||busy||confirm||!current.enabled;
   $('miaoSettingsNote').textContent=dirty?'设置已修改，点击「应用到快捷键」后生效。':current.enabled?'当前设置已用于物理快捷键。':'下次开启或点击试说时使用以上设置。';
   $('miaoStateBadge').textContent=!native?'需要桌面 App':current.enabled?'快捷键已开启':'快捷键已关闭';
   $('miaoStateTitle').textContent=LABELS[current.state]||'喵唤 MiaoCall';
   $('miaoStateMessage').textContent=current.message||'按住「·」说话，松开后识别。喵娘会告诉你任务进行到哪一步。';
   $('miaoCallStage').dataset.state=current.state;
   $('miaoConfirmBox').hidden=!confirm;
   if(confirm&&document.activeElement!==$('miaoTranscript'))$('miaoTranscript').value=current.transcript||'';
   $('miaoHoldBtn').textContent=current.state==='listening'?'松开结束录音':'按住试说一句';
   $('miaoHoldBtn').disabled=!native||pending||(busy&&current.state!=='listening')||confirm||state.aiBusy||state.executing||state.closing;
   $('miaoCancelBtn').hidden=!(busy||confirm);
   controls.filter(id=>$(id)).forEach(id=>$(id).disabled=!native||pending||busy||confirm);
   $('miaoSubmitBtn').disabled=pending||!confirm;
   state.miaoCallBusy=busy||confirm;onBusy?.();
  }
  function event(value){if(value.event!=='miaoCall')return;taskUI?.event(value);setupUI?.event(value);if(value.type!=='state')return;revision++;current={...current,...value};taskUI?.update(current);setupUI?.update(current);companionUI?.update(value);render();}
  async function call(action,payload={}){const token=++operation,before=revision;pending=true;render();try{const result=await api(action,payload);if(token===operation&&before===revision&&result&&typeof result==='object')current={...current,...result};return token===operation?result:null;}catch(error){if(token!==operation||before!==revision)return null;current={...current,state:'error',message:error.message||'喵唤未完成，请重试。'};throw error;}finally{if(token===operation)pending=false;render();}}
  async function load(){if(!native){render();taskUI?.load();return;}try{await call('miaoCallStatus');taskUI?.update(current);await taskUI?.load();}catch{} }
  async function toggle(){try{await call($('miaoCallToggle').checked?'miaoCallEnable':'miaoCallDisable',$('miaoCallToggle').checked?options():{});dirty=false;render();}catch(error){toast(error.message);} }
  async function start(){if(held||pending||!native||ACTIVE.has(current.state)||current.state==='awaitingConfirmation')return;held=true;try{await call('miaoCallStartRecording',options());if(!held&&['preparing','listening'].includes(current.state))await stop();}catch(error){held=false;toast(error.message);} }
  async function stop(){held=false;if(!['preparing','listening'].includes(current.state)||pending)return;try{await call('miaoCallStopRecording');}catch(error){toast(error.message);} }
  async function cancel(){held=false;try{await call('miaoCallCancel');}catch(error){toast(error.message);} }
  $('miaoCallToggle').onchange=toggle;
  for(const id of ['miaoTrackTitle','miaoTrackArtist','miaoTrackLink','miaoConfirm','miaoUseSpotify'].filter(id=>$(id)))$(id).onchange=()=>{dirty=true;render();};
  $('miaoApplySettings').onclick=async()=>{try{await call('miaoCallEnable',options());dirty=false;render();}catch(error){toast(error.message);}};
  $('miaoHoldBtn').onpointerdown=event=>{if(event.button!==0)return;event.preventDefault();event.currentTarget.setPointerCapture?.(event.pointerId);start();};
  $('miaoHoldBtn').onpointerup=stop;$('miaoHoldBtn').onpointercancel=cancel;
  $('miaoHoldBtn').onkeydown=event=>{if([' ','Enter'].includes(event.key)){event.preventDefault();if(!event.repeat)start();}};
  $('miaoHoldBtn').onkeyup=event=>{if([' ','Enter'].includes(event.key)){event.preventDefault();stop();}};
  $('miaoCancelBtn').onclick=cancel;
  $('miaoSubmitBtn').onclick=async()=>{try{const text=$('miaoTranscript').value.trim();if(!text||text.length>2000)throw Error('请填写 1–2000 字的指令。');await call('miaoCallSubmit',{text});}catch(error){toast(error.message);}};
  $('miaoVoiceSettings').onclick=()=>navigate('models');
  $('miaoTrackTitle').value=EXAMPLE.title;$('miaoTrackArtist').value=EXAMPLE.artist;$('miaoTrackLink').value='https://open.spotify.com/track/'+EXAMPLE.uri.split(':').pop();
  taskUI=global.StudioAgentTasks?.create({$,api,native,toast,navigate,options,status:()=>current});
  setupUI=global.StudioCodexSetup?.create({$,api,native,toast});
  companionUI=global.StudioCompanion?.create({$,api,native,toast,busy:()=>ACTIVE.has(current.state)||current.state==='awaitingConfirmation'});
  render();return {load,event,cancel,refresh:render,get status(){return current;}};
 }
 global.StudioMiaoCall={create,track};
})(window);
