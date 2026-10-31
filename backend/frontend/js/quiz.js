/* 测验页（QUIZ-001…006）：客观题 —— 选择题选项按钮 / 是非题「对·错」两键 → 下一题即送出
   页面内不做逐题判分，结果页统一展示解析。 */
(function () {
  const app = document.getElementById('app');
  const UI = window.UI;
  const esc = UI.esc;

  let sid = null;
  let items = [];
  let idx = 0;
  let picked = null;    // 本题已选选项（送出前）
  let submitting = false;
  let back = '#/';      // 结束页的返回入口（错题重刷 → '#/wrong'）

  function render() {
    app.innerHTML = UI.loading();
    api.post('/api/quiz/session').then((r) => {
      run(r.data.session_id, r.data.items || [], '#/');
    }).catch((e) => { app.innerHTML = UI.errorHTML(e.message); });
  }

  // 用给定会话作答（错题重刷复用）；不重新开题。
  function run(sessionId, list, backHash) {
    sid = sessionId;
    items = list || [];
    back = backHash || '#/';
    idx = 0; picked = null; feedback = null; score = 0;
    paint();
  }

  function head() {
    const n = items.length;
    return `<div class="viewhead">
      <span class="mlabel g">出题自测</span>
      <span class="n tnum">第 ${Math.min(idx + 1, n)} / ${n} 题</span>
    </div>`;
  }

  function optionCls(o) {
    return `btn opt${o === picked ? ' sel' : ''}`;
  }

  function paint() {
    if (!items.length) return emptyQuiz();
    if (idx >= items.length) return finish();
    const it = items[idx];
    const last = idx + 1 >= items.length;
    const rows = it.options.map((o) =>
      `<button class="${optionCls(o)}" data-o="${esc(o)}"${submitting ? ' disabled' : ''}>${esc(o)}</button>`).join('');
    const action = `<button class="btn solid wide" id="q-next"${picked && !submitting ? '' : ' disabled'}>` +
      `${last ? '看结果' : '下一题'}${picked ? '' : '<span class="why">请先选择答案</span>'}</button>`;
    app.innerHTML = `${head()}
      <div class="mlabel" style="margin-top:18px">${esc(it.source_label)}</div>
      <p class="q">${esc(it.stem)}</p><div class="opts">${rows}</div><div class="qfoot">${action}</div>`;
    for (const b of app.querySelectorAll('.opt')) b.onclick = () => { picked = b.dataset.o; paint(); };
    document.getElementById('q-next').onclick = () => submitAnswer(it);
  }

  async function submitAnswer(it) {
    if (!picked || submitting) return;
    submitting = true;
    paint();
    try {
      const r = await api.post('/api/quiz/answer', { session_id: sid, item_id: it.id, my_answer: picked });
      idx += 1; picked = null; submitting = false;
      paint();
    } catch (e) {
      submitting = false;
      paint();
      showError(e);
    }
  }

  function showError(e) {
    app.insertAdjacentHTML('beforeend', `<p class="sub">作答失败：${esc(e.message)}</p>`);
  }

  function emptyQuiz() {
    app.innerHTML = `<div class="viewhead">
        <span class="mlabel g">出题自测</span><span class="n tnum">0 / 0</span>
      </div>
      <section class="state rise">
        <div class="mlabel">空 · Empty</div>
        <h2 class="h2">暂无可用题目</h2>
        <p class="sub">出题从<strong>已学卡池</strong>里取（已解锁章内、学过的卡）；池里还没有已学卡时无题可出。</p>
        <div class="hairline"></div>
        <p class="sub">先学几张卡再来：卡片学过后才会进入出题池，首章解锁即可出题。</p>
        <p class="retry"><a class="btn" href="#/subjects">去知识卡片</a></p>
      </section>`;
  }

  function finish() {
    app.innerHTML = UI.loading();
    api.get(`/api/quiz/session/${sid}/result`).then((r) => {
      const d = r.data;
      const cards = (d.items || []).map((it) => `<article class="quiz-explain"><p class="q">${esc(it.stem)}</p><div class="opts">${it.options.map((o) => `<div class="btn opt${o === it.my_answer ? ' mine' : ''}${o === it.correct_answer ? ' correct' : ''}${o === it.my_answer && o !== it.correct_answer ? ' wrong' : ''}">${esc(o)}${o === it.correct_answer ? '<span class="mk">✓ 正确答案</span>' : ''}${o === it.my_answer && o !== it.correct_answer ? '<span class="mk">✗ 你的答案</span>' : ''}</div>`).join('')}</div></article>`).join('');
      const backText = back === '#/wrong' ? '错题本' : '首页';
      app.innerHTML = `<div class="viewhead"><span class="mlabel g">测验完成</span><span class="n tnum">${d.correct} / ${d.answered}</span></div>
        <h2 class="h2 rise">答对 <span class="tnum">${d.correct}</span> / <span class="tnum">${d.answered}</span> · 得分 <span class="tnum">${d.score}</span></h2>
        <p class="sub rise">分母 = 已作答题数（未答不计入），每题等分。</p><div class="sectitle rise">逐题解析</div>${cards}
        <a class="primary rise" href="${esc(back)}"><b>返回${backText}</b><span>已作答 <span class="tnum">${d.answered}</span> 题 · 可随时再测一次</span></a>`;
    }).catch((e) => { app.innerHTML = UI.errorHTML(e.message); });
  }

  window.QuizView = { render, run };
})();
