(() => {
  const $ = (s, el = document) => el.querySelector(s);

  const analyzeBtn = $('#pp-analyze');
  const modal = $('.pp-modal.analyzing');
  const modalBar = modal ? $('.pp-progress .bar', modal) : null;
  const modalState = $('#pp-state');
  const resultsRoot = $('#pp-results');
  const err = $('#pp-error');

  function showAnalyzingModal(open) {
    if (!modal) return;
    modal.hidden = !open;
    if (open) {
      document.body.dataset.analyzing = '1';
    } else {
      delete document.body.dataset.analyzing;
    }
  }
  window.showAnalyzingModal = showAnalyzingModal;

  async function startAnalyze() {
    if (!analyzeBtn) return;
    analyzeBtn.disabled = true;
    if (err) err.textContent = '';
    showAnalyzingModal(true);
    try {
      const session = window.PeakPilot?.session;
      const r = await fetch('/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session })
      });
      if (!r.ok) throw new Error('start failed');
      pollProgress();
    } catch (e) {
      showAnalyzingModal(false);
      analyzeBtn.disabled = false;
      if (err) err.textContent = e.message || 'Error starting analysis';
    }
  }

  if (analyzeBtn) {
    analyzeBtn.addEventListener('click', startAnalyze);
  }

  const stateMap = {
    analyzing: 'Measuring loudness…',
    mastering: 'Rendering masters…',
    finalizing: 'Computing checksums…',
  };

  async function pollProgress() {
    const session = window.PeakPilot.session;
    while (true) {
      await new Promise(r => setTimeout(r, 500));
      const r = await fetch(`/progress/${session}`);
      const j = await r.json();
      if (modalBar) modalBar.style.width = `${j.pct || 0}%`;
      if (modalState && stateMap[j.status]) modalState.textContent = stateMap[j.status];
      if (j.status === 'done') {
        showAnalyzingModal(false);
        analyzeBtn && (analyzeBtn.disabled = false);
        renderMasteringResults(session);
        return;
      }
      if (j.status === 'error') {
        showAnalyzingModal(false);
        analyzeBtn && (analyzeBtn.disabled = false);
        if (err) err.textContent = j.message || 'Error';
        return;
      }
    }
  }

  async function fetchJSON(url) {
    const r = await fetch(url);
    return r.json();
  }

  async function drawWave(canvas, url, color, alpha = 1) {
    const ctx = canvas.getContext('2d');
    const resp = await fetch(url);
    const buf = await resp.arrayBuffer();
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const audio = await ac.decodeAudioData(buf.slice(0));
    const data = audio.getChannelData(0);
    const step = Math.max(1, Math.floor(data.length / canvas.width));
    const amp = canvas.height / 2;
    ctx.fillStyle = color;
    ctx.globalAlpha = alpha;
    for (let x = 0; x < canvas.width; x++) {
      const slice = data.subarray(x * step, (x + 1) * step);
      let min = 1, max = -1;
      for (let s of slice) { if (s < min) min = s; if (s > max) max = s; }
      ctx.fillRect(x, (1 + min) * amp, 1, Math.max(1, (max - min) * amp));
    }
    ctx.globalAlpha = 1;
  }

  function renderMasteringResults(session, cards, opts = {}) {
    if (!resultsRoot) return;
    resultsRoot.innerHTML = '';
    const defs = cards || [
      { key: 'club', title: 'Club', wav: 'club_master.wav', info: 'club_info.json' },
      { key: 'stream', title: 'Streaming', wav: 'stream_master.wav', info: 'stream_info.json' },
      { key: 'unlimited', title: 'Unlimited', wav: 'premaster_unlimited.wav', info: 'premaster_unlimited_info.json' },
    ];

    const audioBus = new Set();
    const stopAll = () => audioBus.forEach(a => a.pause());

    defs.forEach(def => {
      if (def.key === 'custom' && opts.showCustom === false) return;
      const card = document.createElement('div');
      card.className = 'pp-card';
      const h3 = document.createElement('h3');
      h3.textContent = def.title;
      card.appendChild(h3);

      const btn = document.createElement('button');
      btn.className = 'pp-play';
      btn.setAttribute('aria-label', 'Play');
      card.appendChild(btn);
      const audio = new Audio(`/download/${session}/${def.wav}`);
      audioBus.add(audio);
      btn.addEventListener('click', () => {
        if (audio.paused) {
          stopAll();
          audio.play();
          btn.classList.add('playing');
        } else {
          audio.pause();
        }
      });
      audio.addEventListener('pause', () => btn.classList.remove('playing'));
      card.appendChild(audio);

      const canvas = document.createElement('canvas');
      canvas.width = 600; canvas.height = 80;
      card.appendChild(canvas);
      drawWave(canvas, `/download/${session}/input_preview.wav`, '#888', 0.65).then(() =>
        drawWave(canvas, `/download/${session}/${def.wav}`, '#000', 1));

      const table = document.createElement('table');
      table.className = 'pp-metrics';
      table.innerHTML = '<thead><tr><th></th><th>LUFS-I</th><th>TP</th><th>LRA</th><th>Thresh</th></tr></thead><tbody><tr><td>Input</td><td>—</td><td>—</td><td>—</td><td>—</td></tr><tr><td>Output</td><td>—</td><td>—</td><td>—</td><td>—</td></tr></tbody>';
      card.appendChild(table);
      fetchJSON(`/download/${session}/${def.info}`).then(info => {
        const rows = table.querySelectorAll('tbody tr');
        const inp = info.input || {};
        const out = info.output || {};
        rows[0].children[1].textContent = inp.I?.toFixed?.(2) ?? inp.peak_dbfs?.toFixed?.(2) ?? '—';
        rows[0].children[2].textContent = inp.TP?.toFixed?.(2) ?? '';
        rows[0].children[3].textContent = inp.LRA?.toFixed?.(2) ?? '';
        rows[0].children[4].textContent = inp.threshold?.toFixed?.(2) ?? '';
        rows[1].children[1].textContent = out.I?.toFixed?.(2) ?? out.peak_dbfs?.toFixed?.(2) ?? '—';
        rows[1].children[2].textContent = out.TP?.toFixed?.(2) ?? '';
        rows[1].children[3].textContent = out.LRA?.toFixed?.(2) ?? '';
        rows[1].children[4].textContent = out.threshold?.toFixed?.(2) ?? '';
      });

      const dls = document.createElement('div');
      dls.className = 'pp-dls';
      const dw = document.createElement('a');
      dw.textContent = 'WAV';
      dw.href = `/download/${session}/${def.wav}`;
      dw.download = def.wav;
      dls.appendChild(dw);
      const di = document.createElement('a');
      di.textContent = 'INFO';
      di.href = `/download/${session}/${def.info}`;
      di.download = def.info;
      dls.appendChild(di);
      card.appendChild(dls);

      resultsRoot.appendChild(card);
    });
  }

  window.renderMasteringResults = renderMasteringResults;
})();

