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
  const outputs = document.getElementById('outputs-section');

  const PLAY_SVG = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
  const PAUSE_SVG = '<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
  const clamp = (a,b,x)=> Math.max(a, Math.min(b,x));
  const WS = {};
  let currentId = null;

  const ALLOWED = ['wav','aiff','aif','flac','mp3'];
  let fileQueue = []; // at most 1 file
  let session = null;
  let pollTimer = null;
  let refI = -14;

  const isAllowed = name => ALLOWED.includes((name.split('.').pop()||'').toLowerCase());

  // Orb animation
  (function orb(){
    const c = document.getElementById('pp-orb');
    const fb = document.querySelector('.pp-orb-fallback');
    const ctx = c.getContext?.('2d');
    if (!ctx){ return; }
    fb.style.display = 'none';
    let t=0; const dots = Array.from({length:64}, ()=>({a:Math.random()*Math.PI*2, r:60+Math.random()*48}));
    function frame(){
      const w=c.clientWidth|0, h=c.clientHeight|0; if (c.width!==w||c.height!==h){ c.width=w; c.height=h; }
      ctx.clearRect(0,0,w,h);
      ctx.save(); ctx.translate(w/2,h/2);
      const pulse = 28 + Math.sin(t*0.05)*6;
      const grd = ctx.createRadialGradient(0,0,6,0,0,pulse*2);
      grd.addColorStop(0,'#8be9fd'); grd.addColorStop(1,'rgba(139,233,253,0)');
      ctx.fillStyle=grd; ctx.beginPath(); ctx.arc(0,0,pulse*2,0,6.283); ctx.fill();
      dots.forEach((d,i)=>{ const a=d.a+t*0.01*(1+i/64); const r=d.r+Math.sin(t*0.02+i)*2; ctx.fillStyle=`rgba(167,139,250,${0.2+0.6*Math.random()})`; ctx.beginPath(); ctx.arc(Math.cos(a)*r,Math.sin(a)*r,1.8,0,6.283); ctx.fill(); });
      ctx.restore(); t++; requestAnimationFrame(frame);
    }
    frame();
  })();

  function initWaveform(id, el, url, vol=1.0){
    const ws = WaveSurfer.create({ container: el, barWidth: 2, height: 84, cursorWidth: 1 });
    WS[id] = ws;
    ws.load(url);
    ws.on('ready', ()=> ws.setVolume(vol));
    ws.on('play', ()=> updateButtons(id,true));
    ws.on('pause', ()=> updateButtons(id,false));
  }

  function playToggle(id){
    for (const k in WS){ if (k !== id && !WS[k].isPaused()) WS[k].pause(); }
    currentId = id;
    const ws = WS[id];
    if (!ws) return;
    ws.isPlaying() ? ws.pause() : ws.play();
  }

  function updateButtons(activeId, playing){
    document.querySelectorAll('[data-wf]').forEach(btn=>{
      const id = btn.getAttribute('data-wf');
      btn.setAttribute('aria-pressed', id===activeId && playing ? 'true':'false');
      btn.innerHTML = (id===activeId && playing) ? PAUSE_SVG : PLAY_SVG;
    });
  }

  function renderList() {
    fileList.innerHTML = '';
    if (fileQueue.length === 0) return;
    const f = fileQueue[0];
    const el = document.createElement('div');
    el.className = 'pp-filechip';
    el.innerHTML = `
      <div class="pp-fileinfo">
        <div class="pp-filemeta">${f.name} <span aria-hidden="true">•</span> ${(f.size/1024/1024).toFixed(2)} MB</div>
        <div class="pp-fileprog"><div class="bar"></div></div>
      </div>
      <button class="pp-remove" aria-label="Remove file">✕</button>`;
    el.querySelector('.pp-remove').addEventListener('click', () => { clearAll(); });
    fileList.appendChild(el);
  }

  function clearAll(){
    fileQueue = [];
    fileInput.value='';
    analyzeBtn.setAttribute('aria-disabled','true');
    fileList.innerHTML='';
    outputs.innerHTML='';
    errorBox.textContent='';
    if (pollTimer) clearInterval(pollTimer);
    session=null;
    if (WS.original){ try{WS.original.destroy();}catch{} delete WS.original; }
    document.getElementById('wf-original').innerHTML='';
    updateButtons(null,false);
  }

  function createOriginalWaveform(file){
    const url = URL.createObjectURL(file);
    initWaveform('original', document.getElementById('wf-original'), url, 1.0);
    const btn = document.querySelector('[data-wf="original"]');
    btn.innerHTML = PLAY_SVG;
    btn.addEventListener('click', ()=> playToggle('original'));
  }

  async function uploadFile(file){
    const chipProg = fileList.querySelector('.pp-fileprog');
    const chipBar = chipProg?.querySelector('.bar');
    if (chipProg){ chipBar.style.width='0%'; }
    analyzeBtn.setAttribute('aria-disabled','true');
    return new Promise((resolve, reject)=>{
      const data = new FormData();
      data.append('file', file, file.name);
      const xhr = new XMLHttpRequest();
      xhr.open('POST','/upload');
      xhr.upload.onprogress = e=>{
        if (e.lengthComputable && chipBar){
          const pct = (e.loaded/e.total)*100;
          chipBar.style.width = `${pct}%`;
        }
      };
      xhr.onerror = ()=>{ errorBox.textContent='Upload failed'; reject(new Error('upload failed')); };
      xhr.onload = ()=>{
        if (xhr.status>=200 && xhr.status<300){
          analyzeBtn.setAttribute('aria-disabled','false');
          resolve();
        } else {
          errorBox.textContent='Upload failed';
          reject(new Error('upload failed'));
        }
      };
      xhr.send(data);
    });
  }

  function setFiles(list) {
    const arr = Array.from(list || []);
    clearAll();
    if (arr.length) {
      const f = arr[0];
      if (!isAllowed(f.name)) {
        errorBox.textContent = 'Unsupported format. Use WAV/AIFF/FLAC/MP3.';
      } else {
        fileQueue = [f];
        errorBox.textContent = '';
        renderList();
        createOriginalWaveform(f);
        uploadFile(f).catch(()=>{});
      }
    }
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

  clearBtn.addEventListener('click', () => { clearAll(); });

  function openAnalyzingModal(stage='Starting…') {
    modal.hidden = false;
    bar.classList.add('indeterminate');
    bar.style.width = '0%';
    stageEl.textContent = stage;
    flavorEl.textContent = '';
  }

  function closeAnalyzingModal() {
    modal.hidden = true;
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
      const flavors = {
        analyze: 'Analyzing input…',
        reference: 'Dialing in reference curve…',
        club: 'Rendering Club…',
        streaming: 'Rendering Streaming…',
        premaster: 'Preparing Unlimited Premaster…',
        package: 'Packaging downloads…',
        done: 'Ready'
      };
      flavorEl.style.opacity = 0.6;
      flavorEl.textContent = flavors[p.phase] || '';

      if (p.timeline && p.timeline.sec?.length){ drawTimeline(p.timeline); }
      if (p.metrics?.advisor?.input_I != null){ refI = p.metrics.advisor.input_I; }

      addOrUpdateOutput('club', 'Club Master — 48 kHz / 24-bit, −0.8 dBTP, −7.5…−6.5 LUFS-I', p);
      addOrUpdateOutput('streaming', 'Streaming Master — 44.1 kHz / 24-bit, −1.0 dBTP, −10…−9 LUFS-I', p);
      addOrUpdateOutput('premaster', 'Unlimited Premaster — 48 kHz / 24-bit, peaks ≈ −6.0 dBFS (no limiter)', p);

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
    if (analyzeBtn.getAttribute('aria-disabled') === 'true') {
      errorBox.textContent = 'NO_AUDIO: Upload an audio file before analyzing.';
      dropZone.classList.add('pp-dragover');
      setTimeout(() => dropZone.classList.remove('pp-dragover'), 350);
      return;
    }

    try {
      openAnalyzingModal('Starting…');
      const res = await fetch('/start', { method: 'POST' });
      if (!res.ok) {
        closeAnalyzingModal();
        const j = await res.json().catch(()=>({}));
        errorBox.textContent = j.error || 'Server refused to start analysis.';
        return;
      }
      const js = await res.json();
      session = js.session;
      beginPollingProgress();
    } catch (e) {
      closeAnalyzingModal();
      errorBox.textContent = e.message || 'Network error. Try again.';
    }
  });

  function addOrUpdateOutput(name, title, p){
    const fname = p.downloads?.[name];
    const id = `wf-${name}`;
    let card = document.getElementById(`card-${name}`);
    if (!card){
      card = document.createElement('div');
      card.className = 'output-card';
      card.id = `card-${name}`;
      card.innerHTML = `
        <div class="output-title"><strong>${name[0].toUpperCase()+name.slice(1)}</strong><span>${title}</span></div>
        <div class="wf-row">
          <div id="${id}" class="wf"></div>
          <button class="wf-btn" data-wf="${name}" aria-pressed="false" title="Play/Pause"></button>
        </div>
        <div class="metrics" id="metrics-${name}">
          <div class="cell"><span class="label">Input LUFS-I</span><span class="val" data-k="input_i">—</span></div>
          <div class="cell"><span class="label">Input LRA</span><span class="val" data-k="input_lra">—</span></div>
          <div class="cell"><span class="label">Input TP</span><span class="val" data-k="input_tp">—</span></div>
          <div class="cell"><span class="label">Thresh</span><span class="val" data-k="input_thresh">—</span></div>
          <div class="cell"><span class="label">Out LUFS-I</span><span class="val" data-k="out_input_i">—</span></div>
          <div class="cell"><span class="label">Out TP</span><span class="val" data-k="out_input_tp">—</span></div>
          <div class="cell"><span class="label">SR / Bits</span><span class="val" data-k="sr_bits">—</span></div>
          <div class="cell"><span class="label">SHA-256</span><span class="val" data-k="sha256">—</span></div>
        </div>`;
      outputs.appendChild(card);
      card.querySelector(`[data-wf="${name}"]`).addEventListener('click', ()=> playToggle(name));
    }
    const mIn = p.metrics?.[name]?.input || {};
    const mOut = p.metrics?.[name]?.output || {};
    const grid = card.querySelector(`#metrics-${name}`);
    const set = (k,val)=> grid.querySelector(`[data-k="${k}"]`).textContent = (val!=null && !Number.isNaN(val)) ? String(Math.round(val*10)/10) : '—';
    set('input_i', mIn.input_i);
    set('input_lra', mIn.input_lra);
    set('input_tp', mIn.input_tp);
    set('input_thresh', mIn.input_thresh);
    set('out_input_i', mOut.input_i);
    set('out_input_tp', mOut.input_tp);
    grid.querySelector('[data-k="sr_bits"]').textContent = (mOut.sr ? `${mOut.sr} / ${mOut.bits||'—'}` : '—');
    grid.querySelector('[data-k="sha256"]').textContent = mOut.sha256 || '—';

    if (fname && !WS[name]){
      const url = `/download/${session}/${fname}`;
      const trackI = mOut.input_i ?? refI;
      const gain = clamp(0.1, 2.5, Math.pow(10, (refI - trackI)/20));
      initWaveform(name, document.getElementById(id), url, gain);
      card.querySelector(`[data-wf="${name}"]`).innerHTML = PLAY_SVG;
    }
  }

  function drawTimeline(t){
    const c = document.getElementById('timeline-canvas');
    const ctx = c.getContext('2d');
    const w = c.clientWidth|0, h=c.clientHeight|0; if (c.width!==w||c.height!==h){ c.width=w; c.height=h; }
    ctx.clearRect(0,0,w,h);
    if (!t.sec.length) return;
    const minL=-40, maxL=-8;
    const n=t.sec.length; const barW=Math.max(1, Math.floor(w/n));
    for (let i=0;i<n;i++){
      const l=t.short_term[i];
      const v=clamp(0,1,(l-minL)/(maxL-minL));
      const hh=Math.max(2, Math.floor(v*h));
      const x=i*barW; const y=h-hh;
      ctx.fillStyle='#2b3344';
      ctx.fillRect(x,0,barW-1,h);
      ctx.fillStyle='#8be9fd';
      ctx.fillRect(x,y,barW-1,hh);
      if (t.tp_flags[i]){ ctx.fillStyle='#a78bfa'; ctx.fillRect(x,0,barW-1,3); }
    }
  }
})();
