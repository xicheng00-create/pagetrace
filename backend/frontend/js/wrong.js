/* 错题本页（WRONG-001）：按**卡**聚合错题（依据 quiz_attempts 判错记录），**按错次降序**排列；
   每条可展开看「正确答案 / 我的答案」；「重刷这一题」对该卡发起单题测验，作答追加 quiz_attempts
   （复用 quiz.js 的作答 UI —— 不另写一套判分/作答逻辑）。
   空态有话说（「还没有错题」+ 指路），绝不空白。 */
(function () {
  const app = document.getElementById('app');
  const UI = window.UI;
  const esc = UI.esc;

  function render() {
    app.innerHTML = UI.loading();
    api.get('/api/wrong').then((r) => paint(r.data.items || []))
      .catch((e) => { app.innerHTML = UI.errorHTML(e.message); });
  }

  function paint(items) {
    if (!items.length) return emptyWrong();
    app.innerHTML = `${UI.crumb([{ label: '错题本' }])}
      <div class="viewhead"><span class="mlabel g">错题本</span>
        <span class="n tnum">${items.length}</span></div>
      <p class="sub">按每张卡的错次从多到少排列；点开看「正确答案 / 我的答案」，可一键重刷。</p>
      <div class="rowlist">
        ${items.map((w, i) => `
          <details class="chap rise" style="--d:${80 + i * 40}">
            <summary>
              <span class="l"><b>${esc(w.front)}</b>
                <span><span class="mlabel cm">${esc(w.status_label || '')}</span> · 错 <span class="tnum">${w.wrong_count}</span> 次 · 点开对照答案</span></span>
              <span class="r">展开<span class="caret">▾</span></span>
            </summary>
            <div class="chap-body">
              ${w.stem ? `<p class="mlabel">题目</p><p class="q">${esc(w.stem)}</p>` : ''}
              <ul class="points">
                <li><b class="klab">正确答案</b><span class="right">${esc(w.correct_answer || '')}</span></li>
                <li><b class="klab">我的答案</b><span class="mine">${esc(w.my_answer || '')}</span></li>
              </ul>
              <button class="btn solid wide retry" data-card="${w.card_id}">重刷这一题</button>
            </div>
          </details>`).join('')}
      </div>`;
    for (const b of app.querySelectorAll('.retry')) {
      b.onclick = () => retry(b.dataset.card);
    }
  }

  async function retry(cardId) {
    try {
      // 单题测验：作答走 /api/quiz/answer（QUIZ-006 追加 quiz_attempts），结束页返回错题本
      const r = await api.post('/api/wrong/retry', { card_id: Number(cardId) });
      window.QuizView.run(r.data.session_id, r.data.items || [], '#/wrong');
    } catch (e) {
      app.insertAdjacentHTML('beforeend', `<p class="sub">发起重刷失败：${esc(e.message)}</p>`);
    }
  }

  function emptyWrong() {
    app.innerHTML = `${UI.crumb([{ label: '错题本' }])}
      <div class="viewhead"><span class="mlabel g">错题本</span><span class="n tnum">0</span></div>
      <section class="state rise">
        <div class="mlabel">空 · Empty</div>
        <h2 class="h2">还没有错题</h2>
        <p class="sub">测验里答错的卡会自动聚到这里，按错次从多到少排列。</p>
        <div class="hairline"></div>
        <p class="sub">怎么产生内容：去做一次「出题自测」，答错的题就会被收进来；之后可在这里一键重刷。</p>
        <p class="retry"><a class="btn" href="#/quiz">去出题自测</a></p>
      </section>`;
  }

  window.WrongView = { render };
})();
