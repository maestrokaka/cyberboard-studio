/* Offline AI interactions. The mock never calls Kimi, a credential store or USB. */
const assert=require('assert/strict');
const {harness,settle,clone}=require('./ui-check.cjs');
function mock(options={}){
 let settings={provider:'kimi-code',baseUrl:'https://api.kimi.com/coding/v1',model:'k3',hasKey:!!options.hasKey,credentialStore:'offline-test'};
 let resolveGeneration,rejectGeneration;
 const handlers={
  importAIImages:()=>options.importImages?.()||{cancelled:true},
  getAISettings:()=>clone(settings),
  saveAISettings:payload=>{settings={...settings,provider:payload.provider,baseUrl:payload.baseUrl,model:payload.model,hasKey:payload.removeKey?false:!!payload.apiKey||settings.hasKey};return clone(settings);},
  testAIConnection:()=>({success:true,model:settings.model}),
  generateAI:()=>new Promise((resolve,reject)=>{resolveGeneration=resolve;rejectGeneration=reject;}),
  cancelAI:()=>({cancelled:true})
 };
 const h=harness({handlers,platform:options.platform});
 return {...h,complete(value){assert.ok(resolveGeneration);resolveGeneration(value);resolveGeneration=null;},fail(message){assert.ok(rejectGeneration);rejectGeneration(Error(message));rejectGeneration=null;}};
}
function generated(h){const d=clone(h.window.STUDIO_DATA.designs[0]);d.id='ai-offline-created';d.name='棱镜折返';d.description='双束几何光带在中段汇合，再向两侧折返。';return {design:d,provider:'kimi-code',model:'kimi-for-coding'};}
const forbiddenActions=new Set(['plan','restorePlan','execute','detect','setTime']);
(async()=>{
 const h=mock();await settle();
 assert.deepEqual(h.calls.map(c=>c.action),['bootstrap'],'startup must not call AI, a key store or hardware');
 assert.equal(h.el('aiModel').value,'k3','new sessions default to K3');
 assert.equal(h.el('page-settings').querySelectorAll('#aiSettingsCard').length,0,'model configuration must not remain in general settings');
 assert.equal(h.el('page-models').querySelectorAll('#aiSettingsCard').length,1);
 const modelsNav=h.document.querySelectorAll('[data-page]').find(button=>button.dataset.page==='models');assert.ok(modelsNav,'model configuration is a peer workspace page');
 await h.el('generateAIBtn').click();assert.match(h.el('aiGenerationStatus').textContent,/先写下/);assert.equal(h.calls.length,1);
 h.el('creativeBrief').value='黑白装甲，青紫反向纵卷，冷白碰撞后熄灭。';
 await h.el('generateAIBtn').click();assert.equal(h.app.state.page,'models');assert.equal(h.calls.filter(c=>c.action==='generateAI').length,0);
 assert.match(h.el('aiSettingsStatus').textContent,/输入自己的 API Key/);
 const key='offline-test-secret-never-persist';h.el('aiApiKey').value=key;await h.el('saveAISettingsBtn').click();
 assert.equal(h.el('aiApiKey').value,'','saved secrets must be cleared from the form');assert.match(h.el('aiSettingsBadge').textContent,/已保存/);
 assert.equal(h.calls.find(c=>c.action==='saveAISettings').payload.apiKey,key);
 assert.equal(h.calls.find(c=>c.action==='saveAISettings').payload.model,'k3');
 await h.el('testAIConnectionBtn').click();assert.match(h.el('aiSettingsStatus').textContent,/模型权限以实际制作为准/);
 h.app.navigate('workbench');await h.el('assignBtn').click();await h.flushSave();
 const previousPending=JSON.stringify([...h.app.state.pending]),previousDesign=h.app.state.selected.id;
 const making=h.el('generateAIBtn').click();await settle();
 assert.equal(h.app.state.aiBusy,true);assert.equal(h.el('generateAIBtn').disabled,true);assert.equal(h.el('cancelAIBtn').hidden,false);
 assert.equal(h.el('syncBtn').disabled,true);assert.equal(h.el('assignBtn').disabled,true);
 const request=h.calls.find(c=>c.action==='generateAI');assert.deepEqual(Object.keys(request.payload).sort(),['brief','frameCount','images','reference','requestId','speedMs']);
 assert.deepEqual(Object.keys(request.payload.reference).sort(),['palette']);assert.doesNotMatch(JSON.stringify(request.payload),/key_layer|layer_data|page_data|current\.json|snapshot|workspace|apiKey/);
 const progressText=h.el('aiGenerationStatus').textContent;
 h.window.StudioBridge.event({event:'progress',stage:'ai_compile',requestId:'another-request'});assert.equal(h.el('aiGenerationStatus').textContent,progressText);
 h.window.StudioBridge.event({event:'progress',stage:'ai_compile',requestId:request.payload.requestId});assert.match(h.el('aiGenerationStatus').textContent,/检查顶部与轴灯/);
 await h.el('generateAIBtn').click();await h.el('deviceSyncBtn').click();await h.el('timeBtn').onclick();
 assert.equal(h.calls.filter(c=>c.action==='generateAI').length,1,'duplicate clicks must never generate twice');assert.equal(h.calls.filter(c=>forbiddenActions.has(c.action)).length,0,'AI creation must never write or read hardware');
 h.complete(generated(h));await making;assert.equal(h.app.state.aiBusy,false);assert.equal(h.app.state.designs.length,4);
 assert.equal(h.app.state.selected.id,'ai-offline-created');assert.equal(h.app.state.selected.origin,'kimi-ai');assert.equal(h.app.preview.playing,true);
 assert.equal(JSON.stringify([...h.app.state.pending]),previousPending,'new AI work must not replace slot drafts');assert.equal(h.app.state.pending.get(1).design.id,previousDesign);
 assert.match(h.el('draftBadge').textContent,/AI 作品/);assert.match(h.el('aiCreationNote').textContent,/棱|双束几何光带/);
 await h.flushSave();assert.equal(h.control.workspace.designs.length,1);assert.doesNotMatch(JSON.stringify(h.control.workspace),new RegExp(key));
 await h.app.exportJSON();const exported=h.calls.filter(c=>c.action==='exportJSON').at(-1).payload.json;assert.equal(exported.origin,'kimi-ai');assert.doesNotMatch(JSON.stringify(exported),new RegExp(key));
 const restored=harness({workspace:clone(h.control.workspace)});await settle();assert.equal(restored.app.state.selected.id,'ai-offline-created');assert.match(restored.el('aiCreationNote').textContent,/Kimi 创作/);
 // A failed generation leaves the accepted work, drafts and prompt intact.
 const prompt=h.el('creativeBrief').value,current=h.app.state.selected.id;
 h.el('aiUseCurrentStyle').checked=true;const failing=h.el('generateAIBtn').click();await settle();const optedIn=h.calls.filter(c=>c.action==='generateAI').at(-1).payload.reference;assert.deepEqual(Object.keys(optedIn).sort(),['description','name','palette']);h.fail('Kimi Code 返回 403：客户端尚未获准，请使用支持的官方接入方式或开放平台。');await failing;
 assert.equal(h.app.state.selected.id,current);assert.equal(h.el('creativeBrief').value,prompt);assert.equal(h.app.state.designs.length,4);assert.equal(h.app.state.aiBusy,false);assert.match(h.el('aiGenerationStatus').textContent,/403/);
 // Cancelling ignores a response even if it arrives immediately after the cancellation request.
 const cancelling=h.el('generateAIBtn').click();await settle();await h.el('cancelAIBtn').click();assert.match(h.el('aiGenerationStatus').textContent,/正在取消/);
 h.complete({...generated(h),design:{...generated(h).design,id:'late-response'}});await cancelling;
 assert.equal(h.app.state.designs.length,4);assert.equal(h.app.state.selected.id,current);assert.match(h.el('aiGenerationStatus').textContent,/已取消/);assert.equal(h.app.state.aiBusy,false);
 // Local validation catches bad output before it can enter the library.
 const invalid=h.el('generateAIBtn').click();await settle();const bad=generated(h);bad.design.keyframes[0][57]='#FFFFFF';h.complete(bad);await invalid;
 assert.equal(h.app.state.designs.length,4);assert.match(h.el('aiGenerationStatus').textContent,/保留索引/);assert.equal(JSON.stringify([...h.app.state.pending]),previousPending);
 // Service changes remain local until explicitly saved, with no automatic key/network calls.
 h.app.navigate('models');const callsBefore=h.calls.length;h.el('aiProvider').value='kimi-open';h.el('aiProvider').onchange();h.el('aiRegion').value='global';h.el('aiRegion').onchange();
 assert.equal(h.el('aiModel').value,'kimi-k3');assert.equal(h.calls.length,callsBefore);h.el('aiApiKey').value='offline-open-secret';await h.el('saveAISettingsBtn').click();
 const save=h.calls.filter(c=>c.action==='saveAISettings').at(-1).payload;assert.equal(save.baseUrl,'https://api.moonshot.ai/v1');assert.equal(save.model,'kimi-k3');assert.equal(h.el('aiApiKey').value,'');
 const beforeCustomModel=h.calls.length;h.el('aiModel').value='custom';h.el('aiModel').onchange();assert.equal(h.el('aiCustomModel').hidden,false);h.el('aiCustomModel').value='kimi-custom-vision';h.el('aiCustomModel').oninput();assert.equal(h.calls.length,beforeCustomModel,'choosing a model never submits a request');await h.el('saveAISettingsBtn').click();assert.equal(h.calls.filter(c=>c.action==='saveAISettings').at(-1).payload.model,'kimi-custom-vision');
 await h.el('removeAIKeyBtn').click();assert.equal(h.calls.filter(c=>c.action==='saveAISettings').at(-1).payload.removeKey,true);assert.match(h.el('aiSettingsBadge').textContent,/尚未配置/);assert.equal(h.app.state.designs.length,4);
 assert.equal(h.calls.filter(c=>forbiddenActions.has(c.action)).length,0);
 // Imported long frame intervals remain valid designs; AI rejects them locally without reading settings or requesting a model.
 const slow=mock();await settle();const slowDesign=generated(slow).design;slowDesign.id='slow-import';slowDesign.speed_ms=200;slow.control.importValue={fileName:'slow.design.json',json:slowDesign};await slow.app.importJSON();await slow.el('assignBtn').click();slow.el('creativeBrief').value='月光缓慢游动';const beforeSlow=slow.calls.length,slowPending=JSON.stringify([...slow.app.state.pending]);await slow.el('generateAIBtn').click();assert.equal(slow.calls.length,beforeSlow);assert.equal(slow.app.state.speedMs,200);assert.equal(slow.app.state.selected.id,'slow-import');assert.equal(JSON.stringify([...slow.app.state.pending]),slowPending);assert.match(slow.el('aiGenerationStatus').textContent,/先把节奏调整到10–100 ms\/帧/);
 // Selected references remain session-only, and image-only briefs are supported.
 const imageValue={name:'装甲 <svg onload=x>.png',dataUrl:'data:image/jpeg;base64,/9j/AA==',width:1280,height:720};
 let imageResult={images:[imageValue]};const visual=mock({hasKey:true,importImages:()=>imageResult});await settle();
 await visual.el('addAIImagesBtn').click();assert.equal(visual.document.querySelectorAll('.ai-reference-image').length,1);assert.equal(visual.el('aiReferenceImages').querySelectorAll('svg').length,0,'reference filenames cannot inject markup');
 assert.equal(visual.el('aiReferenceImages').querySelectorAll('img')[0].getAttribute('src'),imageValue.dataUrl);
 const imageMaking=visual.el('generateAIBtn').click();await settle();const imageRequest=visual.calls.find(c=>c.action==='generateAI').payload;
 assert.equal(imageRequest.brief,'');assert.deepEqual(imageRequest.images,[{name:imageValue.name,dataUrl:imageValue.dataUrl}]);
 const lockedRemove=visual.document.querySelectorAll('.ai-reference-image')[0].querySelectorAll('button')[0];assert.equal(lockedRemove.disabled,true);
 visual.complete(generated(visual));await imageMaking;await visual.flushSave();assert.doesNotMatch(JSON.stringify(visual.control.workspace),/data:image|装甲/);
 await visual.app.exportJSON();assert.doesNotMatch(JSON.stringify(visual.calls.filter(c=>c.action==='exportJSON').at(-1).payload.json),/data:image|装甲/);
 const reloadVisual=harness({workspace:clone(visual.control.workspace)});await settle();assert.equal(reloadVisual.document.querySelectorAll('.ai-reference-image').length,0,'images must not be restored from workspace');
 imageResult={images:[{name:'bad.svg',dataUrl:'data:image/svg+xml;base64,PHN2Zz4='}]};await visual.el('addAIImagesBtn').click();assert.equal(visual.document.querySelectorAll('.ai-reference-image').length,1);assert.match(visual.el('aiGenerationStatus').textContent,/格式或大小/);
 imageResult={images:[{...imageValue,dataUrl:'data:image/jpeg;base64,'+'A'.repeat(560000)}]};await visual.el('addAIImagesBtn').click();assert.equal(visual.document.querySelectorAll('.ai-reference-image').length,1);
 imageResult={images:[imageValue,imageValue,imageValue]};await visual.el('addAIImagesBtn').click();assert.equal(visual.document.querySelectorAll('.ai-reference-image').length,1);assert.match(visual.el('aiGenerationStatus').textContent,/最多添加 3/);
 imageResult={images:[imageValue,imageValue]};await visual.el('addAIImagesBtn').click();assert.equal(visual.document.querySelectorAll('.ai-reference-image').length,3);assert.equal(visual.el('addAIImagesBtn').disabled,true);
 await visual.document.querySelectorAll('.ai-reference-image')[0].querySelectorAll('button')[0].click();assert.equal(visual.document.querySelectorAll('.ai-reference-image').length,2);assert.equal(visual.el('addAIImagesBtn').disabled,false);
 assert.equal(visual.calls.filter(c=>forbiddenActions.has(c.action)).length,0);
 visual.app.navigate('library');await visual.document.querySelectorAll('[data-delete-design]')[0].click();await visual.flushSave();assert.doesNotMatch(JSON.stringify(visual.control.workspace.trash),/data:image|装甲/,'selected reference images must not enter recycled works');
 const browser=harness({native:false});await settle();browser.el('creativeBrief').value='试试棱镜';await browser.el('generateAIBtn').click();assert.equal(browser.calls.length,0);assert.match(browser.el('toast').textContent,/桌面 App/);
 const windows=mock({platform:'windows',hasKey:true});await settle();windows.el('creativeBrief').value='酸绿电光隧道';const windowsMaking=windows.el('generateAIBtn').click();await settle();windows.complete(generated(windows));await windowsMaking;assert.equal(windows.app.state.selected.origin,'kimi-ai');assert.equal(windows.window.webkit,undefined);
 const migrated=harness({handlers:{getAISettings:()=>({provider:'kimi-code',baseUrl:'https://api.kimi.com/coding/v1',model:'k3',hasKey:true,modelMigrated:true,modelDefaultsVersion:2})}});await settle();await migrated.el('aiSettingsLink').click();await settle();assert.equal(migrated.app.state.page,'models');assert.equal(migrated.el('aiModel').value,'k3');assert.match(migrated.el('aiSettingsStatus').textContent,/默认模型已更新为 K3/);
 assert.deepEqual(migrated.el('aiModel').querySelectorAll('option').map(option=>option.value),['k3','k3-256k','kimi-for-coding','kimi-for-coding-highspeed','custom']);assert.equal(migrated.calls.filter(call=>call.action==='generateAI'||call.action==='testAIConnection').length,0);assert.match(migrated.el('aiModelBadge').textContent,/k3/);
 let unknownSaved;const unknownModel='kimi-future-vision';const unknown=harness({handlers:{getAISettings:()=>({provider:'kimi-code',baseUrl:'https://api.kimi.com/coding/v1',model:unknownModel,hasKey:true}),saveAISettings:payload=>{unknownSaved=payload;return {...payload,hasKey:true};}}});await settle();await unknown.el('aiSettingsLink').click();await settle();assert.equal(unknown.el('aiModel').value,'custom');assert.equal(unknown.el('aiCustomModel').value,unknownModel);assert.equal(unknown.el('aiCustomModel').hidden,false);assert.match(unknown.el('aiModelBadge').textContent,/kimi-future-vision/);await unknown.el('saveAISettingsBtn').click();assert.equal(unknownSaved.model,unknownModel);assert.equal(unknownSaved.apiKey,undefined,'saving metadata must preserve the existing secret');assert.equal(unknown.calls.filter(call=>call.action==='generateAI'||call.action==='testAIConnection').length,0);
 // Closing/reusing an old sync plan is explicit; model output never invalidates and executes it silently.
 windows.app.state.plan={token:'old-plan'};windows.el('syncModal').hidden=false;const generationCount=windows.calls.filter(c=>c.action==='generateAI').length;
 await windows.el('generateAIBtn').click();assert.equal(windows.calls.filter(c=>c.action==='generateAI').length,generationCount);assert.match(windows.el('toast').textContent,/关闭同步计划/);
 console.log('AI UI checks passed: explicit credential setup, service/region/model options, one generation per click, minimal visual-only payload, matching progress, cancellation and stale-response rejection, validation, safe library persistence/exports, draft isolation, hardware lock, browser limits and both desktop adapters. No network or device was accessed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
