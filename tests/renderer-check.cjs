/* Offline behavior checks using shipped designs, calibration and canvas doubles. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const crypto = require('crypto');

const workspace = path.resolve(__dirname, '..');
const read = relative => JSON.parse(fs.readFileSync(path.join(workspace, relative), 'utf8'));
const designs = [
  read('data/designs/neon-rift.design.json'),
  read('data/designs/data-storm.design.json'),
  read('data/designs/redline-rush.design.json')
];
const views = read('data/photos/photo-calibration.json');
const keyLayout = read('data/photos/key-photo-layout.json');
for (const [name, view] of Object.entries(views)) {
  view.image = 'assets/' + name + '.jpg';
  view.keyZones = keyLayout.views[name];
  assert.equal(view.keyZones.length, 83);
}
const source = fs.readFileSync(path.join(__dirname, '../web/preview-engine.js'), 'utf8');
assert.ok(!/\b(fetch|XMLHttpRequest|WebSocket)\s*\(|window\.openai/.test(source));

function harness(reduced = false, tainted = false) {
  const log = { photos: [], photoClips: [], clips: [], top: [], axes: [], warps: [], neutral: [] };
  const callbacks = new Map();
  let nextRAF = 1;
  const styles = new Map();
  const documentEvents = new Map();
  const motionEvents = new Set();
  const motion = { matches: reduced, addEventListener(type, callback) { motionEvents.add(callback); },
    removeEventListener(type, callback) { motionEvents.delete(callback); } };
  const ctx = canvas => {
    let polygon = [], clipping = [];
    const stack = [];
    return new Proxy({}, {
    get(target, prop) {
      if (prop === 'beginPath') return () => { polygon = []; };
      if (prop === 'moveTo' || prop === 'lineTo') return (x, y) => { polygon.push([x, y]); };
      if (prop === 'clip') return () => {
        clipping.push(polygon.map(point => [...point]));
        log.clips.push({ layer: canvas.className || 'sprite', polygon: polygon.map(point => [...point]) });
      };
      if (prop === 'save') return () => { stack.push(clipping.map(points => points.map(point => [...point]))); };
      if (prop === 'restore') return () => { clipping = stack.pop() || []; };
      if (prop === 'createRadialGradient') return () => ({ stops: [], addColorStop(...stop) { this.stops.push(stop); } });
      if (prop === 'createImageData') return (w, h) => ({ width: w, height: h, data: new Uint8ClampedArray(w * h * 4) });
      if (prop === 'getImageData') return (x, y, w, h) => {
        if (tainted) {
          const error = new Error('The canvas has been tainted by cross-origin data.');
          error.name = 'SecurityError';
          throw error;
        }
        const data = new Uint8ClampedArray(w * h * 4);
        for (let at = 0; at < data.length; at += 4) data.set([100, 160, 220, 255], at);
        return { data, width: w, height: h };
      };
      if (prop === 'putImageData') return pixels => {
        if (canvas.className === 'photo-base') log.neutral.push(pixels);
      };
      if (prop === 'setTransform') return (...values) => {
        assert.ok(values.every(Number.isFinite), 'projective mesh must remain finite');
        if (canvas.className === 'led-overlay') log.warps.push(values);
      };
      if (prop === 'drawImage') return (...args) => {
        if (canvas.className === 'photo-base') {
          log.photos.push(args);
          log.photoClips.push(clipping.map(points => points.map(point => [...point])));
        }
      };
      return target[prop] || (() => {});
    },
    set(target, prop, value) {
      target[prop] = value;
      if (prop === 'fillStyle' && typeof value === 'string' && /^rgb\(/.test(value)) {
        if (!canvas.className && canvas.width >= 1600) log.top.push(value);
        else if (!canvas.className && canvas.width < 1600) log.axes.push(value);
      }
      return true;
    }
  });
  };
  function element(tag) {
    const element = { tag, width: 0, height: 0, className: '', style: {}, attributes: {}, children: [],
      clientWidth: 720, parent: null,
      classList: { values: new Set(), add(value) { this.values.add(value); }, remove(value) { this.values.delete(value); } },
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      appendChild(child) { this.children.push(child); child.parent = this; if (child.id) styles.set(child.id, child); },
      remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); },
      getContext() { if (!this.context) this.context = ctx(this); return this.context; }
    };
    return element;
  }
  const document = { hidden: false, head: element('head'), createElement: element,
    getElementById(id) { return styles.get(id); },
    addEventListener(type, callback) {
      if (!documentEvents.has(type)) documentEvents.set(type, new Set());
      documentEvents.get(type).add(callback);
    },
    removeEventListener(type, callback) { documentEvents.get(type)?.delete(callback); }
  };
  const observers = [];
  const window = { devicePixelRatio: 2, matchMedia() { return motion; },
    requestAnimationFrame(callback) { const id = nextRAF++; callbacks.set(id, callback); return id; },
    cancelAnimationFrame(id) { callbacks.delete(id); },
    addEventListener() {}, removeEventListener() {},
    ResizeObserver: class {
      constructor(callback) { this.callback = callback; observers.push(this); }
      observe() { this.active = true; }
      disconnect() { this.active = false; }
    },
    Image: class {
      constructor() { this.naturalWidth = 1350; this.naturalHeight = 901; }
      set src(value) {
        assert.match(value, /^assets\/(front|desk)\.jpg$/);
        if (value.includes('desk')) this.naturalHeight = 863;
        Promise.resolve().then(() => this.onload());
      }
    }
  };
  const context = { window, document, console: { log: console.log, error() {} }, Uint8Array, Uint8ClampedArray, Float32Array };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { log, window, document, motion, observers, callbacks, container: element('div'),
    tick(now) { const entries = [...callbacks]; callbacks.clear(); for (const [, callback] of entries) callback(now); },
    visibility(hidden) { document.hidden = hidden; for (const callback of documentEvents.get('visibilitychange') || []) callback(); },
    reduced(value) { motion.matches = value; for (const callback of motionEvents) callback(); },
    listenerCount() { return [...documentEvents.values()].reduce((sum, set) => sum + set.size, 0) + motionEvents.size; }
  };
}

const color = (hex, factor = 1) => 'rgb(' + [1, 3, 5].map(at => Math.round(parseInt(hex.slice(at, at + 2), 16) * factor)).join(',') + ')';
const digest = data => crypto.createHash('sha256').update(JSON.stringify(data)).digest('hex');

(async () => {
  const viewDigest = digest(views);
  const photoDigests = ['front', 'desk'].map(name => crypto.createHash('sha256')
    .update(fs.readFileSync(path.join(__dirname, '../web/assets/' + name + '.jpg'))).digest('hex'));
  const h = harness();
  const frames = [];
  const preview = new h.window.KeyboardPreview(h.container, { views, design: designs[0], onFrame: value => frames.push(value) });
  await preview.ready;
  assert.equal(h.container.children.length, 3);
  assert.equal(preview.playing, true);
  assert.equal(preview.frameCount, 192);
  assert.equal(frames.at(-1).speedMs, 40);
  assert.equal(preview._warpTriangles.length, 128);
  assert.equal(preview._keySprites.length, 83);
  assert.deepEqual(Array.from(preview._keySprites.filter(sprite => [79, 80, 81].includes(sprite.index)), sprite => sprite.index), [79, 80, 81]);
  assert.ok(h.log.neutral.length > 0, 'original key lighting must be neutralized');
  assert.ok(h.log.neutral.at(-1).data.some((value, at) => at % 4 !== 3 && value !== [100, 160, 220][at % 4]));
  assert.equal(h.container.attributes['data-preview-background'], 'isolated');
  assert.ok(h.container.classList.values.has('keyboard-isolated'));
  assert.equal(h.log.photoClips.at(-1).length, 1, 'photo background must be clipped while drawing the real JPEG');
  const shellOutline = h.log.photoClips.at(-1)[0];
  assert.ok(shellOutline.length >= 8, 'outer shell retains its angled edges and small bevels');
  for (const layer of ['photo-base', 'key-overlay', 'led-overlay']) {
    const clipping = h.log.clips.find(entry => entry.layer === layer && entry.polygon.length === shellOutline.length);
    assert.deepEqual(clipping.polygon, shellOutline, 'all layers must share exactly the same projected enclosure silhouette');
  }
  const inside = (point, polygon) => {
    let hit = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const [x, y] = polygon[i], [previousX, previousY] = polygon[j];
      if (((y > point[1]) !== (previousY > point[1])) &&
        point[0] < (previousX - x) * (point[1] - y) / (previousY - y) + x) hit = !hit;
    }
    return hit;
  };
  const frontPoint = ([x, y]) => [(x - views.front.crop[0]) * preview.background.width / views.front.crop[2],
    (y - views.front.crop[1]) * preview.background.height / views.front.crop[3]];
  assert.ok(inside(frontPoint([830, 220]), shellOutline), 'top metal edge is retained');
  assert.ok(inside(frontPoint([830, 840]), shellOutline), 'bottom metal edge is retained');
  assert.ok(inside(frontPoint([240, 530]), shellOutline), 'side-case graphics are retained');
  assert.ok(!inside(frontPoint([830, 890]), shellOutline), 'reflected keyboard below the case is excluded');
  assert.ok(!inside(frontPoint([1460, 530]), shellOutline), 'busy surrounding photo is excluded');
  assert.ok(!inside(frontPoint([830, 200]), shellOutline), 'background above the LED glass is excluded');

  const distinct = [];
  for (const design of designs) {
    const before = digest(design);
    preview.setDesign(design).setRenderer('library').seek(80);
    h.log.top.length = h.log.axes.length = 0;
    preview.setBrightness(100);
    assert.deepEqual(h.log.top, design.frames[80].map(hex => color(hex)), 'top LEDs must use exact design RGB');
    const expectedAxes = views.front.keyZones.map(zone => design.keyframes[80][zone.index]).filter(hex => hex !== '#000000').map(hex => color(hex));
    assert.deepEqual(h.log.axes, expectedAxes, 'only physical 83 key zones receive raw RGB');
    distinct.push(digest(h.log.top));
    preview.setBrightness(50);
    h.log.top.length = h.log.axes.length = 0;
    preview.setBrightness(50);
    assert.deepEqual(h.log.top, design.frames[80].map(hex => color(hex, .5)), 'brightness scales every top channel equally');
    const halfAxes = views.front.keyZones.map(zone => design.keyframes[80][zone.index]).map(hex => color(hex, .5)).filter(value => value !== 'rgb(0,0,0)');
    assert.deepEqual(h.log.axes, halfAxes, 'brightness uses the same ratio for keys');
    preview.setSpeed(80);
    assert.equal(frames.at(-1).speedMs, 80);
    assert.equal(digest(design), before, 'preview controls must not mutate stored design RGB or speed');
  }
  assert.equal(new Set(distinct).size, 3, 'all three real designs render distinct frames');
  preview.setBrightness(0);
  assert.ok(h.log.top.slice(-200).every(value => value === 'rgb(0,0,0)'));
  preview.setBrightness(110); assert.equal(preview.brightness, 100);
  preview.setBrightness(-20); assert.equal(preview.brightness, 0);
  preview.setBrightness(100);

  preview.seek(-30); assert.equal(preview.frame, 0);
  preview.seek(99999); assert.equal(preview.frame, 191);
  assert.equal(preview.playing, false);
  assert.equal(h.callbacks.size, 0);
  preview.setSpeed(40).play();
  h.tick(1000); h.tick(1040);
  assert.equal(preview.frame, 0);
  assert.equal(preview.keyFrame, 0);
  h.tick(1120); assert.equal(preview.frame, 2, 'elapsed playback advances multiple frames');
  preview.pause(); const stoppedFrame = preview.frame; h.tick(3000);
  assert.equal(preview.frame, stoppedFrame); assert.equal(h.callbacks.size, 0);

  preview.play(); h.tick(4000); h.visibility(true); h.tick(4400); h.visibility(false); h.tick(9000);
  assert.equal(preview.frame, stoppedFrame, 'returning from a hidden window must not skip the animation');
  h.tick(9040); assert.equal(preview.frame, stoppedFrame + 1);
  preview.setDesign(designs[0]); assert.equal(preview.frame, 0); assert.equal(preview.playing, true);
  assert.equal(frames.at(-1).stage, designs[0].stages[0]);

  const unequal = { ...designs[0], keyframes: designs[0].keyframes.slice(0, 42) };
  preview.setDesign(unequal);
  assert.equal(preview._combinedFrames, 1344, '192 top and 42 key frames have a complete cycle of 1344 ticks');
  preview.seek(191).play(); h.tick(10000); h.tick(10040);
  assert.equal(preview.frame, 0); assert.equal(preview.keyFrame, 24, 'top wrap must not reset the independent key animation');
  assert.equal(frames.at(-1).tick, 192); assert.equal(frames.at(-1).combinedFrameCount, 1344);
  preview.seek(1343).play(); h.tick(10100); h.tick(10140);
  assert.equal(preview.frame, 0); assert.equal(preview.keyFrame, 0); assert.equal(frames.at(-1).tick, 0);
  preview.setDesign(designs[0]);

  const keyDraws = h.log.axes.length;
  preview.setKeyMode('off'); assert.equal(h.log.axes.length, keyDraws);
  preview.setKeyMode('photo'); assert.equal(preview._keySprites.length, 0);
  preview.setKeyMode('json'); assert.equal(preview._keySprites.length, 83);
  preview.setRenderer('editor'); assert.equal(preview._texture.width, 1600); assert.equal(preview._texture.height, 200);
  preview.setRenderer('library'); assert.equal(preview._texture.width, 1605); assert.equal(preview._texture.height, 205);
  for (const name of ['front', 'desk']) {
    preview.setView(name).setFraming('full');
    const photo = h.log.photos.at(-1);
    const view = views[name];
    assert.equal(view.full_crop[3], view.source_size[1] - 42, 'full photo must exclude baked footer watermark');
    assert.equal(photo[4], view.full_crop[3] * photo[0].naturalHeight / view.source_size[1]);
    assert.equal(preview._warpTriangles.length, 128);
    assert.equal(preview._keyboardOutline.length, 0, 'full photographs keep their intentional desktop context');
    assert.equal(h.log.photoClips.at(-1).length, 0, 'switching out of isolated mode clears the old canvas clipping');
    assert.equal(h.container.attributes['data-preview-background'], 'photo');
    assert.ok(!h.container.classList.values.has('keyboard-isolated'));
  }
  preview.setView('desk').setFraming('keyboard');
  assert.equal(preview._keyboardOutline.length, 0, 'desk view retains the real desktop photo');
  preview.setView('front').setFraming('keyboard');
  assert.equal(h.log.photoClips.at(-1).length, 1, 'returning to front close-up restores transparent surroundings');
  const projectedTop = views.front.quad.map(([x, y]) => [
    (x - views.front.crop[0]) * preview.background.width / views.front.crop[2],
    (y - views.front.crop[1]) * preview.background.height / views.front.crop[3]]);
  for (const point of projectedTop) assert.ok(inside(point, preview._keyboardOutline), 'calibrated LED corners remain inside the exact outer-case clip');
  assert.equal(digest(views), viewDigest, 'isolating the photo must not mutate calibration coordinates');
  ['front', 'desk'].forEach((name, index) => assert.equal(crypto.createHash('sha256')
    .update(fs.readFileSync(path.join(__dirname, '../web/assets/' + name + '.jpg'))).digest('hex'), photoDigests[index],
  'source photo bytes stay unchanged'));
  h.container.clientWidth = 320; h.observers[0].callback(); assert.equal(preview.background.width, 640);
  h.container.clientWidth = 3000; h.observers[0].callback(); assert.equal(preview.background.width, 1400);
  h.reduced(true); assert.equal(preview.playing, false); assert.equal(h.callbacks.size, 0);
  h.reduced(false); assert.equal(preview.playing, false, 'preference change must not autoplay');

  const designBefore = preview.design;
  assert.throws(() => preview.setDesign({ frames: [['#123456']], keyframes: [] }));
  assert.equal(preview.design, designBefore, 'invalid imported design must leave current preview intact');
  assert.throws(() => preview.setSpeed(0));
  assert.throws(() => preview.setBrightness(NaN));
  assert.throws(() => preview.seek(Infinity));
  assert.throws(() => preview.setView('fake-r6'));
  preview.play(); preview.destroy();
  assert.equal(h.callbacks.size, 0); assert.equal(h.listenerCount(), 0);
  assert.equal(h.container.children.length, 0); assert.equal(h.observers[0].active, false);
  assert.throws(() => preview.play());
  preview.destroy();

  const reduced = harness(true);
  const quiet = new reduced.window.KeyboardPreview(reduced.container, { views, design: designs[0] });
  await quiet.ready;
  assert.equal(quiet.playing, false); assert.equal(reduced.callbacks.size, 0);
  quiet.destroy();
  const early = harness();
  const disposed = new early.window.KeyboardPreview(early.container, { views, design: designs[1] });
  disposed.destroy(); await disposed.ready;
  assert.equal(early.callbacks.size, 0); assert.equal(early.log.photos.length, 0);
  const tainted = harness(false, true);
  const errors = [];
  const broken = new tainted.window.KeyboardPreview(tainted.container, { views, design: designs[0], onError: (error, diagnostic) => errors.push(diagnostic) });
  await assert.rejects(broken.ready, error => error.name === 'SecurityError');
  assert.equal(broken.playing, false); assert.equal(tainted.callbacks.size, 0);
  assert.equal(broken.diagnostic.name, 'SecurityError'); assert.equal(broken.diagnostic.phase, '照片投影');
  assert.equal(tainted.container.attributes['data-preview-error'], 'SecurityError');
  assert.equal(errors.length, 1);
  assert.equal(broken._errorBanner.attributes.role, 'alert');
  assert.ok(broken._errorBanner.textContent.includes('无法读取灯光区域'));
  broken.setBrightness(50).play();
  assert.equal(broken.playing, false); assert.ok(broken._errorBanner, 'preview controls must not erase a persistent renderer diagnostic');
  broken.setKeyMode('photo');
  assert.equal(broken.error, null); assert.equal(broken._errorBanner, null, 'a successful full layout may recover the preview');
  broken.setKeyMode('json');
  assert.equal(broken.diagnostic.name, 'SecurityError'); assert.equal(errors.length, 2);
  broken.destroy(); assert.equal(tainted.container.children.length, 0);
  console.log('PASS: real 192-frame designs, exact RGB and brightness, 128 perspective triangles, 83 lamp zones, independent space lamps, loop/seek/play/pause, shared transparent enclosure clip on all 3 layers, unmodified source photos and calibration, photo/full-view mode reset, watermark-free full crop, visibility, responsive width, reduced motion, cleanup and persistent canvas SecurityError diagnostics.');
})().catch(error => { console.error(error); process.exitCode = 1; });
