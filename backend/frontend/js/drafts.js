/* 草稿页：只读后端可用性，确认通路受阻时按钮常显并解释。 */
(function () {
  const app = document.getElementById('app');
  async function render() {
    app.innerHTML = UI.loading();
    try {
      const d = (await api.get('/api/drafts')).data;
      app.innerHTML = `${UI.crumb([{label: '知识卡片草稿'}])}
        <h1 class="display">知识卡片草稿</h1>
        <p class="sub">草稿不会进入复习，也不会改变掌握度和连胜。</p>
        ${d.drafts.length ? d.drafts.map(card => `<section class="draft-item ${card.confidence === 'low' ? 'draft-low' : ''}">
          <h2>${UI.esc(card.payload.title)}</h2><p>${UI.esc(card.payload.question)}</p>
          <p>${card.payload.answer_points.map(UI.esc).join('<br>')}</p>
          <p class="sub">${UI.esc(card.confidence)} · ${card.status === 'kept' ? '保留' : '删除'}</p>
          <button data-draft="${card.id}" data-status="kept">保留</button>
          <button data-draft="${card.id}" data-status="deleted">删除</button></section>`).join('') : '<div class="state"><h2>还没有待确认的卡片</h2></div>'}
        <p class="why" id="draftWhy">${UI.esc(d.reason)}</p>
        <button class="primary" id="draftConfirm" ${d.can_confirm ? '' : 'disabled'} aria-describedby="draftWhy">确认入库</button>
        <a class="row" href="#/upload"><span class="l"><b>上传自己的书</b><span>查看上传额度与处理说明。</span></span><span class="r">→</span></a>`;
      app.querySelectorAll('[data-draft]').forEach(button => button.onclick = async () => {
        try { await api.put(`/api/drafts/${button.dataset.draft}`, {status: button.dataset.status}); await render(); }
        catch (e) { document.getElementById('draftWhy').textContent = e.message; }
      });
      document.getElementById('draftConfirm').onclick = async () => {
        try { await api.post('/api/drafts/confirm', {}); await render(); }
        catch (e) { document.getElementById('draftWhy').textContent = e.message; }
      };
    } catch (e) { app.innerHTML = UI.errorHTML(e.message); }
  }
  window.DraftsView = {render};
})();
