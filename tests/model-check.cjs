const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const crypto = require('crypto');

const workspace = path.resolve(__dirname, '..');
const read = relative => JSON.parse(fs.readFileSync(path.join(workspace, relative), 'utf8'));
const copy = value => JSON.parse(JSON.stringify(value));
const digest = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
const source = fs.readFileSync(path.join(__dirname, '../web/studio-model.js'), 'utf8');
const context = { window: {} };
vm.createContext(context);
vm.runInContext(source, context);
const model = context.window.StudioModel;
const reserved = [57, 61, 74, 78, 82, 83, 84];
const designs = [
  read('data/designs/neon-rift.design.json'),
  read('data/designs/data-storm.design.json'),
  read('data/designs/redline-rush.design.json')
];
const config = require('../data/test-fixtures.cjs')();
assert.equal(config._fixture, true);
const channels = color => [1, 3, 5].map(at => parseInt(color.slice(at, at + 2), 16));

for (const design of designs) {
  const before = digest(design);
  assert.equal(model.validate(design), design);
  assert.equal(design.frames.length, 192);
  assert.equal(design.keyframes.length, 192);
  for (const palette of ['cyan', 'acid', 'red', 'amber']) {
    const variant = model.variant(design, palette, 75, '测试');
    assert.notEqual(variant, design);
    assert.equal(variant.speed_ms, 75);
    assert.equal(variant.origin, 'template-variant');
    assert.equal(variant.frames.length, design.frames.length);
    assert.equal(variant.keyframes.length, design.keyframes.length);
    assert.equal(model.validate(variant), variant);
    for (const field of ['frames', 'keyframes']) {
      for (let frame = 0; frame < design[field].length; frame++) {
        for (let lamp = 0; lamp < design[field][frame].length; lamp++) {
          const original = channels(design[field][frame][lamp]);
          const changed = channels(variant[field][frame][lamp]);
          assert.equal(Math.max(...changed), Math.max(...original), 'palette rotation must retain peak channel brightness');
          assert.equal(Math.min(...changed), Math.min(...original), 'palette rotation must retain black level');
          if (field === 'keyframes' && reserved.includes(lamp)) assert.equal(variant[field][frame][lamp], '#000000');
        }
      }
    }
    variant.frames[0][0] = '#123456';
    assert.equal(digest(design), before, 'variant editing must never mutate the original design');
  }
}

const imported = model.importDesigns(config);
assert.equal(imported.length, 3);
for (let slot = 1; slot <= 3; slot++) {
  const design = imported[slot - 1];
  const page = config.page_data.find(page => page.page_index === slot + 4);
  assert.deepEqual(copy(design.frames), page.frames.frame_data.map(frame => frame.frame_RGB));
  assert.deepEqual(copy(design.keyframes), page.keyframes.frame_data.map(frame => frame.frame_RGB));
  assert.equal(design.speed_ms, page.speed_ms);
  for (const unsafe of ['page_data', 'key_layer', 'keymap', 'device', 'VID', 'PID', 'word_page']) {
    assert.ok(!(unsafe in design), 'full-config imports must expose lighting designs only: ' + unsafe);
  }
}
const beforeImportEdit = digest(config);
imported[0].frames[0][0] = '#ABCDEF';
imported[0].keyframes[0][0] = '#123456';
assert.equal(digest(config), beforeImportEdit, 'imported animations must not retain mutable references to the configuration baseline');
const standalone = model.importDesigns(designs[0], 'test.json')[0];
standalone.frames[0][0] = '#123456';
assert.notEqual(designs[0].frames[0][0], '#123456');

const disabled = copy(config);
const disabledPage = disabled.page_data.find(page => page.page_index === 6);
disabledPage.valid = false;
disabledPage.word_page = { valid: 1, word_len: 2, unicode: [82, 54] };
disabled._provenance = { marker: 'test only' };
const beforeMerge = digest(disabled), beforeDesign = digest(designs[2]);
const merged = model.merge(disabled, [{ slot: 2, design: designs[2], speedMs: 83, brightness: 67 }]);
assert.equal(digest(disabled), beforeMerge);
assert.equal(digest(designs[2]), beforeDesign);
const updated = merged.page_data.find(page => page.page_index === 6);
assert.equal(updated.valid, true, 'writing an unused slot must enable it');
assert.equal(updated.speed_ms, 83);
assert.equal(updated.lightness, 67);
assert.deepEqual(copy(updated.word_page), { valid: 0, word_len: 0, unicode: [] }, 'animation slot must not remain in text mode');
assert.equal(updated.frames.valid, 1); assert.equal(updated.keyframes.valid, 1);
assert.equal(updated.frames.frame_num, 192); assert.equal(updated.keyframes.frame_num, 192);
assert.deepEqual(copy(updated.frames.frame_data.map(frame => frame.frame_RGB)), designs[2].frames, 'page brightness must not be baked into RGB');
assert.deepEqual(copy(updated.keyframes.frame_data.map(frame => frame.frame_RGB)), designs[2].keyframes);
for (const [index, frame] of updated.frames.frame_data.entries()) assert.equal(frame.frame_index, index);
for (const [index, frame] of updated.keyframes.frame_data.entries()) assert.equal(frame.frame_index, index);
assert.deepEqual(copy(merged.key_layer), disabled.key_layer, 'all live key layers must remain unchanged');
const restored = copy(merged);
const restoredPage = restored.page_data.find(page => page.page_index === 6);
for (const field of ['valid', 'speed_ms', 'lightness', 'word_page', 'frames', 'keyframes']) restoredPage[field] = disabledPage[field];
const expected = copy(disabled); delete expected._provenance;
assert.deepEqual(restored, expected, 'single-slot update must preserve every other configuration field and slot');
updated.frames.frame_data[0].frame_RGB[0] = '#456789';
assert.equal(digest(disabled), beforeMerge); assert.equal(digest(designs[2]), beforeDesign);

const invalid = modifier => { const design = copy(designs[0]); modifier(design); assert.throws(() => model.validate(design)); };
invalid(design => { design.frames = []; });
invalid(design => { design.keyframes = []; });
invalid(design => { design.frames[0].pop(); });
invalid(design => { design.keyframes[0].push('#000000'); });
invalid(design => { design.frames[0][0] = '#FFF'; });
invalid(design => { design.frames[0][0] = '#GG0011'; });
invalid(design => { design.frames[0][0] = [0, 0, 0]; });
for (const index of reserved) invalid(design => { design.keyframes[0][index] = '#000001'; });
invalid(design => { design.frames = Array.from({ length: 256 }, () => design.frames[0].slice()); });
invalid(design => { design.keyframes = Array.from({ length: 256 }, () => design.keyframes[0].slice()); });
for (const speed of [0, -1, 40.5, 32768, Infinity, '40']) invalid(design => { design.speed_ms = speed; });
for (const assignment of [
  { slot: 0, design: designs[0], speedMs: 40, brightness: 100 },
  { slot: 4, design: designs[0], speedMs: 40, brightness: 100 },
  { slot: 1, design: designs[0], speedMs: 32768, brightness: 100 },
  { slot: 1, design: designs[0], speedMs: 40, brightness: 101 },
  { slot: 1, design: designs[0], speedMs: 40, brightness: -1 },
  { slot: 1, design: designs[0], speedMs: 40, brightness: 10.5 }
]) assert.throws(() => model.merge(config, [assignment]));
assert.throws(() => model.merge(config, [
  { slot: 1, design: designs[0], speedMs: 40, brightness: 100 },
  { slot: 1, design: designs[1], speedMs: 40, brightness: 100 }
]));
assert.throws(() => model.merge({ page_data: [] }, [{ slot: 1, design: designs[0], speedMs: 40, brightness: 100 }]));

for (const field of ['frames', 'keyframes']) {
  for (const count of [193, 256, 3.5, -1]) {
    const malformed = copy(config);
    malformed.page_data.find(page => page.page_index === 5)[field].frame_num = count;
    assert.throws(() => model.importDesigns(malformed), 'declared frame count must match actual frame data and be 1–255');
  }
}
const gridCSS = fs.readFileSync(path.join(__dirname, '../web/styles.css'), 'utf8');
const explicitColumns = Number(gridCSS.match(/\.key-grid\{[^}]*grid-template-columns:repeat\((\d+),/)[1]);
const keyGeometry = read('web/assets/keymap-layout.json').keys;
const rowSpans = new Map();
for (const key of keyGeometry) rowSpans.set(key.row, (rowSpans.get(key.row) || 0) + (key.span || 2));
assert.ok([...rowSpans.values()].every(span => span <= explicitColumns), 'physical key span totals must fit explicit grid columns');
assert.equal(new Set(keyGeometry.map(key => key.physical)).size, 81);
assert.equal(new Set(keyGeometry.map(key => key.matrix_index)).size, 81);
assert.equal(keyGeometry.find(key => key.physical === 'z').matrix_index, 102);
assert.equal(keyGeometry.find(key => key.physical === 'slash').matrix_index, 111);
assert.equal(keyGeometry.find(key => key.physical === 'rshift').matrix_index, 112);

// Exported external-AI instructions describe the actual Studio import contract,
// independently of the app's bounded recipe compiler and optional style reference.
const brief = '做一只5像素高的黑猫眨眼；彩虹背景，36帧、90ms，不需要纵向滚动。';
const reference = { name: '旧作品名不应继承', description: '旧六段剧情不应强制', palette: ['#AABBCC', '#00ff41', 'bad', '#FFF'] };
const referenceBefore = digest(reference);
const prompt = model.prompt(brief, reference);
assert.ok(prompt.includes(brief), 'the user visual target and explicit valid timing must survive export');
assert.ok(!prompt.includes(reference.name) && !prompt.includes(reference.description), 'existing style is opt-in');
assert.ok(prompt.includes('#AABBCC') && prompt.includes('#00ff41'));
assert.ok(!prompt.includes('bad'));assert.doesNotMatch(prompt, /#FFF(?:[^0-9A-Fa-f]|$)/);
for (const subject of ['像素角色', '渐变与波浪', '自然元素', '呼吸氛围', '文字信息', '静态纯色',
  '游戏街机', '键帽主题', '彩虹光谱', '数字雨', '运动光效', '节日与电竞']) assert.ok(prompt.includes(subject));
for (const motion of ['像素姿态', '平移滚动', '相位波', '呼吸', '拖尾', '下落', '伪随机', '静态']) assert.ok(prompt.includes(motion));
assert.match(prompt, /顶部为40列×5行，每帧恰好200个颜色/);
assert.match(prompt, /轴灯每帧恰好90个颜色/);
assert.match(prompt, /保留索引57、61、74、78、82、83、84必须全部为#000000/);
assert.match(prompt, /空格三灯为79、80、81/);
assert.match(prompt, /禁止把200灯顶部数据直接复制成轴灯帧/);
assert.match(prompt, /frames和keyframes各含1–255帧/);
assert.match(prompt, /speed_ms是1–32767的整数/);
assert.match(prompt, /内置AI编排支持10–100 ms\/帧/);
assert.match(prompt, /不要固定生成192帧/);
assert.match(prompt, /3–8秒循环/);
assert.match(prompt, /并不保证更丝滑/);
assert.match(prompt, /3×5 ASCII/);
assert.match(prompt, /字符间距1列/);
assert.match(prompt, /4n-1列/);
assert.match(prompt, /超过40列应滚动展示完整内容/);
assert.match(prompt, /并非所有角色都必须纵向滚动/);
assert.match(prompt, /用户要求保留完整高图/);
assert.match(prompt, /只输出一个完整JSON对象/);
assert.match(prompt, /不要输出官网page_data配置、frames\.frame_data对象、scenes配方/);
assert.match(prompt, /不输出8个抽样帧、不用省略号/);
assert.match(prompt, /不询问是否补全/);
assert.match(prompt, /彩虹是有效方向/);
assert.doesNotMatch(prompt, /781|72%|均赞|人气王|318|30\.7|JSON代码块|示意帧/);
assert.ok(!prompt.includes('```'), 'instructions must not embed a fenced output example that contradicts raw JSON');
const optedIn = model.prompt(brief, reference, { useReference: true });
assert.ok(optedIn.includes(reference.name) && optedIn.includes(reference.description));
assert.equal(digest(reference), referenceBefore, 'prompt export never mutates the reference design');
assert.doesNotThrow(() => model.prompt('', null));

console.log('PASS: actual 3 designs, immutable palette variants and RGB intensity, reserved black, LED-only configuration import, isolated single-slot merge with live key-layer preservation and text-mode clearing, invalid input rejection, physical geometry and complete Studio-format external AI prompt with opt-in references, 12 styles, 8 motions and corrected hardware/font/timing limits.');
