(function(global){
 'use strict';
 const endpoints={
  'kimi-code':{china:'https://api.kimi.com/coding/v1',global:'https://api.kimi.ai/coding/v1'},
  'kimi-open':{china:'https://api.moonshot.cn/v1',global:'https://api.moonshot.ai/v1'}
 };
 const defaults={'kimi-code':'k3','kimi-open':'kimi-k3'};
 const models={'kimi-code':['k3','k3-256k','kimi-for-coding','kimi-for-coding-highspeed'],'kimi-open':['kimi-k3']};
 function create(options){
  const {$,api,native,state,M,navigate,status,toast,onBusy,acceptDesign}=options;
  let settings=null,loaded=false,loading=null,settingsBusy=false,activeRequest=null,sequence=0,imageImporting=false;
  const images=[];
  const settingsControls=['aiProvider','aiRegion','aiModel','aiCustomModel','aiApiKey','saveAISettingsBtn'];
  function message(error){const text=String(error?.message||error||'操作未完成');const secret=$('aiApiKey').value.trim();return secret?text.split(secret).join('••••••'):text;}
  function settingsStatus(text,error=false){$('aiSettingsStatus').textContent=text;$('aiSettingsStatus').classList.toggle('error',error);}
  function generationStatus(text,error=false){$('aiGenerationStatus').hidden=false;$('aiGenerationStatus').textContent=text;$('aiGenerationStatus').classList.toggle('error',error);}
  function refresh(){
   const busy=state.aiBusy,configured=!!settings?.hasKey;
   $('generateAIBtn').disabled=busy||state.executing||state.hardwareBusy||settingsBusy||imageImporting;
   $('generateAIBtn').textContent=busy?'Kimi 正在制作…':'用 Kimi 制作灯效';
   $('cancelAIBtn').hidden=!busy;$('cancelAIBtn').disabled=!!activeRequest?.cancelRequested;
   $('cancelAIBtn').textContent=activeRequest?.cancelRequested?'正在取消…':'取消制作';
   $('variantBtn').disabled=busy;$('creativeBrief').disabled=busy;
   $('aiUseCurrentStyle').disabled=busy;document.querySelectorAll('[data-ai-example]').forEach(button=>button.disabled=busy);
   $('addAIImagesBtn').disabled=busy||imageImporting||images.length>=3;
   settingsControls.forEach(id=>$(id).disabled=busy||settingsBusy||!native);
   $('testAIConnectionBtn').disabled=busy||settingsBusy||!configured||!native;
   $('removeAIKeyBtn').disabled=busy||settingsBusy||!configured||!native;
   $('aiModelBadge').textContent=busy?'Kimi · 制作中':'Kimi · '+(settings?.model||defaults['kimi-code'])+(loaded&&!configured?' · 未配置':'');
   $('aiSettingsBadge').textContent=!native?'桌面 App 中配置':configured?'密钥已保存':'尚未配置';
   $('aiApiKey').placeholder=configured?'已保存；输入新密钥可替换':'输入你的 API Key';
  }
  function setBusy(value){state.aiBusy=value;refresh();onBusy();}
  function renderImages(){
   const container=$('aiReferenceImages');container.innerHTML='';container.hidden=!images.length;
   images.forEach((image,index)=>{
    const item=document.createElement('div');item.className='ai-reference-image';
    const thumbnail=document.createElement('img');thumbnail.setAttribute('src',image.dataUrl);thumbnail.setAttribute('alt','参考图 '+(index+1));
    const label=document.createElement('span');label.textContent=image.name;label.setAttribute('title',image.name);
    const remove=document.createElement('button');remove.className='icon-button';remove.textContent='×';remove.setAttribute('aria-label','移除参考图 '+(index+1));remove.disabled=state.aiBusy;
    remove.onclick=()=>{if(state.aiBusy)return;images.splice(index,1);renderImages();refresh();};
    item.appendChild(thumbnail);item.appendChild(label);item.appendChild(remove);container.appendChild(item);
   });
   $('aiImageHint').textContent=images.length?images.length+' / 3 张 · 仅当前会话':'最多 3 张 · 仅当前会话';
  }
  function validImage(image){
   if(!image||typeof image.dataUrl!=='string'||!/^data:image\/jpeg;base64,[A-Za-z0-9+/]+={0,2}$/.test(image.dataUrl)||image.dataUrl.length>560000)throw Error('参考图格式或大小不支持，请重新选择 JPG、PNG、WebP 或 GIF 图片。');
   return {name:String(image.name||'参考图').slice(0,256),dataUrl:image.dataUrl};
  }
  async function browserImages(){
   return new Promise((resolve,reject)=>{
    const input=document.createElement('input');input.type='file';input.accept='image/jpeg,image/png,image/webp,image/gif';input.multiple=true;
    input.oncancel=()=>resolve({cancelled:true});
    input.onchange=async()=>{try{const files=Array.from(input.files||[]);if(!files.length)return resolve({cancelled:true});if(files.length>3-images.length)throw Error('最多添加 3 张参考图。');
     const selected=await Promise.all(files.map(file=>new Promise((yes,no)=>{
      if(file.size>20*1024*1024)return no(Error('参考图原文件不能超过 20 MB。'));
      const reader=new FileReader();reader.onerror=()=>no(Error('参考图读取失败'));reader.onload=()=>{
       const image=new Image();image.onerror=()=>no(Error('参考图格式不支持或文件已损坏'));image.onload=()=>{try{
        if(image.naturalWidth*image.naturalHeight>32000000)throw Error('参考图分辨率过大，请使用小于 3200 万像素的图片。');
        const ratio=Math.min(1,1280/Math.max(image.naturalWidth,image.naturalHeight)),canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.naturalWidth*ratio));canvas.height=Math.max(1,Math.round(image.naturalHeight*ratio));const context=canvas.getContext('2d');context.fillStyle='#FFFFFF';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);
        let dataUrl;for(const quality of [.85,.7,.5,.3]){dataUrl=canvas.toDataURL('image/jpeg',quality);if(dataUrl.length<=560000)break;}if(dataUrl.length>560000)throw Error('参考图细节过多，请缩小图片后重试。');yes({name:file.name,dataUrl});
       }catch(error){no(error);}};image.src=reader.result;
      };reader.readAsDataURL(file);
     })));resolve({images:selected});
    }catch(error){reject(error);}};input.click();
   });
  }
  async function addImages(){
   if(state.aiBusy||imageImporting||images.length>=3)return;imageImporting=true;refresh();
   try{const result=native?await api('importAIImages'):await browserImages();if(result?.cancelled)return;const selected=result?.images;if(!Array.isArray(selected)||!selected.length)return;if(selected.length+images.length>3)throw Error('最多添加 3 张参考图，请减少本次选择。');const checked=selected.map(validImage);images.push(...checked);renderImages();}
   catch(error){generationStatus(message(error),true);}finally{imageImporting=false;refresh();}
  }
  function providerChanged(){
   const code=$('aiProvider').value==='kimi-code';
   $('aiProviderNote').textContent=code?'Kimi Code 使用会员编程配额，需遵守官方客户端接入限制。接口拒绝时可以改用开放平台。':'Kimi 开放平台使用独立 API Key 和 API 额度，与 Code 会员密钥分开。';
   $('aiModel').innerHTML=[...models[$('aiProvider').value],'custom'].map(model=>'<option value="'+model+'">'+(model==='custom'?'自定义模型…':model)+'</option>').join('');modelChanged();
  }
  function modelChanged(){const custom=$('aiModel').value==='custom';$('aiCustomModel').hidden=$('aiCustomModelLabel').hidden=!custom;}
  function applySettings(value){
   // The host returns connection metadata only. Never accept or display a saved secret.
   settings={provider:value?.provider||'kimi-code',baseUrl:value?.baseUrl||endpoints['kimi-code'].china,model:value?.model||defaults['kimi-code'],modelMigrated:!!value?.modelMigrated,hasKey:!!value?.hasKey,credentialStore:value?.credentialStore};
   $('aiProvider').value=settings.provider;$('aiRegion').value=settings.baseUrl===endpoints[settings.provider]?.global?'global':'china';providerChanged();if(!models[settings.provider].includes(settings.model)){$('aiModel').value='custom';$('aiCustomModel').value=settings.model;}else{$('aiModel').value=settings.model;$('aiCustomModel').value='';}modelChanged();
   $('aiApiKey').value='';refresh();
  }
  async function loadSettings(){
   if(!native){settingsStatus('AI 制作需要在 Cyberboard Studio 桌面 App 中使用。',true);refresh();return null;}
   if(loaded)return settings;if(loading)return loading;
   settingsBusy=true;refresh();settingsStatus('正在读取本机连接设置…');
   loading=(async()=>{try{applySettings(await api('getAISettings'));loaded=true;settingsStatus((settings.modelMigrated?'默认模型已更新为 K3，可随时选择其他可用模型。':'')+(settings.hasKey?'连接已保存，可测试服务后开始制作。':'输入自己的 API Key，保存后开始制作。'));return settings;}catch(error){settingsStatus(message(error),true);return null;}finally{settingsBusy=false;loading=null;refresh();}})();
   return loading;
  }
  function formSettings(){const provider=$('aiProvider').value;return {provider,baseUrl:endpoints[provider][$('aiRegion').value],model:($('aiModel').value==='custom'?$('aiCustomModel').value.trim():$('aiModel').value)||defaults[provider]};}
  async function saveSettings(){
   if(settingsBusy||state.aiBusy||!native)return;
   const payload=formSettings(),key=$('aiApiKey').value.trim();if(key)payload.apiKey=key;
   settingsBusy=true;refresh();settingsStatus('正在保存连接…');
   try{applySettings(await api('saveAISettings',payload));loaded=true;settingsStatus('连接已保存。密钥保存在系统凭据库，可继续测试连接。');toast('Kimi 连接已保存。');}
   catch(error){settingsStatus(message(error),true);}finally{settingsBusy=false;refresh();}
  }
  async function testConnection(){
   if(settingsBusy||state.aiBusy||!settings?.hasKey||!native)return;
   settingsBusy=true;refresh();settingsStatus('正在检查 Kimi 服务和凭据…');
   try{const result=await api('testAIConnection',{requestId:'ai-test-'+Date.now().toString(36)+'-'+(++sequence)});if(result.success===false)throw Error(result.message||'服务检查未通过');settingsStatus('服务与凭据检查通过。模型权限以实际制作为准。');}
   catch(error){settingsStatus(message(error),true);}finally{settingsBusy=false;refresh();}
  }
  async function removeKey(){
   if(settingsBusy||state.aiBusy||!settings?.hasKey||!native)return;
   settingsBusy=true;refresh();settingsStatus('正在移除本机密钥…');
   try{applySettings(await api('saveAISettings',{provider:settings.provider,baseUrl:settings.baseUrl,model:settings.model,removeKey:true}));loaded=true;settingsStatus('本机密钥已移除，已有作品仍可预览、导出和同步。');}
   catch(error){settingsStatus(message(error),true);}finally{settingsBusy=false;refresh();}
  }
  async function generate(){
   if(state.aiBusy||settingsBusy||imageImporting)return;
   if(!native){toast('AI 制作需要在 Cyberboard Studio 桌面 App 中使用。');return;}
   if(state.executing||state.hardwareBusy||state.preparingSync){toast('设备操作完成后再制作灯效。');return;}
   if(!$('syncModal').hidden){toast('请先关闭同步计划，再开始 AI 制作。');return;}
   const brief=$('creativeBrief').value.trim();if(!brief&&!images.length){generationStatus('先写下你想要的灯效、配色和转场，或添加参考图。',true);$('creativeBrief').focus?.();return;}
   if(!Number.isInteger(state.speedMs)||state.speedMs<10||state.speedMs>100){generationStatus('先把节奏调整到10–100 ms/帧，再制作AI灯效。',true);return;}
   if(state.designs.filter(d=>!options.builtInIds.has(d.id)).length>=30){generationStatus('自定义作品已达到 30 套，请先导出并整理作品库。',true);return;}
   const saved=await loadSettings();if(!saved?.hasKey){navigate('models');generationStatus('先在模型配置中保存 Kimi 连接，再回到工作台制作。',true);return;}
   if(state.aiBusy||state.executing||state.hardwareBusy||state.preparingSync||!$('syncModal').hidden){toast('当前操作完成后再制作灯效。');return;}
   // Send only the user's brief and a small public visual reference, never device or workspace data.
   const reference={palette:(M.palettes[$('paletteSelect').value]||state.selected.palette||[]).filter(c=>/^#[0-9a-f]{6}$/i.test(c)).slice(0,8)};
   if($('aiUseCurrentStyle').checked){reference.name=String(state.selected.name||'').slice(0,256);reference.description=String(state.selected.description||'').slice(0,2000);}
   const id='ai-'+Date.now().toString(36)+'-'+(++sequence)+'-'+Math.random().toString(36).slice(2,10);
   const request={id,cancelRequested:false};activeRequest=request;setBusy(true);renderImages();generationStatus('正在把你的灵感编排成动画…');status('Kimi 正在制作灯效');
   try{
    const result=await api('generateAI',{requestId:id,brief,reference,images:images.map(image=>({...image})),frameCount:192,speedMs:state.speedMs});
    if(request.cancelRequested||result.cancelled){generationStatus('制作已取消，原作品与槽位草稿保留。');return;}
    const design=M.copy(result.design);M.validate(design);
    if(typeof design.id!=='string'||!design.id||typeof design.name!=='string'||!design.name)throw Error('Kimi 返回的作品缺少名称或标识，请重新制作。');
    if(state.designs.some(d=>d.id===design.id))design.id+='-'+Date.now().toString(36);
    design.origin='kimi-ai';design.ai={...(design.ai||{}),provider:result.provider||saved.provider,model:result.model||saved.model};
    acceptDesign(design);generationStatus('制作完成 · 已加入作品库。预览满意后，放入槽位再同步。');status('Kimi 灯效已生成');toast('Kimi 作品已生成，键盘尚未改变。');
   }catch(error){if(request.cancelRequested)generationStatus('制作已取消，原作品与槽位草稿保留。');else{generationStatus(message(error),true);status('AI 制作未完成，创作描述已保留');}}
   finally{if(activeRequest===request)activeRequest=null;setBusy(false);renderImages();}
  }
  async function cancel(){
   const request=activeRequest;if(!request||request.cancelRequested)return;request.cancelRequested=true;refresh();generationStatus('正在取消本次制作…');
   try{await api('cancelAI',{requestId:request.id});}catch(error){generationStatus('已停止接收本次作品，正在等待请求结束。');}
  }
  function progress(event){if(!activeRequest||activeRequest.cancelRequested||event.requestId!==activeRequest.id)return;const stages={ai_request:'正在向 Kimi 提交创作描述…',ai_receiving:'Kimi 正在编排灯效和转场…',ai_compile:'正在生成帧并检查顶部与轴灯数据…'};if(stages[event.stage])generationStatus(stages[event.stage]);}
  function showCreation(design){const ai=design.origin==='kimi-ai';$('aiCreationNote').hidden=!ai;if(ai)$('aiCreationNote').textContent='Kimi 创作'+(design.ai?.model?' · '+design.ai.model:'')+'\n'+(design.description||'顶部与轴灯已编排，可以调整亮度和节奏后同步。');}
  $('aiSettingsLink').onclick=()=>navigate('models');$('generateAIBtn').onclick=generate;$('cancelAIBtn').onclick=cancel;
  $('addAIImagesBtn').onclick=addImages;
  document.querySelectorAll('[data-ai-example]').forEach(button=>button.onclick=()=>{if(state.aiBusy)return;$('creativeBrief').value=button.dataset.aiExample;options.saveBrief?.();});
  $('saveAISettingsBtn').onclick=saveSettings;$('testAIConnectionBtn').onclick=testConnection;$('removeAIKeyBtn').onclick=removeKey;
  $('aiProvider').onchange=()=>{providerChanged();$('aiModel').value=defaults[$('aiProvider').value];$('aiCustomModel').value='';modelChanged();settingsStatus('连接选项已修改，保存后生效。');};
  $('aiRegion').onchange=()=>settingsStatus('接口区域已修改，保存后生效。');$('aiModel').onchange=()=>{modelChanged();settingsStatus('模型已修改，保存后生效。');};$('aiCustomModel').oninput=()=>settingsStatus('模型已修改，保存后生效。');
  providerChanged();refresh();
  return {loadSettings,refresh,progress,showCreation,generate,cancel};
 }
 global.StudioAI={create};
})(typeof window!=='undefined'?window:globalThis);
