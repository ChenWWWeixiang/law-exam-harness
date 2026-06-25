// 法考 AI 学习 Harness - 前端逻辑
// 单一全局 state + hash 路由 + fetch 封装
'use strict';

const state = {
  view: 'home',
  config: null,
  conversationId: null,
  currentQuestion: null,       // 练习页当前题目
  historyTab: 'questions',
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
    const r = await api('POST', '/api/chat', {
      subject: f.subject.value,
      style: f.style.value,
      question: f.question.value,
      webSearch: f.webSearch.checked,
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
  return html;
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
  if (!f.topic || !f.question.value) {
    toast('需要先填写知识点或问题', 'warn');
    return;
  }
  // 简单复用知识点作为 topic
  location.hash = '#generate';
  setTimeout(() => {
    const g = document.getElementById('form-generate');
    g.topic.value = f.question.value.slice(0, 30);
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
  document.getElementById('practice-meta').innerHTML =
    `<span class="badge">${escapeHtml(q.subject || '')}</span>
     <span class="badge">${escapeHtml(q.type || '')}</span>
     <span class="badge">${escapeHtml(q.difficulty || '')}</span>`;
  document.getElementById('practice-stem').innerHTML = renderMarkdownLite(q.stem);
  const optEl = document.getElementById('practice-options');
  if (q.options && q.options.length) {
    optEl.innerHTML = '<ol class="opts">' + q.options.map(o => `<li>${escapeHtml(o)}</li>`).join('') + '</ol>';
    optEl.hidden = false;
  } else { optEl.hidden = true; }
  document.getElementById('practice-answer').value = '';
  document.getElementById('practice-feedback').hidden = true;
}

document.getElementById('btn-submit-practice').addEventListener('click', async () => {
  const q = state.currentQuestion;
  const userAnswer = document.getElementById('practice-answer').value.trim();
  if (!q) return;
  if (!userAnswer) { toast('请填写答案', 'warn'); return; }
  const fb = document.getElementById('practice-feedback');
  const body = document.getElementById('practice-feedback-body');
  fb.hidden = false;
  body.innerHTML = '<p class="muted">批改中…</p>';
  try {
    const r = await api('POST', '/api/grade-answer', {
      question: q,
      userAnswer,
      maxScore: 20,
    });
    body.innerHTML = renderFeedback(r.feedback);
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

function renderFeedback(f) {
  if (!f) return '';
  const pct = f.maxScore ? Math.round((f.score / f.maxScore) * 100) : 0;
  return `
    <div class="score-line">得分: <strong>${f.score}</strong> / ${f.maxScore} (${pct}%) — ${escapeHtml(f.verdict || '')}</div>
    ${f.earnedPoints && f.earnedPoints.length
      ? '<h4>✅ 得分点</h4><ul>' + f.earnedPoints.map(p => `<li>${escapeHtml(p)}</li>`).join('') + '</ul>' : ''}
    ${f.missedPoints && f.missedPoints.length
      ? '<h4>❌ 扣分点</h4><ul>' + f.missedPoints.map(p => `<li>${escapeHtml(p)}</li>`).join('') + '</ul>' : ''}
    ${f.userAnswerAnalysis ? '<h4>分析</h4>' + renderMarkdownLite(f.userAnswerAnalysis) : ''}
    ${f.referenceAnswer ? '<h4>参考答案</h4>' + renderMarkdownLite(f.referenceAnswer) : ''}
    ${f.suggestions && f.suggestions.length
      ? '<h4>改进建议</h4><ul>' + f.suggestions.map(s => `<li>${escapeHtml(s)}</li>`).join('') + '</ul>' : ''}
    ${f.relatedTopics && f.relatedTopics.length
      ? '<h4>相关知识点</h4><ul>' + f.relatedTopics.map(t => `<li>${escapeHtml(t)}</li>`).join('') + '</ul>' : ''}
  `;
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
    const r = await api('POST', '/api/grade-answer', {
      question: {
        subject: f.subject.value,
        type: f.questionType.value,
        stem: f.stem.value,
      },
      userAnswer: f.userAnswer.value,
      maxScore: parseInt(f.maxScore.value, 10) || 20,
      rubric: f.rubric.value,
      addToMistakes: f.addToMistakes.checked,
    });
    body.innerHTML = renderFeedback(r.feedback);
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
  } catch (e) {
    showError(list, e);
  }
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
              <div class="muted">${escapeHtml((f.verdict || '').slice(0, 80))}</div>`;
    } else if (type === 'mistakes') {
      body = `<div>${escapeHtml(it.reason || '')}</div>
              <div class="muted">关联题目: ${escapeHtml(it.questionId || '无')}</div>`;
    } else if (type === 'sessions') {
      body = `<div class="muted">${it.messages ? it.messages.length : 0} 条消息 · 科目 ${escapeHtml(it.subject || '')}</div>`;
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
}

// ---- 启动 ----
(function init() {
  const m = (location.hash || '#home').match(/#([^?]+)/);
  showView(m ? m[1] : 'home');
  refreshStatus();
})();