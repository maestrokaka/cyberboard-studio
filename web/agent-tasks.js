(function (global) {
  'use strict';
  const RUNNING = new Set(['connecting', 'thinking', 'acting', 'awaitingApproval', 'awaitingInput', 'cancelling']);
  const LABELS = {idle:'未开始',running:'进行中',completed:'已返回结果',cancelled:'已停止',interrupted:'可继续',error:'未完成'};
  function create({ $, api, native, toast, navigate, options, status }) {
    const setup = document.querySelector('.miaocall-setup');
    const panel = document.createElement('section'); panel.className = 'settings-card agent-tasks';
    panel.innerHTML = '<div class="label-row"><h2>交代一个任务</h2><div><button class="text-button" id="agentTaskReload">刷新记录</button><button class="text-button" id="agentTaskDiagnostics">复制诊断</button></div></div>' +
      '<p class="companion-note">交给本机 Codex 完成文件、资料或项目任务。任务文字与结果保存在本机，可继续追问。</p>' +
      '<div class="agent-task-history"><label for="agentTaskSelect">任务记录</label><select id="agentTaskSelect"><option value="">新任务</option></select><button class="button" id="agentTaskNew">新任务</button><button class="button" id="agentTaskArchive" hidden>归档</button><button class="text-button" id="agentTaskDelete" hidden>删除记录</button></div>' +
      '<label class="companion-check"><input id="agentTaskShowArchived" type="checkbox">查看已归档任务</label>' +
      '<div class="agent-task-context"><span id="agentTaskFolder"></span><button class="text-button" id="agentTaskChooseFolder">选择目录</button><button class="text-button" id="agentTaskRevealFolder">在 Finder 查看</button></div>' +
      '<label class="companion-check"><input id="agentTaskWrite" type="checkbox">允许修改新任务的工作目录</label>' +
      '<p class="companion-note" id="agentTaskPermissionNote">默认仅查看；额外权限需要你明确确认。本机 Codex 的可用工具决定实际能力。</p>' +
      '<div id="agentTaskLog" class="agent-task-log" role="log" aria-label="Codex 任务对话"></div>' +
      '<details id="agentTaskSteps" hidden><summary>执行步骤</summary><pre id="agentTaskStepsText"></pre></details>' +
      '<div id="agentTaskFiles" class="agent-task-files"></div><div id="agentTaskRequest" class="agent-task-request" hidden role="region" aria-label="Codex 等待你的答复"></div>' +
      '<label class="sr-only" for="agentTaskInput">交给 Codex 的任务或补充指令</label><textarea id="agentTaskInput" rows="3" maxlength="2000" placeholder="例如：总结附件中的资料；整理这个目录；检查项目并修复一个问题。"></textarea>' +
      '<div id="agentTaskAttachments" class="agent-task-files"></div><div class="miaocall-actions"><button class="button" id="agentTaskAttach">添加文件</button><button class="button primary" id="agentTaskSend">交给 Codex</button><button class="button" id="agentTaskStop" hidden>停止任务</button><button class="button" id="agentTaskExport" hidden>导出记录</button></div>' +
      '<p class="companion-note" id="agentTaskNotice" role="status">生成文件与实际修改请在结果中核对；停止任务不会撤销已经发生的操作。</p>';
    setup.prepend(panel);
    panel.querySelector('.miaocall-actions').prepend($('miaoHoldBtn'));
    $('miaoHoldBtn').setAttribute('aria-label', '按住说出任务');
    const music = $('miaoTrackLink').closest('.settings-card');
    const details = document.createElement('details'); details.className = 'agent-spotify-example';
    const summary = document.createElement('summary'); summary.textContent = 'Spotify 示例（可选）'; details.appendChild(summary);
    music.replaceWith(details); details.appendChild(music);
    const enabled = document.createElement('label'); enabled.className = 'companion-check';
    enabled.innerHTML = '<input id="miaoUseSpotify" type="checkbox">启用已配置歌曲的播放验证工具';
    music.prepend(enabled);
    let tasks = [], selected = '', record = null, context = null, attachments = [], revision = 0, liveText = '', liveSteps = [], current = status(), requestId = '', sending = false, pendingMessages = [];
    function button(text, fn) { const b = document.createElement('button'); b.className = 'button'; b.textContent = text; b.onclick = fn; return b; }
    function note(text) { $('agentTaskNotice').textContent = text; }
    function drawMessages() {
      const log = $('agentTaskLog'); log.replaceChildren();
      for (const item of [...(record?.messages || []), ...pendingMessages]) {
        const entry = document.createElement('div'); entry.className = 'agent-task-message ' + (item.role === 'user' ? 'user' : 'assistant');
        const label = document.createElement('strong'); label.textContent = item.role === 'user' ? '你' : 'Codex';
        const text = document.createElement('div'); text.textContent = item.text || ''; entry.append(label, text); log.appendChild(entry);
      }
      if (liveText) { const text = document.createElement('div'); text.className = 'agent-task-message assistant'; text.textContent = liveText; log.appendChild(text); }
      if (!log.children.length) { const empty = document.createElement('p'); empty.className = 'companion-note'; empty.textContent = '从一句任务开始。也可以按住键盘「·」交代给 Codex。'; log.appendChild(empty); }
      const steps = liveSteps.length ? liveSteps : record?.steps || [];
      $('agentTaskSteps').hidden = !steps.length;
      $('agentTaskStepsText').textContent = steps.map(s => s.title + ' · ' + s.status + (s.exitCode !== undefined ? ' · 返回 ' + s.exitCode : '') + '\n' + (s.detail || '')).join('\n\n');
      $('agentTaskFiles').replaceChildren();
      for (const path of record?.artifacts || current.taskResult?.artifacts || []) {
        const b = button('查看文件：' + path.split('/').pop(), () => api('miaoCallTaskReveal', { taskId: selected, path }).catch(e => toast(e.message)));
        b.title = path; $('agentTaskFiles').appendChild(b);
      }
    }
    function refreshControls() {
      const running = RUNNING.has(current.state), canSteer = ['thinking','acting','connecting'].includes(current.state);
      const busy = running || ['configuring','preparing','listening','transcribing','awaitingConfirmation'].includes(current.state);
      $('agentTaskSelect').disabled = busy; $('agentTaskNew').disabled = busy;
      $('agentTaskChooseFolder').disabled = busy || !!selected; $('agentTaskWrite').disabled = busy || !!selected;
      $('agentTaskDelete').hidden = !record?.archived; $('agentTaskDelete').disabled = busy;
      $('agentTaskArchive').disabled = busy; $('agentTaskArchive').hidden = !selected;
      $('agentTaskArchive').textContent = record?.archived ? '恢复任务' : '归档';
      $('agentTaskSend').disabled = sending || !native || busy && !canSteer || !!record?.archived;
      $('agentTaskSend').textContent = canSteer ? '补充指令' : selected ? '继续任务' : '交给 Codex';
      $('agentTaskStop').hidden = !running; $('agentTaskStop').disabled = current.state === 'cancelling';
      $('agentTaskAttach').disabled = !native || busy;
      $('agentTaskExport').hidden = !selected;
      const scope = record || context;
      $('agentTaskFolder').textContent = scope?.cwd || '正在读取工作目录…';
      $('agentTaskWrite').checked = scope?.mode === 'workspace-write';
      $('agentTaskPermissionNote').textContent = selected ? '沿用此任务的目录与权限。执行时需要额外权限，Codex 会向你请求。' : '默认仅查看；勾选后可修改此工作目录。其他权限需要你逐次确认。';
    }
    async function select(identity, tellHost = true) {
      const token = ++revision; selected = identity || ''; record = null; attachments = []; pendingMessages = []; liveText = ''; liveSteps = [];
      if (tellHost && native) await api('miaoCallTaskSelect', { taskId: selected || null });
      if (selected && native) {
        const data = await api('miaoCallTaskRead', { taskId: selected }); if (token !== revision) return; record = data;
      }
      $('agentTaskSelect').value = selected; renderAttachments(); drawMessages(); refreshControls();
    }
    function fillHistory() {
      const select = $('agentTaskSelect'); select.replaceChildren();
      const first = document.createElement('option'); first.value = ''; first.textContent = '新任务'; select.appendChild(first);
      for (const t of tasks.filter(t => !!t.archived === $('agentTaskShowArchived').checked)) {
        const option = document.createElement('option'); option.value = t.id;
        option.textContent = t.title + ' · ' + (LABELS[t.status] || t.status); select.appendChild(option);
      }
      select.value = selected;
    }
    async function load() {
      if (!native) { context = { cwd: '桌面 App 中选择目录', mode: 'read-only' }; refreshControls(); return; }
      try {
        const data = await api('miaoCallTaskList'); tasks = data.tasks || []; context = data.context;
        fillHistory();
        if (RUNNING.has(current.state)) {
          if (current.taskId && current.taskId !== selected) selected = current.taskId;
          if (selected) record = await api('miaoCallTaskRead', { taskId: selected });
          refreshControls(); drawMessages();
        } else if (selected) await select(selected, false);
        else { refreshControls(); drawMessages(); }
      } catch (e) { note(e.message); }
    }
    function renderAttachments() {
      $('agentTaskAttachments').replaceChildren();
      for (const path of attachments) {
        const b = button(path.split('/').pop() + ' ×', () => { attachments = attachments.filter(p => p !== path); renderAttachments(); });
        b.title = path; $('agentTaskAttachments').appendChild(b);
      }
    }
    async function send() {
      if (sending) return;
      const text = $('agentTaskInput').value.trim();
      if (!text || text.length > 2000) { toast('请填写 1–2000 字的任务。'); return; }
      if (!native) { toast('任务执行需使用 macOS App。'); return; }
      sending = true; refreshControls();
      try {
        if (['thinking','acting','connecting'].includes(current.state)) await api('miaoCallTaskSteer', { text });
        else {
          liveText = ''; liveSteps = [];
          const value = await api('miaoCallRunTask', { text, taskId: selected || null, attachments, tracks: options().tracks });
          update(value); note('已交给 Codex。需要回答或授权时会在这里显示。');
        }
        pendingMessages.push({role:'user',text}); drawMessages();
        $('agentTaskInput').value = '';
      } catch (e) { note(e.message); } finally { sending = false; refreshControls(); }
    }
    function requestForm(request) {
      const nextId = request?.id || ''; if (nextId === requestId) return; requestId = nextId;
      const root = $('agentTaskRequest'); root.replaceChildren(); root.hidden = !request?.id; if (!request?.id) return;
      const title = document.createElement('h3'); title.textContent = request.title || 'Codex 等待你'; root.appendChild(title);
      const text = document.createElement('pre'); text.textContent = [request.reason, request.command, request.cwd,
        request.permissions && JSON.stringify(request.permissions, null, 2), request.network && JSON.stringify(request.network, null, 2)].filter(Boolean).join('\n'); root.appendChild(text);
      const inputs = {};
      for (const q of request.questions || []) {
        const label = document.createElement('label'); label.textContent = q.question;
        if (q.options?.length) {
          const choices = document.createElement('select'); const empty = document.createElement('option'); empty.textContent = '选择建议，或在下方填写'; empty.value = ''; choices.appendChild(empty);
          for (const o of q.options) { const item = document.createElement('option'); item.value = o.label; item.textContent = o.label + (o.description ? ' · ' + o.description : ''); choices.appendChild(item); }
          label.appendChild(choices); choices.onchange = () => inputs[q.id].value = choices.value;
        }
        const input = document.createElement('input'); input.type = q.isSecret ? 'password' : 'text'; input.maxLength = 2000; input.autocomplete = 'off';
        label.appendChild(input); root.appendChild(label); inputs[q.id] = input;
      }
      async function respond(decision) {
        const answers = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value]));
        if (decision === 'accept' && request.kind === 'questions' && Object.values(answers).some(v => !v.trim())) { toast('请先补充问题的答案。'); return; }
        root.querySelectorAll('button').forEach(b => b.disabled = true);
        try { const value = await api('miaoCallTaskRespond', { id: request.id, decision, answers: decision === 'accept' ? answers : {} }); update(value); requestId = ''; root.replaceChildren(); root.hidden = true; }
        catch (e) { note(e.message); root.querySelectorAll('button').forEach(b => b.disabled = false); }
      }
      root.appendChild(button(request.kind === 'questions' ? '提交回答' : request.kind === 'unsupported' ? '返回任务' : '仅允许这一次', () => respond('accept')));
      root.appendChild(button('拒绝', () => respond('decline')));
    }
    function update(value) {
      current = { ...current, ...value };
      if (value.taskId && RUNNING.has(current.state)) selected = value.taskId;
      requestForm(current.request); refreshControls();
      if (['completed','cancelled','error'].includes(value.state)) { if (value.taskId) selected = value.taskId; liveText = ''; liveSteps = []; load(); }
    }
    function event(value) {
      if (value.type === 'openTask') { navigate('miaocall'); document.querySelector('[data-tab="tasks"]')?.click(); load(); }
      else if (value.type === 'text') { liveText = (liveText + (value.delta || '')).slice(-16000); drawMessages(); }
      else if (value.type === 'state' && value.step) { liveSteps.push(value.step); liveSteps = liveSteps.slice(-80); drawMessages(); }
      else if (value.type === 'request') { current.request = value.request; requestForm(value.request); }
      else if (value.type === 'requestResolved') { current.request = null; requestForm(null); }
      else if (['steered','notice'].includes(value.type)) note(value.message || '');
    }
    $('agentTaskSend').onclick = send;
    $('agentTaskInput').onkeydown = e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); send(); } };
    $('agentTaskStop').onclick = () => api('miaoCallCancel').then(update).catch(e => toast(e.message));
    $('agentTaskSelect').onchange = () => select($('agentTaskSelect').value).catch(e => toast(e.message));
    $('agentTaskNew').onclick = () => select('').catch(e => toast(e.message));
    $('agentTaskReload').onclick = load;
    $('agentTaskDiagnostics').onclick = () => api('miaoCallTaskDiagnostics').then(() => note('已复制不含任务正文、文件路径和密钥的诊断信息。')).catch(e => note(e.message));
    $('agentTaskDelete').onclick = async () => { try { const value = await api('miaoCallTaskDelete', { taskId: selected }); if (value.deleted) { await select(''); await load(); } } catch (e) { toast(e.message); } };
    $('agentTaskShowArchived').onchange = fillHistory;
    $('agentTaskArchive').onclick = async () => { try { await api('miaoCallTaskArchive', { taskId: selected, archived: !record?.archived }); await select(''); await load(); } catch (e) { toast(e.message); } };
    $('agentTaskChooseFolder').onclick = async () => { try { const value = await api('miaoCallTaskChooseFolder'); if (!value.cancelled) context = value; refreshControls(); } catch (e) { toast(e.message); } };
    $('agentTaskWrite').onchange = async () => { try { context = await api('miaoCallTaskConfigure', { mode: $('agentTaskWrite').checked ? 'workspace-write' : 'read-only' }); } catch (e) { toast(e.message); } refreshControls(); };
    $('agentTaskRevealFolder').onclick = () => api('miaoCallTaskReveal', { taskId: selected || null }).catch(e => toast(e.message));
    $('agentTaskAttach').onclick = async () => { try { const value = await api('miaoCallTaskChooseFiles'); if (!value.cancelled) attachments = [...new Set([...attachments, ...value.paths])].slice(0,8); renderAttachments(); } catch (e) { toast(e.message); } };
    $('agentTaskExport').onclick = () => api('miaoCallTaskExport', { taskId: selected }).catch(e => toast(e.message));
    refreshControls(); drawMessages(); return { update, event, load };
  }
  global.StudioAgentTasks = { create };
})(window);
