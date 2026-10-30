/* 个人复习 — 钻取式前端（UI-001/002/003/004 + MAST-001/002 + HOME-001 + TASK-001）。
   视觉世界规格见 DESIGN.md（对后续一律适用）：令牌 / 字号尺度 / hairline 结构 / 一屏一主行动。
   纯原生 JS，不引框架；所有渲染 try/catch 兜底，绝不断 boot 链。 */
(function () {
  const app = document.getElementById('app');
  const routeKey = 'review-route-stack';
  let routeBefore = location.hash || '#/';
  let currentNav = null;
  let returning = false;
  function readStack() {
    try {
      const value = JSON.parse(sessionStorage.getItem(routeKey) || '[]');
      return Array.isArray(value) ? value : [];
    } catch (_) { return []; }
  }
  function setupBack() {
    const b = document.getElementById('backBtn'); if (!b) return;
    const row = b.parentElement;
    const here = location.hash || '#/';
    const top = here === '#/' || here === '#';
    // 首頁不做返回：整條 navrow 一起收起來（不留空位、不置灰佔位）
    b.hidden = top; if (row && row.classList.contains('navrow')) row.hidden = top;
    b.disabled = false;
    b.setAttribute('aria-disabled', String(top));
    b.title = '返回上一级';
    b.onclick = () => {
      if (b.disabled) return;
      const stack = readStack();
      const target = stack.length ? stack.pop() : (currentNav && currentNav.parent_href) || '#/';
      sessionStorage.setItem(routeKey, JSON.stringify(stack));
      returning = target !== here;
      location.hash = target;
    };
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function html(markup) { app.innerHTML = markup; }

  function pct(done, total) {
    return total ? Math.round((done / total) * 100) : 0;
  }

  // UNI-MASTER：层级数值及状态标签全部只读后端字段。
  function mLab(m) { return m && m.m !== null ? `掌握度 ${m.m}%` : '掌握度 —'; }
  function mWidth(m) { return m && m.m !== null ? m.m : 0; }
  function mText(m) {
    const o = m || {};
    return `${mLab(o)} · 覆盖率 ${o.coverage}% · 已学 ${o.learned} / 共 ${o.cards_total} · ${o.state_label}`;
  }
  // MAST-004（修订）：渲染了环星的层级，文字行只留「已学 x / 共 y · 状态」，
  // 掌握度/覆盖率数字只出现一次（环心写覆盖率、星旁写掌握度），不得与文字行重复。
  function mCount(m) {
    const o = m || {};
    return `已学 ${o.learned} / 共 ${o.cards_total} · ${o.state_label}`;
  }

  // UI-018 覆盖率环形图 + MAST-008 掌握度五星：数值只读后端，前端零自算（禁自算/禁 emoji/禁外链库）。
  const STAR = 'M12 2 L15.09 8.26 L22 9.27 L17 14.14 L18.18 21.02 L12 17.77 L5.82 21.02 L7 14.14 L2 9.27 L8.91 8.26 Z';
  let gaugeSeq = 0;
  function starsOf(m) {            // round(m/20, 1)：86% → 4.3 星
    if (!m || m.m === null || m.m === undefined) return null;
    return Math.round((m.m / 20) * 10) / 10;
  }
  function coverageOf(m) {
    return (m && m.coverage !== null && m.coverage !== undefined) ? m.coverage : 0;
  }
  function starsFilledWidth(s) {   // 前景层裁剪宽（120 = 5 星 × 24），供断言读 clip 参数
    return s === null ? 0 : (s / 5) * 120;
  }
  function coverageRing(m) {
    const c = coverageOf(m);
    const R = 26;
    const C = 2 * Math.PI * R;
    const frac = Math.min(Math.max(c / 100, 0), 1);
    const dash = `${(frac * C).toFixed(2)} ${C.toFixed(2)}`;
    return `<span class="ring" role="img" aria-label="覆盖率 ${c}%">
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <g transform="rotate(-90 32 32)">
          <circle class="ring-bg" cx="32" cy="32" r="${R}"></circle>
          <circle class="ring-fg" cx="32" cy="32" r="${R}" stroke-dasharray="${dash}"></circle>
        </g>
        <text class="ring-cap" x="32" y="29" text-anchor="middle">覆盖率</text>
        <text class="ring-num" x="32" y="45" text-anchor="middle">${c}%</text>
      </svg>
    </span>`;
  }
  function masteryStars(m) {
    const s = starsOf(m);
    if (s === null) return '<span class="stars none" role="img" aria-label="掌握度 —">—</span>';
    const uid = 'starc' + (++gaugeSeq);
    const filled = starsFilledWidth(s).toFixed(2);
    const five = [0, 1, 2, 3, 4].map((i) => `<path d="${STAR}" transform="translate(${i * 24} 0)"/>`).join('');
    return `<span class="stars" role="img" aria-label="掌握度 ${m.m}% · ${s} 星">
      <svg class="stars-row" viewBox="0 0 120 24" aria-hidden="true">
        <defs><clipPath id="${uid}"><rect x="0" y="0" width="${filled}" height="24"/></clipPath></defs>
        <g class="stars-bg">${five}</g>
        <g class="stars-fg" clip-path="url(#${uid})">${five}</g>
      </svg>
      <span class="stars-line">掌握度 ${m.m}% · ${s}<svg class="star-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="${STAR}"/></svg></span>
    </span>`;
  }
  function masteryGauges(m) {
    return `<span class="gauges">${coverageRing(m)}${masteryStars(m)}</span>`;
  }
  function masteryNote() {
    return '<p class="sub">掌握度 = 已学卡掌握度平均（卡级 = 50% 状态分 + 50% 作答正确率）；覆盖率 = 已学卡 ÷ 全部卡</p>';
  }

  // —— 共用状态块（error / empty / loading）——
  function loading() {
    return `<div class="loading"><div class="mlabel">加载中…</div>
      <div class="skel w70"></div><div class="skel w45"></div></div>`;
  }

  function errorHTML(msg) {
    return `<section class="state rise">
      <div class="mlabel warn">出错 · Error</div>
      <h2 class="h2">加载失败</h2>
      <p class="sub">${esc(msg)}</p>
      <div class="hairline"></div>
      <p class="sub">数据没取到。可返回首页重试；若反复失败，检查本机服务是否在跑。</p>
      <p class="retry"><a class="btn" href="#/">返回首页</a></p>
    </section>`;
  }

  // howto 是内部可控文案（可含 <code>），故不转义；其余字段一律转义。
  function emptyHTML(o) {
    const act = o.href === null ? ''
      : `<p class="retry"><a class="btn" href="${esc(o.href || '#/')}">${esc(o.hrefText || '返回首页')}</a></p>`;
    return `<section class="state rise">
      <div class="mlabel">${esc(o.label || '空 · Empty')}</div>
      <h2 class="h2">${esc(o.title)}</h2>
      <p class="sub">${esc(o.desc)}</p>
      ${o.howto ? `<div class="hairline"></div><p class="sub">${o.howto}</p>` : ''}
      ${act}
    </section>`;
  }

  function crumb(parts) {
    const items = ['<a href="#/">首页</a>'].concat(parts.map((p) => (
      p.href ? `<a href="${p.href}">${esc(p.label)}</a>` : `<b>${esc(p.label)}</b>`)));
    return `<nav class="crumb">${items.join('<span class="sep">›</span>')}</nav>`;
  }

  function errorBox(msg) { html(errorHTML(msg)); }

  // —— 页头连胜（段⑤C：常显，0 天置灰，绝不隐藏；只读、不催促）——
  async function refreshStreak() {
    const el = document.getElementById('streak');
    if (!el) return;
    const n = el.querySelector('.n');
    try {
      const r = await api.get('/api/streak');
      const data = r.data || {};
      const d = data.days || 0;
      if (n) n.textContent = String(d);
      el.classList.toggle('disabled', d === 0);
      const f = data.freezes || {};
      const chip = document.getElementById('freezeChip');
      const count = document.getElementById('freezeCount');
      const note = document.getElementById('freezeNote');
      if (count) count.textContent = String(f.available || 0);
      if (chip) { chip.classList.toggle('disabled', !f.available); chip.onclick = () => {
        const recent = (f.recent || []).map(x => `${esc(x.day)} · 保住 ${x.streak_kept} 天`).join('\n') || '暂无记录';
        window.alert(`初始 3 次；连续达标每 5 天 +1 次。\n漏卡自动消耗；余额不足则连胜清零。\n最近记录：\n${recent}\n当前余额：${f.available || 0}`);
      }; }
      if (note) { const txt = f.available ? '' : '冰冻已用完，漏卡将清空连胜'; note.textContent = txt; note.hidden = !txt; }
      if (f.recent && f.recent.length) { const day=f.recent[0].day, key='review_freeze_seen_'+day;
        if (!localStorage.getItem(key)) { localStorage.setItem(key,'1'); const a=document.getElementById('freezeAnim'); if(a){ a.hidden=false; a.onclick=()=>a.hidden=true; setTimeout(()=>a.hidden=true,1500); } }
      }
    } catch (_) {
      if (n) n.textContent = '—';  // 失败也常显，不断 boot
      el.classList.add('disabled');
    }
  }

  // —— 今日任务子项（TASK-001/002）：按完成态渲染行动控件 ——
  // 未完成 → 按钮「去完成」；已完成 → 绿勾（.tick.on，非 emoji）**且同时**「再来一组」；
  // 目标值一律来自后端（t.target / t.reason），前端不硬编码任何阈值（GOAL-001 / TASK-002）。
  function taskRow(label, t, href, extraHref, unit) {
    const complete = !!(t && t.complete);
    const target = t ? t.target : 0;
    const done = t ? Math.min(t.done, target) : 0;
    // target=0（退化态）：按钮常显 + 置灰 + 写明原因（UI-003）
    const act = target === 0
      ? `<button class="btn act" disabled>去完成<span class="why">${esc((t && t.reason) || '今日无卡可复习')}</span></button>`
      : complete
        ? `<a class="btn act solid" href="${esc(extraHref)}">再来一组</a>`
        : `<a class="btn act" href="${esc(href)}">去完成</a>`;
    return `<div class="row task${complete ? ' on' : ''}">
      <span class="l"><b>${esc(label)} <span class="tnum">${target}</span> ${unit}</b>
        <span>已完成 <span class="tnum">${done}</span> / <span class="tnum">${target}</span> ${unit}</span></span>
      <span class="tick${complete ? ' on' : ''}" aria-hidden="true"></span>
      ${act}
    </div>`;
  }

  // —— 首页（HOME-001 格言 + TASK-001/002 任务 + MAST-002 学科进度；DATA-005 汇总口径） ——
  async function home() {
    html(loading());
    const [subsRes, quoteRes, taskRes, reportRes, scopeRes, uploadRes] = await Promise.all([
      api.get('/api/subjects'),
      api.get('/api/quote').catch(() => ({ data: { text: '今日复习' } })),
      api.get('/api/task').catch(() => ({ data: null })),
      api.get('/api/report').catch(() => ({ data: null })),
      api.get('/api/scope').catch(() => ({ data: null })),
      api.get('/api/upload/quota').catch(() => ({ data: { can_upload: false, reason: '暂时无法读取上传额度，请稍后重试' } })),
    ]);
    const subs = subsRes.data.subjects || [];
    const quote = (quoteRes.data && quoteRes.data.text) || '今日复习';
    const task = taskRes.data;
    const rep = reportRes.data;
    // SCOPE-003：首页「图书」入口常显当前范围文案（只读后端 label，前端零计算）
    const scopeLabel = (scopeRes.data && scopeRes.data.label) || '图书：全部';
    const updatedScope = sessionStorage.getItem('scope-updated');
    if (updatedScope) { sessionStorage.removeItem('scope-updated'); setTimeout(() => { const n = document.createElement('p'); n.className = 'sub'; n.setAttribute('aria-live', 'polite'); n.textContent = '范围已更新：' + updatedScope; app.prepend(n); }, 0); }

    const upload = uploadRes.data || { can_upload: false, reason: '暂时无法读取上传额度，请稍后重试' };
    const uploadEntry = `<a class="row${upload.can_upload ? '' : ' disabled'}" href="#/upload"${upload.can_upload ? '' : ' aria-disabled="true"'}>
      <span class="l"><b>上傳自己的書</b><span>${esc(upload.can_upload
        ? '文字型 PDF → 知識卡片草稿，確認後才進複習'
        : (upload.reason || '上传暂不可用，请稍后重试'))}</span></span>
    </a>`;

    const invitesEntry = `<a class="row" href="#/invites"><span class="l"><b>邀請碼</b><span>邀請他人建立獨立帳號</span></span></a>`;
    if (!subs.length) {
      html(emptyHTML({
        label: '空 · Empty',
        title: '还没有任何卡片',
        desc: '上传文字型 PDF 生成草稿，确认后即可开始复习。',
        howto: '怎么产生内容：在知识库侧跑 <code>export_cards.py</code> 导出契约文件，'
          + '再跑本 app 的 <code>backend/scripts/ingest_kb.py</code> 入库；首章入库即解锁，卡就会出现在这里。',
        href: null,
      }) + `<div class="rowlist">${uploadEntry}${invitesEntry}</div>`);
      return;
    }

    const books = subs.reduce((n, s) => n + (s.books_total || 0), 0);
    const chapters = subs.reduce((n, s) => n + (s.chapters_total || 0), 0);
    const cards = subs.reduce((n, s) => n + (s.cards_total || 0), 0);
    // GOAL-001：首屏唯一复习数字口径 —— 主行动的数字 = 今日任务 review.target（后端下发）
    const goal = task ? task.review.target : 0;
    const goalReason = (task && task.review.reason) || '新卡池已空，今日无卡可复习';
    const minutes = Math.max(1, Math.round(goal * 0.4));

    const taskBlock = task ? `
      <div class="sectitle">今日任务</div>
      <div class="rowlist rise" style="--d:200">
        ${taskRow('今日复习', task.review, '#/review', '#/review?extra=1', '张')}
        ${taskRow('出题', task.quiz, '#/quiz', '#/quiz', '题')}
      </div>` : '';

    // 目标 0（退化态）：主行动常显 + 置灰 + 写明原因（UI-003），绝不隐藏
    const primary = goal > 0
      ? `<a class="primary rise" style="--d:120" href="#/review">
        <b>开始复习 ${goal} 张</b>
        <span>到期优先，新卡自由选 · 约 ${minutes} 分钟</span>
      </a>`
      : `<span class="primary rise" style="--d:120" aria-disabled="true">
        <b>开始复习 0 张</b>
        <span>${esc(goalReason)}</span>
      </span>`;

    // 本周概况一行摘要（RPT-001）：复用 /api/report 同一字段；正确率 null → —
    const accText = (a) => (a === null || a === undefined) ? '—' : a + '%';
    const weekLine = rep ? `<p class="sub rise" style="--d:95">本周：复习
      <span class="tnum">${rep.reviewed_cards || 0}</span> 张 ·
      作答 <span class="tnum">${rep.quiz_answered || 0}</span> 题 ·
      正确率 <span class="tnum">${accText(rep.accuracy)}</span></p>` : '';

    html(`
      <h1 class="display rise">${esc(quote)}</h1>
      <p class="sub rise" style="--d:70">${books} 本书 · ${chapters} 章 · ${cards} 张卡</p>
      ${weekLine}
      ${primary}
      ${taskBlock}
      <div class="sectitle">快捷入口</div>
      <div class="rowlist grid rise" style="--d:280">
        <a class="row" href="#/scope">
          <span class="l"><b>图书</b><span>${esc(scopeLabel)}</span></span>
        </a>
        ${uploadEntry}
        ${invitesEntry}
        <span class="row is-disabled" aria-disabled="true"><span class="l"><b>视频讲解</b><span id="videoCapability">正在检查视频能力</span></span></span>
        <a class="row" href="#/quiz">
          <span class="l"><b>出题自测</b><span>选择题 / 是非题 · 自动判分</span></span>
        </a>
        <a class="row" href="#/subjects">
          <span class="l"><b>知识卡片</b><span>按学科 / 章节自己选</span></span>
        </a>
        <a class="row" href="#/wrong">
          <span class="l"><b>错题本</b><span>按错次排列 · 重刷</span></span>
        </a>
        <a class="row" href="#/plan">
          <span class="l"><b>复习计划</b><span>到期与下次复习</span></span>
        </a>
        <a class="row" href="#/weak">
          <span class="l"><b>薄弱点</b><span>按章聚合错题</span></span>
        </a>
        <a class="row" href="#/report">
          <span class="l"><b>本周概况</b><span>复习 · 正确率</span></span>
        </a>
      </div>
      <div class="sectitle">学科进度</div>
      <div class="rowlist">
        ${subs.map((s, i) => `
          <a class="progline rise" style="--d:${340 + i * 50}" href="#/subject/${s.id}">
            <span class="nm">${esc(s.name)}</span>
            <span class="bar"><i style="--p:${(mWidth(s.mastery)) / 100}"></i></span>
            <span class="num">${mCount(s.mastery)}</span>
            ${masteryGauges(s.mastery)}
          </a>`).join('')}
      </div>`);
  }

  // —— 今日清单（段⑤D）：到期 / 新卡 两组，纵向 hairline，绝不空白 ——
  async function today() {
    html(loading());
    const d = (await api.get('/api/today')).data;
    const due = d.due || [];
    const fresh = d.new || [];
    const total = due.length + fresh.length;

    const group = (title, list, reason) => list.length
      ? `<div class="sectitle">${title}（${list.length}）</div>
         <div class="rowlist">${list.map((c, i) => `
           <a class="row rise" style="--d:${i * 40}" href="#/review">
             <span class="l"><b>${esc(c.front)}</b>
               <span>${esc(c.source_label)}</span></span>
             <span class="r">→</span>
           </a>`).join('')}</div>`
      : `<div class="sectitle">${title}（0）</div><p class="sub">${esc(reason)}</p>`;

    html(`${crumb([{ label: '今日' }])}
      <div class="viewhead"><span class="mlabel g">今日清单</span><span class="n tnum">${total}</span></div>
      ${total ? `<a class="primary" href="#/review"><b>开始复习 ${total} 张</b>
        <span>到期优先，新卡自由选</span></a>` : ''}
      ${group('到期复习', due, '当前没有到期卡（到期即自动出现）')}
      ${group('新卡', fresh, '今日无新卡：可能已全部学过，或解锁章内暂无卡')}`);
  }

  // —— 知识卡片入口（UI-016）：学科列表，学科级只给汇总 + 掌握度进度条（DATA-005 / MAST-002） ——
  async function subjectList() {
    html(loading());
    const subs = (await api.get('/api/subjects')).data.subjects || [];
    if (!subs.length) {
      html(emptyHTML({
        label: '空 · Empty', title: '还没有学科',
        desc: '上游知识库导出契约入库后，这里会出现第一个学科。',
        howto: '怎么产生内容：跑 <code>backend/scripts/ingest_kb.py</code> 把导出契约入库。',
        href: null,
      }));
      return;
    }
    html(`${crumb([{ label: '学科' }])}
      <h1 class="display">知识卡片</h1>
      <p class="sub">无配额、不轮转；点进去按掌握度逐章解锁。</p>
      ${masteryNote()}
      <div class="rowlist">
        ${subs.map((s, i) => `
          <a class="row prog rise" style="--d:${120 + i * 40}" href="#/subject/${s.id}">
            <span class="l"><b>${esc(s.name)}</b>
              <span class="bar"><i style="--p:${(mWidth(s.mastery)) / 100}"></i></span>
              <span class="num">${mText(s.mastery)}</span>
              <span>${s.books_total} 本书 · ${s.chapters_total} 章 · 共 <span class="tnum">${s.cards_total}</span> 张</span></span>
            <span class="r">→</span>
          </a>`).join('')}
      </div>`);
  }

  // 章行：已解锁可展开（懒加载概念）；未解锁常显 + 置灰 + 写明原因（UI-003）。
  // 已解锁章带掌握度进度条 + 百分比（MAST-002 章级）。
  function chapterEntry(c, i) {
    const d = 140 + i * 40;
    if (!c.unlocked) {
      return `<div class="row disabled" style="--d:${d}">
        <span class="l"><b>${esc(c.name)}</b>
          <span>未解锁 · ${esc(c.lock_reason || '待上一章达标后开')}</span></span>
        <span class="r">锁</span>
      </div>`;
    }
    return `<details class="chap rise" style="--d:${d}">
      <summary>
        <span class="l"><b>${esc(c.name)}</b>
          <span class="bar"><i style="--p:${(mWidth(c.mastery)) / 100}"></i></span>
          <span class="num">${mText(c.mastery)}</span>
          <span>共 <span class="tnum">${c.cards_total}</span> 张</span></span>
        <span class="r">展开<span class="caret">▾</span></span>
      </summary>
      <div class="chap-body" data-cid="${c.id}"><p class="sub">展开后加载概念…</p></div>
    </details>`;
  }

  // 书的按钮行（UI-015）：书名 + 书级进度 .bar + 百分比 + 分子分母（MAST-004）；点书 → #/book/<id> 才渲染章。
  function bookRow(b) {
    const m = b.mastery || {};
    const sub = `共 <span class="tnum">${b.cards_total}</span> 张卡 · 已解锁到第 ${b.unlocked_upto} 章 / 共 ${b.chapters_total} 章`;
    if (b.chapters_unlocked === 0) {
      return `<div class="row disabled"><span class="l"><b>${esc(b.title)}</b>
        <span class="bar"><i style="--p:${(mWidth(m)) / 100}"></i></span>
        <span class="num">${mCount(m)}</span>
        ${masteryGauges(m)}
        <span>${sub} · 尚未解锁任何章（首章入库即解锁）</span></span><span class="r">锁</span></div>`;
    }
    return `<a class="row" href="#/book/${b.id}">
      <span class="l"><b>${esc(b.title)}</b>
        <span class="bar"><i style="--p:${(mWidth(m)) / 100}"></i></span>
        <span class="num">${mCount(m)}</span>
        ${masteryGauges(m)}
        <span>${sub}</span></span>
      <span class="r">→</span></a>`;
  }

  // 已解锁章展开 → 懒加载概念（纵向展开，禁横滑 UI-001）
  function bindChapterToggles() {
    app.querySelectorAll('details.chap').forEach((d) => {
      d.addEventListener('toggle', async () => {
        if (!d.open) return;
        const body = d.querySelector('.chap-body');
        if (!body || body.dataset.loaded) return;
        body.dataset.loaded = '1';
        try {
          const r = await api.get(`/api/concepts?chapter_id=${body.dataset.cid}`);
          const cs = r.data.concepts || [];
          body.innerHTML = cs.length
            ? `<div class="rowlist">${cs.map((c) => `
                <a class="row" href="#/concept/${c.id}">
                  <span class="l"><b>${esc(c.name)}</b>
                    <span><span class="mlabel cm">${esc(c.status_label || '')}</span> · ${c.cards_total} 张卡</span></span>
                  <span class="r">→</span></a>`).join('')}</div>`
            : '<p class="sub">本章暂无概念。</p>';
        } catch (e) {
          body.innerHTML = `<p class="sub">展开失败：${esc(e.message)}</p>`;
        }
      });
    });
  }

  // 书页（钻取第 3 级）：面包屑 + 已解锁 x / y 章 + 书级掌握度 + 章行（UI-015）
  async function renderDrill(subject, book) {
    const data = (await api.get(`/api/chapters?book_id=${book.id}`)).data;
    currentNav = data.nav;
    const chs = data.chapters || [];
    const bm = book.mastery || {};
    html(`${crumb([{ label: subject.name, href: `#/subject/${subject.id}` }, { label: book.title }])}
      <h1 class="display">${esc(book.title)}</h1>
      <div class="mlabel">已解锁 <span class="tnum">${book.chapters_unlocked}</span>
        / <span class="tnum">${book.chapters_total}</span> 章</div>
      <p class="sub">共 <span class="tnum">${book.cards_total}</span> 张卡 · 点已解锁的章展开概念</p>
      <div class="meter rise">
        <span class="nm">本书掌握</span>
        <span class="bar"><i style="--p:${(mWidth(bm)) / 100}"></i></span>
        <span class="num">${mCount(bm)}</span>
        ${masteryGauges(bm)}
      </div>
      ${masteryNote()}
      ${chs.length ? `<div class="rowlist">${chs.map(chapterEntry).join('')}</div>`
        : '<p class="sub">该书暂无章。</p>'}`);
    bindChapterToggles();
  }

  // 学科页（UI-015）= **书列表**：`#/subject/<id>` 只渲染「书的按钮」；点书才进 `#/book/<id>` 看章。
  async function subject(id) {
    html(loading());
    const [subsRes, booksRes] = await Promise.all([
      api.get('/api/subjects'), api.get(`/api/books?subject_id=${id}`),
    ]);
    const s = (subsRes.data.subjects || []).find((x) => String(x.id) === String(id));
    currentNav = booksRes.data.nav;
    const books = booksRes.data.books || [];
    if (!s) return errorBox('找不到这个学科');
    if (!books.length) {
      html(`${crumb([{ label: s.name }])}${masteryNote()}${emptyHTML({
        label: '空 · Empty', title: '该学科下还没有书',
        desc: '学科存在，但尚未入库任何书。',
        howto: '怎么产生内容：在知识库侧导出该学科某本书的契约文件，再跑 '
          + '<code>backend/scripts/ingest_kb.py</code> 入库（首章入库即解锁）。',
        href: '#/subjects', hrefText: '返回知识卡片',
      })}`);
      return;
    }
    html(`${crumb([{ label: s.name }])}
      <h1 class="display">${esc(s.name)}</h1>
      <p class="sub">共 ${books.length} 本书 · 点书进入章节</p>
      ${masteryNote()}
      <div class="rowlist">${books.map(bookRow).join('')}</div>`);
  }

  // 书级深链：反查所属学科（不加接口，契约不动）
  async function findBook(bookId) {
    const subs = (await api.get('/api/subjects')).data.subjects || [];
    for (const s of subs) {
      const books = (await api.get(`/api/books?subject_id=${s.id}`)).data.books || [];
      const b = books.find((x) => String(x.id) === String(bookId));
      if (b) return { subject: s, book: b };
    }
    return null;
  }

  async function book(id) {
    html(loading());
    const found = await findBook(id);
    if (!found) return errorBox('找不到这本书');
    await renderDrill(found.subject, found.book);
  }

  // 章深链：未解锁常显 + 置灰 + 写明原因（UI-003）
  async function chapter(id) {
    html(loading());
    const d = (await api.get(`/api/concepts?chapter_id=${id}`)).data;
    currentNav = d.nav;
    if (d.locked) {
      const missing = (d.reason || '').indexOf('不存在') >= 0;
      html(`${crumb([{ label: '概念' }])}${emptyHTML({
        label: missing ? '出错 · Error' : '未解锁 · Locked',
        title: missing ? '找不到这一章' : '本章还没解锁',
        desc: d.reason || '未解锁',
        howto: '解锁规则：上一章掌握度 ≥80%（且已学 ≥5 张）且该章到期复习为 0，才会开下一章。',
        href: '#/subjects', hrefText: '返回学科',
      })}`);
      return;
    }
    const cs = d.concepts || [];
    html(`${crumb([{ label: '概念' }])}
      <h1 class="display">概念</h1>
      ${cs.length ? `<div class="rowlist">${cs.map((c, i) => `
        <a class="row rise" style="--d:${120 + i * 40}" href="#/concept/${c.id}">
          <span class="l"><b>${esc(c.name)}</b>
            <span><span class="mlabel cm">${esc(c.status_label || '')}</span> · ${c.cards_total} 张卡${c.source_pages ? ' · 页 ' + esc(c.source_pages) : ''}${c.confidence ? ' · ' + esc(c.confidence) : ''}</span></span>
          <span class="r">→</span>
        </a>`).join('')}</div>` : '<p class="sub">本章暂无概念。</p>'}`);
  }

  // 卡级状态标签（MAST-003）：四态中文由**后端**下发（`status_label`），前端零映射、不写死。
  function statusBadge(c) {
    const on = c.status === 'mastered';   // 仅用 status 决定强调色，不映射文案
    return `<span class="mlabel cm${on ? ' on' : ''}">${esc(c.status_label || '')}</span>`;
  }

  // 概念页（UI-019）：h1 = 概念名；卡面 = 子卡短名（有则显示）→ 题面 → 要点 → 页脚（四态 · 已学 n 次 · 来源）
  async function concept(id) {
    html(loading());
    const d = (await api.get(`/api/cards?concept_id=${id}`)).data;
    currentNav = d.nav;
    const cards = d.cards || [];
    const cname = d.concept_name || '';
    if (!cards.length) {
      html(`${crumb([{ label: '卡' }])}${emptyHTML({
        label: '空 · Empty', title: '该概念暂无卡', desc: '这个概念还没有生成卡片。',
        href: '#/subjects', hrefText: '返回学科',
      })}`);
      return;
    }
    html(`${crumb([{ label: '卡' }])}
      <h1 class="display">${esc(cname || '卡')}</h1>
      <p class="sub">共 <span class="tnum">${cards.length}</span> 张卡</p>
      ${cards.map((c, i) => `
        <article class="block rise" style="--d:${80 + i * 50}">
          ${c.subtitle ? `<div class="mlabel">${esc(c.subtitle)}</div>` : ''}
          <p class="q">${esc(c.front)}</p>
          <ul class="points">${(c.answer_points || [])
            .map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
          <div class="cardfoot">${statusBadge(c)}
            <span class="mlabel">已学 <span class="tnum">${c.learn_count}</span> 次 · ${esc(c.source)}</span></div>
          <button class="btn video-request" data-video-card="${c.id}" type="button">讲解视频</button>
          <div class="video-slot" data-video-slot="${c.id}"></div>
        </article>`).join('')}`);
    app.querySelectorAll('[data-video-card]').forEach((button) => button.addEventListener('click', async () => {
      const id=button.dataset.videoCard, slot=app.querySelector(`[data-video-slot="${id}"]`);
      const state=(await api.get(`/api/videos/state?card_id=${id}`)).data;
      if (!state.available) { button.disabled=true; button.setAttribute('aria-disabled','true'); slot.textContent=state.reason||'未检测到 VideoKit（设置 VIDEOKIT_HOME）'; return; }
      if (state.status==='ready' && state.url) { slot.innerHTML=`<video controls playsinline preload="metadata" src="${esc(state.url)}"></video>`; return; }
      if (state.status==='failed') { slot.textContent='生成失败：'+(state.error||'未知错误'); return; }
      await api.post('/api/videos/request',{card_id:Number(id)});
      slot.textContent='已加入生成队列，完成后可在此播放';
    }));
  }

  async function videoList(level = 'books', selectedBook = '', selectedChapter = '') {
    const response = await api.get('/api/videos');
    const books = new Map();
    for (const row of response.data.items || []) {
      if (!books.has(row.book_title)) books.set(row.book_title, new Map());
      const chapters = books.get(row.book_title);
      if (!chapters.has(row.chapter_name)) chapters.set(row.chapter_name, new Map());
      const concepts = chapters.get(row.chapter_name);
      if (!concepts.has(row.concept_name)) concepts.set(row.concept_name, []);
      concepts.get(row.concept_name).push(row);
    }
    let tree = '';
    if (level === 'books') {
      for (const [bookName, chapters] of books) tree += `<a class="row" href="#/videos?book=${encodeURIComponent(bookName)}">${esc(bookName)} · ${chapters.size} 章</a>`;
    } else if (level === 'chapters') {
      const chapters = books.get(selectedBook);
      if (chapters) for (const [chapterName, concepts] of chapters) tree += `<a class="row" href="#/videos?book=${encodeURIComponent(selectedBook)}&chapter=${encodeURIComponent(chapterName)}">${esc(chapterName)} · ${concepts.size} 个概念</a>`;
    } else {
      const concepts = books.get(selectedBook)?.get(selectedChapter);
      if (concepts) for (const [conceptName, videos] of concepts) {
        tree += `<section class="video-concept"><h3>${esc(conceptName)}</h3>`;
        for (const video of videos) tree += `<a class="row" href="#/videos/${video.video_id}">${esc(video.title || conceptName)} · ${video.status === 'queued' ? '已加入生成队列，完成后可在此播放' : '播放'}</a>`;
        tree += '</section>';
      }
    }
    html(`<h1 class="display">视频讲解</h1>${level !== 'books' ? '<a class="btn" href="#/videos">返回书目</a>' : ''}${tree || '<p class="sub">还没有讲解视频</p><p class="sub">在卡片详情中请求生成视频。</p>'}`);
  }
  async function videoDetail(id) {
    const response = await api.get(`/api/videos/${id}`);
    const video = response.data;
    const player = video.status === 'ready'
      ? `<video controls playsinline preload="metadata" src="${esc('/media/videos/' + video.file_name)}"></video>`
      : '<p>已加入生成队列，完成后可在此播放</p>';
    html(`<h1 class="display">${esc(video.title || '讲解视频')}</h1>${player}<div class="video-cards">${(video.cards || []).map((card) => `<article class="block"><b>${esc(card.title || card.front)}</b>${card.is_core ? '<span>触发卡</span>' : ''}</article>`).join('')}</div>`);
  }
  function route() {
    refreshStreak();  // 每次导航刷新页头连胜（不阻断渲染）
    const h = location.hash || '#/';
    if (h !== routeBefore) {
      const stack = readStack();
      if (!returning) stack.push(routeBefore);
      sessionStorage.setItem(routeKey, JSON.stringify(stack));
      routeBefore = h;
    }
    returning = false;
    currentNav = null;
    setupBack();
    const m = h.match(/^#\/([a-z]+)(?:\/(\d+))?/);
    const name = m ? m[1] : '';
    const id = m ? m[2] : null;
    try {
      if (name === '') return home();
      if (name === 'videos' && id) return videoDetail(id);
      if (name === 'videos') {
        const params = new URLSearchParams(h.split('?')[1] || '');
        return params.has('chapter')
          ? videoList('concepts', params.get('book'), params.get('chapter'))
          : params.has('book') ? videoList('chapters', params.get('book')) : videoList();
      }
      if (name === 'subjects') return subjectList();
      if (name === 'subject' && id) return subject(id);
      if (name === 'book' && id) return book(id);
      if (name === 'chapter' && id) return chapter(id);
      if (name === 'concept' && id) return concept(id);
      if (name === 'today') return today();
      if (name === 'review') return window.ReviewView.render();
      if (name === 'quiz') return window.QuizView.render();
      if (name === 'wrong') return window.WrongView.render();
      if (name === 'plan') return window.PlanView.render();
      if (name === 'weak') return window.WeakView.render();
      if (name === 'report') return window.ReportView.render();
      if (name === 'invites') return window.InvitesView.render();
      if (name === 'upload') return window.UploadView.render();
      if (name === 'drafts') return window.DraftsView.render();
      if (name === 'scope') return window.ScopeView.render();
      return home();
    } catch (e) {
      errorBox(e.message || String(e));
    }
  }

  api.get('/api/videos/capability').then(r=>{const e=document.getElementById('videoCapability'); if(e)e.textContent=r.data.available?'可选依赖已就绪':r.data.reason;}).catch(()=>{});
  window.addEventListener('hashchange', () => { try { route(); } catch (_) {} });
  window.App = { route, home, refreshStreak };
  // 共享给 review.js / quiz.js / wrong.js（同一设计语法，避免各写一份状态块）
  window.UI = { esc, loading, errorHTML, emptyHTML, crumb, mLab, mWidth };
  // UI-018 / MAST-008 换算单点暴露给 ui-audit 做边界断言（前端零自算，只读后端字段）
  window.MasteryGauge = { starsOf, coverageOf, starsFilledWidth };
  document.addEventListener('DOMContentLoaded', () => { try { route(); } catch (_) {} });
})();
