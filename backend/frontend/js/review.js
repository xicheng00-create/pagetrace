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
    videoButton.addEventListener('click', (event) => {
      event.stopPropagation();
      openVideoSheet(c.card_id, videoButton);
    });
  }

  /* 点「讲解」必须立刻出东西：先开面板显示状态，再轮询到 ready 自动播放。
     旧实现只改按钮文字，点了像没反应（2026-10-30 owner 实测报障）。 */
  function openVideoSheet(cardId, button) {
    const sheet = document.createElement('div');
    sheet.className = 'video-sheet';
    sheet.innerHTML = `<div class="video-sheet-body">
        <p class="sub" data-video-status>正在检查视频…</p>
        <div class="video-holder" data-video-holder></div>
        <button type="button" class="btn">关闭</button>
      </div>`;
    document.body.appendChild(sheet);
    const status = sheet.querySelector('[data-video-status]');
    const holder = sheet.querySelector('[data-video-holder]');
    let timer = null;
    let closed = false;
    let busy = false;

    function close() {
      closed = true;
      if (timer) window.clearInterval(timer);
      const player = sheet.querySelector('video');
      if (player) { player.pause(); player.removeAttribute('src'); player.load(); }
      sheet.remove();
    }
    sheet.querySelector('button').onclick = close;
    sheet.addEventListener('click', (event) => { if (event.target === sheet) close(); });

    async function poll() {
      if (closed || busy) return;
      busy = true;
      try {
        const state = (await api.get(`/api/videos/state?card_id=${cardId}`)).data;
        if (closed) return;
        if (!state.available) {
          status.textContent = state.reason || '未检测到 VideoKit（设置 VIDEOKIT_HOME）';
          if (button) button.textContent = '讲解（不可用）';
          if (timer) { window.clearInterval(timer); timer = null; }
          return;
        }
        if (state.url) {
          status.textContent = '讲解视频';
          holder.innerHTML = `<video controls playsinline preload="metadata" src="${esc(state.url)}"></video>`;
          if (timer) { window.clearInterval(timer); timer = null; }
          if (button) button.textContent = '讲解';
          return;
        }
        if (state.status === 'failed') {
          status.textContent = '生成失败：' + (state.error || '未知错误');
          if (timer) { window.clearInterval(timer); timer = null; }
          return;
        }
        if (state.status === 'queued' || state.status === 'generating') {
          const started = state.requested_at ? Date.parse(state.requested_at) : 0;
          const raw = started ? parseInt((Date.now() - started) / 1000, 10) : 0;
          const seconds = raw > 0 ? raw : 0;
          status.textContent = `正在生成讲解视频…已等待 ${seconds} 秒（完成后自动播放）`;
          return;
        }
        status.textContent = '已加入生成队列，完成后可在此播放（约 1–3 分钟）';
        try {
          await api.post('/api/videos/request', { card_id: cardId });
        } catch (e) {
          if (!closed) status.textContent = '加入队列失败：' + (e.message || '未知错误');
        }
      } catch (e) {
        if (!closed) status.textContent = '读取视频状态失败：' + (e.message || '未知错误');
      } finally {
        busy = false;
      }
    }

    poll();
    timer = window.setInterval(poll, 3000);
  }


  function openVideoSheet(cardId, button) {
    const sheet = document.createElement('div');
    sheet.className = 'video-sheet';
    sheet.innerHTML = '<div class="video-sheet-body"><p class="sub" data-video-status>正在检查视频…</p><div data-video-holder></div><button type="button" class="btn">关闭</button></div>';
    document.body.appendChild(sheet);
    const status = sheet.querySelector('[data-video-status]');
    const holder = sheet.querySelector('[data-video-holder]');
    let timer = null;
    let closed = false;
    let busy = false;
    const close = () => {
      closed = true;
      if (timer) window.clearInterval(timer);
      const player = sheet.querySelector('video');
      if (player) { player.pause(); player.removeAttribute('src'); player.load(); }
      sheet.remove();
    };
    sheet.querySelector('button').onclick = close;
    sheet.addEventListener('click', (event) => { if (event.target === sheet) close(); });
    async function poll() {
      if (closed || busy) return;
      busy = true;
      try {
        let state = (await api.get(`/api/videos/state?card_id=${cardId}`)).data;
        if (closed) return;
        if (!state.available) { status.textContent = state.reason || '视频讲解暂不可用'; if (timer) window.clearInterval(timer); timer = null; return; }
        if (!state.status) {
          await api.post('/api/videos/request', { card_id: cardId });
          state = (await api.get(`/api/videos/state?card_id=${cardId}`)).data;
        }
        if (state.url) {
          status.textContent = '讲解视频已就绪';
          holder.innerHTML = `<video controls playsinline preload="metadata" src="${esc(state.url)}"></video>`;
          if (timer) window.clearInterval(timer); timer = null; return;
        }
        if (state.status === 'failed') { status.textContent = `生成失败：${state.error || '未知原因'}`; if (timer) window.clearInterval(timer); timer = null; return; }
        status.textContent = state.reason || '已加入生成队列，完成后自动播放…';
      } catch (error) { status.textContent = `读取讲解状态失败：${error.message || '请稍后重试'}`; }
      finally { busy = false; }
    }
    poll();
    timer = window.setInterval(poll, 3000);
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
