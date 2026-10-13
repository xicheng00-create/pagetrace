/* 闪卡手势（REVIEW-005 / QUIZ-003）：点击卡面翻转 + 跟手拖拽 + 阈值甩出 + 换卡入场。
   行为照抄 AI学习小组app 的 knowledge deck（kcTouchStart/Move/End、kcMouseDown/Move/Up、
   reviewKnowledge「先播飞出动画再提交、失败回滚」），配色一律走本项目 DESIGN.md 令牌（暖纸/墨/草绿）。
   钩子以行内属性挂在卡上（touchstart/touchmove/touchend/touchcancel、mousedown、click）；
   每次渲染后调用 Flashcard.attach(cardEl, { onFlip, onDecide, onError }) 注册当前卡。 */
(function () {
  const THRESHOLD = 70;   // px：右滑 = 记得/记住了，左滑 = 忘了/没记住（方向不许反）
  const DEAD = 6;         // |dx| < 6 不动；|dy| > |dx| 放弃横拖，竖向滚动优先
  const FLY_MS = 340;     // 先播飞出动画（.out-r/.out-l 的 .32s 对齐）再提交

  let el = null;              // 当前卡元素
  let opts = {};              // { onFlip, onDecide, onError }
  let ptr = null;             // { x, y, dx, dragging }
  let busy = false;           // 换卡进行中，屏蔽重复手势
  let suppress = false;       // 拖动结束后 400ms 内抑制补发的 click（防误翻转）
  let onMove = null;          // document 级 mousemove（桌面拖拽）
  let onUp = null;            // document 级 mouseup

  const reduced = () => !!(window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const wait = (ms) => new Promise((r) => { setTimeout(r, ms); });

  function attach(cardEl, o) {
    el = cardEl; opts = o || {}; ptr = null; suppress = false;
  }

  function flip() {
    if (busy) return;
    if (suppress) { suppress = false; return; }   // 拖动补发的 click：吞掉，不翻转
    if (!el) return;
    el.classList.toggle('is-flipped');
    if (opts.onFlip) { try { opts.onFlip(el.classList.contains('is-flipped')); } catch (_) { /* 忽略 */ } }
  }

  // —— touch 拖拽（iOS 主路径）；竖向滚动优先必须保留 ——
  function touchStart(e) {
    if (busy) return;
    const t = e.touches[0];
    ptr = { x: t.clientX, y: t.clientY, dx: 0, dragging: false };
  }
  function touchMove(e) {
    if (!ptr || busy) return;
    const t = e.touches[0];
    const dx = t.clientX - ptr.x, dy = t.clientY - ptr.y;
    if (!ptr.dragging) {
      if (Math.abs(dx) < DEAD) return;                        // 未到阈值：等 tap / 竖向判定
      if (Math.abs(dy) > Math.abs(dx)) { ptr = null; return; }  // 竖向滚动优先 → 放弃横拖
      ptr.dragging = true;
      if (el) el.classList.add('dragging');                   // 拖拽期关 transition → 跟手
    }
    e.preventDefault();
    ptr.dx = dx;
    if (el) el.style.transform = `translateX(${dx}px) rotate(${dx * 0.045}deg)`;
  }
  function touchEnd() {
    const p = ptr; ptr = null;
    if (!p || !p.dragging) return;   // tap → 交给 click 翻转
    finishDrag(p);
  }

  // —— mouse 拖拽（桌面）；mousedown 起 document 级监听，up 解绑 ——
  function mouseDown(e) {
    if (busy || e.button !== 0) return;
    ptr = { x: e.clientX, y: e.clientY, dx: 0, dragging: false };
    e.preventDefault();
    onMove = (ev) => mouseMove(ev);
    onUp = () => mouseUp();
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }
  function mouseMove(e) {
    if (!ptr) return;
    const dx = e.clientX - ptr.x, dy = e.clientY - ptr.y;
    if (!ptr.dragging) {
      if (Math.abs(dx) < DEAD) return;
      if (Math.abs(dy) > Math.abs(dx)) { mouseUp(); return; }
      ptr.dragging = true;
      if (el) el.classList.add('dragging');
    }
    ptr.dx = dx;
    if (el) el.style.transform = `translateX(${dx}px) rotate(${dx * 0.045}deg)`;
  }
  function mouseUp() {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    onMove = null; onUp = null;
    const p = ptr; ptr = null;
    if (!p || !p.dragging) return;   // 纯点击 → click 翻转
    finishDrag(p);
  }

  function finishDrag(p) {
    if (el) { el.classList.remove('dragging'); el.style.transform = ''; }
    suppress = true;                                          // 400ms 内抑制补发的 click
    setTimeout(() => { suppress = false; }, 400);
    if (Math.abs(p.dx) > THRESHOLD) decide(p.dx > 0);         // 右滑=记住 / 左滑=没记住
    // 未超阈值：transform 已清空 → CSS transition 弹回原位
  }

  // —— 提交：先播飞出动画，340ms 后落库；失败回滚动画与状态 ——
  async function decide(remembered) {
    if (busy || !el) return;
    busy = true;
    const card = el;
    card.style.pointerEvents = 'none';
    card.classList.remove('out-r', 'out-l');
    card.classList.add(remembered ? 'out-r' : 'out-l');
    if (!reduced()) await wait(FLY_MS);   // reduced-motion：瞬时切换，只保留数据提交
    try {
      await opts.onDecide(remembered);
    } catch (err) {
      card.classList.remove('out-r', 'out-l');
      card.style.pointerEvents = '';
      card.style.transform = '';
      if (opts.onError) opts.onError(err);
    } finally {
      busy = false;
    }
  }

  window.Flashcard = {
    attach, flip, decide,
    touchStart, touchMove, touchEnd, mouseDown,
  };
})();
