/* 薄弱点页（WEAK-001）：**按章聚合**（与错题本按卡不同）。
   每章显示「错次总数 · 涉及卡数」，**按错次降序**；点章可展开涉及的具体卡与错次。
   数据源 = quiz_attempts(is_correct=0) → 卡 → 章（后端聚合，前端零计算）。
   空态有话说，绝不空白。 */
(function () {
  const app = document.getElementById('app');
  const UI = window.UI;
  const esc = UI.esc;

  function render() {
    app.innerHTML = UI.loading();
    api.get('/api/weak').then((r) => paint(r.data.chapters || []))
      .catch((e) => { app.innerHTML = UI.errorHTML(e.message); });
  }

  function chapter(g, i) {
    const cards = g.cards.map((c) => `
      <div class="row plain">
        <span class="l"><b>${esc(c.front)}</b><span>错 <span class="tnum">${c.wrong_count}</span> 次</span></span>
      </div>`).join('');
    return `<details class="chap rise" style="--d:${80 + i * 40}">
      <summary>
        <span class="l"><b>${esc(g.chapter_label)}</b>
          <span>${esc(g.book_label)} · 错 <span class="tnum">${g.wrong_count}</span> 次 ·
            涉及 <span class="tnum">${g.card_count}</span> 张卡</span></span>
        <span class="r">展开<span class="caret">▾</span></span>
      </summary>
      <div class="chap-body"><div class="rowlist">${cards}</div></div>
    </details>`;
  }

  function paint(chapters) {
    if (!chapters.length) return empty();
    const totalWrong = chapters.reduce((n, g) => n + g.wrong_count, 0);
    app.innerHTML = `${UI.crumb([{ label: '薄弱点' }])}
      <div class="viewhead"><span class="mlabel g">薄弱点</span>
        <span class="n tnum">${chapters.length}</span></div>
      <p class="sub">按章聚合错题，从错次最多的章排起；共 <span class="tnum">${totalWrong}</span> 次错。
        点开看涉及的具体卡。</p>
      <div class="rowlist">${chapters.map(chapter).join('')}</div>`;
  }

  function empty() {
    app.innerHTML = `${UI.crumb([{ label: '薄弱点' }])}
      <div class="viewhead"><span class="mlabel g">薄弱点</span><span class="n tnum">0</span></div>
      <section class="state rise">
        <div class="mlabel">空 · Empty</div>
        <h2 class="h2">还没有薄弱章</h2>
        <p class="sub">测验里答错的卡会按所在章聚到这里，从错次最多的章排起。</p>
        <div class="hairline"></div>
        <p class="sub">怎么产生内容：去做一次「出题自测」，答错的题就会归入对应章。</p>
        <p class="retry"><a class="btn" href="#/quiz">去出题自测</a></p>
      </section>`;
  }

  window.WeakView = { render };
})();
