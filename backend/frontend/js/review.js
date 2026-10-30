/* 复习页（REVIEW-002/003/005）：闪卡 —— 点击卡面 3D 翻转看答案；拖动右滑 = 记得 / 左滑 = 忘了。
   队列来自 /api/today（到期优先 + 未学新卡补齐，只取已解锁章）；空队列则给状态块 + 怎么产生内容。
   视觉沿用 DESIGN.md 语法：微标签出处 → 大问题 22/800 → 要点 hairline 列表 → 动作。
   手势只是更快的一条路：底部按钮仍在 —— **顺序必须与手势同向：左「忘了」/ 右「记得」**（UI-014；主行动 = 记得）。
   契约不动：提交仍走 POST /api/review/<card_id>，result ∈ {good, again}（后端允许 again/hard/good）。 */
(function () {
  const app = document.getElementById('app');
  const UI = window.UI;
  const esc = UI.esc;

  let queue = [];
  let idx = 0;
  let flipped = false;

  function render() {
    app.innerHTML = UI.loading();
    api.get('/api/today').then((r) => {
      // 段⑤A：今日队列 = 到期 + 新卡（先到期后新卡）
      queue = (r.data.due || []).concat(r.data.new || []);
      idx = 0;
      flipped = false;
      paint();
    }).catch((e) => { app.innerHTML = UI.errorHTML(e.message); });
  }

  function head(total) {
    return `<div class="viewhead">
      <span class="mlabel g">复习中</span>
      <span class="n tnum">${idx + 1} / ${total}</span>
    </div>`;
  }

  function pointsHTML(c) {
    const ps = c.answer_points || [];
    return ps.length ? ps.map((p) => `<li>${esc(p)}</li>`).join('')
      : '<li class="sub">（该卡暂无要点，可直接自评）</li>';
  }

  function paint() {
    if (!queue.length) return emptyQueue();
    if (idx >= queue.length) return done();
    const c = queue[idx];
    const total = queue.length;

    app.innerHTML = `${head(total)}
      <div class="kc-scene" ontouchstart="Flashcard.touchStart(event)" ontouchmove="Flashcard.touchMove(event)" ontouchend="Flashcard.touchEnd(event)" ontouchcancel="Flashcard.touchEnd(event)">
        <div class="kc-card kc-in${flipped ? ' is-flipped' : ''}" onmousedown="Flashcard.mouseDown(event)" onclick="Flashcard.flip()">
          <div class="kc-face kc-front">
            <div class="mlabel">${esc(c.source_status_label)}</div>
            <p class="q">${esc(c.front)}</p>
            <span class="sub">点击卡面看答案</span>
          </div>
          <div class="kc-face kc-back">
            <div class="mlabel">${esc(c.source_points_label)}</div>
            <ul class="points">${pointsHTML(c)}</ul>
          </div>
        </div>
      </div>
      <div class="kc-hint rise">拖动卡片：右滑 = 记得 · 左滑 = 忘了</div>
      <button class="btn video-review" type="button">讲解</button>
      <div class="actions rise" style="--d:80">
        <button class="btn" id="k-again">忘了</button>
        <button class="btn solid" id="k-good">记得</button>
      </div>
      <p class="sub kc-hint" style="--d:120">也可点上方按钮自评；手势只是更快的一条路。</p>`;

    Flashcard.attach(app.querySelector('.kc-card'), {
      onFlip: (f) => { flipped = f; },
      onDecide: (ok) => decide(c, ok),
      onError: (e) => showError(e),
    });
    document.getElementById('k-good').onclick = () => Flashcard.decide(true);
    document.getElementById('k-again').onclick = () => Flashcard.decide(false);
    const videoButton=app.querySelector('.video-review');
    videoButton.addEventListener('touchstart',(event)=>event.stopPropagation(),{passive:true});
    videoButton.addEventListener('click', async (event) => {
      event.stopPropagation();
      const state = (await api.get(`/api/videos/state?card_id=${c.card_id}`)).data;
      if (!state.available) {
        videoButton.disabled = true;
        videoButton.setAttribute('aria-disabled', 'true');
        videoButton.textContent = state.reason || '未检测到 VideoKit（设置 VIDEOKIT_HOME）';
        return;
      }
      if (state.status === 'failed') {
        videoButton.textContent = '生成失败：' + (state.error || '未知错误');
        return;
      }
      if (state.url) {
        const sheet = document.createElement('div');
        sheet.className = 'video-sheet';
        sheet.innerHTML = `<button type="button" class="btn">关闭</button><video controls playsinline preload="metadata" src="${esc(state.url)}"></video>`;
        document.body.appendChild(sheet);
        sheet.querySelector('button').onclick = () => {
          const player = sheet.querySelector('video');
          player.pause(); player.removeAttribute('src'); player.load(); sheet.remove();
        };
        return;
      }
      if (state.status === 'generating' && state.requested_at) {
        const started = Date.parse(state.requested_at);
        const tick = () => {
          const elapsed = parseInt((Date.now() - started) / 1000, 10);
          const seconds = elapsed < 0 ? 0 : elapsed;
          videoButton.textContent = `已加入生成队列，完成后可在此播放 · 已等待 ${seconds} 秒`;
        };
        tick();
        const timer = window.setInterval(tick, 1000);
        videoButton.dataset.waitTimer = timer;
        return;
      }
      await api.post('/api/videos/request', { card_id: c.card_id });
      videoButton.textContent = '已加入生成队列，完成后可在此播放';
    });
  }

  async function decide(c, remembered) {
    await api.post(`/api/review/${c.card_id}`, { result: remembered ? 'good' : 'again' });
    idx += 1;
    flipped = false;
    paint();   // 下一张带 .kc-in 入场动画
  }

  function showError(e) {
    app.insertAdjacentHTML('beforeend', `<p class="sub">提交失败：${esc(e.message)}</p>`);
  }

  function emptyQueue() {
    app.innerHTML = `<div class="viewhead">
        <span class="mlabel g">复习</span><span class="n tnum">0 / 0</span>
      </div>
      <section class="state rise">
        <div class="mlabel">空 · Empty</div>
        <h2 class="h2">今天没有要复习的卡</h2>
        <p class="sub">到期卡会自动出现在这里；未学新卡也可随时学，无配额、不催。</p>
        <div class="hairline"></div>
        <p class="sub">怎么产生内容：上游知识库导出契约 → 跑
          <code>backend/scripts/ingest_kb.py</code> 入库 → 首章解锁，卡就会进队列。</p>
        <p class="retry"><a class="btn" href="#/subjects">去知识卡片</a></p>
      </section>`;
  }

  function done() {
    app.innerHTML = `<div class="viewhead">
        <span class="mlabel g">复习完成</span><span class="n tnum">${queue.length}</span>
      </div>
      <h2 class="h2 rise">本轮复习完成</h2>
      <p class="sub">共 ${queue.length} 张。无配额，随时回来继续。</p>
      <a class="primary rise" style="--d:120" href="#/">
        <b>回到首页</b>
        <span>已复习 ${queue.length} 张 · 到期卡会按调度再出现</span>
      </a>`;
  }

  window.ReviewView = { render };
})();
