/* tutor 前端两个入口（tutor 规格 v0.1 §11 第 3 步 · 本版 REQ-TUTOR-08/09/10/11/12）：
   ① 卡片页「问这个」→ 全屏浮层，首条消息自动带该卡上下文（mode=card）；关闭即回原卡，
      不动 location.hash、不重渲染页面 → 复习进度不丢；
   ② 独立聊天页 #/tutor → 学科范围纵向折叠选择 + 消息流 + 底部固定输入框 + 今日剩余次数；
   ③ `type=clarify` → options 渲染成可点按钮（不是让人打概念名），点一下带 concept_id 重发；
   ④ 〔库外知识〕/〔网上来源〕 → 独立样式块（灰底 + 左边线 + 小标签），绝不方括号直出；
   ⑤ `type=not_found` → 「库里没找到贴合的页」，不给任何伪造引用。

   一键关掉（回滚开关）：index.html 的 <meta name="tutor-ui" content="on">
   改成 "off"（或运行时 window.TUTOR_UI = false）→ 全站入口（首页行 + 卡页按钮）消失；
   #/tutor 固定 URL 仍可用（规格：入口可关，直链不受影响）。
   纯原生 JS，不引框架/依赖（UI-004）；禁横向滑动（UI-001）。 */
(function () {
  const LIB_OPEN = '〔库外知识〕', LIB_CLOSE = '〔/库外知识〕';
  const WEB_OPEN = '〔网上来源〕', WEB_CLOSE = '〔/网上来源〕';
  const CLARIFY_TAG = '〔澄清〕';
  const CARD_DEFAULT = '讲讲这张卡';
  const NOT_FOUND = '库里没找到贴合的页';
  const STYLES = [['explain', '详细解释'], ['brief', '简答'], ['socratic', '苏格拉底式']];

  function savedStyle() {
    try { return localStorage.getItem('tutorStyle') || 'explain'; } catch (_) { return 'explain'; }
  }

  /* 三种作答风格：详细解释（默认）/ 简答 / 苏格拉底引导 —— 常显，当前项高亮 */
  function styleBarHTML() {
    const cur = savedStyle();
    const btns = STYLES.map(([id, label]) =>
      `<button class="btn tutor-style${id === cur ? ' on' : ''}" type="button" data-style="${id}" aria-pressed="${id === cur}">${label}</button>`).join('');
    return `<div class="tutor-styles" role="group" aria-label="作答风格">${btns}</div>`;
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* 回滚开关：meta 优先，window.TUTOR_UI=false 兜底。 */
  function enabled() {
    if (window.TUTOR_UI === false) return false;
    const meta = document.querySelector('meta[name="tutor-ui"]');
    if (!meta) return true;
    return String(meta.getAttribute('content') || '').trim().toLowerCase() !== 'off';
  }

  function linkify(escaped) {
    return escaped.replace(/https?:\/\/[^\s<（)）】"'，。；、]+/g,
      (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`);
  }

  function paragraphs(text) {
    return text.split(/\n+/).filter((p, i, arr) => p.trim() || arr.length === 1)
      .map((p) => `<p>${p}</p>`).join('');
  }

  /* 标记解析：〔库外知识〕…〔/库外知识〕、〔网上来源〕…〔/网上来源〕→ 独立块。
     缺闭合标记时吃到文本末尾（宁可整段标成库外，也不把方括号漏出去）。 */
  function formatReply(raw) {
    const text = String(raw || '').replace(CLARIFY_TAG, '').trim();
    if (!text) return '';
    const re = new RegExp(`\\${LIB_OPEN}([\\s\\S]*?)(?:\\${LIB_CLOSE}|$)|\\${WEB_OPEN}([\\s\\S]*?)(?:\\${WEB_CLOSE}|$)`, 'g');
    const out = [];
    let last = 0;
    let m;
    const plain = (chunk) => (chunk.trim() ? paragraphs(linkify(esc(chunk))) : '');
    while ((m = re.exec(text)) !== null) {
      out.push(plain(text.slice(last, m.index)));
      if (m[1] !== undefined) {
        out.push(`<aside class="tutor-lib"><span class="tlab">库外知识</span>${plain(m[1])}</aside>`);
      } else {
        out.push(`<aside class="tutor-web"><span class="tlab">网上来源</span>${plain(m[2])}</aside>`);
      }
      last = re.lastIndex;
    }
    out.push(plain(text.slice(last)));
    return out.join('');
  }

  function sourcesHTML(sources) {
    const list = (sources || []).filter((s) => s && (s.concept || s.front));
    if (!list.length) return '';
    // 出处字段原样各占一行（前端不拼接/不截断/不换算：display-boundary 口径）
    let items = '';
    list.forEach((src) => {
      items += `<li><b>${esc(src.concept || '')}</b><span>${esc(src.front || '')}</span></li>`;
    });
    return `<div class="tutor-src"><span class="tlab">来源</span><ul>${items}</ul></div>`;
  }

  function quotaText(q) {
    if (!q) return '今日次数读取中…';
    const left = (q.remaining === null || q.remaining === undefined) ? null : q.remaining;
    return left === null ? String(q.label || '') : `今天还能问 ${left} 次`;
  }

  /* ——— 一个对话面板（浮层与独立页共用同一套 DOM/样式，只有 .sheet / .page 之别） ——— */
  function createPanel(node, opts) {
    const o = opts || {};
    const thread = node.querySelector('[data-thread]');
    const form = node.querySelector('[data-form]');
    const input = node.querySelector('[data-input]');
    const quotaEl = node.querySelector('[data-quota]');
    const state = { conversationId: o.conversationId || null, busy: false, mode: o.mode || 'free', style: savedStyle(), cardId: o.cardId || null, subjectId: null };

    /* 浮层内自己滚；独立页随文档滚 —— 只在用户本来就贴着底部时才跟着滚（不抢阅读位置）。
       判断必须在 append 之前做：新消息一进 DOM，scrollHeight 立刻变大，append 之后再算永远「不在底部」。
       必须滚到底：底部输入框是 fixed，最后一条消息若被它压住，手指点到的会是输入框。 */
    function atBottom() {
      if (o.sheet) return true;
      return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 260;
    }

    function scrollEnd() {
      if (o.sheet) { thread.scrollTop = thread.scrollHeight; return; }
      window.scrollTo({ top: document.documentElement.scrollHeight });
    }

    function push(who, html, cls) {
      const follow = atBottom();              // 先记下「用户是否贴着底部」
      const div = document.createElement('div');
      div.className = `tutor-msg ${who === 'me' ? 'me' : 'ai'}${cls ? ' ' + cls : ''}`;
      div.innerHTML = `<span class="who">${who === 'me' ? '我' : '助教'}</span><div class="body">${html}</div>`;
      thread.appendChild(div);
      if (follow) scrollEnd();
      return div;
    }

    function pending(html) {
      return push('ai', `<p class="sub">${esc(html)}</p>`, 'pending');
    }

    function setQuota(q) { if (quotaEl && q) quotaEl.textContent = quotaText(q); }

    async function refreshQuota() {
      try { const r = await api.get('/api/tutor/quota'); setQuota(r.data); } catch (_) { /* 读不到就保持上一行，不打断对话 */ }
    }

    /* 澄清选项：渲染成可点按钮，点一下带 concept_id 重发（不是让人打概念名）。 */
    function clarifyHTML(turn) {
      const options = turn.options || [];
      const buttons = options.length
        ? `<div class="tutor-opts">${options.map((op) => `<button class="btn tutor-opt" type="button" data-concept="${Number(op.concept_id)}">${esc(op.name)}</button>`).join('')}</div>`
        : '';
      return `<p class="tutor-q">${esc(turn.question || '你说的是哪一种？')}</p>
        <p class="sub">点一个最接近的，我按那个概念讲。</p>${buttons}`;
    }

    function render(turn) {
      if (!turn) return;
      if (turn.type === 'clarify') return push('ai', clarifyHTML(turn));
      if (turn.type === 'not_found') {
        return push('ai', `<div class="tutor-none"><span class="tlab">库里没有</span>
          <p>${esc(turn.reply || NOT_FOUND)}</p>
          <p class="sub">不给编造引用；换个更具体的说法，或先告诉我在读哪一章。</p></div>`);
      }
      return push('ai', formatReply(turn.reply) + sourcesHTML(turn.sources));
    }

    async function send(text, extra) {
      if (state.busy) return;
      const ex = extra || {};
      const body = {
        mode: state.mode,
        style: state.style,
        conversation_id: state.conversationId || undefined,
      };
      if (state.cardId) body.card_id = state.cardId;
      if (state.subjectId) body.subject_id = state.subjectId;
      const typed = (text || '').trim();
      if (typed) body.message = typed;
      if (ex.conceptId) body.concept_id = ex.conceptId;

      if (typed) push('me', paragraphs(esc(typed)));
      state.busy = true;
      const waiting = pending(ex.conceptId ? '正在按你选的概念找卡片…' : '正在找库里的页…');
      try {
        const r = await api.post('/api/tutor/chat', body);
        waiting.remove();
        const data = r.data || {};
        if (data.conversation_id) state.conversationId = data.conversation_id;
        if (data.quota) setQuota(data.quota);
        render(data);
      } catch (e) {
        waiting.remove();
        push('ai', `<div class="tutor-none"><span class="tlab">出错了</span>
          <p>${esc(e && e.message ? e.message : '网络不太顺，稍后再试一次。')}</p></div>`);
      } finally {
        state.busy = false;
      }
    }

    /* 点澄清按钮 → 带 concept_id 重发（同一句不重复显示在消息流里）。 */
    thread.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-concept]');
      if (!btn || btn.disabled) return;
      const conceptId = Number(btn.dataset.concept);
      thread.querySelectorAll('[data-concept]').forEach((b) => {
        b.disabled = true;
        b.classList.toggle('sel', b === btn);
      });
      btn.classList.add('sel');
      send('', { conceptId });
    });

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const value = (input.value || '').trim();
      if (!value || state.busy) return;
      input.value = '';
      input.style.height = '';
      send(value);
    });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event('submit', { cancelable: true }));
      }
    });
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      const want = input.scrollHeight;                 // 输入框自动长高，最高 132px（不引 Math）
      input.style.height = `${want > 132 ? 132 : want}px`;
    });

    node.querySelectorAll('[data-style]').forEach((b) => {
      b.addEventListener('click', () => {
        state.style = b.dataset.style;
        try { localStorage.setItem('tutorStyle', state.style); } catch (_) { /* 隐私模式：本次会话内仍生效 */ }
        node.querySelectorAll('[data-style]').forEach((x) => {
          const on = x === b;
          x.classList.toggle('on', on);
          x.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      });
    });

    node.querySelectorAll('[data-quick]').forEach((b) => {
      b.addEventListener('click', () => {
        const kind = b.dataset.quick;                 // quiz → 场景 3 出题陪练；plan → 场景 4 计划建议
        state.mode = kind === 'plan' ? 'plan' : 'quiz';
        send(kind === 'plan' ? '今天学什么' : '考考我');
        state.mode = 'free';
      });
    });

    refreshQuota();

    return { send, push, state, setQuota, refreshQuota };
  }

  /* ——— ① 卡片页浮层 ——— */
  let sheetNode = null;
  let lastFocus = null;

  function closeSheet() {
    if (!sheetNode) return;
    sheetNode.remove();
    sheetNode = null;
    document.removeEventListener('keydown', onSheetKey);
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (_) { /* 原元素已不在页面上 */ } }
    lastFocus = null;
  }

  function onSheetKey(event) { if (event.key === 'Escape') closeSheet(); }

  function askCard(cardId, cardTitle) {
    if (!enabled()) return;
    closeSheet();
    lastFocus = document.activeElement;
    const node = document.createElement('div');
    node.className = 'tutor-sheet';
    node.setAttribute('role', 'dialog');
    node.setAttribute('aria-modal', 'true');
    node.setAttribute('aria-label', '问 tutor：这张卡');
    node.innerHTML = `
      <header class="tutor-sheet-head">
        <span class="l"><b>问这个</b><span class="sub">${esc(cardTitle || '')}</span></span>
        <span class="r"><span class="tutor-quota" data-quota></span>
          <button class="tutor-close" type="button" aria-label="关闭" title="关闭">关闭</button></span>
      </header>
      <div class="tutor-thread" data-thread></div>
      <div class="tutor-composer">
        ${styleBarHTML()}
        <form class="tutor-form" data-form>
          <textarea class="tutor-input" data-input rows="1" placeholder="继续追问这张卡…" enterkeyhint="send" autocomplete="off"></textarea>
          <button class="btn solid tutor-send" type="submit">发送</button>
        </form>
      </div>`;
    document.body.appendChild(node);
    sheetNode = node;
    node.querySelector('.tutor-close').addEventListener('click', closeSheet);
    document.addEventListener('keydown', onSheetKey);

    const panel = createPanel(node, { sheet: true, mode: 'card', cardId: Number(cardId) });
    panel.send(CARD_DEFAULT);   // 首条消息自动带该卡上下文（mode=card + card_id），用户不用先打字
  }

  /* ——— ② 独立聊天页 #/tutor ——— */
  async function page() {
    const root = document.getElementById('app');
    root.innerHTML = `
      <section class="tutor-page">
        <h1 class="display">问 tutor</h1>
        <p class="sub">先找库里的页；库里没有的会单独标成「库外知识」，不冒充卡片原文。</p>
        <div class="tutor-head">
          <span class="mlabel g">Tutor</span>
          <span class="tutor-quota" data-quota>今日次数读取中…</span>
        </div>
        <details class="tutor-scope" data-scope>
          <summary><span class="l"><b>范围</b><span class="sub" data-scope-label>全部学科</span></span>
            <span class="r">展开<span class="caret">▾</span></span></summary>
          <div class="rowlist" data-scope-list><a class="row" href="#/tutor"><span class="l"><b>全部学科</b><span>正在读取学科…</span></span></a></div>
        </details>
        <div class="tutor-thread" data-thread>
          <p class="sub tutor-empty">问点什么：<b>他动手了我怕他</b>、<b>今天学什么</b>、<b>考考我</b>。</p>
        </div>
        <div class="tutor-composer">
          ${styleBarHTML()}
          <div class="tutor-quick">
            <button class="btn tutor-quick-btn" type="button" data-quick="quiz">考考我</button>
            <button class="btn tutor-quick-btn" type="button" data-quick="plan">今天学什么</button>
          </div>
          <form class="tutor-form" data-form>
            <textarea class="tutor-input" data-input rows="1" placeholder="问点什么…" enterkeyhint="send" autocomplete="off"></textarea>
            <button class="btn solid tutor-send" type="submit">发送</button>
          </form>
        </div>
      </section>`;
    const panel = createPanel(root, { sheet: false, mode: 'free' });
    try {
      const subs = (await api.get('/api/subjects')).data.subjects || [];
      const list = root.querySelector('[data-scope-list]');
      const label = root.querySelector('[data-scope-label]');
      list.innerHTML = [`<button class="row tutor-scope-item on" type="button" data-subject="0">
          <span class="l"><b>全部学科</b><span>不缩范围，全库检索</span></span></button>`]
        .concat(subs.map((s) => `<button class="row tutor-scope-item" type="button" data-subject="${Number(s.id)}">
          <span class="l"><b>${esc(s.name)}</b><span>共 <span class="tnum">${s.cards_total || 0}</span> 张卡</span></span></button>`))
        .join('');
      list.addEventListener('click', (event) => {
        const btn = event.target.closest('[data-subject]');
        if (!btn) return;
        const id = Number(btn.dataset.subject);
        panel.state.subjectId = id || null;
        list.querySelectorAll('[data-subject]').forEach((b) => b.classList.toggle('on', b === btn));
        label.textContent = id ? (btn.querySelector('b').textContent || '已选学科') : '全部学科';
        root.querySelector('[data-scope]').open = false;
      });
    } catch (_) {
      root.querySelector('[data-scope-list]').innerHTML = '<p class="sub">学科列表暂时读不到，仍可自由提问。</p>';
    }
  }

  function render() { return page(); }

  window.TutorUI = { enabled, askCard, close: closeSheet, formatReply };
  window.TutorView = { render };
})();
