(() => {
  const analyzeBtn = document.querySelector('#analyzeBtn');
  const clearBtn = document.querySelector('#clearBtn');
  const fileInput = document.querySelector('#fileInput');
  const dropZone = document.querySelector('#dropZone');
  const fileList = document.querySelector('#fileList');
  const errorBox = document.querySelector('#inlineError');

  const modal = document.getElementById('pp-modal');
  const bar = document.getElementById('pp-bar');
  const stageEl = document.getElementById('pp-stage');
  const flavorEl = document.getElementById('pp-flavor');

  const ALLOWED = ['wav','aiff','aif','flac','mp3'];
  let fileQueue = []; // at most 1 file
  let session = null;
  let pollTimer = null;

  const isAllowed = name => ALLOWED.includes((name.split('.').pop()||'').toLowerCase());

  function renderList() {
    fileList.innerHTML = '';
    if (fileQueue.length === 0) return;
    const f = fileQueue[0];
    const el = document.createElement('div');
    el.className = 'pp-filechip';
    el.innerHTML = `\n      <div class="pp-filemeta">${f.name} <span aria-hidden="true">•</span> ${(f.size/1024/1024).toFixed(2)} MB</div>\n      <button class="pp-remove" aria-label="Remove file">✕</button>`;
    el.querySelector('.pp-remove').addEventListener('click', () => { fileQueue = []; syncState(); });
    fileList.appendChild(el);
  }

  function syncState() {
    const ok = fileQueue.length === 1 && isAllowed(fileQueue[0].name);
    analyzeBtn.disabled = !ok;
    analyzeBtn.setAttribute('aria-disabled', String(!ok));
    if (ok) errorBox.textContent = '';
    renderList();
  }

  function setFiles(list) {
    const arr = Array.from(list || []);
    fileQueue = [];
    if (arr.length) {
      const f = arr[0];
      if (!isAllowed(f.name)) {
        errorBox.textContent = 'Unsupported format. Use WAV/AIFF/FLAC/MP3.';
      } else {
        fileQueue = [f];
        errorBox.textContent = '';
      }
    }
    syncState();
  }

  // DnD
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('pp-dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('pp-dragover'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('pp-dragover');
    if (e.dataTransfer?.files?.length) setFiles(e.dataTransfer.files);
  });
  dropZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', e => setFiles(e.target.files));

  clearBtn.addEventListener('click', () => { fileQueue = []; fileInput.value=''; syncState(); });

  function openAnalyzingModal() {
    modal.hidden = false;
    bar.classList.add('indeterminate');
    bar.style.width = '0%';
    stageEl.textContent = 'Starting…';
    flavorEl.textContent = '';
  }

  async function pollProgress() {
    if (!session) return;
    try {
      const r = await fetch(`/progress/${session}`, { cache:'no-store' });
      if (!r.ok) return;
      const p = await r.json();
      if (typeof p.percent === 'number') {
        bar.classList.remove('indeterminate');
        bar.style.width = `${p.percent}%`;
      }
      stageEl.textContent = p.message || p.phase;
      flavorEl.textContent = '';
      if (p.done) {
        clearInterval(pollTimer);
      }
    } catch (e) {
      // silent
    }
  }

  function beginPollingProgress() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollProgress, 1000);
  }

  analyzeBtn.addEventListener('click', async () => {
    if (analyzeBtn.disabled) {
      errorBox.textContent = 'Add an audio file to analyze.';
      dropZone.classList.add('pp-dragover');
      setTimeout(() => dropZone.classList.remove('pp-dragover'), 350);
      return;
    }

    try {
      const data = new FormData();
      data.append('file', fileQueue[0], fileQueue[0].name);
      const up = await fetch('/upload', { method: 'POST', body: data });
      if (!up.ok) {
        const j = await up.json().catch(()=>({}));
        errorBox.textContent = j.error || 'Upload failed.';
        return;
      }

      const res = await fetch('/start', { method: 'POST' });
      if (!res.ok) {
        const j = await res.json().catch(()=>({}));
        errorBox.textContent = j.error || 'Server refused to start analysis.';
        return;
      }
      const js = await res.json();
      session = js.session;

      openAnalyzingModal();
      beginPollingProgress();
    } catch (e) {
      errorBox.textContent = 'Network error. Try again.';
    }
  });
})();
