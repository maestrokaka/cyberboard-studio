(function(global){
 'use strict';
 function create({$,api,native,toast}){
  if(!native||global.StudioNative?.capabilities?.codexSetup!==true)return null;
  const root=document.createElement('section');root.className='settings-card codex-setup';
  root.innerHTML='<div class="label-row"><h2>连接本机 Codex</h2><span class="badge">Windows 原生</span></div><p class="companion-note">首次使用：安装 → 登录 → 检测连接。无需 Node.js、WSL 或复制登录文件。已有官方 CLI 登录可直接复用。</p><ol class="codex-setup-steps"><li>安装官方 Codex CLI</li><li>在浏览器登录 ChatGPT</li><li>检测后交代任务</li></ol><p id="codexSetupStatus" role="status">先检测本机是否已安装和登录。</p><div class="miaocall-actions"><button class="button" id="codexInstall">安装 Codex</button><button class="button" id="codexLogin">登录</button><button class="button primary" id="codexCheck">检测连接</button><button class="button" id="codexChoose">手动选择</button></div><button class="text-button" id="codexCopyInstall">复制官方安装命令</button><p class="companion-note">首次运行命令时，Windows 隔离环境可能需要官方初始化。按系统提示确认；软件不会关闭隔离或静默提升权限。</p>';
  document.querySelector('.miaocall-setup').prepend(root);
  let pending=false,busy=false;
  function render(){for(const id of ['codexInstall','codexLogin','codexCheck','codexChoose'])$(id).disabled=pending||busy;}
  async function run(action){if(pending||busy)return;pending=true;render();$('codexSetupStatus').textContent='正在处理，请完成系统或浏览器中的提示…';try{const r=await api(action);$('codexSetupStatus').textContent=r.cancelled?'本次已取消。':r.message||(action==='miaoCallCodexChoose'?'已选择 Codex，请检测连接。':'操作已完成。');root.dataset.connected=String(r.authenticated===true&&r.protocolReady===true);}catch(e){$('codexSetupStatus').textContent=e.message||'连接未完成，请重试。';}finally{pending=false;render();}}
  $('codexInstall').onclick=()=>run('miaoCallCodexInstall');$('codexLogin').onclick=()=>run('miaoCallCodexLogin');$('codexCheck').onclick=()=>run('miaoCallCodexCheck');$('codexChoose').onclick=()=>run('miaoCallCodexChoose');
  $('codexCopyInstall').onclick=()=>api('miaoCallCodexCopyInstall').then(()=>toast('已复制 OpenAI 官方安装命令，在 PowerShell 中运行即可。')).catch(e=>toast(e.message));
  return{update(value){busy=['configuring','preparing','listening','transcribing','awaitingConfirmation','connecting','thinking','acting','awaitingApproval','awaitingInput','cancelling'].includes(value.state);render();},event(value){if(value.type==='codexLogin')$('codexSetupStatus').textContent='请在官方浏览器登录页完成登录；无需在本软件填写密码。';}};
 }
 global.StudioCodexSetup={create};
})(window);
