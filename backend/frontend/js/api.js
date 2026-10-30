/* 极简 API 客户端：统一 {code:0,data} / {code:E,msg} 契约。 */
(function () {

  async function req(method, path, body) {
    const opt = { method, headers: {}, credentials: 'same-origin' };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt); let data = null;
    try { data = await r.json(); } catch (_) { /* 非 JSON */ }
    if (r.status === 401 && !path.startsWith('/api/auth/')) { window.dispatchEvent(new CustomEvent('auth-required')); throw new Error('请先登录'); }
    if (!data) throw new Error('HTTP ' + r.status);
    if (data.code !== 0) throw new Error(data.msg || ('code ' + data.code)); return data;
  }
  window.api = { get: (p) => req('GET', p), post: (p, b) => req('POST', p, b), put: (p, b) => req('PUT', p, b), del: (p) => req('DELETE', p) };
})();

(function () {
  let mode = 'login', state = {};
  function panel(show) {
    const p = document.getElementById('authPanel');
    if (p) { p.hidden = !show; if (show) document.getElementById('authUsername').focus(); }
  }
  function update() {
    const register = mode === 'register', bootstrap = mode === 'bootstrap';
    document.getElementById('authTitle').textContent = register ? '註冊 / 建立小組' : bootstrap ? '建立第一個帳號' : '登入';
    document.getElementById('authGuide').textContent = register ? '填邀請碼＝加入對方小組；留空＝新建你自己的小組。密碼 ≥8 位。'
      : bootstrap ? '首次啟動：建立第一個帳號，密碼至少 8 位；之後可用邀請碼邀請他人。'
      : state.needs_claim ? '首次使用：用任意 ≥8 位新密碼登入以認領此帳號'
      : '已有帳號請登入；首次加入可用邀請碼註冊。';
    document.getElementById('authCodeField').hidden = !register;
    document.getElementById('authCode').required = false;
    document.getElementById('authPassword').minLength = (register || bootstrap || state.needs_claim) ? 8 : 1;
    document.getElementById('authPassword').autocomplete = (register || bootstrap || state.needs_claim) ? 'new-password' : 'current-password';
    document.getElementById('authSubmit').textContent = register ? '註冊 / 建立小組' : bootstrap ? '建立第一個帳號' : '登入';
    document.getElementById('authSwitch').textContent = register ? (state.needs_bootstrap ? '建立第一個帳號' : '返回登入') : '註冊 / 建立小組';
  }
  // 顶栏账号区：头像 + 退出登录。单独挂载，兼容 DOMContentLoaded 已过的情况。
  function mountAccountUI() {
  const logout = document.createElement('button'); logout.type = 'button'; logout.id = 'logoutBtn'; logout.className = 'logout-btn'; logout.textContent = '退出登录';
  logout.addEventListener('click', async () => { await api.post('/api/auth/logout', {}); panel(true); refreshState(); location.hash = '#/'; });
  const avatar = document.createElement('a');
  avatar.id = 'avatarBtn'; avatar.className = 'avatar'; avatar.href = '#/account';
  avatar.setAttribute('aria-label', '我的账号');
  avatar.textContent = document.documentElement.dataset.avatarLetter || '我';
  document.querySelector('.topbar-inner')?.append(avatar);
  fetch('/api/account', {credentials:'same-origin'})
    .then(r => r.ok ? r.json() : null)
    .then(j => {
      if (j && j.data) {
        const letter = (j.data.username || '我').slice(0, 1).toUpperCase();
          document.documentElement.dataset.avatarLetter = letter;
        document.querySelectorAll('#avatarBtn').forEach(el => { el.textContent = letter; });
      }
    })
    .catch(() => {});
  document.querySelector('.topbar-inner')?.append(logout);
  }

  async function refreshState() {
    try { state = (await api.get('/api/auth/state')).data; mode = state.needs_bootstrap ? 'bootstrap' : 'login'; update(); }
    catch (_) { document.getElementById('authGuide').textContent = '無法讀取首次使用狀態，請重試；已有帳號可登入，或用邀請碼註冊。'; }
  }
  window.addEventListener('auth-required', () => { panel(true); refreshState(); });
  document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('authForm'); if (!form) return;
    refreshState();
    document.getElementById('authSwitch').onclick = () => {
      mode = mode === 'register' ? (state.needs_bootstrap ? 'bootstrap' : 'login') : 'register';
      document.getElementById('authError').hidden = true; update();
    };
    form.addEventListener('submit', async e => {
      e.preventDefault(); const error = document.getElementById('authError'); error.hidden = true;
      const username = document.getElementById('authUsername').value.trim(), password = document.getElementById('authPassword').value;
      const button = document.getElementById('authSubmit'); button.disabled = true;
      try {
        if (mode === 'bootstrap') { await api.post('/api/auth/bootstrap', {username, password}); await api.post('/api/auth/login', {username, password}); }
        else if (mode === 'register') {
          const code = (document.getElementById('authCode').value || '').trim();
          await api.post('/api/auth/register', {code, username, password});
          await api.post('/api/auth/login', {username, password});
        }
        else await api.post('/api/auth/login', {username, password});
        panel(false); window.App.route();
      } catch (err) { error.textContent = err.message || '登入失敗，請檢查帳號和密碼'; error.hidden = false; }
      finally { button.disabled = false; }
    });
    fetch('/api/auth/me', {credentials:'same-origin'}).then(r => panel(r.status === 401)).catch(() => panel(true));
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountAccountUI);
  else mountAccountUI();
})();
