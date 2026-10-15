// Public bundled art and synthetic configuration only. No model, workspace or USB.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const read = file => JSON.parse(fs.readFileSync(path.join(root, file), 'utf8'));
const plain = value => JSON.parse(JSON.stringify(value));
const context = {window: {}};
vm.createContext(context);
for (const file of ['web/studio-model.js', 'web/data.js'])
  vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), context);
const M = context.window.StudioModel, D = plain(context.window.STUDIO_DATA);
const catalog = read('data/preset-catalog.json');
const required = ['neon-rift', 'data-storm', 'redline-rush', 'kaka-rossonero-22',
  'kaka-breakaway', 'candidate-kaka-san-siro', 'art-eva-unit01', 'cyberpunk-glitch-override'];
assert.deepEqual(D.designs.map(d => d.id).sort(), required.sort(), 'release includes only the selected presets');
assert.equal(catalog.works.length, D.designs.length);
assert.equal(new Set(D.designs.map(d => d.id)).size, D.designs.length);
assert.equal(new Set(catalog.works.map(e => e.file)).size, catalog.works.length);
assert.equal(D.baseConfig, null);
assert.deepEqual(D.snapshot, {productId: null, firmware: null, connected: false});
const fixture = require('../data/test-fixtures.cjs')();
const unchanged = JSON.stringify(fixture);
for (const entry of catalog.works) {
  assert.equal(path.basename(entry.file), entry.file);
  const source = read('data/designs/' + entry.file);
  const bundled = D.designs.find(d => d.id === source.id);
  assert.ok(bundled, entry.file + ' must be in the actual App bundle');
  // prepare-data may supply a description for older works; all source content,
  // including every RGB byte, must otherwise survive bundling unchanged.
  for (const [key, value] of Object.entries(source)) assert.deepEqual(bundled[key], value, source.id + ': ' + key);
  assert.equal(M.validate(bundled), bundled);
  const cover = D.presetPreviews[bundled.id];
  assert.equal(cover, entry.preview_frame);
  assert.ok(Number.isInteger(cover) && cover >= 0 && cover < bundled.frames.length);
  assert.ok(bundled.frames[cover].some(rgb => rgb !== '#000000'), 'cover cannot be a blank transition');
  assert.ok(bundled.frames.length <= 255 && bundled.keyframes.length <= 255);
  assert.ok(bundled.keyframes.every(frame => frame.length === 90 &&
    [57,61,74,78,82,83,84].every(i => frame[i] === '#000000')));
  const imported = M.importDesigns(bundled, entry.file)[0];
  for (const field of ['frames', 'keyframes']) assert.deepEqual(plain(imported[field]), bundled[field]);
  const merged = plain(M.merge(fixture, [{slot: 3, design: bundled, speedMs: bundled.speed_ms, brightness: 100}]));
  const page = merged.page_data.find(p => p.page_index === 7);
  assert.equal(page.speed_ms, bundled.speed_ms);
  assert.equal(page.lightness, 100);
  for (const field of ['frames', 'keyframes'])
    assert.deepEqual(page[field].frame_data.map(frame => frame.frame_RGB), bundled[field], 'slot 3 keeps exact source RGB');
  assert.deepEqual(merged.key_layer, fixture.key_layer, 'all keyboard bindings survive each new preset');
  for (const oldPage of fixture.page_data.filter(p => p.page_index !== 7))
    assert.deepEqual(merged.page_data.find(p => p.page_index === oldPage.page_index), oldPage, 'all unselected slots/modes survive');
  assert.equal(JSON.stringify(fixture), unchanged);
}
const title = D.designs.find(d => d.id === 'kaka-breakaway');
for (let frame = 80; frame < 108; frame++) {
  assert.deepEqual(title.frames[frame], title.frames[92], 'KAKA 22 has a complete undisturbed recognition hold');
  for (let y = 0; y < 5; y++)
    assert.ok(title.frames[frame].slice(y * 40, y * 40 + 5).every(c => c === '#000000'), 'no leading slash before KAKA');
}
console.log('PASS ' + D.designs.length + ' public presets: actual bundle, representative covers, exact RGB import/export, isolated slot-3 merge and clean KAKA 22 hold. No device accessed.');
