/* 本周概况页（RPT-001）：统计窗口 = 本周一 00:00（本地时区）起。
   复习卡数（card_reviews 去重卡数）/ 出题作答数 / 判对数 / 正确率 / 最弱一章。
   正确率**必须来自后端字段** `accuracy`（与 QUIZ-005 同一分子分母口径，单一入口），
   前端**不得自行计算**；0 作答 → 后端给 null → 这里显示 `—`（不得显示 0%）。 */
(function () {
  const app = document.getElementById('app');
  const UI = window.UI;
  const esc = UI.esc;

  function render() {
    app.innerHTML = UI.loading();
    api.get('/api/report').then((r) => paint(r.data))
      .catch((e) => { app.innerHTML = UI.errorHTML(e.message); });
  }

  // 正确率：只用后端字段；null/undefined → —（0 作答不得显示 0%）
  function accText(a) {
    return (a === null || a === undefined) ? '—' : a + '%';
  }

  function line(label, note, value, cls) {
    return `<div class="row plain">
      <span class="l"><b>${esc(label)}</b><span>${esc(note)}</span></span>
      <span class="r tnum${cls ? ' ' + cls : ''}">${value}</span></div>`;
  }

  function paint(d) {
    d = d || {};
    const acc = accText(d.accuracy);
    const weak = d.weakest_chapter;
    const weakBlock = weak
      ? `<div class="sectitle">最弱一章</div>
        <div class="rowlist">
          <a class="row" href="#/weak">
            <span class="l"><b>${esc(weak.chapter_label)}</b>
              <span>${esc(weak.book_label)} · 错 <span class="tnum">${weak.wrong_count}</span> 次 ·
                涉及 <span class="tnum">${weak.card_count}</span> 张卡</span></span>
            <span class="r">→</span></a>
        </div>`
      : `<div class="sectitle">最弱一章</div>
        <p class="sub">本周还没有答错记录，暂无最弱章。去做一次「出题自测」就会有了。</p>`;

    const emptyHint = (d.quiz_answered === 0 && d.reviewed_cards === 0)
      ? '<p class="sub rise" style="--d:60">本周还没有复习或作答记录；学几张、测几题后这里会有数据。</p>'
      : '';

    app.innerHTML = `${UI.crumb([{ label: '本周概况' }])}
      <h1 class="display rise">本周概况</h1>
      <p class="sub rise" style="--d:70">统计自本周一 00:00 起（本地时区）。</p>
      ${emptyHint}
      <div class="rowlist">
        ${line('复习卡数', '本周复习过的去重卡数', d.reviewed_cards || 0)}
        ${line('出题作答', '本周已作答题数', d.quiz_answered || 0)}
        ${line('判对数', '其中答对的题数', d.quiz_correct || 0)}
        ${line('正确率', '判对 ÷ 已作答', acc)}
      </div>
      ${weakBlock}`;
  }

  window.ReportView = { render };
})();
