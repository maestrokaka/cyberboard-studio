/* Shipped setup controller, synthetic native bridge. No installer/login/network. */
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert/strict');
const {harness,settle}=require('./ui-check.cjs');
const web=process.env.STUDIO_TEST_WEB_ROOT||path.join(__dirname,'../web');
(async()=>{
 const h=harness();await settle();const calls=[],notices=[];let resolve,fail=false;
 const sandbox={window:h.window,document:h.document,console};vm.createContext(sandbox);
 vm.runInContext(fs.readFileSync(path.join(web,'codex-setup.js'),'utf8'),sandbox);
 const options={$:h.el,native:true,toast:m=>notices.push(m),api:async(action)=>{calls.push(action);if(action==='miaoCallCodexCheck')return new Promise(r=>resolve=r);if(fail)throw Error('连接暂不可用');return {message:'已处理'};}};
 assert.equal(h.window.StudioCodexSetup.create(options),null,'Mac must not get Windows installer');
 h.window.StudioNative={platform:'windows',capabilities:{codexSetup:true}};
 const ui=h.window.StudioCodexSetup.create(options);assert(ui);assert.equal(calls.length,0,'Creating UI must not install or sign in');
 const first=h.el('codexCheck').click();await settle();assert.equal(h.el('codexLogin').disabled,true);
 await h.el('codexCheck').click();assert.equal(calls.length,1,'No duplicate request');
 ui.event({type:'codexLogin'});assert.match(h.el('codexSetupStatus').textContent,/官方浏览器/);
 resolve({authenticated:true,protocolReady:true,message:'Codex 已连接'});await first;
 assert.equal(h.document.querySelector('.codex-setup').dataset.connected,'true');
 ui.update({state:'acting'});await h.el('codexInstall').click();assert.equal(calls.length,1,'Busy tasks block setup');
 ui.update({state:'idle'});await h.el('codexInstall').click();assert.equal(calls.at(-1),'miaoCallCodexInstall');
 fail=true;await h.el('codexLogin').click();assert.match(h.el('codexSetupStatus').textContent,/暂不可用/);assert.equal(h.el('codexCheck').disabled,false);
 fail=false;await h.el('codexCopyInstall').click();assert.equal(calls.at(-1),'miaoCallCodexCopyInstall');assert.equal(notices.length,1);
 console.log('PASS Windows-only explicit setup, no automatic side effects, request deduplication, busy gating, official login status and recovery');
})().catch(e=>{console.error(e);process.exitCode=1});
