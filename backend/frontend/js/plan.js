/* 复习计划页（PLAN-001）：列出**状态非 new** 的卡，按「已到期在前 → 下次复习时间升序」排列。
   每条显示 书 · 章 · 卡面 + 间隔（`已到期` / `N 天后` / `N 小时后`）——间隔文案由后端
   `when_label` 机械换算，**前端不另算一套、不写死**。
   已到期的卡给**直接作答**入口（复用复习卡作答路径 `#/review`，唯一调度 `review_sched.apply_result`）。
   空态有话说，绝不空白。 */
(function () {
  const app = document.getElementById('app');
  const UI = window.UI;
  const esc = UI.esc;

  function render() {
    app.innerHTML = UI.loading();
    api.get('/api/plan').then((r) => paint(r.data.items || []))
      .catch((e) => { app.innerHTML = UI.errorHTML(e.message); });
  }

  function row(x, i) {
    const src = esc(x.source_label);
    // 卡级状态标签（MAST-003）：后端下发，前端只读
    const inner = `<span class="l"><b>${esc(x.front)}</b>
      <span><span class="mlabel cm">${esc(x.status_label || '')}</span> · ${src}</span></span>
      <span class="r when${x.due ? ' due' : ''}">${esc(x.when_label)}${x.due ? ' →' : ''}</span>`;
    // 已到期：可点 → 直接作答；未到期：信息块（不可点、不置灰）
    return x.due
      ? `<a class="row rise" style="--d:${80 + i * 40}" href="#/review">${inner}</a>`
      : `<div class="row plain rise" style="--d:${80 + i * 40}">${inner}</div>`;
  }

  function paint(items) {
    if (!items.length) return empty();
    const due = items.filter((x) => x.due).length;
    app.innerHTML = `${UI.crumb([{ label: '复习计划' }])}
      <div class="viewhead"><span class="mlabel g">复习计划</span>
        <span class="n tnum">${items.length}</span></div>
      <p class="sub">按「已到期在前 → 下次复习时间升序」排列；间隔由下次复习时间换算。
        ${due ? `其中已到期 <span class="tnum">${due}</span> 张，可直接作答。` : '当前没有已到期的卡。'}</p>
      <div class="rowlist">${items.map(row).join('')}</div>`;
  }

  function empty() {
    app.innerHTML = `${UI.crumb([{ label: '复习计划' }])}
      <div class="viewhead"><span class="mlabel g">复习计划</span><span class="n tnum">0</span></div>
      <section class="state rise">
        <div class="mlabel">空 · Empty</div>
        <h2 class="h2">还没有排上复习的卡</h2>
        <p class="sub">学过一张卡后，它会按调度出现在这里，并显示下次复习的间隔。</p>
        <div class="hairline"></div>
        <p class="sub">怎么产生内容：去「开始复习」学几张卡，之后这里就会排出到期与下次复习时间。</p>
        <p class="retry"><a class="btn" href="#/review">去复习</a></p>
      </section>`;
  }

  window.PlanView = { render };
})();
