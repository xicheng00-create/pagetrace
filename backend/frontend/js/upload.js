/* UP-009/011：后端可用性、进度与告知；上传只发送 multipart PDF。 */
(function () {
  const app = document.getElementById('app');
  const notice = document.getElementById('uploadNotice');
  let timer;
  async function render() {
    clearTimeout(timer);
    app.innerHTML = UI.loading();
    app.appendChild(notice);
    try {
      const d = (await api.get('/api/upload/quota')).data;
      app.innerHTML = `${UI.crumb([{label: '上传自己的书'}])}
        <h1 class="display">上传自己的书</h1>
        <p class="sub">文字型 PDF → 知识卡片草稿 → 确认入库。扫描件暂不支持。</p>
        <p id="uploadQuota" class="sub tnum">${UI.esc(d.label)}</p>
        <div class="upload-fields"><label for="uploadFile">选择 PDF</label>
          <input id="uploadFile" type="file" accept="application/pdf,.pdf" ${d.can_upload ? '' : 'disabled'} aria-describedby="uploadWhy"></div>
        <p class="why" id="uploadWhy">${UI.esc(d.reason)}</p>
        <button class="primary" id="uploadSubmit" ${d.can_upload ? '' : 'disabled'}>上传并生成草稿</button>
        <div class="state" id="uploadProgress" role="status">选择 PDF 后上传；处理进度由后端提供。</div>
        <a class="row" href="#/drafts"><span class="l"><b>查看草稿</b><span>只有确认入库后，卡片才会进入复习。</span></span><span class="r">→</span></a>`;
      app.insertBefore(notice, document.getElementById('uploadQuota'));
      document.getElementById('uploadSubmit').onclick = async () => {
        const file = document.getElementById('uploadFile').files[0];
        const why = document.getElementById('uploadWhy');
        if (!file) { why.textContent = '请选择 PDF 文件。'; return; }
        const button = document.getElementById('uploadSubmit');
        button.disabled = true;
        why.textContent = '';
        try {
          const form = new FormData();
          form.append('file', file);
          const response = await fetch('/api/upload', {method: 'POST', body: form});
          const result = await response.json();
          if (result.code !== 0) throw new Error(result.msg || '上传失败，请重试。');
          if (result.data.reused) {
            document.getElementById('uploadProgress').textContent = '已复用卡片池；无需再次生成草稿。';
            button.disabled = false;
          } else await showJob(result.data.id, true);
        } catch (e) { why.textContent = e.message; button.disabled = false; }
      };
    } catch (e) {
      app.innerHTML = UI.errorHTML(e.message);
      app.appendChild(notice);
    }
  }
  async function showJob(id, poll = false) {
    const d = (await api.get(`/api/upload/jobs/${id}`)).data;
    const node = document.getElementById('uploadProgress');
    if (!node || location.hash !== '#/upload') return;
    node.textContent = `${d.stage} · ${d.progress}%${d.error ? ' · ' + d.error : ''}`;
    if (poll && !['ready', 'failed'].includes(d.status)) {
      timer = setTimeout(() => showJob(id, true).catch(e => {
        document.getElementById('uploadWhy').textContent = e.message;
        document.getElementById('uploadSubmit').disabled = false;
      }), 400);
    } else if (poll) document.getElementById('uploadSubmit').disabled = false;
  }
  window.UploadView = {render, showJob};
})();
