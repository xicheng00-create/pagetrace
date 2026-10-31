/* 图书范围页（SCOPE-001~004）：多选「纳入复习 / 出题 / 今日任务计数」的书集。
   勾选框复用现有 .tick 视觉（accent 绿），禁系统 checkbox 原生样式。
   SCOPE-004（v0.11.0）：范围改动「先草稿、后确认」——勾选/全选/清空只改本地草稿、不发请求；
   只有点「确认」才 PUT /api/scope；草稿为空时确认被拦（「至少选择一本书」，role=alert，不跳转）。
   空范围不再是合法状态：后端同样拒空（防旁路）；历史 "[]" 读取时归一为全部并提示（repaired）。 */
(function () {
  const app = document.getElementById('app');
  const UI = window.UI;
  const esc = UI.esc;

  // 草稿态：null=全部（全选）；否则数组。只改内存，不落库。
  let draft = null;            // 本地草稿（selected book ids 数组，或 null=全部）
  let savedAll = true;         // 已保存态是否为「全部」（用于对比「尚未确认」）
  let savedIds = null;         // 已保存态选中 id（null=全部）
  let savedLabel = '图书：全部';  // 已保存态范围文案（只读后端 label，前端零计算）
  let booksAll = [];           // 当前全部书（含 title/subject/…，供渲染行用）

  function render() {
    app.innerHTML = UI.loading();
    api.get('/api/scope').then((r) => paint(r.data)).catch((e) => { app.innerHTML = UI.errorHTML(e.message); });
  }

  function mPct(m) { return (m && m.m !== null && m.m !== undefined) ? `${m.m}%` : '—'; }

  function paint(d) {
    const books = d.books || [];
    const all = !!d.all;
    const selected = d.selected_ids;          // null = 全部
    const repaired = !!d.repaired;

    booksAll = books.slice();

    // 初始草稿 = 已保存态（后端已把空态归一为全部，故 saved 只可能是「全部」或「非空 id 列表」）
    savedAll = all;
    savedIds = all ? null : (selected || []).slice();
    savedLabel = d.label || '图书：全部';
    draft = all ? null : (selected || []).slice();

    if (!books.length) {
      app.innerHTML = `${UI.crumb([{ label: '图书范围' }])}${UI.emptyHTML({
        label: '空 · Empty', title: '还没有书',
        desc: '书架上有书之后，这里会出现可勾选的图书。',
        howto: '上传一本 PDF，后台出完草稿确认后，书就在这里可选。',
        href: '#/', hrefText: '返回首页',
      })}`;
      return;
    }

    repaint(repaired);
  }

  // 重绘（保留草稿，不发请求）。repairedHint 只首次提示（后端归一脏态）。
  function repaint(repairedHint) {
    const books = booksAll;
    const all = draft === null;
    const on = (id) => all || (draft || []).indexOf(id) >= 0;
    const dirty = !(all ? savedAll : (savedAll === false && (savedIds || []).join(',') === (draft || []).join(',')));

    const rows = books.map((b, i) => {
      const onId = on(b.id);
      return `<div class="row scope-book rise${onId ? ' on' : ''}" data-id="${b.id}" role="button" tabindex="0" aria-pressed="${onId}" style="--d:${80 + i * 40}">
        <span class="l"><b>${esc(b.title)}</b>
          <span>${esc(b.subject)} · 已学 ${b.learned} / 共 ${b.cards_total} · 覆盖率 ${b.coverage}% · 掌握度 ${mPct(b.mastery)}</span></span>
        <span class="tick${onId ? ' on' : ''}" aria-hidden="true"></span>
      </div>`;
    }).join('');

    const toolbar = `<div class="actions scope-actions">
      <button class="btn" id="scope-all" type="button">全选</button>
      <button class="btn" id="scope-clear" type="button">清空</button>
    </div>`;
    const repairedLine = repairedHint
      ? `<p class="sub scope-repaired"><span class="mlabel warn">已修复</span> 检测到空范围，已恢复为全部图书</p>`
      : '';
    const dirtyLine = dirty
      ? `<p class="sub scope-dirty"><span class="mlabel">尚未确认</span> 修改未保存，点「确认」后生效</p>`
      : '';
    const errorLine = `<p class="sub scope-error" id="scope-error" role="alert" hidden></p>`;

    app.innerHTML = `${UI.crumb([{ label: '图书范围' }])}
      <h1 class="display">图书范围</h1>
      <div class="mlabel g">${esc(savedLabel)}</div>
      <p class="sub">勾选纳入复习 / 出题 / 今日任务的图书；范围外到期卡仍到期（不吃卡、不改期、不丢卡）。</p>
      ${toolbar}
      ${repairedLine}
      ${dirtyLine}
      ${errorLine}
      <div class="actions scope-actions"><button class="primary" id="scope-confirm" type="button"><b>确认</b><span>保存当前勾选为复习 / 出题 / 今日任务范围</span></button></div>
      <div class="rowlist">${rows}</div>`;

    // 全选 / 清空：只改草稿（SCOPE-004）
    document.getElementById('scope-all').addEventListener('click', () => {
      draft = null;
      setError('');
      repaint(false);
    });
    document.getElementById('scope-clear').addEventListener('click', () => {
      draft = [];
      setError('');
      repaint(false);
    });
    // 确认：草稿空 → 拦（不发请求、不跳转）；否则 PUT
    document.getElementById('scope-confirm').addEventListener('click', () => {
      if (draft === null) { confirm(); return; }
      if (draft.length === 0) {
        setError('至少选择一本书');
        return;
      }
      confirm();
    });
    app.querySelectorAll('.scope-book').forEach((el) => {
      const id = Number(el.dataset.id);
      const toggle = () => {
        const allIds = books.map((x) => x.id);
        const cur = draft === null ? allIds : draft.slice();
        const next = cur.indexOf(id) >= 0 ? cur.filter((x) => x !== id) : cur.concat([id]);
        draft = next;
        setError('');
        repaint(false);
      };
      el.addEventListener('click', toggle);
      el.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); }
      });
    });
  }

  // 提交草稿：草稿为 null → 全选（all:true）；否则写 book_ids
  function confirm() {
    const body = draft === null ? { all: true } : { book_ids: draft.slice() };
    api.put('/api/scope', body).then((r) => { sessionStorage.setItem('scope-updated', r.data.label || '范围已更新'); location.hash = '#/'; }).catch((e) => {
      setError(e.message || '保存失败');
    });
  }

  // 错误条（role=alert，常显在按钮下方；空串 = 隐藏）
  function setError(msg) {
    const el = document.getElementById('scope-error');
    if (!el) return;
    el.textContent = msg;
    el.hidden = !msg;
  }

  window.ScopeView = { render };
})();
