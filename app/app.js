// 法考 AI 学习 Harness - 前端逻辑
// 单一全局 state + hash 路由 + fetch 封装
'use strict';

const state = {
  view: 'home',
  config: null,
  conversationId: null,
  currentQuestion: null,       // 练习页当前题目
  historyTab: 'questions',
  // F1: 题库检索
  searchKind: 'questions',     // 'questions' | 'mistakes'
  searchTags: [],              // 当前选中的 tag 过滤
  searchSelected: new Set(),   // 当前结果里被勾选的题 id
  searchResults: [],           // 当前结果缓存(批量打标签要用)
  _searchSeq: 0,               // 防止旧请求覆盖新结果
};

// ---- fetch 封装 ----
async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch (e) {
    throw new Error('网络错误: ' + e.message);
  }
  const text = await resp.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!resp.ok) {
    const msg = (data && (data.error || data.detail)) || `HTTP ${resp.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

// ---- toast / 错误显示 ----
function toast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast ' + (type || 'info');
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 3000);
}

function showError(target, err) {
  if (typeof target === 'string') target = document.getElementById(target);
  if (!target) { toast(err.message || String(err), 'error'); return; }
  target.innerHTML =
    `<div class="error">⚠️ ${escapeHtml(err.message || String(err))}</div>`;
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderMarkdownLite(md) {
  if (!md) return '';
  // 极简 markdown:仅处理换行、**粗体**、标题前缀
  const lines = String(md).split(/\r?\n/);
  let html = '';
  let inOl = false, inUl = false;
  const closeLists = () => {
    if (inOl) { html += '</ol>'; inOl = false; }
    if (inUl) { html += '</ul>'; inUl = false; }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) { closeLists(); html += '<br/>'; continue; }
    if (/^#{1,3}\s+/.test(line)) {
      closeLists();
      html += `<h4>${formatInline(line.replace(/^#{1,3}\s+/, ''))}</h4>`;
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      if (!inOl) { closeLists(); html += '<ol>'; inOl = true; }
      html += `<li>${formatInline(line.replace(/^\d+\.\s+/, ''))}</li>`;
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      if (!inUl) { closeLists(); html += '<ul>'; inUl = true; }
      html += `<li>${formatInline(line.replace(/^[-*]\s+/, ''))}</li>`;
      continue;
    }
    closeLists();
    html += `<p>${formatInline(line)}</p>`;
  }
  closeLists();
  return html;
}

function formatInline(s) {
  return escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

// ---- 视图切换 ----
function showView(name) {
  state.view = name;
  document.querySelectorAll('main .view').forEach(v => {
    v.hidden = v.dataset.view !== name;
  });
  document.querySelectorAll('#nav a').forEach(a => {
    a.classList.toggle('active', a.dataset.route === name);
  });
  if (name === 'history') refreshHistory();
  if (name === 'settings') loadConfigForm();
  if (name === 'search') { refreshTagFilter(); runSearch(); }
  if (name === 'laws') { initLawsView(); }
}

window.addEventListener('hashchange', () => {
  const m = (location.hash || '#home').match(/#([^?]+)/);
  showView(m ? m[1] : 'home');
});

// ---- 健康检查 / 配置状态 ----
async function refreshStatus() {
  try {
    const h = await api('GET', '/api/health');
    const el = document.getElementById('status');
    const home = document.getElementById('home-status');
    if (h.configured) {
      el.textContent = `✅ ${h.model}`;
      el.className = 'status ok';
      if (home) home.innerHTML = `API 已配置 (模型: <code>${escapeHtml(h.model)}</code>)。可以开始使用了。`;
    } else {
      el.textContent = '⚠️ 未配置 API';
      el.className = 'status warn';
      if (home) home.innerHTML = '尚未配置 API。请前往 <a href="#settings">设置</a> 填写 API Base URL、Key 和模型名。';
    }
  } catch (e) {
    document.getElementById('status').textContent = '后端不可达';
    document.getElementById('status').className = 'status err';
  }
}

// ---- 设置页 ----
async function loadConfigForm() {
  try {
    const cfg = await api('GET', '/api/config');
    state.config = cfg;
    const form = document.getElementById('form-config');
    form.apiBaseUrl.value = cfg.apiBaseUrl || '';
    form.model.value = cfg.model || '';
    form.temperature.value = cfg.temperature ?? 0.3;
    form.maxTokens.value = cfg.maxTokens ?? 4000;
    form.webSearchEnabled.checked = !!cfg.webSearchEnabled;
    form.webSearchProvider.value = cfg.webSearchProvider || 'tavily';
    form.defaultSubject.value = cfg.defaultSubject || '不限科目';
    form.defaultQuestionType.value = cfg.defaultQuestionType || '案例分析题';
    form.defaultDifficulty.value = cfg.defaultDifficulty || '中等';
    const msg = document.getElementById('config-msg');
    const parts = [];
    if (cfg.apiKeyConfigured) parts.push('API Key 已设置');
    if (cfg.webSearchApiKeyConfigured) parts.push('WebSearch Key 已设置');
    msg.textContent = parts.length ? parts.join(' · ') + ' (留空输入框保留原值)' : '尚未配置 API Key';
  } catch (e) {
    showError('config-msg', e);
  }
}

document.getElementById('form-config').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const body = {
    apiBaseUrl: form.apiBaseUrl.value.trim(),
    model: form.model.value.trim(),
    temperature: parseFloat(form.temperature.value),
    maxTokens: parseInt(form.maxTokens.value, 10),
    webSearchEnabled: form.webSearchEnabled.checked,
    webSearchProvider: form.webSearchProvider.value.trim() || 'tavily',
    defaultSubject: form.defaultSubject.value.trim() || '不限科目',
    defaultQuestionType: form.defaultQuestionType.value.trim() || '案例分析题',
    defaultDifficulty: form.defaultDifficulty.value.trim() || '中等',
  };
  if (form.apiKey.value) body.apiKey = form.apiKey.value;
  if (form.webSearchApiKey.value) body.webSearchApiKey = form.webSearchApiKey.value;
  try {
    await api('POST', '/api/config', body);
    toast('已保存', 'ok');
    form.apiKey.value = '';
    form.webSearchApiKey.value = '';
    await refreshStatus();
    await loadConfigForm();
  } catch (e) {
    showError('config-msg', e);
  }
});

document.getElementById('btn-test-ai').addEventListener('click', async () => {
  const msg = document.getElementById('config-msg');
  msg.textContent = '测试中…';
  try {
    const h = await api('GET', '/api/health');
    if (!h.configured) throw new Error('尚未配置 API');
    msg.textContent = `连接正常 · 模型 ${h.model}`;
  } catch (e) {
    msg.innerHTML = `<span class="error">⚠️ ${escapeHtml(e.message)}</span>`;
  }
});

// ---- 知识点咨询 ----
document.getElementById('form-explain').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const out = document.getElementById('explain-output');
  out.innerHTML = '<p class="muted">AI 正在思考…</p>';
  if (!state.conversationId) state.conversationId = 'session_' + Date.now();
  try {
    const userQuestion = await collectAnswerParts('explain-image', f.question.value);
    const payload = (userQuestion.length === 1 && typeof userQuestion[0] === 'string' && !userQuestion[0].startsWith('data:image'))
      ? userQuestion[0]
      : userQuestion;
    const r = await api('POST', '/api/chat', {
      subject: f.subject.value,
      style: f.style.value,
      question: payload,
      webSearch: f.webSearch.checked,
      extremeThinking: f.extremeThinking && f.extremeThinking.checked,
      conversationId: state.conversationId,
    });
    out.innerHTML = renderChatAnswer(r);
  } catch (e) {
    showError(out, e);
  }
});

document.getElementById('form-explain-followup').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  if (!f.question.value.trim()) return;
  const out = document.getElementById('explain-output');
  const prevHtml = out.innerHTML;
  out.innerHTML = '<p class="muted">追问中…</p>';
  if (!state.conversationId) state.conversationId = 'session_' + Date.now();
  try {
    const r = await api('POST', '/api/chat', {
      subject: '不限科目',
      style: '法考应试角度',
      question: f.question.value,
      webSearch: false,
      conversationId: state.conversationId,
    });
    out.innerHTML = prevHtml + '<hr/>' + renderChatAnswer(r, true);
    f.question.value = '';
  } catch (e) {
    showError(out, e);
  }
});

function renderChatAnswer(r, isFollowup) {
  let html = '';
  if (r.isRelevant === false) {
    html += '<div class="reject-banner">🚫 ' + escapeHtml(r.answer || '这个问题与法考无关') + '</div>';
    return html;
  }
  if (r.extremeThinking) {
    html += '<div class="warn">🧠 已启用超长思考模式,本次思考消耗 ' + (r.reasoning_tokens || 0) + ' tokens,响应可能较慢。</div>';
  }
  if (!isFollowup && r.summary) html += `<div class="callout">${renderMarkdownLite(r.summary)}</div>`;
  html += renderMarkdownLite(r.answer || '');
  if (r.pitfalls && r.pitfalls.length) {
    html += '<h4>⚠️ 易错点</h4><ul>' + r.pitfalls.map(p => `<li>${escapeHtml(p)}</li>`).join('') + '</ul>';
  }
  if (r.examples && r.examples.length) {
    html += '<h4>📖 示例</h4><ul>' + r.examples.map(p => `<li>${renderMarkdownLite(p)}</li>`).join('') + '</ul>';
  }
  if (r.searchResults && r.searchResults.length) {
    html += '<h4>🔗 联网来源</h4><ul>' + r.searchResults.map(s =>
      `<li><a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.title || s.url)}</a></li>`
    ).join('') + '</ul>';
  }
  if (r.warnings && r.warnings.length) {
    html += '<div class="warn">' + r.warnings.map(w => escapeHtml(w)).join('；') + '</div>';
  }
  if (r.warning && !r.warnings) {
    html += '<div class="warn">' + escapeHtml(r.warning) + '</div>';
  }
  // 思考链折叠面板
  if (r.reasoning_content) {
    html += renderReasoningPanel(r.reasoning_content, r.reasoning_tokens);
  }
  return html;
}

function renderReasoningPanel(reasoning, tokens) {
  const head = tokens ? `🧠 AI 思考过程(消耗 ${tokens} tokens)` : '🧠 AI 思考过程';
  return `<details class="reasoning"><summary>${escapeHtml(head)}</summary><pre>${escapeHtml(reasoning)}</pre></details>`;
}

// ---- 图片上传辅助:把 <input type=file> 的文件转 base64 data URL,组成 userAnswer 数组 ----
async function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function collectAnswerParts(fileInputId, text) {
  const parts = [];
  if (text && text.trim()) parts.push(text.trim());
  const input = document.getElementById(fileInputId);
  if (input && input.files && input.files.length) {
    for (const f of input.files) {
      if (!f.type.startsWith('image/')) continue;
      try {
        const url = await fileToDataUrl(f);
        parts.push(url);
      } catch (e) {
        console.warn('图片读取失败', e);
      }
    }
  }
  return parts;
}

function bindImagePreview(fileInputId, previewId) {
  const input = document.getElementById(fileInputId);
  const preview = document.getElementById(previewId);
  if (!input || !preview) return;
  input.addEventListener('change', async () => refreshImagePreview(input, preview));
}

// ---- 粘贴截图支持 ----
// 在 textarea 上监听 paste 事件,如果粘贴的是图片文件,自动加到 file input 并预览。
// 浏览器 clipboard API: e.clipboardData.items,kind=file 且 type=image/* 时是图片。
async function handlePasteImages(ev, fileInputId, previewId) {
  const items = ev.clipboardData && ev.clipboardData.items;
  if (!items || !items.length) return;
  let anyImage = false;
  for (const item of items) {
    if (item.kind !== 'file') continue;
    if (!item.type.startsWith('image/')) continue;
    const file = item.getAsFile();
    if (!file) continue;
    // 把 file 加到对应 file input
    const input = document.getElementById(fileInputId);
    if (input) {
      const dt = new DataTransfer();
      // 保留已有文件
      if (input.files) for (const f of input.files) dt.items.add(f);
      dt.items.add(file);
      input.files = dt.files;
    }
    anyImage = true;
    ev.preventDefault();
  }
  if (anyImage) {
    const input = document.getElementById(fileInputId);
    const preview = document.getElementById(previewId);
    if (input && preview) await refreshImagePreview(input, preview);
    toast('已粘贴图片', 'ok');
  }
}

async function refreshImagePreview(input, preview) {
  preview.innerHTML = '';
  if (!input.files || !input.files.length) return;
  for (const f of input.files) {
    if (!f.type.startsWith('image/')) continue;
    const url = await fileToDataUrl(f);
    const img = document.createElement('img');
    img.src = url;
    img.alt = f.name;
    preview.appendChild(img);
  }
}

// 给指定 textarea 绑定粘贴
function bindPasteOnTextarea(textareaId, fileInputId, previewId) {
  const ta = document.getElementById(textareaId);
  if (!ta) return;
  ta.addEventListener('paste', (ev) => handlePasteImages(ev, fileInputId, previewId));
}

// ---- 例题生成 ----
document.getElementById('form-generate').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const out = document.getElementById('generate-output');
  out.innerHTML = '<p class="muted">生成中…</p>';
  try {
    const r = await api('POST', '/api/generate-question', {
      subject: f.subject.value,
      topic: f.topic.value,
      questionType: f.questionType.value,
      difficulty: f.difficulty.value,
      count: parseInt(f.count.value, 10) || 1,
      avoidDuplicate: f.avoidDuplicate.checked,
      extremeThinking: f.extremeThinking && f.extremeThinking.checked,
    });
    state._generatedQuestions = r.questions || [];
    out.innerHTML = renderQuestions(state._generatedQuestions);
    bindQuestionActions();
  } catch (e) {
    showError(out, e);
  }
});

document.querySelector('[data-action="generate-from-topic"]').addEventListener('click', async () => {
  const f = document.getElementById('form-explain');
  if (!f.question.value || !f.question.value.trim()) {
    toast('请先在上方「问题」框里填写内容,再生成相关例题', 'warn');
    return;
  }
  // 把当前问题当作 topic,跳到生成页后预填并自动提交
  location.hash = '#generate';
  setTimeout(() => {
    const g = document.getElementById('form-generate');
    g.topic.value = f.question.value.trim().slice(0, 30);
    g.subject.value = f.subject.value;
    g.requestSubmit();
  }, 50);
});

function renderQuestions(questions) {
  if (!questions || !questions.length) return '<p class="muted">未生成题目</p>';
  return questions.map((q, i) => `
    <article class="qcard" data-qid="${escapeHtml(q.id)}">
      <header>
        <span class="badge">${escapeHtml(q.type || '')}</span>
        <span class="badge">${escapeHtml(q.difficulty || '')}</span>
        <span class="badge">${escapeHtml(q.subject || '')} · ${escapeHtml(q.topic || '')}</span>
      </header>
      <h4>第 ${i + 1} 题</h4>
      <div class="stem">${renderMarkdownLite(q.stem)}</div>
      ${q.options && q.options.length
        ? '<ol class="opts">' + q.options.map(o => `<li>${escapeHtml(o)}</li>`).join('') + '</ol>'
        : ''}
      <details>
        <summary>查看答案与解析</summary>
        <p><strong>答案:</strong> ${escapeHtml(q.answer || '')}</p>
        <p><strong>解析:</strong> ${renderMarkdownLite(q.explanation || '')}</p>
        ${q.keyPoints && q.keyPoints.length
          ? '<p><strong>考点:</strong></p><ul>' + q.keyPoints.map(k => `<li>${escapeHtml(k)}</li>`).join('') + '</ul>' : ''}
        ${q.pitfalls && q.pitfalls.length
          ? '<p><strong>易错点:</strong></p><ul>' + q.pitfalls.map(p => `<li>${escapeHtml(p)}</li>`).join('') + '</ul>' : ''}
        ${q.reasoning_content
          ? renderReasoningPanel(q.reasoning_content, q.reasoning_tokens)
          : ''}
      </details>
      <div class="actions">
        <button class="btn-practice" data-idx="${i}">开始作答</button>
        <button class="btn-add-mistake" data-idx="${i}">加入错题本</button>
      </div>
    </article>
  `).join('');
}

function bindQuestionActions() {
  document.querySelectorAll('.btn-practice').forEach(btn => {
    btn.onclick = () => {
      const idx = parseInt(btn.dataset.idx, 10);
      state.currentQuestion = state._generatedQuestions[idx];
      state._practiceQueue = state._generatedQuestions.slice(idx + 1);
      location.hash = '#practice';
      renderPractice();
    };
  });
  document.querySelectorAll('.btn-add-mistake').forEach(btn => {
    btn.onclick = async () => {
      const idx = parseInt(btn.dataset.idx, 10);
      const q = state._generatedQuestions[idx];
      try {
        // 通过 grade-answer 把"空答案"加为错题?这里简化为直接 POST mistakes
        await api('DELETE', '/api/history/mistakes/' + encodeURIComponent(q.id));  // 清旧
        // 由于后端没有 POST /api/mistakes,这里走 grade 占位
        await api('POST', '/api/grade-answer', {
          question: q,
          userAnswer: '(已加入错题本,未作答)',
          maxScore: 1,
          rubric: '手动加入错题',
          addToMistakes: true,
        });
        toast('已加入错题本', 'ok');
      } catch (e) { toast(e.message, 'error'); }
    };
  });
}

// ---- 练习 ----
function renderPractice() {
  const empty = document.getElementById('practice-empty');
  const area = document.getElementById('practice-area');
  const q = state.currentQuestion;
  if (!q) { empty.hidden = false; area.hidden = true; return; }
  empty.hidden = true; area.hidden = false;
  // 错题复习模式提示
  const metaEl = document.getElementById('practice-meta');
  const spacedTag = q._spacedMistake ? '<span class="badge" style="background:#007aff;color:#fff;">🔁 错题复习</span>' : '';
  metaEl.innerHTML =
    `<span class="badge">${escapeHtml(q.subject || '')}</span>
     <span class="badge">${escapeHtml(q.type || '')}</span>
     <span class="badge">${escapeHtml(q.difficulty || '')}</span>
     ${spacedTag}`;
  document.getElementById('practice-stem').innerHTML = renderMarkdownLite(q.stem);
  const optEl = document.getElementById('practice-options');
  if (q.options && q.options.length) {
    optEl.innerHTML = '<ol class="opts">' + q.options.map(o => `<li>${escapeHtml(o)}</li>`).join('') + '</ol>';
    optEl.hidden = false;
  } else { optEl.hidden = true; }
  document.getElementById('practice-answer').value = '';
  document.getElementById('practice-feedback').hidden = true;
}

// "从错题本开始"按钮:拉 spaced queue,如果非空,装载到 currentQuestion + 队列
document.getElementById('btn-start-spaced').addEventListener('click', async () => {
  try {
    const r = await api('GET', '/api/spaced-queue');
    const items = r.items || [];
    if (items.length === 0) {
      toast('错题本里没有勾选「自动加入未来练习」的题', 'info');
      return;
    }
    state._practiceQueue = items.slice(1);
    state.currentQuestion = items[0];
    state.currentQuestion._spacedMistake = true;
    location.hash = '#practice';
    renderPractice();
    toast(`已从错题本载入 ${items.length} 道题,作答后会自动置灰`, 'ok');
  } catch (e) { toast(e.message, 'error'); }
});

document.getElementById('btn-submit-practice').addEventListener('click', async () => {
  const q = state.currentQuestion;
  if (!q) return;
  const text = document.getElementById('practice-answer').value.trim();
  const fb = document.getElementById('practice-feedback');
  const body = document.getElementById('practice-feedback-body');
  fb.hidden = false;
  body.innerHTML = '<p class="muted">批改中…</p>';
  try {
    const userAnswerParts = await collectAnswerParts('practice-image', text);
    const r = await api('POST', '/api/grade-answer', {
      question: q,
      userAnswer: userAnswerParts,
      maxScore: 20,
    });
    body.innerHTML = renderFeedback(r.feedback, { stem: q.stem });
    // 自动置灰提示:如果本次答对且题在 spaced queue 里
    if (r.autoMarkedMistakes && r.autoMarkedMistakes.length) {
      toast(`✅ 已自动置灰 ${r.autoMarkedMistakes.length} 条错题(答对)`, 'ok');
    }
    // 如果是错题复习模式,做完一题后从 queue 弹出
    if (q._spacedMistake) {
      body.insertAdjacentHTML('beforeend',
        '<p class="muted">🔁 这道题来自错题复习队列;点「下一题」继续。</p>');
    }
  } catch (e) {
    showError(body, e);
  }
});

document.getElementById('btn-next-practice').addEventListener('click', () => {
  if (state._practiceQueue && state._practiceQueue.length) {
    state.currentQuestion = state._practiceQueue.shift();
    renderPractice();
  } else {
    toast('没有更多题目了', 'info');
    location.hash = '#generate';
  }
});

function renderFeedback(f, opts) {
  if (!f) return '';
  if (f.isRelevant === false) {
    return '<div class="reject-banner">🚫 ' + escapeHtml(f.verdict || '本题与法考/法律学习无关,无法批改') + '</div>';
  }
  const pct = f.maxScore ? Math.round((f.score / f.maxScore) * 100) : 0;
  let html = `<div class="score-line">得分: <strong>${f.score}</strong> / ${f.maxScore} (${pct}%) — ${escapeHtml(f.verdict || '')}</div>`;

  // rubric 结构化采分点表格
  if (f.rubric && f.rubric.length) {
    html += '<h4>📋 采分点</h4><table class="rubric-table"><thead><tr><th>命中</th><th>分值</th><th>采分点</th><th>理由</th></tr></thead><tbody>';
    for (const r of f.rubric) {
      const ok = r.hit ? '✓' : '✗';
      const cls = r.hit ? 'hit' : 'miss';
      html += `<tr class="${cls}"><td>${ok}</td><td>${escapeHtml(String(r.points || 0))}</td><td>${escapeHtml(r.id || '')}. ${escapeHtml(r.criterion || '')}</td><td>${escapeHtml(r.reason || '')}</td></tr>`;
    }
    if (f._rubric_total != null) {
      html += `<tr class="rubric-summary"><td colspan="2">命中 ${f._rubric_hit_total || 0} / ${f._rubric_total || 0}</td><td colspan="2">scoring_mode: ${escapeHtml(f._scoring_mode || '')}</td></tr>`;
    }
    html += '</tbody></table>';
  }

  if (f.earnedPoints && f.earnedPoints.length) {
    html += '<h4>✅ 得分点</h4><ul>' + f.earnedPoints.map(p => `<li>${escapeHtml(p)}</li>`).join('') + '</ul>';
  }
  if (f.missedPoints && f.missedPoints.length) {
    html += '<h4>❌ 扣分点</h4><ul>' + f.missedPoints.map(p => `<li>${escapeHtml(p)}</li>`).join('') + '</ul>';
  }
  if (f.userAnswerAnalysis) html += '<h4>分析</h4>' + renderMarkdownLite(f.userAnswerAnalysis);
  if (f.referenceAnswer) html += '<h4>参考答案(满分)</h4>' + renderMarkdownLite(f.referenceAnswer);
  if (f.suggestions && f.suggestions.length) {
    html += '<h4>改进建议</h4><ul>' + f.suggestions.map(s => `<li>${escapeHtml(s)}</li>`).join('') + '</ul>';
  }
  if (f.relatedTopics && f.relatedTopics.length) {
    html += '<h4>相关知识点</h4><ul>' + f.relatedTopics.map(t => `<li>${escapeHtml(t)}</li>`).join('') + '</ul>';
  }
  if (f.reasoning_content) {
    html += renderReasoningPanel(f.reasoning_content, f.reasoning_tokens);
  }
  // F5: 打开法条栏(带题干关键词)
  if (opts && opts.stem) {
    const q = String(opts.stem).slice(0, 30);
    html += `<div class="actions"><button type="button" class="btn-search-laws" data-q="${escapeHtml(q)}">📖 打开法条栏</button></div>`;
  }
  return html;
}

// ---- 主观题批改 ----
document.getElementById('form-grade').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const out = document.getElementById('grade-output');
  const body = document.getElementById('grade-feedback-body');
  out.hidden = false;
  body.innerHTML = '<p class="muted">批改中…</p>';
  try {
    const userAnswerParts = await collectAnswerParts('grade-image', f.userAnswer.value);
    const r = await api('POST', '/api/grade-answer', {
      question: {
        subject: f.subject.value,
        type: f.questionType.value,
        stem: f.stem.value,
      },
      userAnswer: userAnswerParts,
      maxScore: parseInt(f.maxScore.value, 10) || 20,
      rubric: f.rubric.value,
      addToMistakes: f.addToMistakes.checked,
      extremeThinking: f.extremeThinking && f.extremeThinking.checked,
    });
    body.innerHTML = renderFeedback(r.feedback, { stem: f.stem.value });
    toast(f.addToMistakes.checked ? '已批改并加入错题本' : '已批改', 'ok');
  } catch (e) {
    showError(body, e);
  }
});

// ---- 历史记录 ----
document.querySelectorAll('.tabs .tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tabs .tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    state.historyTab = t.dataset.tab;
    refreshHistory();
  });
});

document.getElementById('btn-refresh-history').addEventListener('click', refreshHistory);

async function refreshHistory() {
  const list = document.getElementById('history-list');
  list.innerHTML = '<p class="muted">加载中…</p>';
  try {
    const r = await api('GET', '/api/history?type=' + encodeURIComponent(state.historyTab));
    list.innerHTML = renderHistory(r.items || [], r.type);
    bindHistoryActions();
    // 错题 tab:额外加载错题分析面板
    if (state.historyTab === 'mistakes') await loadMistakeStatsPanel();
  } catch (e) {
    showError(list, e);
  }
}

async function loadMistakeStatsPanel() {
  const panel = document.getElementById('mistake-stats-panel');
  if (!panel) return;
  try {
    const r = await api('GET', '/api/mistake-stats');
    panel.hidden = false;
    panel.innerHTML = `
      <h3>📊 错题分析</h3>
      <div class="exam-score-summary">
        <div>错题总数 <strong>${r.total}</strong></div>
        <div>未掌握 <strong style="color:#ff9500;">${r.pending}</strong></div>
        <div>已掌握 <strong style="color:#34c759;">${r.reviewed}</strong></div>
        <div>待复习队列 <strong style="color:#007aff;">${r.inSpacedQueue}</strong></div>
      </div>
      <div class="grid-3">
        <div>
          <h4>按题型</h4>
          ${renderMistakeBucketTable(r.byType)}
        </div>
        <div>
          <h4>按考点</h4>
          ${renderMistakeBucketTable(r.byTopic)}
        </div>
        <div>
          <h4>按科目</h4>
          ${renderMistakeBucketTable(r.bySubject)}
        </div>
      </div>
    `;
  } catch (e) {
    panel.innerHTML = `<div class="error">⚠️ ${escapeHtml(e.message)}</div>`;
  }
  // 错题复习出卷入口
  renderMistakeReviewBar();
}

function renderMistakeBucketTable(rows) {
  if (!rows || rows.length === 0) return '<p class="muted">暂无数据</p>';
  return `<table class="stats-table">
    <thead><tr><th>项目</th><th>错题数</th><th>未掌握</th></tr></thead>
    <tbody>${rows.map(r => `<tr>
      <td>${escapeHtml(r.key)}</td>
      <td>${r.total}</td>
      <td><strong style="color:${r.pending > 0 ? '#ff9500' : '#34c759'}">${r.pending}</strong></td>
    </tr>`).join('')}</tbody>
  </table>`;
}

function renderHistory(items, type) {
  if (!items.length) return '<p class="muted">暂无记录</p>';
  return items.map(it => {
    const time = it.createdAt || it.answeredAt || it.updatedAt || it.addedAt || '';
    let body = '';
    let actions = `<button class="btn-del" data-id="${escapeHtml(it.id)}">删除</button>`;
    if (type === 'questions') {
      body = `<div class="stem">${renderMarkdownLite(it.stem || '')}</div>
              <details><summary>答案 / 解析</summary>
                <p><strong>答案:</strong> ${escapeHtml(it.answer || '')}</p>
                <p><strong>解析:</strong> ${renderMarkdownLite(it.explanation || '')}</p>
              </details>`;
      actions += ` <button class="btn-practice-hist" data-id="${escapeHtml(it.id)}">开始练习</button>`;
    } else if (type === 'answers') {
      const f = it.feedback || {};
      body = `<div>得分 <strong>${it.score}</strong> / ${it.maxScore}</div>
              <div class="muted">${escapeHtml((f.verdict || '').slice(0, 80))}</div>
              <button class="btn-detail" data-attempt-id="${escapeHtml(it.id)}">📖 展开完整答卷</button>
              <div class="detail-body" id="detail-${escapeHtml(it.id)}" hidden></div>`;
    } else if (type === 'mistakes') {
      // 错题卡片:显示题干 + 元信息 + 重做/auto-add toggle + 删除
      const stemShort = (it.stem || '(题目已删除)').slice(0, 200);
      const reviewBadge = it.reviewed
        ? '<span class="badge" style="background:#34c759;color:#fff;">✓ 已掌握</span>'
        : '<span class="badge" style="background:#ff9500;color:#fff;">未掌握</span>';
      const autoChecked = it.autoPractice ? 'checked' : '';
      const meta = [it.subject, it.topic, it.type, it.difficulty].filter(Boolean).map(escapeHtml).join(' · ');
      body = `
        <div class="muted">${meta}</div>
        <div class="stem">${renderMarkdownLite(stemShort)}${it.stem && it.stem.length > 200 ? '…' : ''}</div>
        <div>${reviewBadge} ${it.reason ? '<span class="muted">' + escapeHtml(it.reason.slice(0, 100)) + '</span>' : ''}</div>
        <div class="mistake-meta muted">关联题目: <code>${escapeHtml(it.questionId || '无')}</code> · 关联作答: <code>${escapeHtml(it.attemptId || '无')}</code></div>
        <div class="detail-body" id="mistake-${escapeHtml(it.id)}" hidden></div>`;
      actions =
        `<button class="btn-redo-mistake" data-mistake-id="${escapeHtml(it.id)}" data-question-id="${escapeHtml(it.questionId || '')}">🔁 重做</button>` +
        `<label class="auto-practice-toggle">
           <input type="checkbox" class="btn-toggle-auto" data-mistake-id="${escapeHtml(it.id)}" ${autoChecked}/>
           自动加入未来练习
         </label>` +
        ` <button class="btn-del" data-id="${escapeHtml(it.id)}">删除</button>`;
    } else if (type === 'sessions') {
      const msgCount = it.messages ? it.messages.length : 0;
      const firstQ = it.messages && it.messages[0] ? it.messages[0].content.slice(0, 80) : '(空会话)';
      body = `<div class="muted">${msgCount} 条消息 · 科目 ${escapeHtml(it.subject || '')}</div>
              <div><strong>首问:</strong> ${escapeHtml(firstQ)}${firstQ.length >= 80 ? '…' : ''}</div>
              <button class="btn-detail" data-session-id="${escapeHtml(it.id)}">💬 查看完整对话</button>
              <button class="btn-continue-chat" data-session-id="${escapeHtml(it.id)}">继续聊 ↗</button>
              <div class="detail-body" id="session-${escapeHtml(it.id)}" hidden></div>`;
    }
    return `<article class="hcard" data-id="${escapeHtml(it.id)}">
      <header><span class="muted">${escapeHtml(time)}</span></header>
      ${body}
      <div class="actions">${actions}</div>
    </article>`;
  }).join('');
}

function bindHistoryActions() {
  document.querySelectorAll('.btn-del').forEach(b => {
    b.onclick = async () => {
      if (!confirm('删除这条记录?')) return;
      try {
        await api('DELETE', `/api/history/${state.historyTab}/${encodeURIComponent(b.dataset.id)}`);
        refreshHistory();
      } catch (e) { toast(e.message, 'error'); }
    };
  });
  document.querySelectorAll('.btn-practice-hist').forEach(b => {
    b.onclick = async () => {
      try {
        const r = await api('GET', '/api/history?type=questions');
        const q = (r.items || []).find(x => x.id === b.dataset.id);
        if (!q) { toast('未找到题目', 'error'); return; }
        state.currentQuestion = q;
        state._practiceQueue = [];
        location.hash = '#practice';
        renderPractice();
      } catch (e) { toast(e.message, 'error'); }
    };
  });
  // 详情展开(支持 attempt / session 两种)
  document.querySelectorAll('.btn-detail').forEach(b => {
    b.onclick = async () => {
      // attempt 类型
      if (b.dataset.attemptId) {
        const aid = b.dataset.attemptId;
        const body = document.getElementById(`detail-${aid}`);
        if (!body.hidden) {
          body.hidden = true;
          b.textContent = '📖 展开完整答卷';
          return;
        }
        b.disabled = true;
        b.textContent = '⏳ 加载中…';
        try {
          const r = await api('GET', `/api/attempt/${encodeURIComponent(aid)}`);
          body.innerHTML = renderAttemptDetail(r.attempt);
          body.hidden = false;
          b.textContent = '🔼 收起';
        } catch (e) { toast(e.message, 'error'); }
        b.disabled = false;
      }
      // session 类型
      else if (b.dataset.sessionId) {
        const sid = b.dataset.sessionId;
        const body = document.getElementById(`session-${sid}`);
        if (!body.hidden) {
          body.hidden = true;
          b.textContent = '💬 查看完整对话';
          return;
        }
        b.disabled = true;
        b.textContent = '⏳ 加载中…';
        try {
          const r = await api('GET', `/api/session/${encodeURIComponent(sid)}`);
          body.innerHTML = renderSessionDetail(r.session);
          body.hidden = false;
          b.textContent = '🔼 收起';
        } catch (e) { toast(e.message, 'error'); }
        b.disabled = false;
      }
    };
  });
  // 继续聊:从历史会话跳到知识点咨询页,带入历史消息做上下文
  document.querySelectorAll('.btn-continue-chat').forEach(b => {
    b.onclick = async () => {
      const sid = b.dataset.sessionId;
      b.disabled = true;
      try {
        const r = await api('GET', `/api/session/${encodeURIComponent(sid)}`);
        continueChatFromSession(r.session);
      } catch (e) { toast(e.message, 'error'); }
      b.disabled = false;
    };
  });

  // 错题 → 重做
  document.querySelectorAll('.btn-redo-mistake').forEach(b => {
    b.onclick = async () => {
      const qid = b.dataset.questionId;
      if (!qid) { toast('错题没有关联到具体题目,无法重做', 'error'); return; }
      b.disabled = true;
      try {
        const r = await api('GET', `/api/question/${encodeURIComponent(qid)}`);
        const q = r.question;
        if (!q) { toast('未找到题目', 'error'); return; }
        state.currentQuestion = q;
        state._practiceQueue = [];
        // 如果是错题本自动加入队列的题,做完会走自动置灰逻辑
        q._spacedMistake = true;
        location.hash = '#practice';
        renderPractice();
        toast('已载入错题,作答后会自动置灰(若答对)', 'ok');
      } catch (e) { toast(e.message, 'error'); }
      b.disabled = false;
    };
  });
  // 错题 → 自动加入未来练习 toggle
  document.querySelectorAll('.btn-toggle-auto').forEach(b => {
    b.onchange = async () => {
      const mid = b.dataset.mistakeId;
      b.disabled = true;
      try {
        const r = await api('POST', `/api/mistake/${encodeURIComponent(mid)}/toggle-auto`, { auto: b.checked });
        toast(r.autoPractice ? '✅ 已加入未来自由练习队列' : '已关闭自动加入', 'ok');
        // 同步更新页面顶部的"错题分析"统计(如果已渲染)
        if (state.historyTab === 'mistakes') await loadMistakeStatsPanel();
      } catch (e) { toast(e.message, 'error'); b.checked = !b.checked; }
      b.disabled = false;
    };
  });
}

function continueChatFromSession(s) {
  if (!s) return;
  // 1) 切到 explain 视图
  state.conversationId = s.id;
  // 2) 把历史消息渲染到 explain-output
  const out = document.getElementById('explain-output');
  const msgs = s.messages || [];
  if (msgs.length === 0) {
    out.innerHTML = '<p class="muted">(该会话无消息历史)</p>';
  } else {
    out.innerHTML = renderSessionDetail(s);
  }
  // 3) 把"科目"带上,样式保留默认"法考应试角度"
  const form = document.getElementById('form-explain');
  if (form && s.subject) {
    const opts = Array.from(form.subject.options).map(o => o.value);
    if (opts.includes(s.subject)) form.subject.value = s.subject;
  }
  // 4) 清空主问题框(避免误把上次问题再发一次)
  if (form) form.question.value = '';
  // 5) 跳视图
  location.hash = '#explain';
  showView('explain');
  // 6) 聚焦到追问框
  const followup = document.getElementById('form-explain-followup');
  if (followup) {
    followup.question.value = '';
    followup.question.focus();
  }
  toast(`已加载 ${msgs.length} 条历史消息,基于此会话继续`, 'ok');
}

function renderSessionDetail(s) {
  const msgs = s.messages || [];
  return `
    <div class="attempt-detail panel">
      <h4>💬 完整对话 <span class="muted">(${msgs.length} 条消息)</span></h4>
      <div class="chat-thread">
        ${msgs.map(m => {
          const cls = m.role === 'user' ? 'chat-user' : 'chat-assistant';
          const sources = (m.sources && m.sources.length) ?
            `<div class="muted">📎 来源: ${m.sources.map(s => `<a href="${escapeHtml(s)}" target="_blank">${escapeHtml(s)}</a>`).join(', ')}</div>` : '';
          return `<div class="chat-msg ${cls}">
            <div class="chat-role">${m.role === 'user' ? '👤 你' : '🤖 AI'}</div>
            <div class="chat-content">${renderMarkdownLite(m.content)}</div>
            ${sources}
          </div>`;
        }).join('')}
      </div>
    </div>
  `;
}

function renderAttemptDetail(a) {
  const q = a.question || {};
  const rubric = a.rubricHits || [];
  let rubricHtml = '';
  if (rubric.length > 0) {
    rubricHtml = `<h4>📐 采分点</h4><table class="stats-table">
      <thead><tr><th>采分点</th><th>命中</th><th>说明</th></tr></thead>
      <tbody>${rubric.map(r => `<tr>
        <td>${escapeHtml(r.id || '')}</td>
        <td>${r.hit ? '✓' : '✗'}</td>
        <td>${escapeHtml(r.reason || r.criterion || '')}</td>
      </tr>`).join('')}</tbody>
    </table>`;
  }
  return `
    <div class="attempt-detail panel">
      <h4>📌 题目</h4>
      <div class="muted">${escapeHtml(q.subject || '')} · ${escapeHtml(q.topic || '')} · ${escapeHtml(q.type || '')}${q.difficulty ? ' · ' + escapeHtml(q.difficulty) : ''}</div>
      <div class="stem">${renderMarkdownLite(q.stem || '')}</div>
      ${q.options && q.options.length ? '<ol class="opts">' + q.options.map((o, i) => `<li>${escapeHtml(o)}</li>`).join('') + '</ol>' : ''}
      ${q.answer ? `<p><strong>标准答案:</strong> ${escapeHtml(q.answer)}</p>` : ''}
      ${q.explanation ? '<details><summary>题目解析</summary><div>' + renderMarkdownLite(q.explanation) + '</div></details>' : ''}
      <h4>✍️ 你的作答</h4>
      <div class="user-answer">${escapeHtml(a.userAnswer || '(未作答)')}</div>
      ${a.durationMs ? `<div class="muted">用时 ${Math.round(a.durationMs / 1000)} 秒</div>` : ''}
      ${a.referenceAnswer ? '<details><summary>📖 参考答案</summary><div>' + renderMarkdownLite(a.referenceAnswer) + '</div></details>' : ''}
      ${a.aiVerdict ? '<h4>🤖 AI 批改</h4><div>' + renderMarkdownLite(a.aiVerdict) + '</div>' : ''}
      ${rubricHtml}
    </div>
  `;
}

// ---- 模拟考试模块 ----
const exam = {
  current: null,        // 当前答卷对象 {exam, answers, currentIdx, startTime, durations}
  answers: [],          // 每题 [{questionId, userAnswer, durationMs}]
  durations: [],        // 每题累计停留毫秒
  currentIdx: 0,
  startTime: 0,
  durationMinutes: 90,
  timerHandle: null,
  timeUp: false,
};

// 子页面 tab 切换
document.querySelectorAll('[data-practice-tab]').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('[data-practice-tab]').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    const tab = t.dataset.practiceTab;
    document.getElementById('practice-free').hidden = tab !== 'free';
    document.getElementById('practice-exam').hidden = tab !== 'exam';
  });
});

// Step 1: 生成模拟卷 → 进入确认页(尚未计时)
document.getElementById('btn-exam-generate').addEventListener('click', async () => {
  const btn = document.getElementById('btn-exam-generate');
  const msg = document.getElementById('exam-setup-msg');
  const subject = document.getElementById('exam-subject').value;
  const duration = parseInt(document.getElementById('exam-duration').value, 10) || 90;
  const single = parseInt(document.getElementById('exam-single').value, 10) || 0;
  const multi = parseInt(document.getElementById('exam-multi').value, 10) || 0;
  const essay = parseInt(document.getElementById('exam-essay').value, 10) || 0;
  const extreme = document.getElementById('exam-extreme').checked;
  const title = (document.getElementById('exam-title').value || '').trim();
  if (single + multi + essay === 0) { toast('至少要生成一种题型的题目', 'warn'); return; }

  btn.disabled = true;
  msg.textContent = `⏳ 正在生成 ${single + multi + essay} 道题... (按经验需要 30-90 秒)`;
  try {
    const r = await api('POST', '/api/exam/generate', {
      subject, durationMinutes: duration,
      singleCount: single, multiCount: multi, essayCount: essay,
      extremeThinking: extreme,
      title,
    });
    exam.durationMinutes = duration;
    exam.timeUp = false;
    showConfirmPage(r.exam);
    document.getElementById('exam-title').value = '';  // 生成成功后清空,下次不残留
  } catch (e) {
    msg.innerHTML = `<div class="error">⚠️ ${escapeHtml(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
});

// 显示确认页(还没计时)
function showConfirmPage(examObj) {
  exam.current = examObj;
  exam.answers = exam.current.questions.map(q => ({ questionId: q.id, userAnswer: '', durationMs: 0 }));
  exam.durations = new Array(exam.current.questions.length).fill(0);
  exam.currentIdx = 0;
  exam.lastFlip = null;
  // 题型分布
  const breakdown = {};
  exam.current.questions.forEach(q => {
    const t = q.type || '其他';
    breakdown[t] = (breakdown[t] || 0) + 1;
  });
  const meta = document.getElementById('exam-confirm-meta');
  const titleLine = exam.current.title ? `<div>名称 <strong>${escapeHtml(exam.current.title)}</strong></div>` : '';
  meta.innerHTML = `
    ${titleLine}
    <div>科目 <strong>${escapeHtml(exam.current.subject)}</strong></div>
    <div>题量 <strong>${exam.current.totalQuestions}</strong></div>
    <div>时长 <strong>${exam.durationMinutes}</strong> 分钟</div>
    <div>题型 <strong>${Object.entries(breakdown).map(([k,v])=>`${k}×${v}`).join(' ')}</strong></div>
  `;
  // TOC
  const toc = document.getElementById('exam-confirm-toc');
  toc.innerHTML = exam.current.questions.map((q, i) =>
    `<li>${escapeHtml(q.type || '')} — ${escapeHtml((q.stem || '').slice(0, 60))}${q.stem && q.stem.length > 60 ? '…' : ''}</li>`
  ).join('');
  // 切视图
  document.getElementById('exam-setup').hidden = true;
  document.getElementById('exam-confirm').hidden = false;
  document.getElementById('exam-paper').hidden = true;
  document.getElementById('exam-result').hidden = true;
  document.getElementById('exam-history').hidden = true;
}

// 确认页 → 开始作答(启动计时)
document.getElementById('btn-exam-start').addEventListener('click', () => {
  document.getElementById('exam-confirm').hidden = true;
  document.getElementById('exam-paper').hidden = false;
  document.getElementById('exam-paper-title').textContent =
    exam.current.title || `${exam.current.subject} 模拟卷`;
  document.getElementById('exam-paper-meta').textContent =
    ` · 共 ${exam.current.totalQuestions} 题 · 时长 ${exam.durationMinutes} 分钟`;
  exam.startTime = Date.now();
  exam.lastFlip = exam.startTime;
  startExamTimer();
  renderExamQuestion();
});

document.getElementById('btn-exam-back-from-confirm').addEventListener('click', () => {
  exam.current = null;
  document.getElementById('exam-confirm').hidden = true;
  document.getElementById('exam-setup').hidden = false;
});

// 历史试卷列表
document.getElementById('btn-exam-show-history').addEventListener('click', async () => {
  const panel = document.getElementById('exam-history');
  const list = document.getElementById('exam-history-list');
  if (!panel.hidden) { panel.hidden = true; return; }
  try {
    const r = await api('GET', '/api/exams');
    if (!r.items || r.items.length === 0) {
      list.innerHTML = '<p class="muted">暂无历史试卷</p>';
    } else {
      list.innerHTML = r.items.map(it => {
        const breakdown = Object.entries(it.typeBreakdown || {}).map(([k,v])=>`${k}×${v}`).join(' ') || '-';
        return `<div class="exam-history-item">
          <div>
            ${it.title ? `<strong>${escapeHtml(it.title)}</strong><br/>` : ''}
            <span class="muted">科目 ${escapeHtml(it.subject || '')} · ${escapeHtml(it.createdAt)}</span>
            <div class="muted">${it.totalQuestions} 题 · ${it.durationMinutes} 分钟 · ${breakdown}</div>
          </div>
          <div>
            <button type="button" data-load-exam="${it.id}">加载并答卷</button>
            <button type="button" class="muted" data-delete-exam="${it.id}">删除</button>
          </div>
        </div>`;
      }).join('');
      // 绑定每行的加载/删除
      list.querySelectorAll('[data-load-exam]').forEach(btn => {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.loadExam;
          try {
            const r = await api('GET', `/api/exam/${id}`);
            exam.durationMinutes = r.exam.durationMinutes || 90;
            exam.timeUp = false;
            showConfirmPage(r.exam);
          } catch (e) { toast(e.message, 'error'); }
        });
      });
      list.querySelectorAll('[data-delete-exam]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('确定删除这张历史试卷?(不可恢复)')) return;
          try {
            await api('DELETE', `/api/exam/${btn.dataset.deleteExam}`);
            btn.closest('.exam-history-item').remove();
            toast('已删除', 'info');
          } catch (e) { toast(e.message, 'error'); }
        });
      });
    }
    panel.hidden = false;
  } catch (e) {
    toast('加载历史失败: ' + e.message, 'error');
  }
});

function startExamTimer() {
  if (exam.timerHandle) clearInterval(exam.timerHandle);
  const totalMs = exam.durationMinutes * 60 * 1000;
  document.getElementById('exam-timer-total').textContent = `/ ${exam.durationMinutes}:00`;
  exam.timerHandle = setInterval(() => {
    const elapsed = Date.now() - exam.startTime;
    const remain = Math.max(0, totalMs - elapsed);
    const m = Math.floor(remain / 60000);
    const s = Math.floor((remain % 60000) / 1000);
    document.getElementById('exam-timer').textContent =
      `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    if (remain === 0 && !exam.timeUp) {
      exam.timeUp = true;
      clearInterval(exam.timerHandle);
      toast('⏰ 考试时间已到!你可以继续检查,但建议尽快交卷。', 'warn');
      if (confirm('⏰ 考试时间已到。是否立即交卷?')) {
        submitExam();
      }
    }
  }, 1000);
}

function renderExamQuestion() {
  if (!exam.current) return;
  const idx = exam.currentIdx;
  const q = exam.current.questions[idx];
  document.getElementById('exam-q-no').textContent = idx + 1;
  document.getElementById('exam-q-total').textContent = exam.current.questions.length;
  document.getElementById('exam-q-type').textContent = q.type || '';
  document.getElementById('exam-q-stem').innerHTML = renderMarkdownLite(q.stem || '');
  document.getElementById('exam-q-answer').value = exam.answers[idx].userAnswer || '';
  document.getElementById('exam-q-dur').textContent = Math.round(exam.durations[idx] / 1000);

  // 选项:单选 radio, 多选 checkbox
  const optEl = document.getElementById('exam-q-options');
  if (q.options && q.options.length) {
    const isMulti = (q.type || '').includes('多');
    const currentVal = exam.answers[idx].userAnswer || '';
    const currentSet = isMulti ? currentVal.split(',') : [];
    optEl.innerHTML = '<ol class="opts">' + q.options.map((o, i) => {
      const letter = String.fromCharCode(65 + i);
      if (isMulti) {
        const checked = currentSet.includes(letter) ? 'checked' : '';
        return `<li><label><input type="checkbox" name="exam-opt" value="${letter}" ${checked}/> ${escapeHtml(o)}</label></li>`;
      } else {
        const checked = currentVal === letter ? 'checked' : '';
        return `<li><label><input type="radio" name="exam-opt" value="${letter}" ${checked}/> ${escapeHtml(o)}</label></li>`;
      }
    }).join('') + '</ol>';
    optEl.hidden = false;
    optEl.querySelectorAll('input[name="exam-opt"]').forEach(inp => {
      inp.addEventListener('change', () => collectExamAnswer());
    });
  } else {
    optEl.hidden = true;
  }

  // 更新进度
  const answered = exam.answers.filter(a => a.userAnswer && a.userAnswer.trim()).length;
  document.getElementById('exam-q-progress').textContent = `已答 ${answered} / ${exam.current.questions.length}`;

  // 翻页按钮可用性
  document.getElementById('btn-exam-prev').disabled = idx === 0;
  document.getElementById('btn-exam-next').disabled = idx === exam.current.questions.length - 1;
}

function collectExamAnswer() {
  if (!exam.current) return;
  const idx = exam.currentIdx;
  const q = exam.current.questions[idx];
  let ans = '';
  if (q.options && q.options.length) {
    const isMulti = (q.type || '').includes('多');
    if (isMulti) {
      const checked = Array.from(document.querySelectorAll('input[name="exam-opt"]:checked')).map(x => x.value);
      ans = checked.sort().join(',');
    } else {
      const checked = document.querySelector('input[name="exam-opt"]:checked');
      ans = checked ? checked.value : '';
    }
  }
  // 叠加 textarea 输入(简答题)
  const text = document.getElementById('exam-q-answer').value.trim();
  if (text) ans = ans ? ans + "\n" + text : text;
  exam.answers[idx].userAnswer = ans;
}

document.getElementById('exam-q-answer').addEventListener('input', collectExamAnswer);

// 翻页:先把当前题停留时长累加,再切换
function examFlipTo(newIdx) {
  if (!exam.current) return;
  // 累加当前题
  exam.durations[exam.currentIdx] = exam.durations[exam.currentIdx] || 0;
  // 当前题停留时长:用 performance.now() 不准确(刷新会丢),改用翻页瞬间记录
  exam.lastFlip = exam.lastFlip || Date.now();
  const now = Date.now();
  exam.durations[exam.currentIdx] += (now - exam.lastFlip);
  exam.lastFlip = now;
  // 切题
  exam.currentIdx = newIdx;
  renderExamQuestion();
}

document.getElementById('btn-exam-prev').addEventListener('click', () => {
  if (exam.currentIdx > 0) examFlipTo(exam.currentIdx - 1);
});
document.getElementById('btn-exam-next').addEventListener('click', () => {
  if (exam.currentIdx < exam.current.questions.length - 1) examFlipTo(exam.currentIdx + 1);
});

// 交卷
document.getElementById('btn-exam-submit').addEventListener('click', () => {
  if (!exam.current) return;
  // 把最后一题的停留时长累加
  exam.durations[exam.currentIdx] += (Date.now() - exam.lastFlip);
  // 把 durations 写到 answers
  exam.answers.forEach((a, i) => a.durationMs = exam.durations[i] || 0);
  if (!confirm('确认交卷?交卷后无法修改答案。')) return;
  submitExam();
});

async function submitExam() {
  const btn = document.getElementById('btn-exam-submit');
  btn.disabled = true;
  if (exam.timerHandle) clearInterval(exam.timerHandle);
  try {
    const r = await api('POST', `/api/exam/${exam.current.id}/grade`, {
      answers: exam.answers,
      timeUp: exam.timeUp,
    });
    showExamResult(r);
  } catch (e) {
    toast(e.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

function showExamResult(r) {
  document.getElementById('exam-paper').hidden = true;
  document.getElementById('exam-result').hidden = false;
  const s = r.summary;
  document.getElementById('exam-total-score').textContent = s.totalScore;
  document.getElementById('exam-total-max').textContent = s.totalMax;
  document.getElementById('exam-total-pct').textContent = s.percent;
  document.getElementById('exam-total-dur').textContent = s.totalDurationSec;
  document.getElementById('exam-time-up-banner').hidden = !s.timeUp;

  const list = document.getElementById('exam-results-list');
  list.innerHTML = r.attempt.results.map((it, i) => {
    const cls = it.isCorrect ? 'correct' : 'wrong';
    const durMin = Math.floor((it.durationSec || 0) / 60);
    const durSec = Math.round((it.durationSec || 0) % 60);
    let feedback = '';
    if (it.gradingMode === 'ai' && it.feedback) {
      feedback = `<details><summary>AI 批改详情</summary>
        <div class="muted">${escapeHtml(it.feedback.verdict || '')}</div>
        ${it.feedback.referenceAnswer ? '<p><strong>参考答案:</strong> ' + renderMarkdownLite(it.feedback.referenceAnswer) + '</p>' : ''}
      </details>`;
    }
    return `<article class="exam-result-item ${cls}">
      <header>
        <strong>#${i+1} ${escapeHtml(it.type)}</strong>
        <span class="badge">${it.score} / ${it.maxScore} 分</span>
        <span class="muted">用时 ${durMin}:${String(durSec).padStart(2,'0')}</span>
        ${it.isCorrect ? '<span class="badge">✓ 正确</span>' : '<span class="badge" style="background:#dc3545;color:#fff;">✗ 错误</span>'}
      </header>
      <div class="stem">${renderMarkdownLite(it.stem)}</div>
      <div class="muted"><strong>你的答案:</strong> ${escapeHtml(it.userAnswer || '(未作答)')}</div>
      <div class="muted"><strong>正确答案:</strong> ${escapeHtml(it.correctAnswer || '(无)')}</div>
      ${it.explanation ? '<details><summary>题目解析</summary><div>' + renderMarkdownLite(it.explanation) + '</div></details>' : ''}
      ${feedback}
    </article>`;
  }).join('');
}

document.getElementById('btn-exam-back-setup').addEventListener('click', () => {
  exam.current = null;
  document.getElementById('exam-result').hidden = true;
  document.getElementById('exam-paper').hidden = true;
  document.getElementById('exam-setup').hidden = false;
});

// 复盘入口
document.getElementById('btn-exam-review').addEventListener('click', () => {
  document.getElementById('exam-result').hidden = true;
  document.getElementById('exam-review').hidden = false;
  loadReview();
});

document.querySelectorAll('[data-review-tab]').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('[data-review-tab]').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    const tab = t.dataset.reviewTab;
    document.getElementById('review-attempts').hidden = tab !== 'attempts';
    document.getElementById('review-stats').hidden = tab !== 'stats';
  });
});

async function loadReview() {
  await Promise.all([loadAttempts(), loadStats()]);
}

async function loadAttempts() {
  const list = document.getElementById('review-attempts-list');
  try {
    const r = await api('GET', '/api/exam-attempts');
    if (!r.items || r.items.length === 0) {
      list.innerHTML = '<p class="muted">还没有考试记录。完成一次模拟考试后会出现在这里。</p>';
      return;
    }
    list.innerHTML = r.items.map(it => {
      const dur = Math.round(it.totalDurationSec || 0);
      return `<div class="exam-history-item">
        <div>
          <strong>${escapeHtml(it.subject || '-')}</strong>
          <span class="muted">${escapeHtml(it.submittedAt || '')}</span>
          <div class="muted">
            ${it.totalScore}/${it.totalMax} 分 · 正确率 ${it.percent}% · ${it.questionCount} 题 · 用时 ${dur}s
            ${it.timeUp ? '<span class="warn">⏰ 超时提交</span>' : ''}
          </div>
        </div>
        <div>
          <button type="button" data-view-attempt="${it.id}">查看答卷</button>
          <button type="button" class="muted" data-del-attempt="${it.id}">删除</button>
        </div>
      </div>`;
    }).join('');
    list.querySelectorAll('[data-view-attempt]').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          const r = await api('GET', `/api/exam-attempt/${btn.dataset.viewAttempt}`);
          showReviewAttempt(r.attempt);
        } catch (e) { toast(e.message, 'error'); }
      });
    });
    list.querySelectorAll('[data-del-attempt]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm('删除这条考试记录?')) return;
        try {
          await api('DELETE', `/api/exam-attempt/${btn.dataset.delAttempt}`);
          loadAttempts();
          loadStats();
          toast('已删除', 'info');
        } catch (e) { toast(e.message, 'error'); }
      });
    });
  } catch (e) {
    list.innerHTML = `<div class="error">⚠️ ${escapeHtml(e.message)}</div>`;
  }
}

function showReviewAttempt(a) {
  // 复用 exam-result 的 DOM 结构
  document.getElementById('exam-review').hidden = true;
  document.getElementById('exam-result').hidden = false;
  document.getElementById('exam-total-score').textContent = a.totalScore;
  document.getElementById('exam-total-max').textContent = a.totalMax;
  document.getElementById('exam-total-pct').textContent =
    a.totalMax ? Math.round(a.totalScore / a.totalMax * 1000) / 10 : 0;
  document.getElementById('exam-total-dur').textContent =
    Math.round((a.totalDurationMs || 0) / 1000);
  document.getElementById('exam-time-up-banner').hidden = !a.timeUp;
  const list = document.getElementById('exam-results-list');
  list.innerHTML = (a.results || []).map((it, i) => {
    const cls = it.isCorrect ? 'correct' : 'wrong';
    let fb = '';
    if (it.gradingMode === 'ai' && it.feedback) {
      fb = `<details><summary>AI 批改详情</summary>
        <div class="muted">${escapeHtml(it.feedback.verdict || '')}</div>
        ${it.feedback.referenceAnswer ? '<p><strong>参考答案:</strong> ' + renderMarkdownLite(it.feedback.referenceAnswer) + '</p>' : ''}
      </details>`;
    }
    return `<article class="exam-result-item ${cls}">
      <header>
        <strong>#${i+1} ${escapeHtml(it.type)} · ${escapeHtml(it.topic || '')}</strong>
        <span class="badge">${it.score} / ${it.maxScore} 分</span>
        <span class="muted">用时 ${Math.round(it.durationSec || 0)}s</span>
        ${it.isCorrect ? '<span class="badge">✓ 正确</span>' : '<span class="badge" style="background:#dc3545;color:#fff;">✗ 错误</span>'}
      </header>
      <div class="stem">${renderMarkdownLite(it.stem)}</div>
      <div class="muted"><strong>你的答案:</strong> ${escapeHtml(it.userAnswer || '(未作答)')}</div>
      <div class="muted"><strong>正确答案:</strong> ${escapeHtml(it.correctAnswer || '(无)')}</div>
      ${it.explanation ? '<details><summary>题目解析</summary><div>' + renderMarkdownLite(it.explanation) + '</div></details>' : ''}
      ${fb}
    </article>`;
  }).join('');
}

async function loadStats() {
  try {
    const r = await api('GET', '/api/exam-stats');
    const summary = document.getElementById('review-stats-summary');
    summary.innerHTML = `
      <div class="exam-score-summary">
        <div>考试次数 <strong>${r.totalAttempts}</strong></div>
        <div>累计答题 <strong>${r.totalQuestions}</strong></div>
        <div>总正确 <strong>${r.totalCorrect}</strong></div>
        <div>总正确率 <strong>${r.overallRate}</strong>%</div>
      </div>
    `;
    renderStatsTable('review-stats-type', r.byType);
    renderStatsTable('review-stats-topic', r.byTopic);
    renderStatsTable('review-stats-subject', r.bySubject);
  } catch (e) {
    document.getElementById('review-stats').innerHTML =
      `<div class="error">⚠️ ${escapeHtml(e.message)}</div>`;
  }
}

function renderStatsTable(elId, rows) {
  const el = document.getElementById(elId);
  if (!rows || rows.length === 0) {
    el.innerHTML = '<tr><td class="muted">暂无数据</td></tr>';
    return;
  }
  el.innerHTML = `
    <thead><tr><th>项目</th><th>题数</th><th>正确</th><th>正确率</th><th>得分率</th></tr></thead>
    <tbody>${rows.map(r => {
      const color = r.rate >= 75 ? '#34c759' : r.rate >= 50 ? '#ff9500' : '#dc3545';
      return `<tr>
        <td>${escapeHtml(r.key)}</td>
        <td>${r.total}</td>
        <td>${r.correct}</td>
        <td><strong style="color:${color}">${r.rate}%</strong></td>
        <td>${r.scoreRate}%</td>
      </tr>`;
    }).join('')}</tbody>
  `;
}

// 从复盘回配置页(若想完全退出复盘)
function exitReview() {
  document.getElementById('exam-review').hidden = true;
  document.getElementById('exam-setup').hidden = false;
}

// 启动时初始化
document.addEventListener('DOMContentLoaded', () => {
  // exam.lastFlip 用于累计停留时长
});


// ---- 启动 ----
(function init() {
  const m = (location.hash || '#home').match(/#([^?]+)/);
  showView(m ? m[1] : 'home');
  refreshStatus();
  bindImagePreview('explain-image', 'explain-image-preview');
  bindImagePreview('grade-image', 'grade-image-preview');
  bindImagePreview('practice-image', 'practice-image-preview');
  // 粘贴截图支持
  bindPasteOnTextarea('explain-question', 'explain-image', 'explain-image-preview');
  bindPasteOnTextarea('grade-userAnswer', 'grade-image', 'grade-image-preview');
  bindPasteOnTextarea('practice-answer', 'practice-image', 'practice-image-preview');
  bindModelSelect();
})();

// ---- 模型选择器:下拉切换 + 写回 config.json ----
function bindModelSelect() {
  const sel = document.getElementById('model-select');
  if (!sel) return;
  sel.addEventListener('change', async () => {
    try {
      await api('POST', '/api/config', { model: sel.value });
      toast('模型已切换为 ' + sel.value, 'ok');
      document.getElementById('model-input').value = sel.value;
    } catch (e) { toast(e.message, 'error'); sel.value = document.getElementById('model-input').value || sel.value; }
  });
  // 从 config 同步当前值
  api('GET', '/api/config').then(cfg => {
    sel.value = cfg.model || sel.value;
  }).catch(() => {});
}

// ---- F5: 法条常驻侧边栏(可折叠、可浏览索引、可搜索) ----
const state_laws = { inited: false, railOpen: false, lastQuery: '' };

function setRailOpen(open) {
  const panel = document.getElementById('law-side-panel');
  const btn = document.getElementById('btn-law-rail-toggle');
  panel.hidden = !open;
  state_laws.railOpen = open;
  if (btn) btn.classList.toggle('active', open);
  try { localStorage.setItem('lawRailOpen', open ? '1' : '0'); } catch {}
  if (open && !panel.dataset.loaded) {
    initRailLawsIndex();
    panel.dataset.loaded = '1';
  }
}

async function initRailLawsIndex() {
  const sel = document.getElementById('lsp-law-select');
  const body = document.getElementById('lsp-body');
  if (!sel || !body) return;
  body.innerHTML = '<p class="muted">载入法条索引…</p>';
  try {
    const r = await api('GET', '/api/laws');
    const items = r.items || [];
    if (!state_laws.inited) {
      sel.innerHTML = '<option value="">全部法律</option>' +
        items.map(it => `<option value="${escapeHtml(it.name)}">${escapeHtml(it.name)} (${it.articleCount})</option>`).join('');
      state_laws.inited = true;
    }
    body.innerHTML = renderRailIndex(items);
    bindRailBody();
  } catch (e) {
    body.innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
  }
}

function renderRailIndex(items) {
  if (!items.length) return '<p class="muted">法条库为空。</p>';
  return items.map(it => `
    <div class="law-item" data-law="${escapeHtml(it.name)}">
      <div class="law-name">📘 ${escapeHtml(it.name)}</div>
      <div class="law-meta">${it.articleCount} 条 · 点击展开</div>
    </div>`).join('');
}

async function runRailSearch() {
  const qInput = document.getElementById('lsp-q');
  const lawSel = document.getElementById('lsp-law-select');
  const body = document.getElementById('lsp-body');
  const q = (qInput.value || '').trim();
  const law = (lawSel.value || '').trim();
  state_laws.lastQuery = q;
  try { localStorage.setItem('lawRailLastQuery', q); } catch {}
  if (!q) {
    // 不输入关键词 → 回退到索引浏览
    initRailLawsIndex();
    return;
  }
  body.innerHTML = '<p class="muted">搜索中…</p>';
  try {
    const params = new URLSearchParams({ q });
    if (law) params.set('law', law);
    const r = await api('GET', '/api/laws/search?' + params.toString());
    const items = r.items || [];
    body.innerHTML = items.length
      ? items.map(it => `
        <div class="law-item" data-load-law="${escapeHtml(it.law)}" data-load-art="${escapeHtml(it.article)}">
          <div class="law-name">《${escapeHtml(it.law)}》 第 ${escapeHtml(it.article)} 条</div>
          <div class="muted" style="font-size:11px;">${escapeHtml(it.chapter || '')}</div>
          <p style="font-size:12px;margin:4px 0;">${escapeHtml(it.snippet)}</p>
        </div>`).join('')
      : '<p class="muted">未找到相关法条。试试清空关键词浏览索引。</p>';
    bindRailBody();
  } catch (e) {
    body.innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
  }
}

async function loadRailArticle(law, art) {
  const body = document.getElementById('lsp-body');
  body.innerHTML = '<p class="muted">载入全文…</p>';
  try {
    const detail = await api('GET', `/api/laws/${encodeURIComponent(law)}/${encodeURIComponent(art)}`);
    body.innerHTML = `
      <div class="row" style="justify-content:space-between;margin-bottom:6px;">
        <button type="button" class="muted" id="btn-rail-back">← 返回</button>
        ${detail.sourceUrl ? `<a href="${escapeHtml(detail.sourceUrl)}" target="_blank" rel="noopener" class="muted" style="font-size:11px;">📖 官方原文</a>` : ''}
      </div>
      <div class="article-full">
        <h5>《${escapeHtml(detail.law)}》 第 ${escapeHtml(detail.article)} 条</h5>
        <div class="muted" style="font-size:11px;margin-bottom:4px;">${escapeHtml(detail.chapter || '')}</div>
        <div>${renderMarkdownLite(detail.content || '')}</div>
      </div>`;
    document.getElementById('btn-rail-back').onclick = () => {
      if (state_laws.lastQuery) runRailSearch();
      else initRailLawsIndex();
    };
  } catch (e) {
    body.innerHTML = `<p class="error">${escapeHtml(e.message)}</p>`;
  }
}

function bindRailBody() {
  const body = document.getElementById('lsp-body');
  // 索引项:点击 → 展开该法律所有条号
  body.querySelectorAll('.law-item[data-law]').forEach(el => {
    el.onclick = async () => {
      const law = el.dataset.law;
      el.querySelector('.law-meta').textContent = '载入中…';
      try {
        // 没有 list-all 接口,改用 search 通配——但 laws 没 list 端点
        // 改为直接展示该法所有 article 号:用 _internal_list?没有则用本地的 laws.json 接口
        // 后端没提供 → 这里走 search 兜底:用第 1 条 content 长度反查?不行
        // 解决方案:后端加 GET /api/laws/<name>/articles
        const r = await api('GET', `/api/laws/${encodeURIComponent(law)}/articles`);
        el.insertAdjacentHTML('afterend', renderRailArticles(law, r.items || []));
        el.style.display = 'none';
      } catch (e) {
        el.querySelector('.law-meta').textContent = '载入失败';
        toast(e.message, 'error');
      }
    };
  });
  // 搜索结果项:点击 → 加载全文
  body.querySelectorAll('.law-item[data-load-law]').forEach(el => {
    el.onclick = () => loadRailArticle(el.dataset.loadLaw, el.dataset.loadArt);
  });
}

function renderRailArticles(law, articles) {
  return `<div class="law-articles">
    <div class="row" style="justify-content:space-between;margin:4px 0;">
      <strong style="font-size:13px;">《${escapeHtml(law)}》</strong>
      <button type="button" class="muted" data-articles-back>← 返回索引</button>
    </div>
    <div>${articles.map(a => `<span class="article-link" data-load-law="${escapeHtml(law)}" data-load-art="${escapeHtml(a.article)}">第 ${escapeHtml(a.article)} 条</span>`).join('')}</div>
  </div>`;
}

// 顶部开关按钮 + 表单提交 + 关闭
document.getElementById('btn-law-rail-toggle').onclick = () => setRailOpen(!state_laws.railOpen);
document.getElementById('lsp-close').onclick = () => setRailOpen(false);
document.getElementById('lsp-form').addEventListener('submit', (ev) => {
  ev.preventDefault();
  runRailSearch();
});
// 委托:article 链接 / 返回索引
document.addEventListener('click', (ev) => {
  const artLink = ev.target.closest('.article-link[data-load-law]');
  if (artLink && artLink.closest('#law-side-panel')) {
    loadRailArticle(artLink.dataset.loadLaw, artLink.dataset.loadArt);
    return;
  }
  const backBtn = ev.target.closest('[data-articles-back]');
  if (backBtn && backBtn.closest('#law-side-panel')) {
    initRailLawsIndex();
    return;
  }
});

// 委托:主观题批改里的"打开法条栏"按钮
document.addEventListener('click', (ev) => {
  const btn = ev.target.closest('.btn-search-laws');
  if (!btn) return;
  const q = btn.dataset.q || '';
  setRailOpen(true);
  if (q) {
    document.getElementById('lsp-q').value = q.slice(0, 30);
    runRailSearch();
  }
});
// 委托:练习 / 考试答题区的小「📖 打开法条栏」按钮
document.addEventListener('click', (ev) => {
  const btn = ev.target.closest('.btn-open-law-rail');
  if (!btn) return;
  setRailOpen(true);
});

// 恢复用户上次的折叠状态
try {
  const wasOpen = localStorage.getItem('lawRailOpen') === '1';
  const lastQ = localStorage.getItem('lawRailLastQuery') || '';
  if (wasOpen) {
    setRailOpen(true);
    if (lastQ) {
      document.getElementById('lsp-q').value = lastQ;
      setTimeout(runRailSearch, 50);
    }
  }
} catch {}

// 旧的 /api/laws 视图初始化入口也走索引浏览
async function initLawsView() {
  const results = document.getElementById('laws-results');
  if (!results) return;
  try {
    const r = await api('GET', '/api/laws');
    results.innerHTML = (r.items || []).length
      ? `<p class="muted">点击右上角「📖 法条」打开常驻侧边栏,在这里浏览/搜索全部法条。</p>` +
        (r.items || []).map(it => `
        <div class="panel" style="margin-bottom:6px;">
          <strong>${escapeHtml(it.name)}</strong>
          <span class="muted">${it.articleCount} 条</span>
        </div>`).join('')
      : '<p class="muted">法条库为空。</p>';
  } catch (e) { showError(results, e); }
}


// ---- F1: 题库检索 + 打标签 ----

async function refreshTagFilter() {
  const bar = document.getElementById('search-tags-filter');
  if (!bar) return;
  try {
    const r = await api('GET', '/api/tags');
    const tags = r.items || [];
    if (!tags.length) {
      bar.innerHTML = '<span class="muted">暂无标签(选中题目后用下方"打标签"按钮创建)</span>';
      return;
    }
    bar.innerHTML = '<span class="muted">按标签筛选:</span>' + tags.map(t => {
      const active = state.searchTags.includes(t.name);
      return `<span class="tag-chip${active ? '' : ' inactive'}" data-tag="${escapeHtml(t.name)}">${escapeHtml(t.name)} <small>(${t.count})</small></span>`;
    }).join('');
    bar.querySelectorAll('.tag-chip').forEach(chip => {
      chip.onclick = () => {
        const t = chip.dataset.tag;
        const i = state.searchTags.indexOf(t);
        if (i >= 0) state.searchTags.splice(i, 1);
        else state.searchTags.push(t);
        runSearch();
      };
    });
  } catch (e) {
    bar.innerHTML = `<span class="error">${escapeHtml(e.message)}</span>`;
  }
}

async function runSearch() {
  const form = document.getElementById('form-search');
  if (!form) return;
  const fd = new FormData(form);
  const kind = fd.get('kind') || 'questions';
  state.searchKind = kind;
  const params = new URLSearchParams();
  params.set('type', kind);
  const q = (fd.get('q') || '').toString().trim();
  if (q) params.set('q', q);
  const subject = (fd.get('subject') || '').toString().trim();
  if (subject) params.set('subject', subject);
  const topic = (fd.get('topic') || '').toString().trim();
  if (topic) params.set('topic', topic);
  if (kind === 'questions' && state.searchTags.length) {
    params.set('tags', state.searchTags.join(','));
  }
  params.set('limit', '50');

  const seq = ++state._searchSeq;
  const out = document.getElementById('search-results');
  out.innerHTML = '<p class="muted">搜索中…</p>';
  try {
    const r = await api('GET', `/api/search?${params}`);
    if (seq !== state._searchSeq) return;  // 旧请求,忽略
    state.searchResults = r.items || [];
    // 同步已勾选项(保留跨搜索的勾选,但丢弃已不在结果里的)
    const presentIds = new Set(state.searchResults.map(it => it.id));
    state.searchSelected = new Set([...state.searchSelected].filter(id => presentIds.has(id)));
    renderSearchResults();
    // 搜索后刷新一下 tag chip(可能新增)
    if (kind === 'questions') refreshTagFilter();
  } catch (e) {
    out.innerHTML = `<div class="error">⚠️ ${escapeHtml(e.message)}</div>`;
  }
}

function renderSearchResults() {
  const out = document.getElementById('search-results');
  const items = state.searchResults;
  if (!items.length) {
    out.innerHTML = '<p class="muted">没有结果。</p>';
    updateBatchBar();
    return;
  }
  const isQ = state.searchKind === 'questions';
  out.innerHTML = `<p class="muted">共 ${items.length} 条${isQ ? '' : '错题'}</p>` + items.map(it => {
    if (isQ) {
      const checked = state.searchSelected.has(it.id) ? 'checked' : '';
      const optsHtml = (it.options || []).map(o => `<div>${escapeHtml(o)}</div>`).join('');
      const tagsHtml = (it.tags || []).map(t =>
        `<span class="tag-chip removable" data-qid="${escapeHtml(it.id)}" data-tag="${escapeHtml(t)}">${escapeHtml(t)}</span>`
      ).join('');
      return `<div class="search-card" data-qid="${escapeHtml(it.id)}">
        <div class="qhead">
          <input type="checkbox" class="qselect" data-qid="${escapeHtml(it.id)}" ${checked}/>
          <strong>${escapeHtml(it.subject || '?')}</strong>
          <span class="muted">· ${escapeHtml(it.type || '')}</span>
          <span class="muted">· ${escapeHtml(it.topic || '')}</span>
          <span class="muted">· ${escapeHtml(it.difficulty || '')}</span>
          <span style="margin-left:auto;">
            <button type="button" class="btn-detail" data-detail-qid="${escapeHtml(it.id)}">查看详情</button>
          </span>
        </div>
        <div class="qstem">${escapeHtml(it.stem || '').slice(0, 240)}${(it.stem || '').length > 240 ? '…' : ''}</div>
        ${optsHtml ? `<div class="qopts">${optsHtml}</div>` : ''}
        ${tagsHtml ? `<div class="tag-row">${tagsHtml}</div>` : ''}
      </div>`;
    } else {
      // mistake card
      const checked = state.searchSelected.has(it.id) ? 'checked' : '';
      return `<div class="search-card" data-mistake-id="${escapeHtml(it.id)}">
        <div class="qhead">
          <span style="color:#999;font-size:11px;">${it.reviewed ? '✓ 已掌握' : '✗ 未掌握'}</span>
          <strong>${escapeHtml(it.subject || '?')}</strong>
          <span class="muted">· ${escapeHtml(it.type || '')}</span>
          <span class="muted">· ${escapeHtml(it.topic || '')}</span>
          <span class="muted" style="margin-left:auto;">错题于 ${escapeHtml((it.addedAt || '').slice(0, 10))}</span>
        </div>
        <div class="qstem">${escapeHtml(it.stem || '(已无题干)').slice(0, 240)}</div>
        <div class="muted" style="font-size:12px;">你的答案:${escapeHtml((it.userAnswer || '').slice(0, 80))} | 得分:${it.score}/${it.maxScore}</div>
      </div>`;
    }
  }).join('');
  bindSearchResultActions();
  updateBatchBar();
}

function updateBatchBar() {
  const bar = document.getElementById('search-batch-bar');
  const cnt = document.getElementById('search-batch-count');
  if (!bar || !cnt) return;
  const n = state.searchSelected.size;
  cnt.textContent = `已选 ${n} 题`;
  bar.hidden = state.searchKind !== 'questions' || n === 0;
}

function bindSearchResultActions() {
  // checkbox 切换选中
  document.querySelectorAll('#search-results .qselect').forEach(cb => {
    cb.onchange = () => {
      const id = cb.dataset.qid;
      if (cb.checked) state.searchSelected.add(id);
      else state.searchSelected.delete(id);
      updateBatchBar();
    };
  });
  // tag chip 移除
  document.querySelectorAll('#search-results .tag-chip.removable').forEach(chip => {
    chip.onclick = async () => {
      const qid = chip.dataset.qid;
      const tag = chip.dataset.tag;
      try {
        await api('DELETE', `/api/question/${encodeURIComponent(qid)}/tag/${encodeURIComponent(tag)}`);
        runSearch();
      } catch (e) {
        toast(e.message, 'error');
      }
    };
  });
  // 查看详情
  document.querySelectorAll('#search-results [data-detail-qid]').forEach(btn => {
    btn.onclick = async () => {
      const qid = btn.dataset.detailQid;
      try {
        const r = await api('GET', `/api/question/${encodeURIComponent(qid)}`);
        const q = r.question;
        showQuestionDetailModal(q, r.attempts || []);
      } catch (e) {
        toast(e.message, 'error');
      }
    };
  });
}

function showQuestionDetailModal(q, attempts) {
  // 用一个简单的 panel 替换 search-results 区显示详情
  const out = document.getElementById('search-results');
  const opts = (q.options || []).map(o => `<div>${escapeHtml(o)}</div>`).join('');
  const hist = attempts.map(a =>
    `<li>${escapeHtml((a.submittedAt || '').slice(0, 16))} · 得分 ${a.score}/${a.maxScore} · ${a.isCorrect ? '✓' : '✗'}</li>`
  ).join('') || '<li class="muted">无</li>';
  const tagsHtml = (q.tags || []).map(t => `<span class="tag-chip">${escapeHtml(t)}</span>`).join(' ');
  out.innerHTML = `
    <div class="row" style="justify-content:space-between;">
      <strong>题目详情</strong>
      <button type="button" class="muted" id="btn-back-to-results">← 返回搜索结果</button>
    </div>
    <div class="search-card">
      <div class="qhead">
        <strong>${escapeHtml(q.subject || '?')}</strong>
        <span class="muted">· ${escapeHtml(q.type || '')}</span>
        <span class="muted">· ${escapeHtml(q.topic || '')}</span>
      </div>
      <div class="qstem">${escapeHtml(q.stem || '')}</div>
      ${opts ? `<div class="qopts">${opts}</div>` : ''}
      <div><strong>答案:</strong>${escapeHtml(q.answer || '')}</div>
      <div><strong>解析:</strong>${escapeHtml(q.explanation || '')}</div>
      ${tagsHtml ? `<div class="tag-row" style="margin-top:6px;">${tagsHtml}</div>` : ''}
    </div>
    <h4>历史作答 (${attempts.length})</h4>
    <ul>${hist}</ul>
  `;
  document.getElementById('btn-back-to-results').onclick = renderSearchResults;
}

// ---- F1 表单 + 批量打标签 交互 ----
function initSearchForm() {
  const form = document.getElementById('form-search');
  if (!form) return;
  form.onsubmit = (ev) => { ev.preventDefault(); runSearch(); };
  // radio 切换时清掉选择(避免题型错乱)
  form.querySelectorAll('input[name="kind"]').forEach(r => {
    r.onchange = () => {
      state.searchSelected.clear();
      runSearch();
    };
  });

  const bar = document.getElementById('search-batch-bar');
  document.getElementById('btn-open-tag-editor').onclick = openTagEditor;
  document.getElementById('btn-clear-selection').onclick = () => {
    state.searchSelected.clear();
    document.querySelectorAll('#search-results .qselect').forEach(cb => cb.checked = false);
    updateBatchBar();
  };
  document.getElementById('btn-close-tag-editor').onclick = closeTagEditor;
  document.getElementById('btn-apply-tag-batch').onclick = applyTagBatch;
}

async function openTagEditor() {
  const editor = document.getElementById('tag-editor');
  editor.hidden = false;
  const msg = document.getElementById('tag-editor-msg');
  msg.textContent = '';
  document.getElementById('tag-new-input').value = '';
  // 渲染已有 tag(从 /api/tags 取前 20 个常用)
  try {
    const r = await api('GET', '/api/tags');
    const chips = document.getElementById('tag-existing-chips');
    const top = (r.items || []).slice(0, 20);
    chips.innerHTML = top.length
      ? top.map(t => `<span class="tag-chip muted" data-tag="${escapeHtml(t.name)}">+ ${escapeHtml(t.name)}</span>`).join('')
      : '<span class="muted">暂无</span>';
    chips.querySelectorAll('.tag-chip').forEach(c => {
      c.onclick = () => {
        const t = c.dataset.tag;
        const inp = document.getElementById('tag-new-input');
        const current = inp.value.split(/[,，\s]+/).filter(Boolean);
        if (!current.includes(t)) inp.value = [...current, t].join(',');
      };
    });
  } catch (e) { /* ignore */ }
}

function closeTagEditor() {
  document.getElementById('tag-editor').hidden = true;
}

async function applyTagBatch() {
  const inp = document.getElementById('tag-new-input').value;
  const newTags = inp.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean);
  const msg = document.getElementById('tag-editor-msg');
  const ids = [...state.searchSelected];
  if (!ids.length) { msg.innerHTML = '<span class="error">未选择任何题目</span>'; return; }
  if (!newTags.length) { msg.innerHTML = '<span class="error">请填写至少一个标签</span>'; return; }
  msg.textContent = `正在为 ${ids.length} 题打标签…`;
  try {
    const r = await api('POST', '/api/questions/batch-tags', { ids, addTags: newTags });
    msg.innerHTML = `<span style="color:#0a7a0a;">✓ 已更新 ${r.affected} 题的标签</span>`;
    toast(`已为 ${r.affected} 题打标签`, 'info');
    closeTagEditor();
    runSearch();  // 重新拉,刷新视图 + tag chip
  } catch (e) {
    msg.innerHTML = `<span class="error">${escapeHtml(e.message)}</span>`;
  }
}

initSearchForm();


// ---- F3: 错题复习出卷 ----

function renderMistakeReviewBar() {
  // 在 #mistake-stats-panel 之后追加(若无则插入到 #history-list 之前)
  const host = document.getElementById('history-list');
  if (!host) return;
  if (document.getElementById('mistake-review-bar')) return;  // 已存在
  const bar = document.createElement('div');
  bar.id = 'mistake-review-bar';
  bar.className = 'panel';
  bar.innerHTML = `
    <h3 style="margin-top:0;">🔁 错题复习出卷</h3>
    <p class="muted">从错题本里挑一批题打包成一张复习卷(复用现有考试流程)。</p>
    <form id="form-mistake-review" class="row" style="flex-wrap:wrap;gap:12px;align-items:end;">
      <label>科目
        <select id="mr-subject">
          <option value="">全部</option>
          <option>民法</option><option>刑法</option><option>行政法</option>
          <option>民事诉讼法</option><option>刑事诉讼法</option>
          <option>商经法</option><option>理论法</option><option>三国法</option>
        </select>
      </label>
      <label>考点(可选) <input id="mr-topic" placeholder="如:诉讼时效" style="width:160px;"/></label>
      <label>题数 <input id="mr-max" type="number" value="15" min="3" max="30" style="width:60px;"/></label>
      <label class="row"><input type="checkbox" id="mr-include-reviewed"/> 包含已掌握</label>
      <button type="submit">📝 生成复习卷</button>
      <div id="mr-msg" class="muted" style="flex-basis:100%;"></div>
    </form>
  `;
  host.parentNode.insertBefore(bar, host);
  document.getElementById('form-mistake-review').onsubmit = async (ev) => {
    ev.preventDefault();
    const msg = document.getElementById('mr-msg');
    msg.textContent = '生成中…';
    try {
      const r = await api('POST', '/api/exam/review-mistakes', {
        subject: document.getElementById('mr-subject').value || null,
        topic: document.getElementById('mr-topic').value.trim() || null,
        maxQuestions: parseInt(document.getElementById('mr-max').value, 10) || 15,
        includeReviewed: document.getElementById('mr-include-reviewed').checked,
      });
      msg.innerHTML = `<span style="color:#0a7a0a;">✓ 已生成:${escapeHtml(r.exam.title || '复习卷')}(${r.exam.totalQuestions} 题)</span>`;
      toast(`复习卷已就绪:${r.exam.totalQuestions} 题`, 'info');
      const exam = r.exam;
      // 跳到考试子 tab + 加载确认页
      location.hash = '#practice';
      setTimeout(() => {
        const tab = document.querySelector('[data-practice-tab="exam"]');
        if (tab) tab.click();
        exam.durationMinutes = exam.durationMinutes || 90;
        exam.timeUp = false;
        showConfirmPage(exam);
      }, 100);
    } catch (e) {
      msg.innerHTML = `<span class="error">${escapeHtml(e.message)}</span>`;
    }
  };
}