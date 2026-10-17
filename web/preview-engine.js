/* Cyberboard photo preview. All device RGB stays in the supplied design. */
(function (global) {
  'use strict';

  // Source-photo coordinates: trace only the real metal enclosure, ending at
  // its lower edge before the mirrored keyboard. The original JPEG is retained.
  const FRONT_KEYBOARD_OUTLINE = [
    [220, 220], [224, 217], [1431, 212], [1436, 215], [1437, 221],
    [1435, 849], [1431, 856], [235, 860], [230, 857], [228, 850]
  ];

  // Gallery entries retain a real horizontal front photograph. Explicitly
  // excluded or angled sources may be archived, but cannot become preview views.
  // Older front-only callers may identify their view with the original label.
  function galleryAllowed(view) {
    return Boolean(view && view.galleryAllowed !== false &&
      (view.angle === 'front' || (!view.angle && view.name === '正面整机')));
  }

  function homography(q) {
    const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = q;
    const dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3;
    const dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3;
    const denominator = dx1 * dy2 - dx2 * dy1;
    if (Math.abs(denominator) < 1e-12) throw new Error('照片校准区域无效');
    const g = (dx3 * dy2 - dx2 * dy3) / denominator;
    const h = (dx1 * dy3 - dx3 * dy1) / denominator;
    return [x1 - x0 + g * x1, x3 - x0 + h * x3, x0,
      y1 - y0 + g * y1, y3 - y0 + h * y3, y0, g, h];
  }

  function project(h, u, v) {
    const denominator = h[6] * u + h[7] * v + 1;
    return [(h[0] * u + h[1] * v + h[2]) / denominator,
      (h[3] * u + h[4] * v + h[5]) / denominator];
  }

  function invert(h) {
    const [a, b, c, d, e, f, g, k] = h;
    const A = e - f * k, B = c * k - b, C = b * f - c * e;
    const D = f * g - d, E = a - c * g, F = c * d - a * f;
    const G = d * k - e * g, H = b * g - a * k, I = a * e - b * d;
    return [A / I, B / I, C / I, D / I, E / I, F / I, G / I, H / I];
  }

  function affine(source, destination) {
    const [[x0, y0], [x1, y1], [x2, y2]] = source;
    const [[u0, v0], [u1, v1], [u2, v2]] = destination;
    const det = x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1);
    const a = (u0 * (y1 - y2) + u1 * (y2 - y0) + u2 * (y0 - y1)) / det;
    const c = (u0 * (x2 - x1) + u1 * (x0 - x2) + u2 * (x1 - x0)) / det;
    const e = (u0 * (x1 * y2 - x2 * y1) + u1 * (x2 * y0 - x0 * y2) + u2 * (x0 * y1 - x1 * y0)) / det;
    const b = (v0 * (y1 - y2) + v1 * (y2 - y0) + v2 * (y0 - y1)) / det;
    const d = (v0 * (x2 - x1) + v1 * (x0 - x2) + v2 * (x1 - x0)) / det;
    const f = (v0 * (x1 * y2 - x2 * y1) + v1 * (x2 * y0 - x0 * y2) + v2 * (x0 * y1 - x1 * y0)) / det;
    return [a, b, c, d, e, f];
  }

  function rgbBytes(frames, size, label) {
    if (!Array.isArray(frames) || !frames.length) throw new TypeError(label + '至少需要一帧');
    const bytes = new Uint8Array(frames.length * size * 3);
    let at = 0;
    frames.forEach((frame, frameIndex) => {
      if (!Array.isArray(frame) || frame.length !== size) {
        throw new TypeError(label + '第 ' + (frameIndex + 1) + ' 帧需要 ' + size + ' 个 RGB 颜色');
      }
      frame.forEach(color => {
        if (typeof color !== 'string' || !/^#[0-9a-f]{6}$/i.test(color)) {
          throw new TypeError(label + '颜色必须为 #RRGGBB');
        }
        bytes[at++] = parseInt(color.slice(1, 3), 16);
        bytes[at++] = parseInt(color.slice(3, 5), 16);
        bytes[at++] = parseInt(color.slice(5, 7), 16);
      });
    });
    return bytes;
  }

  function interval(ms) {
    if (!Number.isFinite(Number(ms)) || Number(ms) < 1 || Number(ms) > 60000) {
      throw new RangeError('每帧时间需要为 1 到 60000 毫秒');
    }
    return Math.round(Number(ms));
  }

  function sharedCycle(a, b) {
    let x = a, y = b;
    while (y) { const remainder = x % y; x = y; y = remainder; }
    return a / x * b;
  }

  function addStyles() {
    if (document.getElementById('keyboard-preview-engine-style')) return;
    const style = document.createElement('style');
    style.id = 'keyboard-preview-engine-style';
    style.textContent = '.keyboard-preview{position:relative;isolation:isolate;width:100%;overflow:hidden;}' +
      '.keyboard-preview>.photo-base,.keyboard-preview>.key-overlay,.keyboard-preview>.led-overlay{' +
      'position:absolute;display:block;object-fit:fill;}' +
      '.keyboard-preview>.key-overlay{pointer-events:none;mix-blend-mode:screen;}' +
      '.keyboard-preview>.led-overlay{pointer-events:none;}' +
      '.keyboard-preview>.preview-error{position:absolute;z-index:3;inset:auto 12px 12px;padding:10px 12px;' +
      'border:1px solid #70484b;border-radius:6px;color:#ffe0e0;background:#271619;font:12px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;}';
    (document.head || document.documentElement).appendChild(style);
  }

  // Every layer uses the same centered viewport. Aspect-ratio on the host is
  // only an intrinsic size hint: fixed-height panels can override both axes.
  function containBounds(availableWidth, availableHeight, sourceWidth, sourceHeight) {
    if (![sourceWidth, sourceHeight].every(value => Number.isFinite(value) && value > 0)) {
      throw new RangeError('照片裁切尺寸必须为正数');
    }
    const width = Number.isFinite(availableWidth) ? Math.max(0, availableWidth) : 0;
    const height = Number.isFinite(availableHeight) && availableHeight > 0
      ? availableHeight : width * sourceHeight / sourceWidth;
    const scale = Math.min(width / sourceWidth, height / sourceHeight);
    const fittedWidth = sourceWidth * scale, fittedHeight = sourceHeight * scale;
    return { width: fittedWidth, height: fittedHeight,
      left: (width - fittedWidth) / 2, top: (height - fittedHeight) / 2 };
  }

  class KeyboardPreview {
    constructor(container, options) {
      if (!container || !options || !options.views || !options.design) {
        throw new TypeError('预览需要容器、照片视角和灯效设计');
      }
      this.container = container;
      this.views = Object.fromEntries(Object.entries(options.views).filter(([, view]) => galleryAllowed(view)));
      if (!Object.keys(this.views).length) throw new TypeError('预览需要水平正面整机照片');
      this.onFrame = typeof options.onFrame === 'function' ? options.onFrame : function () {};
      this.onError = typeof options.onError === 'function' ? options.onError : function () {};
      this.error = null;
      this.diagnostic = null;
      this._errorBanner = null;
      this.view = this.views[options.view] ? options.view : this.views.front ? 'front' : Object.keys(this.views)[0];
      this.framing = 'keyboard';
      this.renderer = 'editor';
      this.keyMode = 'json';
      this.brightness = 100;
      this.frame = 0;
      this.keyFrame = 0;
      this._tick = 0;
      this._ready = false;
      this._destroyed = false;
      this._lastTime = null;
      this._accumulator = 0;
      this._raf = null;
      this._images = {};
      this._keySprites = [];
      this._warpTriangles = [];
      this._screenQuad = [];
      this._keyboardOutline = [];
      this._motion = global.matchMedia ? global.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
      this.playing = !this._motion.matches;
      addStyles();
      container.classList.add('keyboard-preview');

      this.background = this._canvas('photo-base', 'Cyberboard 实体照片，含外壳、键帽和桌面环境');
      this.keyOverlay = this._canvas('key-overlay', '83 颗轴灯动画，空格键下为三颗独立灯');
      this.overlay = this._canvas('led-overlay', '顶部 40 列 5 行灯屏动画');
      this._bg = this.background.getContext('2d');
      this._key = this.keyOverlay.getContext('2d');
      this._led = this.overlay.getContext('2d');
      this._texture = document.createElement('canvas');
      this._texture.width = 1600;
      this._texture.height = 200;
      this._tx = this._texture.getContext('2d');
      this.setDesign(options.design);

      this._resizeListener = () => this._layout();
      if (typeof global.ResizeObserver === 'function') {
        this._observer = new global.ResizeObserver(this._resizeListener);
        this._observer.observe(container);
      } else global.addEventListener('resize', this._resizeListener);
      this._visibilityListener = () => this._resetClock();
      document.addEventListener('visibilitychange', this._visibilityListener);
      this._motionListener = () => { if (this._motion.matches) this.pause(); };
      if (this._motion.addEventListener) this._motion.addEventListener('change', this._motionListener);
      else if (this._motion.addListener) this._motion.addListener(this._motionListener);
      this._animate = now => {
        this._raf = null;
        if (this._destroyed || !this.playing) return;
        if (!this._ready || document.hidden) this._resetClock();
        else {
          if (this._lastTime === null) this._lastTime = now;
          this._accumulator += Math.min(Math.max(now - this._lastTime, 0), 250);
          const steps = Math.floor(this._accumulator / this.speedMs);
          if (steps > 0) {
            this._tick = (this._tick + steps) % this._combinedFrames;
            this.frame = this._tick % this.frameCount;
            this.keyFrame = this._tick % this.keyFrameCount;
            this._accumulator -= steps * this.speedMs;
            this._drawLights();
            this._emit();
          }
          this._lastTime = now;
        }
        this._schedule();
      };
      this.ready = Promise.all(Object.entries(this.views).map(([key, view]) => new Promise((resolve, reject) => {
        if (!view.image || !view.source_size || !view.crop || !view.full_crop || !view.quad || !view.mask_quad) {
          reject(new TypeError('缺少 ' + key + ' 照片校准信息'));
          return;
        }
        const image = new global.Image();
        this._images[key] = image;
        image.onload = resolve;
        image.onerror = () => reject(new Error(view.name + '照片加载失败'));
        image.src = view.image;
      }))).then(() => {
        if (this._destroyed) return this;
        this._ready = true;
        if (!this._layout()) throw this.error || new Error('照片灯效预览未完成');
        this._emit();
        this._schedule();
        return this;
      }).catch(error => {
        if (!this._destroyed && this.error !== error) this._reportError(error, '照片加载');
        throw error;
      });
    }

    _canvas(className, label) {
      const canvas = document.createElement('canvas');
      canvas.className = className;
      canvas.setAttribute('role', 'img');
      canvas.setAttribute('aria-label', label);
      this.container.appendChild(canvas);
      return canvas;
    }

    _ensureActive() {
      if (this._destroyed) throw new Error('预览已关闭');
    }

    _resetClock() {
      this._lastTime = null;
      this._accumulator = 0;
    }

    _schedule() {
      if (this._ready && this.playing && !this.error && !this._destroyed && this._raf === null) {
        this._raf = global.requestAnimationFrame(this._animate);
      }
    }

    _reportError(error, phase) {
      this.error = error;
      this.diagnostic = { phase, name: error.name || 'Error', message: error.message || String(error),
        view: this.view, framing: this.framing, keyMode: this.keyMode, renderer: this.renderer,
        designId: this.design.id || '', frame: this.frame };
      this.playing = false;
      this._resetClock();
      if (this._raf !== null) global.cancelAnimationFrame(this._raf);
      this._raf = null;
      this.container.setAttribute('data-preview-error', this.diagnostic.name);
      if (!this._errorBanner) {
        this._errorBanner = document.createElement('div');
        this._errorBanner.className = 'preview-error';
        this._errorBanner.setAttribute('role', 'alert');
        this.container.appendChild(this._errorBanner);
      }
      this._errorBanner.textContent = this.diagnostic.name === 'SecurityError'
        ? '照片灯效预览未完成：当前照片无法读取灯光区域。请重新打开应用。'
        : '照片灯效预览未完成：' + this.diagnostic.message;
      console.error('KeyboardPreview rendering failed', this.diagnostic);
      this._emit();
      try { this.onError(error, this.diagnostic); } catch (callbackError) { console.error(callbackError); }
    }

    _clearError() {
      this.error = null;
      this.diagnostic = null;
      this.container.removeAttribute('data-preview-error');
      if (this._errorBanner) this._errorBanner.remove();
      this._errorBanner = null;
    }

    _stage() {
      const stages = this.design.stages;
      if (!Array.isArray(stages) || !stages.length) return this.design.name || '';
      if (typeof stages[0] === 'string') return stages[this.frame] || stages[stages.length - 1];
      const stage = stages.find(item => this.frame < item.end) || stages[stages.length - 1];
      return stage.name || '';
    }

    _emit() {
      if (this._destroyed) return;
      this.onFrame({ frame: this.frame, frameCount: this.frameCount, keyFrame: this.keyFrame,
        keyFrameCount: this.keyFrameCount, tick: this._tick, combinedFrameCount: this._combinedFrames,
        stage: this._stage(), playing: this.playing, speedMs: this.speedMs });
    }

    setDesign(design) {
      this._ensureActive();
      const top = rgbBytes(design.frames, 200, '顶屏');
      const keys = rgbBytes(design.keyframes, 90, '轴灯');
      const speed = interval(design.speed_ms);
      this.design = design;
      this._frameBytes = top;
      this._keyBytes = keys;
      this.frameCount = design.frames.length;
      this.keyFrameCount = design.keyframes.length;
      // Independent device animations only share a complete cycle at their LCM.
      this._combinedFrames = sharedCycle(this.frameCount, this.keyFrameCount);
      this.speedMs = speed;
      this._tick = this.frame = this.keyFrame = 0;
      this._resetClock();
      this._drawLights();
      if (this._ready) this._emit();
      return this;
    }

    setView(view) {
      this._ensureActive();
      if (!this.views[view]) throw new RangeError('未知照片视角');
      this.view = view;
      this._layout();
      return this;
    }

    drawAppearanceThumbnail(canvas, viewId) {
      this._ensureActive();
      const view = this.views[viewId], image = this._images[viewId];
      if (!view) throw new RangeError('未知参考外观');
      if (!this._ready) return false;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('缩略图画布不可用');
      const [cx, cy, cw, ch] = view.crop, [sw, sh] = view.source_size;
      const outline = view.keyboard_outline || (viewId === 'front' ? FRONT_KEYBOARD_OUTLINE : null);
      if (!outline || outline.length < 3) throw new Error('缺少键盘外壳轮廓');
      canvas.width = 320;
      canvas.height = Math.round(canvas.width * ch / cw);
      const scale = canvas.width / cw;
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.save();
      try {
        context.beginPath();
        outline.forEach(([x, y], index) => {
          const point = [(x - cx) * scale, (y - cy) * scale];
          if (index === 0) context.moveTo(...point);
          else context.lineTo(...point);
        });
        context.closePath();
        context.clip();
        const sx = image.naturalWidth / sw, sy = image.naturalHeight / sh;
        context.drawImage(image, cx * sx, cy * sy, cw * sx, ch * sy,
          0, 0, canvas.width, canvas.height);
      } finally { context.restore(); }
      return true;
    }

    setFraming(framing) {
      this._ensureActive();
      if (!['keyboard', 'full'].includes(framing)) throw new RangeError('未知画面范围');
      this.framing = framing;
      this._layout();
      return this;
    }

    setRenderer(renderer) {
      this._ensureActive();
      if (!['editor', 'library'].includes(renderer)) throw new RangeError('未知灯珠样式');
      this.renderer = renderer;
      this._layout();
      return this;
    }

    setKeyMode(mode) {
      this._ensureActive();
      if (!['json', 'off', 'photo'].includes(mode)) throw new RangeError('未知轴灯模式');
      this.keyMode = mode;
      this._layout();
      return this;
    }

    setBrightness(percent) {
      this._ensureActive();
      if (!Number.isFinite(Number(percent))) throw new RangeError('亮度需要为数字');
      this.brightness = Math.max(0, Math.min(100, Number(percent)));
      this._drawLights();
      return this;
    }

    setSpeed(ms) {
      this._ensureActive();
      this.speedMs = interval(ms);
      this._resetClock();
      this._emit();
      return this;
    }

    seek(frame) {
      this._ensureActive();
      if (!Number.isFinite(Number(frame))) throw new RangeError('帧序号需要为数字');
      this.pause();
      this._tick = Math.max(0, Math.min(this._combinedFrames - 1, Math.round(Number(frame))));
      this.frame = this._tick % this.frameCount;
      this.keyFrame = this._tick % this.keyFrameCount;
      this._resetClock();
      this._drawLights();
      this._emit();
      return this;
    }

    play() {
      this._ensureActive();
      if (this.error) return this;
      this.playing = true;
      this._resetClock();
      this._schedule();
      this._emit();
      return this;
    }

    pause() {
      if (this._destroyed) return this;
      this.playing = false;
      this._resetClock();
      if (this._raf !== null) global.cancelAnimationFrame(this._raf);
      this._raf = null;
      this._emit();
      return this;
    }

    destroy() {
      if (this._destroyed) return;
      this.pause();
      this._destroyed = true;
      if (this._observer) this._observer.disconnect();
      else global.removeEventListener('resize', this._resizeListener);
      document.removeEventListener('visibilitychange', this._visibilityListener);
      if (this._motion.removeEventListener) this._motion.removeEventListener('change', this._motionListener);
      else if (this._motion.removeListener) this._motion.removeListener(this._motionListener);
      [this.background, this.keyOverlay, this.overlay].forEach(canvas => canvas.remove());
      if (this._errorBanner) this._errorBanner.remove();
      this.container.removeAttribute('data-preview-error');
      this.container.classList.remove('keyboard-preview');
      this.container.classList.remove('keyboard-isolated');
      this.container.removeAttribute('data-preview-background');
      this._keySprites = [];
    }

    _clipKeyboard(context) {
      if (!this._keyboardOutline.length) return;
      context.beginPath();
      this._keyboardOutline.forEach(([x, y], i) => i ? context.lineTo(x, y) : context.moveTo(x, y));
      context.closePath();
      context.clip();
    }

    _prepareKeyLighting(zones) {
      this._keySprites = [];
      if (this.keyMode === 'photo') return;
      const width = this.background.width, height = this.background.height;
      const source = this._bg.getImageData(0, 0, width, height);
      const neutral = this._bg.createImageData(width, height);
      neutral.data.set(source.data);
      const shade = new Float32Array(width * height), coverage = new Float32Array(width * height);
      // Opaque caps show spill around their lower edge, not colors painted over
      // their legends. The material profile is photo metadata, never device RGB.
      const opaque = this.views[this.view].key_lighting === 'opaque';
      const allColors = this.views[this.view].key_neutralization === 'all-colors';
      for (const zone of zones) {
        const q = zone.quad, h = homography(q), inverse = invert(h);
        const x0 = Math.max(0, Math.floor(Math.min(...q.map(p => p[0]))));
        const y0 = Math.max(0, Math.floor(Math.min(...q.map(p => p[1]))));
        const x1 = Math.min(width, Math.ceil(Math.max(...q.map(p => p[0]))));
        const y1 = Math.min(height, Math.ceil(Math.max(...q.map(p => p[1]))));
        const w = x1 - x0, hh = y1 - y0;
        if (w <= 0 || hh <= 0) continue;
        const mask = document.createElement('canvas');
        mask.width = w; mask.height = hh;
        const context = mask.getContext('2d'), pixels = context.createImageData(w, hh);
        const averageWidth = (Math.hypot(q[1][0] - q[0][0], q[1][1] - q[0][1]) + Math.hypot(q[2][0] - q[3][0], q[2][1] - q[3][1])) / 2;
        const averageHeight = (Math.hypot(q[3][0] - q[0][0], q[3][1] - q[0][1]) + Math.hypot(q[2][0] - q[1][0], q[2][1] - q[1][1])) / 2;
        for (let yy = 0; yy < hh; yy++) for (let xx = 0; xx < w; xx++) {
          const [u, v] = project(inverse, x0 + xx + .5, y0 + yy + .5);
          if (u < 0 || u > 1 || v < 0 || v > 1) continue;
          const edge = Math.min(1, Math.min(u, 1 - u) * averageWidth / 2, Math.min(v, 1 - v) * averageHeight / 2);
          const spatial = Math.exp(-(((u - zone.lamp_uv[0]) / zone.spread_x) ** 2 + ((v - zone.lamp_uv[1]) / .46) ** 2));
          const index = (y0 + yy) * width + x0 + xx, p = index * 4;
          const r = source.data[p], g = source.data[p + 1], b = source.data[p + 2];
          const maximum = Math.max(r, g, b), minimum = Math.min(r, g, b);
          const signal = Math.min(255, (maximum - minimum) * .7 + maximum * (.28 + .18 * spatial));
          const dest = (yy * w + xx) * 4;
          pixels.data[dest] = pixels.data[dest + 1] = pixels.data[dest + 2] = 255;
          const rim = Math.exp(-Math.min(u, 1 - u, v, 1 - v) * Math.min(averageWidth, averageHeight) / 1.5);
          pixels.data[dest + 3] = opaque
            ? Math.round(90 * spatial * edge * rim)
            : Math.round(Math.min(255, signal * spatial * edge));
          if (!opaque) {
            coverage[index] = Math.max(coverage[index], edge);
            shade[index] = Math.max(shade[index], (.22 + .6 * spatial) * edge);
          }
        }
        context.putImageData(pixels, 0, 0);
        const colored = document.createElement('canvas');
        colored.width = w; colored.height = hh;
        this._keySprites.push({ index: zone.index, x: x0, y: y0, w, h: hh, mask, colored, ctx: colored.getContext('2d') });
      }
      // Estimate unlit glass from the photo; preserve print, highlights and orange materials.
      for (let index = 0; index < coverage.length; index++) {
        if (coverage[index] === 0) continue;
        const p = index * 4, r = source.data[p], g = source.data[p + 1], b = source.data[p + 2];
        const maximum = Math.max(r, g, b), minimum = Math.min(r, g, b);
        const blueish = (b > r * .5 && b > g * 1.05) || b > r * 1.1;
        const gray = minimum + (maximum - minimum) * .25;
        const lit = allColors || blueish;
        const decolor = lit ? coverage[index] : 0;
        const dim = 1 - shade[index] * (lit ? .82 : .42);
        for (let channel = 0; channel < 3; channel++) {
          neutral.data[p + channel] = Math.round((source.data[p + channel] * (1 - decolor) + gray * decolor) * dim);
        }
      }
      this._bg.putImageData(neutral, 0, 0);
    }

    _drawKeyLights() {
      this._key.clearRect(0, 0, this.keyOverlay.width, this.keyOverlay.height);
      if (this.keyMode !== 'json') return;
      this._key.save();
      this._clipKeyboard(this._key);
      this._key.globalCompositeOperation = 'screen';
      const offset = this.keyFrame * 270, brightness = this.brightness / 100;
      for (const sprite of this._keySprites) {
        const at = offset + sprite.index * 3;
        const color = [this._keyBytes[at], this._keyBytes[at + 1], this._keyBytes[at + 2]].map(c => Math.round(c * brightness));
        if (color.every(c => c === 0)) continue;
        const context = sprite.ctx;
        context.globalCompositeOperation = 'source-over';
        context.clearRect(0, 0, sprite.w, sprite.h);
        context.fillStyle = 'rgb(' + color.join(',') + ')';
        context.fillRect(0, 0, sprite.w, sprite.h);
        context.globalCompositeOperation = 'destination-in';
        context.drawImage(sprite.mask, 0, 0);
        this._key.drawImage(sprite.colored, sprite.x, sprite.y);
      }
      this._key.globalCompositeOperation = 'source-over';
      this._key.restore();
    }

    _buildMesh(q) {
      const h = homography(q), triangles = [], columns = 16, rows = 4;
      for (let y = 0; y < rows; y++) for (let x = 0; x < columns; x++) {
        const uv = [[x / columns, y / rows], [(x + 1) / columns, y / rows],
          [(x + 1) / columns, (y + 1) / rows], [x / columns, (y + 1) / rows]];
        for (const ids of [[0, 1, 2], [0, 2, 3]]) {
          const src = ids.map(i => [uv[i][0] * this._texture.width, uv[i][1] * this._texture.height]);
          const dst = ids.map(i => project(h, ...uv[i]));
          triangles.push({ dst, transform: affine(src, dst) });
        }
      }
      return triangles;
    }

    _drawTexture() {
      const tx = this._tx;
      tx.fillStyle = '#020405';
      tx.fillRect(0, 0, this._texture.width, this._texture.height);
      const offset = this.frame * 600, brightness = this.brightness / 100;
      for (let i = 0; i < 200; i++) {
        const r = Math.round(this._frameBytes[offset + i * 3] * brightness);
        const g = Math.round(this._frameBytes[offset + i * 3 + 1] * brightness);
        const b = Math.round(this._frameBytes[offset + i * 3 + 2] * brightness);
        if (this.renderer === 'library') {
          tx.fillStyle = 'rgb(' + [r, g, b].join(',') + ')';
          tx.beginPath(); tx.roundRect(5 + (i % 40) * 40, 5 + Math.floor(i / 40) * 40, 35, 35, 9); tx.fill();
        } else {
          // Keep the same-color glow within the design RGB; this is a visual material, not hardware calibration.
          const x = (i % 40) * 40 + 20, y = Math.floor(i / 40) * 40 + 20;
          const size = 35.2, radius = size * .2;
          tx.beginPath(); tx.roundRect(x - size / 2, y - size / 2, size, size, radius);
          tx.fillStyle = 'rgb(' + [r, g, b].map(c => Math.round(c * .6)).join(',') + ')'; tx.fill();
          const center = [r, g, b];
          const grad = tx.createRadialGradient(x, y, 0, x, y, Math.hypot(size / 2, size / 2));
          grad.addColorStop(0, 'rgb(' + center.join(',') + ')');
          grad.addColorStop(.25, 'rgb(' + center.join(',') + ')');
          grad.addColorStop(1, 'rgba(' + center.join(',') + ',0)');
          tx.fillStyle = grad; tx.fill();
        }
      }
    }

    _drawLights() {
      if (!this._ready || this._destroyed || this.error) return false;
      try {
        this._drawLightsCanvas();
        return true;
      } catch (error) {
        this._reportError(error, '灯效绘制');
        return false;
      }
    }

    _drawLightsCanvas() {
      this._drawTexture();
      this._led.clearRect(0, 0, this.overlay.width, this.overlay.height);
      this._led.save();
      this._clipKeyboard(this._led);
      this._led.fillStyle = '#020405';
      this._led.beginPath();
      this._screenQuad.forEach(([x, y], i) => i ? this._led.lineTo(x, y) : this._led.moveTo(x, y));
      this._led.closePath(); this._led.fill();
      for (const triangle of this._warpTriangles) {
        this._led.save(); this._led.beginPath();
        triangle.dst.forEach(([x, y], i) => i ? this._led.lineTo(x, y) : this._led.moveTo(x, y));
        this._led.closePath(); this._led.clip();
        this._led.setTransform(...triangle.transform);
        this._led.drawImage(this._texture, 0, 0);
        this._led.restore();
      }
      this._led.restore();
      this._drawKeyLights();
    }

    _layout() {
      if (!this._ready || this._destroyed) return false;
      try {
        this._layoutCanvas();
        this._clearError();
        return true;
      } catch (error) {
        this._reportError(error, '照片投影');
        return false;
      }
    }

    _layoutCanvas() {
      const view = this.views[this.view], image = this._images[this.view];
      const [sw, sh] = view.source_size;
      // full_crop excludes the baked watermark strip in both original photographs.
      const [cx, cy, cw, ch] = this.framing === 'full' ? view.full_crop : view.crop;
      const tw = this.renderer === 'library' ? 1605 : 1600, th = this.renderer === 'library' ? 205 : 200;
      if (this._texture.width !== tw || this._texture.height !== th) {
        this._texture.width = tw; this._texture.height = th;
      }
      this.container.style.aspectRatio = cw + ' / ' + ch;
      const viewport = containBounds(this.container.clientWidth, this.container.clientHeight, cw, ch);
      const desiredWidth = Math.max(640, Math.round(viewport.width * Math.min(global.devicePixelRatio || 1, 2)));
      const width = Math.min(1400, desiredWidth), height = Math.round(width * ch / cw);
      // Explicit CSS geometry is compatible with older WKWebView/WebView2 and
      // prevents photo, key lights and top lights from choosing different fits.
      for (const layer of [this.background, this.overlay, this.keyOverlay]) {
        layer.style.width = viewport.width + 'px';
        layer.style.height = viewport.height + 'px';
        layer.style.left = viewport.left + 'px';
        layer.style.top = viewport.top + 'px';
        layer.style.right = layer.style.bottom = 'auto';
      }
      this.viewport = viewport;
      this.background.width = this.overlay.width = this.keyOverlay.width = width;
      this.background.height = this.overlay.height = this.keyOverlay.height = height;
      const isolated = this.framing === 'keyboard' && (this.view === 'front' || Array.isArray(view.keyboard_outline));
      const outline = isolated ? (view.keyboard_outline || FRONT_KEYBOARD_OUTLINE) : [];
      if (isolated && (!Array.isArray(outline) || outline.length < 3 || outline.some(point =>
        !Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite) ||
        point[0] < 0 || point[0] > sw || point[1] < 0 || point[1] > sh))) {
        throw new TypeError('键盘外壳轮廓需要为照片坐标内的有效多边形');
      }
      this._keyboardOutline = outline.map(([x, y]) => [(x - cx) * width / cw, (y - cy) * height / ch]);
      this.container.classList[isolated ? 'add' : 'remove']('keyboard-isolated');
      this.container.setAttribute('data-preview-background', isolated ? 'isolated' : 'photo');
      this.background.setAttribute('aria-label', isolated
        ? 'Cyberboard 实体键盘，保留外壳、键帽和真实印花，背景透明'
        : 'Cyberboard 实体照片，含外壳、键帽和桌面环境');
      const sx = image.naturalWidth / sw, sy = image.naturalHeight / sh;
      this._bg.save();
      this._clipKeyboard(this._bg);
      this._bg.drawImage(image, cx * sx, cy * sy, cw * sx, ch * sy, 0, 0, width, height);
      this._bg.restore();
      const zones = (view.keyZones || []).map(zone => ({ ...zone,
        quad: zone.quad.map(([x, y]) => [(x - cx) * width / cw, (y - cy) * height / ch]) }));
      this._prepareKeyLighting(zones);
      const q = view.quad.map(([x, y]) => [(x - cx) * width / cw, (y - cy) * height / ch]);
      this._screenQuad = view.mask_quad.map(([x, y]) => [(x - cx) * width / cw, (y - cy) * height / ch]);
      this._warpTriangles = this._buildMesh(q);
      this._drawLightsCanvas();
    }
  }

  KeyboardPreview.isGalleryAllowed = galleryAllowed;
  KeyboardPreview.containBounds = containBounds;
  global.KeyboardPreview = KeyboardPreview;
})(window);
