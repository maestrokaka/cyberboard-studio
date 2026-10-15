(function(global){
 'use strict';
 const endpoints={
  'kimi-code':{china:'https://api.kimi.com/coding/v1',global:'https://api.kimi.ai/coding/v1'},
  'kimi-open':{china:'https://api.moonshot.cn/v1',global:'https://api.moonshot.ai/v1'},
  'minimax':{china:'https://api.minimax.cn/v1',global:'https://api.minimax.io/v1'},
  'deepseek':{china:'https://api.deepseek.com',global:'https://api.deepseek.com/v1'}
 };
 const defaults={'kimi-code':'k3','kimi-open':'kimi-k3',minimax:'MiniMax-M3',deepseek:'deepseek-flash'};
 const models={'kimi-code':['k3','k3-256k','kimi-for-coding','kimi-for-coding-highspeed'],'kimi-open':['kimi-k3'],minimax:['MiniMax-M3','MiniMax-M3.1-Flash-Preview','MiniMax-M2.7'],deepseek:['deepseek-flash','deepseek-v4-pro','deepseek-v4-flash-vision-exp']};
 const labels={'kimi-code':'Kimi Code','kimi-open':'Kimi',minimax:'MiniMax',deepseek:'DeepSeek'};
 const notes={'kimi-code':'Kimi Code 使用会员编程配额，需遵守官方客户端接入限制。接口拒绝时可以改用开放平台。','kimi-open':'Kimi 开放平台使用独立 API Key 和 API 额度，与 Code 会员密钥分开。',minimax:'MiniMax 开放平台使用独立 API Key。M3 支持参考图；M3.1 Flash Preview 仅限具备 MPlan / Coding Plan 权限的账户。',deepseek:'DeepSeek 使用独立 API Key。Flash 支持参考图；V4 Pro 用于文字创作。模型可用性以账户权限为准。'};
 function providerName(provider){return labels[provider]||'AI';}
 function isAIWork(design){return ['kimi-ai','minimax-ai','deepseek-ai','ai-generated'].includes(design?.origin);}
 function supportsImages(value){if(typeof value?.supportsImages==='boolean')return value.supportsImages;const model=value?.model||defaults[value?.provider];return value?.provider==='kimi-code'||value?.provider==='kimi-open'?true:value?.provider==='minimax'?['MiniMax-M3','MiniMax-M3.1-Flash-Preview'].includes(model):value?.provider==='deepseek'?['deepseek-flash','deepseek-v4-flash-vision-exp'].includes(model):false;}
 function create(options){
  const {$,api,native,state,M,navigate,status,toast,onBusy,acceptDesign}=options;
  let settings=null,loaded=false,loading=null,settingsBusy=false,activeRequest=null,sequence=0,imageImporting=false,profiles={},keyRevealBusy=false,keyRevealSequence=0,revealedKey=null;
  const images=[];
  const settingsControls=['aiProvider','aiRegion','aiModel','aiCustomModel','aiApiKey','saveAISettingsBtn'];
  function message(error){const text=String(error?.message||error||'操作未完成');const secret=$('aiApiKey').value.trim();return secret?text.split(secret).join('••••••'):text;}
  function settingsStatus(text,error=false){$('aiSettingsStatus').textContent=text;$('aiSettingsStatus').classList.toggle('error',error);}
  function generationStatus(text,error=false){$('aiGenerationStatus').hidden=false;$('aiGenerationStatus').textContent=text;$('aiGenerationStatus').classList.toggle('error',error);}
  function selectedProfile(){const provider=$('aiProvider').value;return profiles[provider]||{provider,baseUrl:endpoints[provider].china,model:defaults[provider],hasKey:false};}
  function credentialProblem(){const profile=selectedProfile();return profile.credentialError||(profile.hasKey===null?'旧 Key 暂时无法读取，请重新输入并保存。':'');}
  function unchangedRevealedKey(){return !!revealedKey&&revealedKey.provider===$('aiProvider').value&&$('aiApiKey').value===revealedKey.value;}
  function replacementKey(){return !!$('aiApiKey').value.trim()&&!unchangedRevealedKey();}
  function hideKey(){keyRevealSequence++;keyRevealBusy=false;if(revealedKey&&$('aiApiKey').value===revealedKey.value)$('aiApiKey').value='';revealedKey=null;$('aiApiKey').type='password';}
  function pageChanged(page){if(page!=='models'){hideKey();refresh();}}
  function formIsSaved(){const form=formSettings(),saved=selectedProfile();return form.baseUrl===saved.baseUrl&&form.model===saved.model&&(!$('aiApiKey').value.trim()||unchangedRevealedKey());}
  function capabilityNote(){const form=formSettings(),saved=selectedProfile(),known=form.model===saved.model&&form.baseUrl===saved.baseUrl?saved:form;return supportsImages(known)?'支持文字与参考图创作；图片只在你点击制作时发送。':models[form.provider].includes(form.model)?'此模型仅支持文字创作。参考图会保留，但制作前需要移除图片或换用支持图片的模型。':'自定义模型的图片能力尚未确认，仅开放文字创作。';}
  function refresh(){
   const busy=state.aiBusy,configured=selectedProfile().hasKey===true,credentialError=credentialProblem(),name=providerName(settings?.provider||'kimi-code');
   $('generateAIBtn').disabled=busy||state.executing||state.hardwareBusy||settingsBusy||imageImporting||keyRevealBusy;
   $('generateAIBtn').textContent=busy?providerName(activeRequest?.provider||settings?.provider)+' 正在制作…':loaded?'用 '+name+' 制作灯效':'制作 AI 灯效';
   $('cancelAIBtn').hidden=!busy;$('cancelAIBtn').disabled=!!activeRequest?.cancelRequested;
   $('cancelAIBtn').textContent=activeRequest?.cancelRequested?'正在取消…':'取消制作';
   $('variantBtn').disabled=busy;$('creativeBrief').disabled=busy;
   $('aiUseCurrentStyle').disabled=busy;document.querySelectorAll('[data-ai-example]').forEach(button=>button.disabled=busy);
   $('addAIImagesBtn').disabled=busy||imageImporting||images.length>=3;
   settingsControls.forEach(id=>$(id).disabled=busy||settingsBusy||keyRevealBusy||!native);
   $('saveAISettingsBtn').disabled=busy||settingsBusy||keyRevealBusy||!native||!!credentialError&&!replacementKey();
   $('testAIConnectionBtn').disabled=busy||settingsBusy||keyRevealBusy||!configured||!native||!formIsSaved();
   $('removeAIKeyBtn').disabled=busy||settingsBusy||keyRevealBusy||!configured||!native;
   const keyVisible=$('aiApiKey').type==='text';$('toggleAIKeyBtn').textContent=keyRevealBusy?'读取中…':keyVisible?'隐藏':'显示';$('toggleAIKeyBtn').setAttribute('aria-pressed',String(keyVisible));$('toggleAIKeyBtn').setAttribute('aria-label',keyVisible?'隐藏 API Key':'显示 API Key');$('toggleAIKeyBtn').disabled=busy||settingsBusy||keyRevealBusy||!native||(!$('aiApiKey').value&&!configured&&selectedProfile().hasKey!==null);
   $('aiModelBadge').textContent=busy?providerName(activeRequest?.provider||settings?.provider)+' · 制作中':loaded?name+' · '+settings.model+(settings.hasKey===null?' · 密钥状态未确认':settings.hasKey===false?' · 未配置':''):'AI · 尚未读取连接';
   $('aiSettingsBadge').textContent=!native?'桌面 App 中配置':credentialError?'密钥无法读取':!loaded?'尚未读取':configured?'密钥已保存':'尚未配置';
   $('aiApiKey').placeholder=credentialError?'重新输入 Key 后可直接保存':configured?'已保存；输入新密钥可替换':'输入你的 API Key';
   $('aiCredentialNote').textContent=credentialError?'旧 Key 暂时无法读取；输入新的 Key 可直接保存。':'Key 仅保存在本机；默认隐藏，点击「显示」查看。';
   $('aiModelCapability').textContent=capabilityNote();
   $('aiActiveConnection').textContent=loaded?'工作台当前使用：'+name+' · '+settings.model+'。服务和模型修改后，点击「保存并使用」生效。':'每个服务分别保存模型、接口与密钥，切换不会删除已有连接。';
   $('aiSendHint').textContent='描述'+(images.length?'和 '+images.length+' 张参考图':'与所选参考图')+'发送给 '+(loaded?name:'已保存的创作服务')+'。节奏自动编排，可在描述里指定时长；预览后再同步。';
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
   const provider=$('aiProvider').value;
   $('aiProviderNote').textContent=notes[provider];
   $('aiRegionLabel').textContent=provider==='deepseek'?'接口地址':'接口区域';
   $('aiRegion').innerHTML=provider==='deepseek'?'<option value="china">标准地址（推荐）</option><option value="global">兼容 /v1 地址</option>':'<option value="china">中国区</option><option value="global">国际区</option>';
   $('aiModel').innerHTML=[...models[provider],'custom'].map(model=>'<option value="'+model+'">'+(model==='custom'?'自定义模型…':model+(supportsImages({provider,model})?' · 支持参考图':' · 文字创作'))+'</option>').join('');modelChanged();
  }
  function modelChanged(){const custom=$('aiModel').value==='custom';$('aiCustomModel').hidden=$('aiCustomModelLabel').hidden=!custom;}
  function showProfile(profile){
   hideKey();
   $('aiProvider').value=profile.provider;providerChanged();$('aiRegion').value=profile.baseUrl===endpoints[profile.provider]?.global?'global':'china';
   if(!models[profile.provider].includes(profile.model)){$('aiModel').value='custom';$('aiCustomModel').value=profile.model;}else{$('aiModel').value=profile.model;$('aiCustomModel').value='';}modelChanged();$('aiApiKey').value='';
  }
  function applySettings(value){
   // Connection metadata never contains a secret. Only the explicit reveal action can load one.
   const clean=(item,provider)=>({provider,baseUrl:item?.baseUrl||endpoints[provider].china,model:item?.model||defaults[provider],hasKey:item?.hasKey===null?null:!!item?.hasKey,...(typeof item?.credentialError==='string'?{credentialError:item.credentialError.slice(0,1000)}:{}),...(typeof item?.supportsImages==='boolean'?{supportsImages:item.supportsImages}:{})});
   const provider=endpoints[value?.provider]?value.provider:'kimi-code';
   Object.keys(endpoints).forEach(id=>{if(value?.profiles?.[id])profiles[id]=clean(value.profiles[id],id);else if(!profiles[id])profiles[id]=clean(null,id);});
   settings={...clean(value,provider),modelMigrated:!!value?.modelMigrated,credentialStore:value?.credentialStore};profiles[provider]={...settings};showProfile(settings);refresh();
  }
  async function loadSettings(){
   if(!native){settingsStatus('AI 制作需要在 Cyberboard Studio 桌面 App 中使用。',true);refresh();return null;}
   const retryCredentials=loaded&&state.page==='models'&&Object.values(profiles).some(profile=>profile.credentialError||profile.hasKey===null),retryProvider=retryCredentials?$('aiProvider').value:null;
   if(loaded&&!retryCredentials)return settings;if(loading)return loading;
   settingsBusy=true;refresh();settingsStatus('正在读取本机连接设置…');
   loading=(async()=>{try{applySettings(await api('getAISettings'));loaded=true;if(retryProvider)showProfile(profiles[retryProvider]);settingsStatus(credentialProblem()||(settings.modelMigrated?'默认模型已更新为 K3，可随时选择其他可用模型。':'')+(selectedProfile().hasKey?'连接已保存，可测试服务后开始制作。':'输入自己的 API Key，保存后开始制作。'),!!credentialProblem());return settings;}catch(error){settingsStatus(message(error),true);return null;}finally{settingsBusy=false;loading=null;refresh();}})();
   return loading;
  }
  function formSettings(){const provider=$('aiProvider').value;return {provider,baseUrl:endpoints[provider][$('aiRegion').value],model:$('aiModel').value==='custom'?$('aiCustomModel').value.trim():$('aiModel').value||defaults[provider]};}
  async function toggleKeyVisibility(){
   if(settingsBusy||state.aiBusy||keyRevealBusy||!native)return;
   const input=$('aiApiKey');if(input.type==='text'){hideKey();refresh();return;}
   if(input.value){input.type='text';refresh();return;}
   if(selectedProfile().hasKey!==true&&selectedProfile().hasKey!==null)return;
   const provider=$('aiProvider').value,request=++keyRevealSequence;keyRevealBusy=true;refresh();
   try{
    const result=await api('revealAIKey',{provider});
    if(request!==keyRevealSequence||provider!==$('aiProvider').value||state.page!=='models')return;
    if(typeof result?.apiKey!=='string')throw Error('无法读取已保存的 API Key，请重试。');
    profiles[provider]={...selectedProfile(),hasKey:!!result.apiKey};delete profiles[provider].credentialError;
    if(settings?.provider===provider){settings={...settings,hasKey:!!result.apiKey};delete settings.credentialError;}
    if(!result.apiKey){settingsStatus('此服务尚未保存 API Key。');return;}
    revealedKey={provider,value:result.apiKey};input.value=result.apiKey;input.type='text';
    settingsStatus('Key 已显示，点击「隐藏」可收起。');
   }catch(error){if(request===keyRevealSequence&&provider===$('aiProvider').value&&state.page==='models')settingsStatus(message(error),true);}
   finally{if(request===keyRevealSequence){keyRevealBusy=false;refresh();}}
  }
  async function saveSettings(){
   if(settingsBusy||state.aiBusy||keyRevealBusy||!native)return;
   if(credentialProblem()&&!replacementKey()){settingsStatus('旧 Key 暂时无法读取，重新输入 Key 后可直接保存。',true);return;}
   const payload=formSettings(),key=$('aiApiKey').value.trim();if(!payload.model){settingsStatus('请填写官方模型 ID，或选择已有模型。',true);return;}if(key&&!unchangedRevealedKey())payload.apiKey=key;
   settingsBusy=true;refresh();settingsStatus('正在保存连接…');
   try{applySettings(await api('saveAISettings',payload));loaded=true;settingsStatus(providerName(settings.provider)+' 连接已保存，工作台将使用此服务，可继续测试连接。');toast(providerName(settings.provider)+' 连接已保存。');}
   catch(error){settingsStatus(message(error),true);}finally{settingsBusy=false;refresh();}
  }
  async function testConnection(){
   if(settingsBusy||state.aiBusy||keyRevealBusy||!selectedProfile().hasKey||!native||!formIsSaved())return;
   const provider=$('aiProvider').value;settingsBusy=true;refresh();settingsStatus('正在检查 '+providerName(provider)+' 服务和凭据…');
   try{const result=await api('testAIConnection',{provider,requestId:'ai-test-'+Date.now().toString(36)+'-'+(++sequence)});if(result.success===false||result.needsGenerationTest||result.requiresGenerationTest){settingsStatus(result.message||'此服务未提供独立连接检测，尚未确认模型权限。请在工作台主动制作一次进行验证。',true);return;}settingsStatus('服务与凭据检查通过。模型权限以实际制作为准。');}
   catch(error){settingsStatus(message(error),true);}finally{settingsBusy=false;refresh();}
  }
  async function removeKey(){
   if(settingsBusy||state.aiBusy||keyRevealBusy||!selectedProfile().hasKey||!native)return;
   const selected=selectedProfile();
   settingsBusy=true;refresh();settingsStatus('正在移除本机密钥…');
   try{applySettings(await api('saveAISettings',{provider:selected.provider,baseUrl:selected.baseUrl,model:selected.model,removeKey:true}));loaded=true;settingsStatus(providerName(selected.provider)+' 本机密钥已移除，其他服务的密钥保留。已有作品仍可预览、导出和同步。');}
   catch(error){settingsStatus(message(error),true);}finally{settingsBusy=false;refresh();}
  }
  async function generate(){
   if(state.aiBusy||settingsBusy||imageImporting||keyRevealBusy)return;
   if(!native){toast('AI 制作需要在 Cyberboard Studio 桌面 App 中使用。');return;}
   if(state.executing||state.hardwareBusy||state.preparingSync){toast('设备操作完成后再制作灯效。');return;}
   if(!$('syncModal').hidden){toast('请先关闭同步计划，再开始 AI 制作。');return;}
   const brief=$('creativeBrief').value.trim();if(!brief&&!images.length){generationStatus('先写下你想要的灯效、配色和转场，或添加参考图。',true);$('creativeBrief').focus?.();return;}
   if(state.designs.filter(d=>!options.builtInIds.has(d.id)).length>=30){generationStatus('自定义作品已达到 30 套，请先导出并整理作品库。',true);return;}
   const saved=await loadSettings();if(!saved?.hasKey){navigate('models');generationStatus('先在模型配置中保存 '+providerName(saved?.provider||'kimi-code')+' 连接，再回到工作台制作。',true);return;}
   if(images.length&&!supportsImages(saved)){generationStatus(providerName(saved.provider)+' · '+saved.model+' 未开放参考图创作。图片已保留，请换用支持图片的模型并保存，或移除图片后用文字制作。',true);return;}
   if(state.aiBusy||state.executing||state.hardwareBusy||state.preparingSync||!$('syncModal').hidden){toast('当前操作完成后再制作灯效。');return;}
   // Existing work is a visual reference only when explicitly requested. Its playback settings belong to preview.
   const reference=$('aiUseCurrentStyle').checked?{name:String(state.selected.name||'').slice(0,256),description:String(state.selected.description||'').slice(0,2000),palette:(M.palettes[$('paletteSelect').value]||state.selected.palette||[]).filter(c=>/^#[0-9a-f]{6}$/i.test(c)).slice(0,8)}:null;
   const id='ai-'+Date.now().toString(36)+'-'+(++sequence)+'-'+Math.random().toString(36).slice(2,10);
   const request={id,provider:saved.provider,cancelRequested:false};activeRequest=request;setBusy(true);renderImages();generationStatus('正在把你的灵感编排成动画…');status(providerName(saved.provider)+' 正在制作灯效');
   try{
    const result=await api('generateAI',{provider:saved.provider,requestId:id,brief,...(reference?{reference}:{}),images:images.map(image=>({...image})),timing:'auto'});
    if(request.cancelRequested||result.cancelled){generationStatus('制作已取消，原作品与槽位草稿保留。');return;}
    const design=M.copy(result.design);M.validate(design);
    if(typeof design.id!=='string'||!design.id||typeof design.name!=='string'||!design.name)throw Error(providerName(saved.provider)+' 返回的作品缺少名称或标识，请重新制作。');
    if(state.designs.some(d=>d.id===design.id))design.id+='-'+Date.now().toString(36);
    const provider=result.provider||saved.provider;design.origin=provider.startsWith('kimi-')?'kimi-ai':provider+'-ai';design.ai={...(design.ai||{}),provider,model:result.model||saved.model};
    acceptDesign(design);generationStatus('制作完成 · 已加入作品库。预览满意后，放入槽位再同步。');status(providerName(provider)+' 灯效已生成');toast(providerName(provider)+' 作品已生成，键盘尚未改变。');
   }catch(error){if(request.cancelRequested)generationStatus('制作已取消，原作品与槽位草稿保留。');else{generationStatus(message(error),true);status('AI 制作未完成，创作描述已保留');}}
   finally{if(activeRequest===request)activeRequest=null;setBusy(false);renderImages();}
  }
  async function cancel(){
   const request=activeRequest;if(!request||request.cancelRequested)return;request.cancelRequested=true;refresh();generationStatus('正在取消本次制作…');
   try{await api('cancelAI',{requestId:request.id});}catch(error){generationStatus('已停止接收本次作品，正在等待请求结束。');}
  }
  function progress(event){if(!activeRequest||activeRequest.cancelRequested||event.requestId!==activeRequest.id)return;const name=providerName(activeRequest.provider),stages={ai_request:'正在向 '+name+' 提交创作描述…',ai_receiving:name+' 正在编排灯效和转场…',ai_compile:'正在生成帧并检查顶部与轴灯数据…',ai_quality:'正在检查灯光可见性与循环衔接…'};if(stages[event.stage])generationStatus(stages[event.stage]);}
  function showCreation(design){
   const ai=isAIWork(design);$('aiCreationNote').hidden=!ai;if(!ai)return;
   const colorWarnings=new Set(['weak_top_intensity','saturated_layers_whitened']);
   const warnings=Array.isArray(design.ai?.quality?.warnings)?design.ai.quality.warnings.filter(item=>item&&colorWarnings.has(item.code)&&typeof item.message==='string').slice(0,2).map(item=>item.message.slice(0,180)):[];
   $('aiCreationNote').textContent=providerName(design.ai?.provider||(design.origin==='kimi-ai'?'kimi-open':design.origin.replace(/-ai$/,'')))+' 创作'+(design.ai?.model?' · '+design.ai.model:'')+'\n'+(design.description||'顶部与轴灯已编排，可以调整亮度和节奏后同步。')+(warnings.length?'\n预览留意：'+warnings.join(' '):'');
  }
  $('aiSettingsLink').onclick=()=>navigate('models');$('generateAIBtn').onclick=generate;$('cancelAIBtn').onclick=cancel;
  $('addAIImagesBtn').onclick=addImages;
  document.querySelectorAll('[data-ai-example]').forEach(button=>button.onclick=()=>{if(state.aiBusy)return;$('creativeBrief').value=button.dataset.aiExample;options.saveBrief?.();});
  $('saveAISettingsBtn').onclick=saveSettings;$('testAIConnectionBtn').onclick=testConnection;$('removeAIKeyBtn').onclick=removeKey;$('toggleAIKeyBtn').onclick=toggleKeyVisibility;
  $('aiProvider').onchange=()=>{showProfile(selectedProfile());refresh();settingsStatus(credentialProblem()||'已载入该服务的本机连接。点击「保存并使用」后，工作台才会切换服务。',!!credentialProblem());};
  $('aiRegion').onchange=()=>{refresh();settingsStatus(credentialProblem()||'接口选项已修改，保存后生效。',!!credentialProblem());};$('aiModel').onchange=()=>{modelChanged();refresh();settingsStatus(credentialProblem()||'模型已修改，保存后生效。',!!credentialProblem());};$('aiCustomModel').oninput=()=>{refresh();settingsStatus(credentialProblem()||'模型已修改，保存后生效。',!!credentialProblem());};$('aiApiKey').oninput=()=>{revealedKey=null;refresh();const problem=credentialProblem();settingsStatus(replacementKey()?'新的 Key 尚未保存，点击「保存并使用」即可。':problem||'密钥尚未保存，点击「保存并使用」后生效。',!!problem&&!replacementKey());};
  $('aiApiKey').type='password';providerChanged();refresh();
  return {loadSettings,refresh,progress,showCreation,generate,cancel,pageChanged};
 }
 global.StudioAI={create,providerName,isAIWork};
})(typeof window!=='undefined'?window:globalThis);
