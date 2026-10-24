/* Offline interaction checks for the shipped UI. No browser, USB or backend process runs. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const root = path.resolve(__dirname, '..');
const webRoot = process.env.STUDIO_TEST_WEB_ROOT ? path.resolve(process.env.STUDIO_TEST_WEB_ROOT) : path.join(root, 'web');
const read = name => fs.readFileSync(path.join(webRoot, name), 'utf8');
const clone = value => JSON.parse(JSON.stringify(value));
const syntheticConfig = require('../data/test-fixtures.cjs');
const syntheticDevice = { productId: 'AM01R6', firmware: 'offline-test-r6', connected: false };

class Classes {
  constructor(el) { this.el = el; }
  get values() { return new Set(this.el.className.split(/\s+/).filter(Boolean)); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) { const values = this.values; const on = force === undefined ? !values.has(name) : !!force; if (on) values.add(name); else values.delete(name); this.el.className = [...values].join(' '); return on; }
  add(...names) { names.forEach(name => this.toggle(name, true)); }
  remove(...names) { names.forEach(name => this.toggle(name, false)); }
}
const dataKey = name => name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const unescape = s => String(s).replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
class Element {
  constructor(tag, attributes = {}) {
    this.tagName = tag.toUpperCase(); this.attributes = {}; this.children = []; this.parent = null;
    this.listeners = {}; this.dataset = {}; this.style = {}; this.className = ''; this.hidden = false; this.disabled = false; this.checked = false;
    this._value = undefined; this._html = ''; this._text = ''; this.classList = new Classes(this);
    Object.entries(attributes).forEach(([key, value]) => this.setAttribute(key, value));
  }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'id') this.id = value; if (name === 'class') this.className = value; if (name.startsWith('data-')) this.dataset[dataKey(name)] = unescape(value); if (name === 'value') this._value = unescape(value); if (name === 'hidden' || name === 'disabled' || name === 'checked') this[name] = true; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  get value() { if (this._value !== undefined) return this._value; if (this.tagName === 'SELECT') { const options = this.querySelectorAll('option'); return (options.find(o => o.attributes.selected !== undefined) || options[0])?.value || ''; } return ''; }
  set value(value) { this._value = String(value); }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value); this._html = String(value); this.children = []; }
  get innerHTML() { return this._html || this.children.map(serialize).join(''); }
  set innerHTML(value) { this._html = String(value); this.children = []; if (this.tagName === 'SELECT') this._value = undefined; parse(this._html, this); }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  append(...children) { children.forEach(child=>this.appendChild(child)); }
  after(child) { if(this.parent){child.parent=this.parent;this.parent.children.splice(this.parent.children.indexOf(this)+1,0,child);} }
  remove() { if(this.parent)this.parent.children.splice(this.parent.children.indexOf(this),1);this.parent=null; }
  removeAttribute(name) { delete this.attributes[name]; }
  closest(selector) { let el=this;while(el){if(matches(el,selector))return el;el=el.parent;}return null; }
  querySelector(selector) { return this.querySelectorAll(selector)[0]||null; }
  insertAdjacentHTML(position, html) { if (position === 'beforeend') { this._html += html; parse(html, this); } else if (position === 'afterend') { parse(html, this.parent); } else throw Error('Unsupported test insertion: ' + position); }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  async click() { if (this.disabled) return; if (this.tagName === 'INPUT' && this.getAttribute('type') === 'checkbox') { this.checked = !this.checked; if (this.onchange) await this.onchange({ target: this }); } if (this.onclick) await this.onclick({ target: this }); for (const callback of this.listeners.click || []) await callback({ target: this }); }
  focus() { let root = this; while (root.parent) root = root.parent; if (root.ownerDocument) root.ownerDocument.activeElement = this; }
  scrollIntoView(options) { this.scrollOptions = options; }
  querySelectorAll(selector) { return descendants(this).filter(el => matches(el, selector)); }
  getContext() { return this.context ||= { fillStyle: '', calls: [], fillRect(...args) { this.calls.push({ fillStyle: this.fillStyle, args }); } }; }
}
function serialize(el) {
  const attributes = Object.entries(el.attributes).map(([name, value]) => ` ${name}="${String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"`).join('');
  return `<${el.tagName.toLowerCase()}${attributes}>${el._html || el.children.map(serialize).join('')}</${el.tagName.toLowerCase()}>`;
}
function descendants(el) { return el.children.flatMap(child => [child, ...descendants(child)]); }
function matches(el, selector) {
  if(selector.includes(','))return selector.split(',').some(part=>matches(el,part.trim()));
  if (selector.startsWith('.')) return el.classList.contains(selector.slice(1));
  if (selector.startsWith('#')) return el.id === selector.slice(1);
  const attribute = /^\[([^=\]]+)(?:=["']?([^"'\]]*)["']?)?\]$/.exec(selector);
  if (attribute) return el.attributes[attribute[1]] !== undefined && (attribute[2] === undefined || el.attributes[attribute[1]] === attribute[2]);
  return el.tagName.toLowerCase() === selector.toLowerCase();
}
function parse(html, parent) {
  const stack = [parent]; const voids = new Set(['input', 'img', 'meta', 'link', 'br', 'hr', 'path']);
  for (const match of html.matchAll(/<(\/?)([\w-]+)([^>]*?)>/g)) {
    const closing = match[1], tag = match[2].toLowerCase();
    if (closing) { const index = stack.map(x => x.tagName.toLowerCase()).lastIndexOf(tag); if (index > 0) stack.length = index; continue; }
    const attributes = {};
    for (const attr of match[3].matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) attributes[attr[1]] = unescape(attr[2] ?? attr[3] ?? attr[4] ?? '');
    const element = new Element(tag, attributes); stack.at(-1).appendChild(element);
    if (!voids.has(tag) && !match[3].endsWith('/')) stack.push(element);
  }
}
async function settle() { for (let i = 0; i < 12; i++) await Promise.resolve(); }
function harness(options = {}) {
  const fixture = syntheticConfig();
  const documentRoot = new Element('document'); parse(read('index.html'), documentRoot);
  const document = { getElementById: id => descendants(documentRoot).find(el => el.id === id) || null,
    querySelector: selector => documentRoot.querySelector(selector),
    querySelectorAll: selector => documentRoot.querySelectorAll(selector), createElement: tag => new Element(tag),
    addEventListener() {} };
  documentRoot.ownerDocument = document;document.documentElement=documentRoot.querySelector('html');
  const calls = [], timers = new Map(); let timerID = 0; let executeReply;
  const control = { importValue: null, detectValue: null, detectError: null, workspace: options.workspace || null, executionResult: options.executionResult || null, planKeymap: null, planPreservation: options.planPreservation || {source:'live',comparedKeycodes:1400,differentFromStored:0,differentPhysicalBindings:0,differentInternalKeycodes:0,refreshApplied:false} };
  const window = { KeyboardPreview: class {
    constructor(container, options) { this.container = container; this.onFrame = options.onFrame; this.design = options.design; this.speedMs = options.design.speed_ms; this.view=options.view||'front';this.playing = true; this.ready = Promise.resolve(this); }
    setDesign(d) { assert.ok(d); this.design = d; return this; }
    setBrightness(v) { this.brightness = v; return this; }
    setSpeed(v) { this.speedMs = v; return this; }
    setView(v) { this.view = v; } setFraming(v) { this.framing = v; } setRenderer(v) { this.renderer = v; } setKeyMode(v) { this.keyMode = v; }
    drawAppearanceThumbnail(canvas, viewId) { (this.thumbnailCalls ||= []).push({ canvas, viewId }); canvas.thumbnailViewId = viewId; return true; }
    pause() { this.playing = false; } play() { this.playing = true; } seek(v) { this.frame = v; }
    destroy() { this.destroyed=true;this.pause(); }
  }};
  const postMessage = message => {
    calls.push(clone(message));
    queueMicrotask(async () => {
      const { id, action, payload } = message; const D = window.STUDIO_DATA; let result;
      if(options.handlers?.[action]){try{result=await options.handlers[action](payload,message);window.StudioBridge.receive({id,result});}catch(error){window.StudioBridge.receive({id,error:{message:error.message,code:error.code,details:error.details}});}return;}
      if (action === 'execute') { executeReply = value => window.StudioBridge.receive({ id, result: value }); return; }
      if (action === 'detect' && control.detectError) { window.StudioBridge.receive({ id, error: typeof control.detectError === 'string' ? { message: control.detectError } : clone(control.detectError) }); return; }
      switch (action) {
        case 'setAppearance': result={theme:payload.theme};break;
        case 'bootstrap': result = { config: options.emptyBaseline ? null : clone(fixture), device: options.emptyBaseline ? clone(D.snapshot) : clone(syntheticDevice), history: [], cliVersion: 'offline-test', workspace: control.workspace }; break;
        case 'keymapCatalog': { const entries=new Map();D.keyLayout.forEach(key=>key.bindings.forEach(binding=>entries.set(binding.code.toUpperCase(),{...binding,token:binding.short,category:'keyboard'})));result={schemaVersion:1,layerCount:7,physicalKeyCount:81,entries:[...entries.values()],modifiers:[]};break;}
        case 'keymap': result={keymap:{...clone(fixture.key_layer),keymapHash:'b'.repeat(64),source:'live'},device:{...syntheticDevice,connected:true}};break;
        case 'getAISettings': result={provider:'kimi-code',baseUrl:'https://api.kimi.com/coding/v1',model:'k3',hasKey:false,credentialStore:'test'}; break;
        case 'saveWorkspace': control.workspace = clone(payload); result = { saved: true }; break;
        case 'detect': result = control.detectValue || { connected: true, device: { ...syntheticDevice, connected: true, port: '/dev/mock-board' }, keymap: clone(fixture.key_layer), config: clone(fixture) }; break;
        case 'importJSON': result = control.importValue; break;
        case 'exportJSON': result = { fileName: payload.fileName, path: '/offline/export.json' }; break;
        case 'history': result = { history: [{ id: 'app:offline.json', snapshotId: 'app:offline.json', filename: 'offline.json', createdAt: '2026-10-12T03:00:00Z' }] }; break;
        case 'plan': case 'restorePlan': { const assignments = payload.assignments || D.designs.slice(0, 3).map((design, i) => ({ slot: i + 1, design, brightness: 100, speedMs: design.speed_ms })); result = { token: 'offline-token', keyChangeCount:0, keymap:control.planKeymap?clone(control.planKeymap):null, keymapPreservation:clone(control.planPreservation), config: window.StudioModel.merge(fixture, assignments), changedSlots: assignments.map(a => a.slot), totalFrames: 9315, estimatedSeconds: 67, summary: assignments.map(a => ({ slot: a.slot, name: a.design.name, topFrames: a.design.frames.length, keyFrames: a.design.keyframes.length })) }; break; }
        default: throw Error('Unexpected mocked request: ' + action);
      }
      window.StudioBridge.receive({ id, result });
    });
  };
  if(options.native !== false) {
    if(options.platform === 'windows') window.StudioNative = { platform: 'windows', postMessage };
    else window.webkit = { messageHandlers: { studio: { postMessage } } };
  }
  const themeCache=new Map(options.themeCache?[['cyberboard-ui-theme',options.themeCache]]:[]);
  const context = { window, document, console, localStorage:{getItem:key=>themeCache.get(key)||null,setItem:(key,value)=>themeCache.set(key,value)}, setTimeout(fn, ms) { const id = ++timerID; timers.set(id, { fn, ms }); return id; }, clearTimeout(id) { timers.delete(id); }, Blob, URL };
  vm.createContext(context); ['theme.js','data.js', 'studio-model.js', 'preview-selector.js', 'ai-client.js', 'library-client.js', 'keymap-client.js', ...(options.chat?['chat-client.js']:[]), 'app.js'].forEach(name => vm.runInContext(name === 'data.js' && options.dataPath ? fs.readFileSync(options.dataPath, 'utf8') : read(name), context, { filename: name }));
  return { window, document, calls, control, get app() { return window.StudioApp; }, el: id => document.getElementById(id),
    async flushSave() { for (const [id, item] of [...timers]) if (item.ms <= 250) { timers.delete(id); await item.fn(); } await settle(); },
    replyExecute(value) { assert.ok(executeReply, 'execute must have an explicit click'); executeReply(value); executeReply = null; } };
}

module.exports={harness,settle,clone,syntheticConfig,syntheticDevice};
if(require.main===module)(async () => {
  const h = harness({platform: process.env.STUDIO_UI_PLATFORM}); await settle(); const state = h.app.state, builtinCount = h.window.STUDIO_DATA.designs.length;
  assert.equal(h.window.STUDIO_DATA.baseConfig, null, 'production data never includes the test fixture or a device baseline');
  assert.equal(state.config._fixture, true, 'the mocked backend alone supplies synthetic configuration');
  assert.equal(state.workspaceLoaded, true); assert.equal(state.designs.length, builtinCount); assert.equal(state.pending.size, 0);
  assert.equal(state.page, 'create', 'AI creation opens as the home page');
  assert.ok(h.el('page-create').classList.contains('active'), 'the initial page must match the startup state');
  assert.equal(h.calls.filter(c => c.action === 'execute').length, 0, 'startup must never write');
  const formalLogo = 'assets/branding/product-icon/cyberboard-studio-approved-am-paw-v10.png';
  assert.equal(h.el('brandMark').querySelectorAll('img').length, 1, 'the approved PNG remains the sidebar mark');
  assert.equal(h.el('brandMark').querySelectorAll('img')[0].getAttribute('src'), formalLogo);
  assert.ok(h.el('brandMark').classList.contains('brand-official-mark'));
  for (const id of ['page-branding','brandReviewBtn','settingsBrandBtn','logoGrid']) assert.equal(h.el(id), null, 'temporary logo review is removed from the product');
  assert.equal(h.window.StudioBrandReview, undefined);assert.equal(h.document.querySelectorAll('.name-editor')[0].hidden,true,'fixed built-in names do not occupy the parameter editor');
  for (const id of ['inspectorParametersTab','inspectorAITab','inspectorParametersPanel','inspectorAIPanel']) assert.equal(h.el(id), null, 'AI creation remains visible on the workbench');
  assert.equal(h.document.querySelectorAll('.creation-chat').length,1,'AI creation has a standalone page');
  assert.equal(h.el('syncSingleBtn').disabled, true,'an offline keyboard cannot receive a draft');
  assert.equal(h.el('syncBtn').hidden, true,'the all-drafts action is reserved for multiple drafts');
  const initialLighting = JSON.stringify({selected:state.selected,brightness:state.brightness,speedMs:state.speedMs,pending:[...state.pending]});
  await h.document.querySelectorAll('[data-target-slot]').find(b=>b.dataset.targetSlot==='2').click();
  assert.equal(state.targetSlot,2);assert.equal(h.el('targetSlotLabel').textContent,'目标槽位 02');
  assert.equal(JSON.stringify({selected:state.selected,brightness:state.brightness,speedMs:state.speedMs,pending:[...state.pending]}),initialLighting,'choosing a target must not replace the preview or reset its parameters');
  assert.equal(h.document.querySelectorAll('[data-target-slot]').filter(b=>b.getAttribute('aria-pressed')==='true').length,1);
  await h.document.querySelectorAll('[data-preview-slot]').find(b=>b.dataset.previewSlot==='2').click();
  assert.equal(state.selected.id,state.slots[1].design.id,'only the separate preview action loads a slot work');
  assert.equal(state.brightness,state.slots[1].brightness);assert.equal(state.speedMs,state.slots[1].speedMs);assert.equal(state.pending.size,0);
  h.el('designSelect').value=h.window.STUDIO_DATA.designs[0].id;h.el('designSelect').onchange({target:h.el('designSelect')});
  for (const page of ['library', 'models', 'device', 'keymap', 'history', 'settings', 'workbench']) {
    const button = h.document.querySelectorAll('[data-page]').find(x => x.dataset.page === page); await button.click(); await settle();
    assert.equal(state.page, page, 'navigation: ' + page); assert.ok(h.el('page-' + page).classList.contains('active'));
    assert.equal(h.document.querySelectorAll('.page').filter(p => p.classList.contains('active')).length, 1);
  }
  h.app.navigate('library'); h.el('librarySearch').value = '数据暴雨'; h.el('librarySearch').oninput();
  assert.equal(h.document.querySelectorAll('[data-preview-design]').length, 1); assert.match(h.el('libraryCount').textContent, /^1 /);
  h.el('librarySearch').value = '不存在的作品'; h.el('librarySearch').oninput(); assert.match(h.el('libraryGrid').innerHTML, /没有匹配/);
  h.app.navigate('workbench'); h.el('brightness').value = '64'; h.el('brightness').oninput({ target: h.el('brightness') }); h.el('speed').value = '53'; h.el('speed').oninput({ target: h.el('speed') });
  await h.document.querySelectorAll('[data-target-slot]').find(b => b.dataset.targetSlot === '2').click(); await h.el('assignBtn').click();
  assert.equal(state.pending.get(2).brightness, 64); assert.equal(state.pending.get(2).speedMs, 53); assert.equal(h.app.preview.brightness, 64); assert.equal(h.el('syncSingleBtn').disabled, true);assert.equal(h.el('syncBtn').hidden, true);assert.equal(h.el('assignBtn').textContent,'更新槽位 02 草稿');assert.match(h.el('targetSlotContents').textContent,/待同步/);
  await h.flushSave(); const saved = clone(h.control.workspace); assert.equal(saved.pending[0].slot, 2); assert.equal(saved.pending[0].brightness, 64);
  await h.app.exportJSON(); const exported = h.calls.filter(c => c.action === 'exportJSON').at(-1).payload.json;
  assert.equal(exported.preview_brightness, 64); assert.equal(exported.speed_ms, 53);
  h.control.importValue = { fileName: 'reimport.json', json: { ...exported, id: 'offline-import', name: '离线导入作品' } };
  await h.app.importJSON(); assert.equal(state.selected.id, 'offline-import'); assert.equal(state.brightness, 64); assert.equal(state.speedMs, 53); assert.equal(state.designs.length, builtinCount + 1);assert.equal(h.document.querySelectorAll('.name-editor')[0].hidden,false,'imported works expose the existing validated name editor');
  await h.flushSave(); assert.equal(h.control.workspace.designs.length, 1);
  const restored = harness({ workspace: clone(h.control.workspace) }); await settle();
  assert.equal(restored.app.state.designs.length, builtinCount + 1); assert.equal(restored.app.state.pending.get(2).brightness, 64); assert.equal(restored.app.state.selected.id, 'offline-import'); assert.equal(restored.app.state.brightness, 64);
  h.app.navigate('keymap'); assert.equal(h.document.querySelectorAll('[data-key]').length, 81); assert.equal(h.document.querySelectorAll('[data-layer]').length, 7);
  for (const button of h.document.querySelectorAll('[data-layer]')) { await button.click(); assert.equal(h.document.querySelectorAll('[data-key]').length, 81); }
  await h.document.querySelectorAll('[data-key]')[0].click(); assert.match(h.el('bindingPanel').innerHTML, /矩阵/);
  await h.el('detectBtn').click(); assert.equal(state.device.connected, true); assert.ok(state.keymap); assert.match(h.el('keymapSource').textContent, /实时/);
  await h.flushSave();
  const retainedWork = () => JSON.stringify({designs:state.designs,selected:state.selected,brightness:state.brightness,speedMs:state.speedMs,targetSlot:state.targetSlot,pending:[...state.pending],slots:state.slots,config:state.config});
  const workBeforeTimeout = retainedWork(), workspaceBeforeTimeout = JSON.stringify(h.control.workspace);
  h.control.detectError = {code:'serial_keymap_failed',message:'COM12 键位查询通信超时。请关闭其他键盘配置软件，重新连接后再检查。',details:{port:'COM12',stage:'keymap',kind:'timeout',reason:'Write timeout'}};
  await h.el('detectBtn').click();
  assert.equal(state.device.connected, false); assert.equal(state.keymap, null); assert.doesNotMatch(h.el('keymapSource').textContent, /实时/);
  assert.equal(h.el('toast').textContent, h.control.detectError.message, 'structured transport failures display the friendly message without raw JSON');
  assert.equal(retainedWork(), workBeforeTimeout, 'failed detection preserves cached configuration, preview parameters, works and slot drafts');
  await h.flushSave();assert.equal(JSON.stringify(h.control.workspace), workspaceBeforeTimeout, 'failed detection does not replace the saved workspace');
  assert.equal(h.el('syncSingleBtn').disabled, true);assert.equal(h.el('detectBtn').disabled, false);
  h.control.detectError = null; h.control.detectValue = { connected: true, device: { productId: 'CB04', firmware: 'offline-r4', port: '/dev/mock-r4' }, keymap: syntheticConfig().key_layer, config: null };
  await h.el('detectBtn').click(); assert.equal(state.config, null); assert.equal(state.baselineMissing, true); assert.ok(state.slots.every(s => s.design === null));
  h.control.detectValue = null; await h.el('detectBtn').click();
  const beforePlan = h.calls.length; await h.el('syncSingleBtn').click();
  assert.equal(h.el('syncModal').hidden, false); assert.equal(state.plan.token, 'offline-token'); assert.equal(h.el('executeBtn').disabled, false);
  assert.equal(h.calls.slice(beforePlan).filter(c => c.action === 'plan').length, 1); assert.equal(h.calls.filter(c => c.action === 'execute').length, 0, 'planning must not execute');
  await h.el('cancelSyncBtn').click(); assert.equal(state.plan, null); assert.equal(h.el('syncModal').hidden, true);
  await h.el('syncSingleBtn').click(); const executing = h.el('executeBtn').click(); await settle();
  assert.equal(state.executing, true); assert.equal(h.el('cancelSyncBtn').disabled, true); h.app.navigate('library'); assert.notEqual(state.page, 'library');
  for (const [stage, expected] of [['starting', '开始传输'], ['page_control', '传输完整配置'], ['committing', '等待设备提交'], ['verifying', '读取键位并验证']]) {
    h.window.StudioBridge.event({ event: 'progress', stage, transferred: 4660, total: 9315 }); assert.equal(h.el('syncStage').textContent, expected);
  }
  h.replyExecute({ success: true, deviceAck: true, keymapMatch: true, stateStored: false, warning: '离线测试保存警告', changedSlots: [2], device: { ...syntheticDevice, connected: true } }); await executing;
  assert.equal(state.executing, false); assert.equal(state.pending.size, 0); await h.flushSave(); assert.equal(h.control.workspace.pending.length,0,'successful USB sync must persist cleared drafts after execution releases its lock'); assert.match(h.el('syncContent').innerHTML, /本机记录或报告保存未完成/); assert.match(h.el('globalStatus').textContent, /本机记录或报告保存未完成/);
  assert.equal(h.calls.filter(c => c.action === 'execute').length, 1, 'only explicit execution writes');
  const fresh = harness({platform:'windows', emptyBaseline:true, dataPath:process.env.STUDIO_PACKED_DATA}); await settle();
  assert.equal(fresh.app.state.config, null); assert.equal(fresh.app.state.baselineMissing, true);
  assert.ok(fresh.app.state.slots.every(slot => slot.design === null));
  assert.match(fresh.el('keymapSource').textContent, /缺少本机键位记录/);
  assert.match(fresh.el('slotsSource').textContent, /暂无同步记录/);
  assert.equal(fresh.window.webkit, undefined, 'Windows must not depend on the macOS bridge');
  assert.equal(fresh.document.querySelectorAll('[data-key]').length, 81);
  assert.doesNotMatch(fresh.el('keyGrid').innerHTML, /#00000000/, 'unread keys display physical labels instead of fake zero bindings');
  assert.deepEqual(fresh.calls.map(c => c.action), ['bootstrap','setAppearance'], 'fresh Windows launch only bootstraps and applies appearance; no USB actions');
  fresh.el('exportFormat').value='config'; await fresh.app.exportJSON();
  assert.match(fresh.el('toast').textContent, /缺少完整配置基线/);
  assert.equal(fresh.calls.filter(c=>c.action==='exportJSON').length,0);
  const browser = harness({ native: false }); await settle(); assert.match(browser.el('globalStatus').textContent, /界面预览模式/); assert.equal(browser.calls.length, 0);
  console.log('UI checks passed: approved sidebar PNG, removed logo review, always-visible AI creation, target-only slot cards and separate preview, navigation, library, assignments, JSON round-trip, persistence, 81×7 keymap, disconnect, missing baseline, plan-only flow, real stage labels and store warnings. No device was accessed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
