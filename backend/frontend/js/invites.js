/* 邀請碼：只顯示本次生成的明文，不將碼寫入本地儲存。 */
(function () {
  async function render() {
    const app = document.getElementById('app'); app.innerHTML = UI.loading();
    try {
      const me = (await api.get('/api/auth/me')).data;
      const isOwner = me.role === 'owner';
      const list = isOwner ? (await api.get('/api/invites')).data.invites : [];
      app.innerHTML = `${UI.crumb([{label:'邀請碼'}])}<h1 class="display">邀請碼</h1>
        <p class="sub">一次性使用，24 小時內有效。明文只在生成時顯示，請自行交給受邀者。</p>
        <button id="inviteGenerate" class="primary" ${isOwner ? '' : 'disabled'}>生成邀請碼</button>
        <p class="why">${isOwner ? '受邀者用邀請碼自行建立帳號，資料與你隔離。' : '只有 owner 可以生成邀請碼'}</p>
        <p id="inviteResult" role="status"></p><p id="inviteError" role="alert" hidden></p>
        <div class="sectitle">已生成清單</div><div id="inviteList" class="rowlist">${list.length ? list.map(item =>
          `<div class="row"><span class="l"><b>${UI.esc(item.status)}</b><span>到期：${UI.esc(item.expires_at)}${item.used_by ? ' · 使用者 ID：' + UI.esc(item.used_by) : ''}</span></span></div>`).join('') : '<p class="sub">尚無邀請碼</p>'}</div>`;
      document.getElementById('inviteGenerate').onclick = async () => {
        const button = document.getElementById('inviteGenerate'); button.disabled = true;
        const error = document.getElementById('inviteError'); error.hidden = true;
        try {
          const data = (await api.post('/api/invites', {})).data;
          document.getElementById('inviteResult').textContent = `邀請碼：${data.code} · 到期：${data.expires_at}`;
          const row = document.createElement('p'); row.className = 'sub'; row.textContent = '未用 · 到期：' + data.expires_at;
          document.getElementById('inviteList').prepend(row);
        } catch (e) { error.textContent = e.message; error.hidden = false; }
        finally { button.disabled = false; }
      };
    } catch (e) { app.innerHTML = UI.errorHTML(e.message); }
  }
  window.InvitesView = {render};
})();
