/* MiaoCall's real UI controller, synthetic bridge only: no mic, agent, capture or USB. */
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert/strict');
const { harness, settle, clone } = require('./ui-check.cjs');
const webRoot = process.env.STUDIO_TEST_WEB_ROOT ? path.resolve(process.env.STUDIO_TEST_WEB_ROOT) : path.join(__dirname, '../web');
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

async function fixture({ native = true, handlers = {} } = {}) {
  const h = harness(); await settle();
  const calls = [], state = h.app.state;
  const spotify = h.document.createElement('input'); spotify.id = 'miaoUseSpotify'; spotify.checked = true; h.document.documentElement.appendChild(spotify);
  const sandbox = { window: h.window, document: h.document, console, Date, Promise };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(webRoot, 'miaocall.js'), 'utf8'), sandbox, { filename: 'miaocall.js' });
  const controller = h.window.StudioMiaoCall.create({
    $: h.el, native, state, navigate: page => { state.page = page; }, toast: text => { h.el('toast').textContent = text; }, onBusy() {},
    api(action, payload = {}) {
      calls.push({ action, payload: clone(payload) });
      if (handlers[action]) return handlers[action](payload);
      if (action === 'miaoCallStatus') return Promise.resolve({ enabled: false, state: 'idle', transcript: '', message: '' });
      if (action === 'miaoCallCancel') return Promise.resolve({ enabled: false, state: 'cancelled', message: '已取消' });
      if (action === 'miaoCallStopRecording') return Promise.resolve({ enabled: false, state: 'transcribing', message: '正在识别' });
      if (action === 'miaoCallEnable') return Promise.resolve({ enabled: true, state: 'idle' });
      if (action === 'miaoCallDisable') return Promise.resolve({ enabled: false, state: 'idle' });
      throw Error('Unexpected mocked MiaoCall action: ' + action);
    }
  });
  const event = (phase, fields = {}) => controller.event({ event: 'miaoCall', type: 'state', state: phase, ...fields });
  const down = () => h.el('miaoHoldBtn').onpointerdown({ button: 0, pointerId: 7, preventDefault() {}, currentTarget: h.el('miaoHoldBtn') });
  const up = () => h.el('miaoHoldBtn').onpointerup();
  return { h, calls, controller, state, event, down, up };
}

const cases = [];

const test = (name, body) => cases.push([name, body]);

test('starts off, reads status only, and does not create global or microphone actions', async () => {
  const f = await fixture();
  assert.equal(f.controller.status.enabled, false);
  assert.equal(f.h.el('miaoCallToggle').checked, false);
  assert.equal(f.state.miaoCallBusy, false);
  assert.deepEqual(f.calls, []);
  await f.controller.load();
  assert.deepEqual(f.calls.map(x => x.action), ['miaoCallStatus']);
  assert.equal(f.controller.status.enabled, false);
  assert.equal(f.h.el('miaoConfirm').checked, true, 'default requires transcript confirmation');
  await f.h.el('miaoCallToggle').click();
  assert.equal(f.controller.status.enabled, true);
  assert.equal(f.calls.at(-1).action, 'miaoCallEnable');
  assert.equal(f.calls.at(-1).payload.confirmBeforeSend, true);
  assert.equal(f.calls.at(-1).payload.tracks[0].title, '晴天');
  assert.equal(f.calls.filter(x => x.action === 'miaoCallStartRecording').length, 0);
  await f.h.el('miaoCallToggle').click();
  assert.equal(f.controller.status.enabled, false);
  assert.equal(f.calls.at(-1).action, 'miaoCallDisable');
});

test('browser preview never invokes native actions', async () => {
  const f = await fixture({ native: false });
  await f.controller.load(); f.down(); await settle();
  assert.deepEqual(f.calls, []);
  assert.equal(f.h.el('miaoCallToggle').disabled, true);
  assert.equal(f.h.el('miaoHoldBtn').disabled, true);
  assert.equal(f.controller.status.enabled, false);
});

test('early key release is retained through a delayed start acknowledgement', async () => {
  const start = deferred();
  const f = await fixture({ handlers: { miaoCallStartRecording: () => start.promise } });
  f.down(); f.down(); await settle();
  assert.equal(f.calls.filter(x => x.action === 'miaoCallStartRecording').length, 1);
  await f.up();
  start.resolve({ state: 'preparing', enabled: false }); await settle();
  assert.equal(f.calls.filter(x => x.action === 'miaoCallStopRecording').length, 1,
    'releasing before the start acknowledgement must still reach the native preparation state');
  assert.equal(f.controller.status.state, 'transcribing');
  assert.equal(f.calls.filter(x => x.action === 'miaoCallSubmit').length, 0);
});

test('a native state event is not overwritten by an earlier status reply', async () => {
  const status = deferred();
  const f = await fixture({ handlers: { miaoCallStatus: () => status.promise } });
  const pending = f.controller.load(); await settle();
  f.event('thinking', { enabled: true, message: 'Codex 正在处理' });
  status.resolve({ enabled: false, state: 'idle', message: '旧状态' }); await pending;
  assert.equal(f.controller.status.state, 'thinking');
  assert.equal(f.controller.status.enabled, true);
  assert.equal(f.state.miaoCallBusy, true);
  assert.equal(f.h.el('miaoStateMessage').textContent, 'Codex 正在处理');
});

test('cancel can interrupt pending start and its late success cannot resume recording UI', async () => {
  const start = deferred();
  const f = await fixture({ handlers: { miaoCallStartRecording: () => start.promise } });
  f.down(); await settle(); f.event('preparing');
  await f.controller.cancel();
  assert.equal(f.controller.status.state, 'cancelled');
  assert.equal(f.state.miaoCallBusy, false);
  start.resolve({ enabled: true, state: 'listening', message: '旧录音' }); await settle();
  assert.equal(f.controller.status.state, 'cancelled');
  assert.equal(f.state.miaoCallBusy, false);
  assert.equal(f.calls.filter(x => x.action === 'miaoCallStopRecording').length, 0);
});

test('a stale failed status read cannot replace an acknowledged cancellation', async () => {
  const status = deferred();
  const f = await fixture({ handlers: { miaoCallStatus: () => status.promise } });
  const pending = f.controller.load(); await settle(); f.event('thinking');
  await f.controller.cancel(); status.reject(Error('旧读取超时')); await pending;
  assert.equal(f.controller.status.state, 'cancelled');
  assert.equal(f.h.el('miaoStateMessage').textContent, '已取消');
  assert.equal(f.state.miaoCallBusy, false);
});

test('a stale failed start cannot replace a newer native error or restart after release', async () => {
  const start = deferred();
  const f = await fixture({ handlers: { miaoCallStartRecording: () => start.promise } });
  f.down(); await settle();
  f.event('error', { message: '麦克风权限未开启' });
  start.reject(Error('旧录音请求失败')); await settle();
  assert.equal(f.controller.status.state, 'error');
  assert.equal(f.h.el('miaoStateMessage').textContent, '麦克风权限未开启');
  assert.equal(f.state.miaoCallBusy, false);
});

test('all active and terminal phases have consistent confirmation and busy boundaries', async () => {
  const f = await fixture();
  for (const phase of ['configuring', 'preparing', 'listening', 'transcribing', 'connecting', 'thinking', 'acting']) {
    f.event(phase);
    assert.equal(f.state.miaoCallBusy, true, phase);
    assert.equal(f.h.el('miaoCancelBtn').hidden, false, phase);
    assert.equal(f.h.el('miaoConfirmBox').hidden, true, phase);
    assert.equal(f.h.el('miaoSubmitBtn').disabled, true, phase);
    assert.equal(f.h.el('miaoCallToggle').disabled, true, phase);
  }
  f.event('awaitingConfirmation', { transcript: '打开 Spotify，播放周杰伦的晴天。' });
  assert.equal(f.state.miaoCallBusy, true);
  assert.equal(f.h.el('miaoConfirmBox').hidden, false);
  assert.equal(f.h.el('miaoTranscript').value, '打开 Spotify，播放周杰伦的晴天。');
  assert.equal(f.h.el('miaoSubmitBtn').disabled, false);
  assert.equal(f.calls.length, 0, 'receiving ASR text never submits the Codex task automatically');
  for (const phase of ['completed', 'cancelled', 'error', 'idle']) {
    f.event(phase);
    assert.equal(f.state.miaoCallBusy, false, phase);
    assert.equal(f.h.el('miaoCancelBtn').hidden, true, phase);
    assert.equal(f.h.el('miaoConfirmBox').hidden, true, phase);
    assert.equal(f.h.el('miaoSubmitBtn').disabled, true, phase);
    assert.equal(f.h.el('miaoCallToggle').disabled, false, phase);
  }
});

test('confirmation preserves edits and sends only the explicitly confirmed text', async () => {
  const f = await fixture({ handlers: { miaoCallSubmit: () => Promise.resolve({ state: 'connecting' }) } });
  f.event('awaitingConfirmation', { transcript: '原始识别文字' });
  f.h.document.activeElement = f.h.el('miaoTranscript');
  f.h.el('miaoTranscript').value = '请播放周杰伦的晴天。';
  f.event('awaitingConfirmation', { message: '仍等待确认' });
  assert.equal(f.h.el('miaoTranscript').value, '请播放周杰伦的晴天。');
  assert.equal(f.calls.length, 0);
  await f.h.el('miaoSubmitBtn').click();
  assert.deepEqual(f.calls, [{ action: 'miaoCallSubmit', payload: { text: '请播放周杰伦的晴天。' } }]);
  assert.equal(f.controller.status.state, 'connecting');
});

test('edited shortcut settings require Apply and send the exact current song and confirmation choice', async () => {
  const f = await fixture();
  assert.equal(f.h.el('miaoApplySettings').disabled, true, 'off means no live shortcut settings to apply');
  f.event('idle', { enabled: true });
  f.h.el('miaoTrackTitle').value = '新的歌曲';
  f.h.el('miaoTrackArtist').value = '新的歌手';
  f.h.el('miaoTrackLink').value = 'https://open.spotify.com/track/0123456789ABCDEFGHIJKL?si=public-fixture';
  f.h.el('miaoConfirm').checked = false;
  f.h.el('miaoTrackTitle').onchange();
  assert.equal(f.calls.length, 0, 'editing options does not reconfigure the global shortcut itself');
  assert.match(f.h.el('miaoSettingsNote').textContent, /设置已修改.*应用到快捷键/);
  assert.equal(f.h.el('miaoTrackSummary').textContent, '新的歌曲 · 新的歌手');
  assert.equal(f.h.el('miaoApplySettings').disabled, false);
  await f.h.el('miaoApplySettings').click();
  assert.deepEqual(f.calls, [{ action: 'miaoCallEnable', payload: {
    confirmBeforeSend: false,
    tracks: [{ uri: 'spotify:track:0123456789ABCDEFGHIJKL', title: '新的歌曲', artist: '新的歌手' }]
  } }]);
  assert.equal(f.controller.status.enabled, true);
  assert.equal(f.h.el('miaoSettingsNote').textContent, '当前设置已用于物理快捷键。');
  assert.equal(f.calls.filter(x => x.action === 'miaoCallStartRecording' || x.action === 'miaoCallSubmit').length, 0);
});

test('Apply stays disabled during an update, every active phase, confirmation, and browser preview', async () => {
  const applying = deferred();
  const f = await fixture({ handlers: { miaoCallEnable: () => applying.promise } });
  f.event('idle', { enabled: true });
  const pending = f.h.el('miaoApplySettings').click(); await settle();
  assert.equal(f.h.el('miaoApplySettings').disabled, true);
  assert.equal(f.h.el('miaoTrackTitle').disabled, true);
  await f.h.el('miaoApplySettings').click();
  assert.equal(f.calls.length, 1, 'a pending application cannot be submitted twice');
  applying.resolve({ enabled: true, state: 'idle' }); await pending;
  assert.equal(f.h.el('miaoApplySettings').disabled, false);
  for (const phase of ['configuring', 'preparing', 'listening', 'transcribing', 'connecting', 'thinking', 'acting', 'awaitingConfirmation']) {
    f.event(phase);
    assert.equal(f.h.el('miaoApplySettings').disabled, true, phase);
    await f.h.el('miaoApplySettings').click();
  }
  assert.equal(f.calls.length, 1, 'active tasks keep the previously applied catalog immutable');
  const browser = await fixture({ native: false });
  assert.equal(browser.h.el('miaoApplySettings').disabled, true);
  await browser.h.el('miaoApplySettings').click();
  assert.deepEqual(browser.calls, []);
});

test('Apply validates a changed song before native configuration and preserves the unapplied warning', async () => {
  const f = await fixture();
  f.event('idle', { enabled: true });
  f.h.el('miaoTrackLink').value = 'spotify:album:0123456789ABCDEFGHIJKL';
  f.h.el('miaoTrackLink').onchange();
  await f.h.el('miaoApplySettings').click();
  assert.deepEqual(f.calls, []);
  assert.match(f.h.el('toast').textContent, /填写歌曲名称、歌手和 Spotify 歌曲链接/);
  assert.match(f.h.el('miaoSettingsNote').textContent, /设置已修改/);
  assert.equal(f.controller.status.enabled, true);
});

test('confirmation rejects blank or over-2000 text locally and retains the editable instruction', async () => {
  const f = await fixture({ handlers: { miaoCallSubmit: () => Promise.resolve({ state: 'connecting' }) } });
  f.event('awaitingConfirmation', { transcript: '原始识别文字' });
  for (const text of ['', '  \n\t  ', '字'.repeat(2001)]) {
    f.h.el('miaoTranscript').value = text;
    await f.h.el('miaoSubmitBtn').click();
    assert.deepEqual(f.calls, [], 'invalid text never starts a Codex worker');
    assert.equal(f.h.el('toast').textContent, '请填写 1–2000 字的指令。');
    assert.equal(f.h.el('miaoTranscript').value, text, 'validation never discards the editable draft');
    assert.equal(f.controller.status.state, 'awaitingConfirmation');
    assert.equal(f.h.el('miaoConfirmBox').hidden, false);
    assert.equal(f.state.miaoCallBusy, true);
  }
  const maximum = '字'.repeat(2000);
  f.h.el('miaoTranscript').value = '  ' + maximum + '\n';
  await f.h.el('miaoSubmitBtn').click();
  assert.deepEqual(f.calls, [{ action: 'miaoCallSubmit', payload: { text: maximum } }], 'the 2000-character trimmed boundary is accepted');
  assert.equal(f.controller.status.state, 'connecting');
});

test('an active global task cannot import, change the draft slot, or navigate into another operation', async () => {
  const f = await fixture();
  const before = JSON.stringify({ designs: f.state.designs, pending: [...f.state.pending], targetSlot: f.state.targetSlot, page: f.state.page });
  const existingCalls = f.h.calls.length;
  f.event('thinking', { enabled: true });
  await f.h.app.importJSON();
  f.h.app.navigate('models');
  await f.h.el('assignBtn').click();
  assert.equal(JSON.stringify({ designs: f.state.designs, pending: [...f.state.pending], targetSlot: f.state.targetSlot, page: f.state.page }), before);
  assert.equal(f.h.calls.length, existingCalls, 'task guards must stop native import, USB and workspace mutations');
});

test('a running task can open its own detail page for approvals', async () => {
  const f=await fixture(); f.state.miaoCallBusy=true;
  f.h.app.navigate('miaocall'); assert.equal(f.state.page,'miaocall');
  f.h.app.navigate('workbench'); assert.equal(f.state.page,'miaocall');
});

test('track validation accepts only exact Spotify track links and does not alter the keyboard', async () => {
  const f = await fixture();
  assert.equal(f.h.window.StudioMiaoCall.track('https://open.spotify.com/track/5pIcwtJYNJx93l420oR2Vm?si=example', '晴天', '周杰倫').uri,
    'spotify:track:5pIcwtJYNJx93l420oR2Vm');
  for (const link of ['https://untrusted.example/track/5pIcwtJYNJx93l420oR2Vm', 'spotify:album:5pIcwtJYNJx93l420oR2Vm', 'spotify:track:not-valid']) {
    assert.throws(() => f.h.window.StudioMiaoCall.track(link, '晴天', '周杰倫'));
  }
  assert.deepEqual(f.calls, []);
});

(async () => {
  let failures = 0;
  for (const [name, body] of cases) {
    try { await body(); console.log('PASS ' + name); }
    catch (error) { failures++; console.error('FAIL ' + name + '\n' + error.stack); }
  }
  if (failures) process.exitCode = 1;
  else console.log('MiaoCall UI checks passed: ' + cases.length + ' cases. No microphone, native agent, playback, screen capture or USB accessed.');
})();
