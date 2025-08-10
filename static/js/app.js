// Minimal utilities
const $ = (q, el=document)=> el.querySelector(q);
const $$ = (q, el=document)=> Array.from(el.querySelectorAll(q));
const clamp = (a,b,x)=> Math.max(a, Math.min(b, x));

// Icons
const PLAY_SVG = '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
const PAUSE_SVG = '<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';

// WaveSurfer manager
const WS = {}; // id -> wavesurfer (or audio fallback)
let currentId = null;

function audioFallback(container, url) {
  const audio = new Audio(url);
  audio.controls = false;
  container.innerHTML = '';
  container.appendChild(audio);
  return {
    load: ()=>{},
    on: ()=>{},
    setVolume: (v)=> { audio.volume = clamp(0,1,v); },
    isPlaying: ()=> !audio.paused,
    play: ()=> audio.play(),
    pause: ()=> audio.pause()
  };
}

function initWaveform(id, el, url, vol=1.0){
  let ws;
  if (window.WaveSurfer) {
    ws = WaveSurfer.create({ container: el, barWidth: 2, height: 84, cursorWidth: 1 });
    ws.load(url);
    ws.on('ready', ()=> ws.setVolume(vol));
    ws.on('play',  ()=> updateButtons(id, true));
    ws.on('pause', ()=> updateButtons(id, false));
  } else {
    ws = audioFallback(el, url);
    ws.setVolume(vol);
  }
  WS[id] = ws;
}

function playToggle(id){
  for (const k in WS){ if (k !== id && !WS[k].isPaused?.() && WS[k].pause) WS[k].pause(); }
  currentId = id;
  const w = WS[id];
  if (!w) return;
  if (w.isPlaying && w.isPlaying()) { w.pause(); } else { w.play(); }
}

function updateButtons(activeId, playing){
  $$('[data-wf]').forEach(btn => {
    const id = btn.getAttribute('data-wf');
    btn.setAttribute('aria-pressed', (id===activeId && playing) ? 'true' : 'false');
    btn.innerHTML = (id===activeId && playing) ? PAUSE_SVG : PLAY_SVG;
  });
}

// Orb animation (transparent canvas)
(function orb(){
  const c = document.getElementById('pp-orb');
  const fb = document.querySelector('.pp-orb-fallback');
  const ctx = c.getContext?.('2d');
  if (!ctx){ return; }
  fb.style.display = 'none'; // Hide fallback when canvas works
  let t = 0; const dots = Array.from({length:64}, (_,i)=>({a:Math.random()*Math.PI*2,r:60+Math.random()*48}));
  function frame(){
    const w = c.clientWidth|0, h = c.clientHeight|0; if (c.width!==w||c.height!==h){ c.width=w; c.height=h; }
    ctx.clearRect(0,0,w,h);
    ctx.save(); ctx.translate(w/2,h/2);
    // nucleus
    const pulse = 28 + Math.sin(t*0.05)*6;
    const grd = ctx.createRadialGradient(0,0,6, 0,0,pulse*2);
    grd.addColorStop(0,'#8be9fd'); grd.addColorStop(1,'rgba(139,233,253,0)');
    ctx.fillStyle=grd; ctx.beginPath(); ctx.arc(0,0,pulse*2,0,Math.PI*2); ctx.fill();
    // particles
    dots.forEach((d,i)=>{ const a = d.a + t*0.01*(1+i/64); const r=d.r + Math.sin(t*0.02+i)*2; ctx.fillStyle=`rgba(167,139,250,${0.2+0.6*Math.random()})`; ctx.beginPath(); ctx.arc(Math.cos(a)*r,Math.sin(a)*r,1.8,0,6.28); ctx.fill(); });
    ctx.restore(); t++; requestAnimationFrame(frame);
  }
  frame();
})();

// Upload & polling
const form = $('#upload-form');
const fileInput = $('#file-input');
const modal = $('#pp-modal');
const bar = $('#pp-bar');
const stageEl = $('#pp-stage');
const flavorEl = $('#pp-flavor');
const outputs = $('#outputs-section');

let session = null;
let timer = null;
let originalURL = null;
let refI = -14;

form.addEventListener('submit', async (e)=>{
  e.preventDefault();
  const file = fileInput.files?.[0];
  if (!file) return;
  // Show modal
  modal.hidden = false;
  bar.classList.add('indeterminate');
  stageEl.textContent = 'Starting…';
  flavorEl.textContent = '';

  // Create original waveform immediately
  originalURL = URL.createObjectURL(file);
  initWaveform('original', $('#wf-original'), originalURL, 1.0);
  $('[data-wf="original"]').innerHTML = PLAY_SVG;
  $('[data-wf="original"]').addEventListener('click', ()=> playToggle('original'));

  // POST /start
  const fd = new FormData();
  fd.append('audio', file);
  const res = await fetch('/start', { method:'POST', body: fd });
  const js = await res.json();
  if (!res.ok){
    stageEl.textContent = js.error || 'Upload failed';
    bar.classList.remove('indeterminate');
    return;
  }
  session = js.session;
  // Poll
  timer = setInterval(pollProgress, 1000);
});

async function pollProgress(){
  const r = await fetch(`/progress/${session}`, { cache:'no-store' });
  if (!r.ok) return;
  const p = await r.json();

  // determinate when percent arrives
  if (typeof p.percent === 'number'){
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

  // Timeline overlay for original
  if (p.timeline && p.timeline.sec?.length){ drawTimeline(p.timeline); }

  // Ref loudness for gain matching
  if (p.metrics?.advisor?.input_I != null){ refI = p.metrics.advisor.input_I; }

  // Create processed waveforms as they appear
  addOrUpdateOutput('club', 'Club Master — 48 kHz / 24-bit, −0.8 dBTP, −7.5…−6.5 LUFS-I', p);
  addOrUpdateOutput('streaming', 'Streaming Master — 44.1 kHz / 24-bit, −1.0 dBTP, −10…−9 LUFS-I', p);
  addOrUpdateOutput('premaster', 'Unlimited Premaster — 48 kHz / 24-bit, peaks ≈ −6.0 dBFS (no limiter)', p);

  if (p.done){ clearInterval(timer); }
}

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
  // Populate metrics (incremental)
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
  grid.querySelector('[data-k="sr_bits"]').textContent = (mOut.sr? `${mOut.sr} / ${mOut.bits||'—'}`:'—');
  grid.querySelector('[data-k="sha256"]').textContent = mOut.sha256||'—';

  // Waveform once file is ready
  if (fname && !WS[name]){
    const url = `/download/${session}/${fname}`;
    // Gain match to advisor input
    const trackI = mOut.input_i ?? refI;
    const gain = clamp(0.1, 2.5, Math.pow(10, (refI - trackI)/20));
    initWaveform(name, document.getElementById(id), url, gain);
    card.querySelector(`[data-wf="${name}"]`).innerHTML = PLAY_SVG;
  }
}

function drawTimeline(t){
  const c = document.getElementById('timeline-canvas');
  const ctx = c.getContext('2d');
  const w = c.clientWidth|0, h = c.clientHeight|0; if (c.width!==w||c.height!==h){ c.width=w; c.height=h; }
  ctx.clearRect(0,0,w,h);
  if (!t.sec.length) return;
  const minL = -40, maxL = -8; // map ST-LUFS range
  const n = t.sec.length; const barW = Math.max(1, Math.floor(w / n));
  for (let i=0;i<n;i++){
    const l = t.short_term[i];
    const v = clamp(0,1,(l - minL) / (maxL - minL));
    const hh = Math.max(2, Math.floor(v*h));
    const x = i*barW; const y = h - hh;
    ctx.fillStyle = '#2b3344';
    ctx.fillRect(x, 0, barW-1, h);
    ctx.fillStyle = '#8be9fd';
    ctx.fillRect(x, y, barW-1, hh);
    if (t.tp_flags[i]){ ctx.fillStyle = '#a78bfa'; ctx.fillRect(x, 0, barW-1, 3); }
  }
}
