(function (global) {
  'use strict';
  const catalog = global.STUDIO_COMPANION_CATALOG;
  function zoneAt(x, y) {
    return catalog.zones.find(z => x >= z.rect[0] && y >= z.rect[1] && x <= z.rect[0] + z.rect[2] && y <= z.rect[1] + z.rect[3]);
  }
  function create({ $, api, native, toast, busy }) {
    let preferences = { ...catalog.defaults }, custom = [], selected = preferences.outfit;
    let settingsDirty = false;
    let tab = 'companion', generation = 0, pending = false, timer = null, last = 0, lastZone = {};
    const layout = document.querySelector('.miaocall-layout');
    const stage = $('miaoCallStage'), art = stage.querySelector('img'); art.id = 'companionArt';
    const controls = document.createElement('section'); controls.className = 'settings-card companion-controls';
    controls.innerHTML = `<h2>桌面陪伴</h2><p class="companion-subtitle">让她留在桌面，也可以只在你唤醒时出现。</p>
      <div class="companion-fields"><label>出现方式<select id="companionMode"><option value="wake">仅唤醒时出现</option><option value="resident">常驻桌面</option></select></label>
      <label>角色大小 <output id="companionSizeLabel">340</output><input id="companionSize" type="range" min="240" max="440" step="10" value="340"></label>
      <label class="companion-check"><input id="companionHover" type="checkbox" checked>鼠标停留互动</label><label class="companion-check"><input id="companionSound" type="checkbox">互动声音</label>
      <label>声线<select id="companionVoice"></select></label><label>音量<input id="companionVolume" type="range" min="0" max="1" step="0.05" value="0.45"></label></div>
      <p class="companion-note">四种内置离线声线，声音默认关闭。停留约半秒才回应，同一部位有冷却；拖动与语音任务时不闲聊。</p>
      <div class="miaocall-actions"><button class="button" id="companionAudition">试听声线</button><button class="button primary" id="companionSave">应用桌面设置</button></div>
      <p class="companion-note" id="companionSavedNote" role="status"></p>
      <details class="companion-touch-guide"><summary>15 处互动 · 查看动作设计</summary><div id="companionZoneList"></div></details>`;
    const wardrobe = document.createElement('section'); wardrobe.className = 'settings-card companion-wardrobe';
    wardrobe.innerHTML = `<h2>她的衣橱</h2><p class="companion-subtitle">橙白水手服、奶油针织 JK、雪白套装；水手服另有长发。</p>
      <div class="companion-hair" role="group" aria-label="发型"><button class="button" data-hair="all">全部</button><button class="button" data-hair="short">短发</button><button class="button" data-hair="long">长发</button></div>
      <div class="companion-outfits" id="companionOutfits"></div><div class="miaocall-actions"><button class="button primary" id="companionWear">穿上这一套</button><button class="button" id="companionDelete" hidden>删除 AI 衣装</button></div>
      <p class="companion-note" id="companionOutfitNote" role="status">内置套装各有 8 个独立姿势，AI 新衣装目前为静态立绘。</p>
      <details class="companion-ai"><summary>AI 换装</summary><label class="sr-only" for="companionBrief">衣装描述</label><textarea id="companionBrief" maxlength="600" rows="3" placeholder="例如：奶白针织上衣、浅灰百褶裙、白色膝袜，橙色小领结。"></textarea>
      <label>发型<select id="companionGenerateHair"><option value="short">保留短发</option><option value="long">橙白长发</option></select></label>
      <details><summary>生图连接 · MiniMax image-01</summary><label>接口区域<select id="companionImageRegion"><option value="china">中国区</option><option value="global">国际区</option></select></label>
      <label>生图 API Key<input id="companionImageKey" type="password" autocomplete="off" placeholder="按服务保存在本机"></label><button class="button" id="companionImageReveal">显示</button>
      <label class="companion-check"><input id="companionReuseVoice" type="checkbox">使用已保存的 MiniMax 语音 Key</label><button class="button" id="companionImageSave">保存连接</button><p class="companion-note" id="companionImageStatus"></p></details>
      <button class="button primary" id="companionGenerate">生成衣装预览</button><button class="button" id="companionGenerateCancel" hidden>取消生成</button><p class="companion-note" id="companionGenerateStatus" role="status">仅点击生成时提交角色参考与服装描述。先预览，再由你决定穿上；生图按服务账户计费。</p></details>`;
    const tabs = document.createElement('div'); tabs.className = 'companion-tabs'; tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '喵唤功能');
    for (const [id, name] of [['companion', '桌面陪伴'], ['wardrobe', '换装衣橱'], ['tasks', '语音任务']]) {
      const b = document.createElement('button'); b.className = 'button'; b.textContent = name; b.setAttribute('role', 'tab'); b.dataset.tab = id;
      b.onclick = () => switchTab(id); tabs.appendChild(b);
      b.onkeydown = event => { const buttons = [...tabs.querySelectorAll('button')]; let i = buttons.indexOf(b); if (event.key === 'ArrowRight') i = (i + 1) % buttons.length; else if (event.key === 'ArrowLeft') i = (i + buttons.length - 1) % buttons.length; else if (event.key === 'Home') i = 0; else if (event.key === 'End') i = buttons.length - 1; else return; event.preventDefault(); switchTab(buttons[i].dataset.tab); buttons[i].focus(); };
    }
    layout.before(tabs);
    controls.addEventListener('input', () => settingsDirty = true); controls.addEventListener('change', () => settingsDirty = true);
    const setup = layout.querySelector('.miaocall-setup'); const original = Array.from(setup.children);
    setup.prepend(wardrobe); setup.prepend(controls);
    const zones = document.createElement('div'); zones.id = 'companionHotspots'; zones.className = 'companion-hotspots'; stage.appendChild(zones);
    const caption = document.createElement('div'); caption.className = 'companion-caption'; stage.appendChild(caption);
    const bubble = document.createElement('div'); bubble.className = 'companion-preview-bubble'; bubble.id = 'companionPreviewBubble'; bubble.setAttribute('aria-live', 'polite'); stage.appendChild(bubble);
    function outfit() { return [...catalog.outfits, ...custom].find(o => o.id === selected) || catalog.outfits[0]; }
    function picture(pose = 'idle') { const o = outfit(); art.src = o.imageDataUrl || o.frames[pose] || o.frames.idle; art.alt = o.name + (o.hair === 'long' ? ' · 长发' : ' · 短发'); }
    function switchTab(next) {
      tab = next; tabs.querySelectorAll('button').forEach(b => { const active = b.dataset.tab === tab; b.setAttribute('aria-selected', String(active)); b.tabIndex = active ? 0 : -1; });
      controls.hidden = tab !== 'companion'; wardrobe.hidden = tab !== 'wardrobe'; original.forEach(el => el.hidden = tab !== 'tasks');
      zones.hidden = tab === 'tasks'; bubble.textContent = ''; picture();
      stage.dataset.companion = tab === 'tasks' ? 'false' : 'true';
      caption.textContent = tab === 'wardrobe' ? '衣橱预览 · 选好后再穿上' : '拖动桌面喵娘，放在喜欢的位置。'; caption.hidden = tab === 'tasks';
    }
    let hairFilter = 'all';
    function renderOutfits() {
      $('companionOutfits').replaceChildren();
      for (const o of [...catalog.outfits, ...custom].filter(o => hairFilter === 'all' || o.hair === hairFilter || !o.builtin)) {
        const card = document.createElement('button'); card.className = 'companion-outfit'; card.setAttribute('aria-pressed', String(selected === o.id));
        const image = document.createElement('img'); image.src = o.imageDataUrl || o.frames.idle; image.alt = ''; image.loading = 'lazy';
        const name = document.createElement('strong'); name.textContent = o.name;
        const hint = document.createElement('span'); hint.textContent = o.builtin ? (o.hair === 'long' ? '长发 · 8 姿势' : '短发 · 8 姿势') : 'AI 衣装 · 静态';
        card.append(image, name, hint); card.onclick = () => { selected = o.id; renderOutfits(); picture(); };
        $('companionOutfits').appendChild(card);
      }
      $('companionDelete').hidden = outfit().builtin !== false;
    }
    wardrobe.querySelectorAll('[data-hair]').forEach(b => { b.setAttribute('aria-pressed', String(b.dataset.hair === hairFilter)); b.onclick = () => { hairFilter = b.dataset.hair; wardrobe.querySelectorAll('[data-hair]').forEach(v => v.setAttribute('aria-pressed', String(v.dataset.hair === hairFilter))); renderOutfits(); }; });
    function react(z, explicit = false) {
      if (busy() || (tab === 'tasks' && !explicit)) return;
      const now = Date.now();
      if (!explicit && (now - last < 3200 || now - (lastZone[z.id] || 0) < 9000)) return;
      last = now; lastZone[z.id] = now; picture(z.pose); bubble.textContent = z.text;
      clearTimeout(timer); timer = setTimeout(() => { picture(); bubble.textContent = ''; }, 2400);
    }
    catalog.zones.forEach(z => {
      const b = document.createElement('button'); b.className = 'companion-hotspot'; b.title = z.name; b.setAttribute('aria-label', '互动：' + z.name);
      const [x, y, w, h] = z.rect; Object.assign(b.style, { left: x * 100 + '%', top: y * 100 + '%', width: w * 100 + '%', height: h * 100 + '%', zIndex: String(catalog.zones.length - catalog.zones.indexOf(z)) });
      let dwell; b.onpointerenter = () => { if ($('companionHover').checked) dwell = setTimeout(() => react(z), 480); };
      b.onpointerleave = () => clearTimeout(dwell); b.onclick = () => react(z, true); zones.appendChild(b);
      const line = document.createElement('button'); line.className = 'companion-zone-demo'; line.textContent = z.name + ' · ' + z.text;
      line.onclick = () => { react(z, true); if (native) api('miaoCallCompanionTest', { zone: z.id }).catch(e => toast(e.message)); }; $('companionZoneList').appendChild(line);
    });
    catalog.voices.forEach(v => { const o = document.createElement('option'); o.value = v.id; o.textContent = v.name; $('companionVoice').appendChild(o); });
    function populate() {
      $('companionMode').value = preferences.mode; $('companionSound').checked = preferences.sound; $('companionHover').checked = preferences.hover;
      $('companionVoice').value = preferences.voice; $('companionVolume').value = preferences.volume; $('companionSize').value = preferences.size; $('companionSizeLabel').value = preferences.size;
    }
    function candidate() { return { ...preferences, mode: $('companionMode').value, sound: $('companionSound').checked, hover: $('companionHover').checked, voice: $('companionVoice').value, volume: Number($('companionVolume').value), size: Number($('companionSize').value), outfit: selected }; }
    async function save() {
      if (!native) { toast('桌面常驻与声音设置请在 macOS App 中使用。'); return; }
      try { const result = await api('miaoCallCompanionSave', candidate()); settingsDirty = false; update(result); $('companionSavedNote').textContent = '已保存；桌面显示与声音设置已生效。'; return true; }
      catch (e) { toast(e.message); return false; }
    }
    $('companionSize').oninput = () => $('companionSizeLabel').value = $('companionSize').value;
    $('companionSave').onclick = save; $('companionWear').onclick = save;
    $('companionAudition').onclick = async () => {
      if (!native) { toast('声线试听请在 macOS App 中使用。'); return; }
      try { await api('miaoCallCompanionTest', { zone: 'cheek', sound: true, voice: $('companionVoice').value, volume: Number($('companionVolume').value) }); } catch (e) { toast(e.message); }
    };
    $('companionDelete').onclick = async () => {
      if (!native || outfit().builtin !== false) return;
      try { await api('miaoCallOutfitDelete', { id: selected }); custom = custom.filter(o => o.id !== selected); selected = catalog.outfits[0].id; renderOutfits(); picture(); }
      catch (e) { toast(e.message); }
    };
    $('companionImageSave').onclick = async () => {
      if (!native) { toast('AI 换装需使用桌面 App。'); return; }
      try { const s = await api('miaoCallImageSave', { apiKey: $('companionImageKey').value, region: $('companionImageRegion').value, reuseVoiceKey: $('companionReuseVoice').checked }); $('companionImageKey').value = ''; $('companionImageKey').type = 'password'; $('companionImageStatus').textContent = s.hasKey ? '连接已保存。需要 image-01 生图权限，Coding Key 不一定可用。' : '尚未保存 Key。'; } catch (e) { toast(e.message); }
    };
    $('companionImageReveal').onclick = async () => {
      if (!native) return;
      try { const input = $('companionImageKey'); if (input.type === 'password') { input.value = (await api('miaoCallImageReveal')).apiKey || input.value; input.type = 'text'; $('companionImageReveal').textContent = '隐藏'; } else { input.type = 'password'; $('companionImageReveal').textContent = '显示'; } } catch (e) { toast(e.message); }
    };
    $('companionGenerateCancel').onclick = async () => {
      if (!pending) return;
      generation += 1; pending = false; $('companionGenerateCancel').hidden = true; $('companionGenerate').disabled = false;
      $('companionGenerateStatus').textContent = '已取消生成，描述已保留。';
      try { await api('miaoCallOutfitCancel'); } catch (e) { toast(e.message); }
    };
    $('companionGenerate').onclick = async () => {
      if (!native) { toast('AI 换装需使用桌面 App。'); return; }
      if (pending || busy()) return;
      const prompt = $('companionBrief').value.trim(); if (!prompt) { toast('先描述想穿的衣服。'); return; }
      const token = ++generation; pending = true; $('companionGenerate').disabled = true; $('companionGenerateCancel').hidden = false; $('companionGenerateStatus').textContent = '正在生成衣装，完成后先预览，不会自动换上。';
      try { const result = await api('miaoCallOutfitGenerate', { prompt, hair: $('companionGenerateHair').value }); if (token !== generation) return; custom.push(result); selected = result.id; hairFilter = 'all'; renderOutfits(); picture(); $('companionGenerateStatus').textContent = '衣装预览已就绪。喜欢的话，点击「穿上这一套」。'; }
      catch (e) { if (token === generation) $('companionGenerateStatus').textContent = e.message; }
      finally { if (token === generation) { pending = false; $('companionGenerate').disabled = false; $('companionGenerateCancel').hidden = true; } }
    };
    function update(status) { if (status.companion) { const wasApplied = selected === preferences.outfit, changed = status.companion.outfit !== preferences.outfit; preferences = { ...preferences, ...status.companion }; if (wasApplied || changed) selected = preferences.outfit; if (!settingsDirty) populate(); } if (status.customOutfits) custom = status.customOutfits; renderOutfits(); if (tab !== 'tasks') picture(); }
    async function load() { if (!native) return; try { update(await api('miaoCallStatus')); const s = await api('miaoCallImageSettings'); $('companionImageRegion').value = s.region; $('companionReuseVoice').disabled = !s.canReuseVoiceKey; $('companionImageStatus').textContent = s.hasKey ? '生图 Key 已保存。' : '填写支持 image-01 的 MiniMax Key，或选择已有语音 Key。'; } catch (e) { $('companionImageStatus').textContent = e.message; } }
    populate(); renderOutfits(); switchTab('companion'); load();
    return { update, zoneAt };
  }
  global.StudioCompanion = { create, zoneAt };
})(window);
