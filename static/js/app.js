// DOM refs
const pick = document.getElementById('pick');
const fileInput = document.getElementById('file');
const drop = document.getElementById('drop');

const presetSel = document.getElementById('preset');
const bitsSel = document.getElementById('bits');
const ditherSel = document.getElementById('dither');
const trimChk = document.getElementById('trim');
const padInput = document.getElementById('pad_ms');
const smartChk = document.getElementById('smart_limiter');

const analyzeBtn = document.getElementById('analyze');
const modal = document.getElementById('modal');
function showAnalyzingModal(isOpen){
  if (!modal) return;
  if (isOpen) {
    modal.classList.remove('hidden');
  } else {
    modal.classList.add('hidden');
  }
}

window.PeakPilot = window.PeakPilot || {};
window.PeakPilot.PlayerBus = window.PeakPilot.PlayerBus || { cur:null, claim(p){ if(this.cur && this.cur!==p) this.cur.pause?.(); this.cur=p; }, release(p){ if(this.cur===p) this.cur=null; } };
const PlayerBus = window.PeakPilot.PlayerBus;

const preview = document.getElementById('preview');
const playBtn = document.getElementById('play');
const curEl = document.getElementById('cur');
const durEl = document.getElementById('dur');
const previewSource = document.getElementById('previewSource');
const abOrig = document.getElementById('abOriginal');

const result = document.getElementById('result');
const dlClub = document.getElementById('dlClub');
const dlStreaming = document.getElementById('dlStreaming');
const dlPremaster = document.getElementById('dlPremaster');
const dlCustom = document.getElementById('dlCustom');
const dlZip = document.getElementById('dlZip');
const dlSession = document.getElementById('dlSession');

const pvClub = document.getElementById('pvClub');
const pvStreaming = document.getElementById('pvStreaming');
const pvPremaster = document.getElementById('pvPremaster');
const pvCustom = document.getElementById('pvCustom');

const metricsPanel = document.getElementById('metrics');
if(metricsPanel){ metricsPanel.hidden = true; metricsPanel.setAttribute('aria-hidden','true'); }
const customMetrics = document.getElementById('customMetrics');
const abProcessed = document.getElementById('abProcessed');
if(abProcessed){ abProcessed.hidden = true; abProcessed.addEventListener('click', e=>{ e.preventDefault(); return false; }); }
const loudCanvas = document.getElementById('loudCanvas');
const loudCtx = loudCanvas.getContext('2d');

let polling = null;
let wave = null;
let lastMetrics = null;

let currentLabel = 'Original';
let currentGain = 1.0;   // for A/B gain-match
let selectedFile = null;
let selectedBlobUrl = null;

// --- utils ---
function t(sec){
  if(!isFinite(sec)) return "0:00";
  const m = Math.floor(sec/60), s = Math.floor(sec%60);
  return `${m}:${s.toString().padStart(2,'0')}`;
}
// progress display handled by setAnalyzeState / setAnalyzeProgress
function setIf(id, v){ const el = document.getElementById(id); if(!el) return; el.textContent = (v==null? '—' : (typeof v === 'number' ? v.toFixed(2) : v)); }

function makeWaveform(){
  if (wave) { wave.destroy(); wave = null; }
  const width = document.getElementById('waveWrap').clientWidth;
  loudCanvas.width = width;
  wave = WaveSurfer.create({
    container: '#waveform',
    height: 120,
    waveColor: 'rgba(31,241,233,0.35)',
    progressColor: 'rgba(108,248,255,0.9)',
    cursorColor: '#fff',
    barWidth: 2, barRadius: 1, barGap: 1,
    normalize: true, responsive: true,
  });
  wave.on('ready', ()=>{ durEl.textContent = t(wave.getDuration()); wave.setVolume(currentGain); drawTimelineOverlay(lastMetrics?.timeline || null); });
  wave.on('audioprocess', ()=>{ curEl.textContent = t(wave.getCurrentTime()); });
  wave.on('seek', ()=>{ curEl.textContent = t(wave.getCurrentTime()); });
  wave.on('finish', ()=>{ playBtn.setAttribute('aria-pressed','false'); playBtn.setAttribute('aria-label','Play preview'); playBtn.innerHTML='<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>'; PlayerBus.release(previewPlayer); });
}

function loadIntoWave(srcUrl, label, matchGain=null){
  currentLabel = label;
  if (matchGain != null) currentGain = matchGain;
  preview.classList.remove('hidden');
  previewSource.textContent = 'Preview: ' + label;
  makeWaveform();
  wave.load(srcUrl);
  playBtn.setAttribute('aria-pressed','false'); playBtn.setAttribute('aria-label','Play preview'); playBtn.innerHTML='<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
}

function gainForI(I, targetRef){
  if (I == null || !isFinite(I)) return 1.0;
  const deltaDb = targetRef - I;             // positive means boost, negative means cut
  const lin = Math.pow(10, deltaDb/20);
  return Math.max(0.1, Math.min(2.5, lin));  // clamp sane range
}

function updateMetrics(j){
  lastMetrics = j;
  if (j.timeline) drawTimelineOverlay(j.timeline);
  if (!metricsPanel || metricsPanel.hasAttribute('aria-hidden') || !j.metrics) return;

  metricsPanel.classList.remove('hidden');
  const ci = j.metrics?.club?.input || {}, co = j.metrics?.club?.output || {};
  setIf('club_in_I', ci.I); setIf('club_in_TP', ci.TP); setIf('club_in_LRA', ci.LRA); setIf('club_in_TH', ci.threshold);
  setIf('club_out_I', co.I); setIf('club_out_TP', co.TP); setIf('club_out_LRA', co.LRA); setIf('club_out_TH', co.threshold);
  const si = j.metrics?.streaming?.input || {}, so = j.metrics?.streaming?.output || {};
  setIf('str_in_I', si.I); setIf('str_in_TP', si.TP); setIf('str_in_LRA', si.LRA); setIf('str_in_TH', si.threshold);
  setIf('str_out_I', so.I); setIf('str_out_TP', so.TP); setIf('str_out_LRA', so.LRA); setIf('str_out_TH', so.threshold);
  const pi = j.metrics?.premaster?.input || {}, po = j.metrics?.premaster?.output || {};
  setIf('pre_in_P', pi.peak_dbfs); setIf('pre_out_P', po.peak_dbfs);
  if (j.metrics?.custom && customMetrics){
    const ci2 = j.metrics.custom.input || {}, co2 = j.metrics.custom.output || {};
    setIf('cus_in_I', ci2.I); setIf('cus_in_TP', ci2.TP); setIf('cus_in_LRA', ci2.LRA); setIf('cus_in_TH', ci2.threshold);
    setIf('cus_out_I', co2.I); setIf('cus_out_TP', co2.TP); setIf('cus_out_LRA', co2.LRA); setIf('cus_out_TH', co2.threshold);
    customMetrics.classList.remove('hidden');
  } else if (customMetrics) {
    customMetrics.classList.add('hidden');
  }
}

function drawTimelineOverlay(tl){
  const ctx = loudCtx;
  const canvas = loudCanvas;
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if (!tl || !tl.sec || tl.sec.length === 0) return;

  const W = canvas.width, H = canvas.height;
  const minL = Math.min(...tl.short_term, -30), maxL = Math.max(...tl.short_term, 0);
  const n = tl.sec.length;
  const step = Math.max(1, Math.floor(n / W)); // one px per sample approx

  for (let x=0, i=0; i<n; i+=step, x++){
    const lufs = tl.short_term[i];
    const y = H - ((lufs - minL) / (maxL - minL)) * H;
    ctx.fillStyle = 'rgba(31,241,233,0.35)';
    ctx.fillRect(x, y, 1, H - y);
    if (tl.tp_flags[i]) {
      ctx.fillStyle = 'rgba(255,80,80,0.9)';
      ctx.fillRect(x, 0, 1, 6);
    }
  }
}

async function startJob(file, blobUrl){
  // send with options
  const fd = new FormData();
  fd.append('audio', file);
  fd.append('preset', presetSel.value);
  fd.append('bits', bitsSel.value);
  fd.append('dither', ditherSel.value);
  fd.append('trim', trimChk.checked ? 'true' : 'false');
  fd.append('pad_ms', padInput.value || '100');
  fd.append('smart_limiter', smartChk.checked ? 'true' : 'false');
  fd.append('do_trim_pad', 'true');

  const r = await fetch('/start', { method:'POST', body: fd });
  if (!r.ok) { alert('Failed to start: ' + (await r.text())); return; }
  const { session, progress_url } = await r.json();
  window.PeakPilot = window.PeakPilot || {};
  window.PeakPilot.session = session;
  if (typeof attachOriginalPlayer === 'function') {
    attachOriginalPlayer();
  }
  poll(progress_url, blobUrl, session);
}

function setABGains(metrics){
  // Use advisor.input_I as reference; otherwise -14 LUFS
  const refI = metrics?.metrics?.advisor?.input_I ?? -14.0;

  const srcI = metrics?.metrics?.advisor?.input_I; // original
  const clubI = metrics?.metrics?.club?.output?.I;
  const strI  = metrics?.metrics?.streaming?.output?.I;
  const preI  = metrics?.metrics?.premaster?.output?.I; // may be undefined; ignore
  const cusI  = metrics?.metrics?.custom?.output?.I;

  return {
    original: gainForI(srcI, refI),
    club:     gainForI(clubI, refI),
    streaming:gainForI(strI, refI),
    premaster:gainForI(preI, refI),
    custom:   gainForI(cusI, refI)
  };
}

async function poll(url, originalBlobUrl, session){
  clearInterval(polling);
  polling = setInterval(async ()=>{
    try{
      const r = await fetch(url, { cache: 'no-store' });
      const j = await r.json();
      setAnalyzeProgress(j.percent);
      if (j.phase || j.message) setAnalyzeState(j.phase || j.message);
      updateMetrics(j);
      if (typeof updateMasterCardsProgress === 'function') {
        updateMasterCardsProgress(j);
      }

      if (j.done) {
        clearInterval(polling);
        showAnalyzingModal(false);
        if (window.renderUploadedAudioCanvas) {
          window.renderUploadedAudioCanvas(session);
        }
        const s = window.PeakPilot.session;
        if (typeof renderMasteringResultsInHero === 'function') {
          renderMasteringResultsInHero(s, [
            {
              id: "club",
              title: "Club (48k/24, target −7.2 LUFS, −0.8 dBTP)",
              wavKey: "club_master.wav",
              infoKey: "ClubMaster_24b_48k_INFO.txt",
              metrics: { labelRow:["LUFS-I","TP","LRA","Thresh"], input:["-17.19","-5.60","27.24","-60.00"], output:["-7.40","0.00","27.24","—"] }
            },
            {
              id: "stream",
              title: "Streaming (44.1k/24, target −9.5 LUFS, −1.0 dBTP)",
              wavKey: "stream_master.wav",
              infoKey: "StreamingMaster_24b_44k1_INFO.txt",
              metrics: { labelRow:["LUFS-I","TP","LRA","Thresh"], input:["-17.19","-5.60","27.24","-60.00"], output:["-9.52","0.00","27.24","—"] }
            },
            {
              id: "unlimited",
              title: "Unlimited Premaster (48k/24, peak −6 dBFS)",
              wavKey: "premaster_unlimited.wav",
              infoKey: "UnlimitedPremaster_24b_48k_INFO.txt",
              metrics: { labelRow:["Peak dBFS"], input:["-5.60"], output:["-6.00"] }
            }
          ], { showCustom: false });
          updateMasterCardsProgress(j);
        }
        if (window.drawPeakHighlightsOnOriginal){
          const pv = `/stream/${s}/` + encodeURIComponent("input_preview.wav");
          fetch(pv).then(r=>r.arrayBuffer()).then(ab=> window.PeakPilot.getAC().decodeAudioData(ab)).then(buf=> window.drawPeakHighlightsOnOriginal(loudCanvas, buf, -1.0)).catch(()=>{});
        }
        const preTech = document.getElementById('preTech');
        if(preTech){
          const adv = j.metrics?.advisor || {};
          if(adv.input_I!=null){
            preTech.textContent = `LUFS-I: ${adv.input_I.toFixed(2)}\nTP: ${(adv.input_TP??0).toFixed(2)}\nLRA: ${(adv.input_LRA??0).toFixed(2)}`;
          } else {
            preTech.textContent = 'No technical data';
          }
        }
      }
    }catch(e){ /* ignore transient errors */ }
  }, 1000);
}

// UI wiring
pick?.addEventListener('click', ()=> fileInput.click());
drop?.addEventListener('click', ()=> fileInput.click());
  fileInput?.addEventListener('change', ()=>{ const f=fileInput.files[0]; if(f){ selectedFile=f; selectedBlobUrl=URL.createObjectURL(f); loadIntoWave(selectedBlobUrl,'Original',1.0); analyzeBtn.disabled=false; }});
['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
  drop.addEventListener('drop', e=>{ e.preventDefault(); const f=e.dataTransfer.files[0]; if(f){ selectedFile=f; selectedBlobUrl=URL.createObjectURL(f); loadIntoWave(selectedBlobUrl,'Original',1.0); analyzeBtn.disabled=false; }});
  analyzeBtn?.addEventListener('click', ()=>{ if(!selectedFile) return; showAnalyzingModal(true); setAnalyzeProgress(0); setAnalyzeState('Starting…'); startJob(selectedFile, selectedBlobUrl); });

// Player
const previewPlayer = { pause(){ if(wave){ wave.pause(); } } };
playBtn?.addEventListener('click', ()=>{
  if(!wave) return;
  if (wave.isPlaying()){
    wave.pause();
    playBtn.setAttribute('aria-pressed','false');
    playBtn.setAttribute('aria-label','Play preview');
    playBtn.innerHTML='<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
    PlayerBus.release(previewPlayer);
  } else {
    PlayerBus.claim(previewPlayer);
    wave.play();
    playBtn.setAttribute('aria-pressed','true');
    playBtn.setAttribute('aria-label','Pause preview');
    playBtn.innerHTML='<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
  }
});
window.addEventListener('resize', ()=> drawTimelineOverlay(lastMetrics?.timeline || null));

// Orb animator singleton and modal helpers
(() => {
  window.PeakPilot = window.PeakPilot || {};

  function attachOrb() {
    const canvas = document.getElementById('orb');
    if (!canvas) return;
    if (window.PeakPilot.orbAnimator) {
      window.PeakPilot.orbAnimator.destroy();
      window.PeakPilot.orbAnimator = null;
    }
    const animator = new OrbAnimator(canvas);
    animator.start();
    window.PeakPilot.orbAnimator = animator;
  }

  function detachOrb() {
    if (window.PeakPilot.orbAnimator) {
      window.PeakPilot.orbAnimator.destroy();
      window.PeakPilot.orbAnimator = null;
    }
  }

  class OrbAnimator {
    constructor(canvas) {
      this.c = canvas;
      this.ctx = canvas.getContext('2d', { alpha: true });
      this.handleResize = this.resize.bind(this);
      this.running = false;
      this.raf = 0;
      this.t0 = performance.now();
      this.particles = [];
      this.baseR = 58;
      this.waveAmp = 14;
      this.count = 200;
      this.noiseSeed = Math.random() * 1000;

      this.resize();
      this.buildParticles();

      this.ro = new ResizeObserver(() => this.resize());
      this.ro.observe(this.c);
    }

    resize() {
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      const cssW = parseFloat(getComputedStyle(this.c).width);
      const cssH = parseFloat(getComputedStyle(this.c).height);
      this.c.width = Math.round(cssW * dpr);
      this.c.height = Math.round(cssH * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    buildParticles() {
      this.particles.length = 0;
      for (let i = 0; i < this.count; i++) {
        const a = (i / this.count) * Math.PI * 2;
        this.particles.push({ a, w: 0 });
      }
    }

    n1(x) { return Math.sin(x) * 0.5 + Math.sin(2.7 * x + 1.3) * 0.3 + Math.sin(5.1 * x + 2.2) * 0.2; }

    drawOrbGlow(cx, cy, r, t) {
      const g = this.ctx.createRadialGradient(cx, cy, r * 0.2, cx, cy, r * 1.2);
      const p = (Math.sin(t * 0.0015) + 1) * 0.5;
      const c1 = `rgba(${Math.round(90 + 30*p)}, ${Math.round(220)}, ${Math.round(255 - 20*p)}, 0.65)`;
      const c2 = `rgba(${Math.round(120)}, ${Math.round(255)}, ${Math.round(220)}, 0.08)`;
      g.addColorStop(0, c1);
      g.addColorStop(1, c2);

      this.ctx.beginPath();
      this.ctx.fillStyle = g;
      this.ctx.arc(cx, cy, r * 1.15, 0, Math.PI * 2);
      this.ctx.fill();
    }

    drawWaveRing(cx, cy, baseR, t) {
      const ctx = this.ctx;
      ctx.beginPath();
      for (let i = 0; i < this.particles.length; i++) {
        const p = this.particles[i];
        const wobble = this.waveAmp * this.n1(p.a * 1.5 + t * 0.002 + this.noiseSeed);
        const r = baseR + wobble;
        const x = cx + Math.cos(p.a) * r;
        const y = cy + Math.sin(p.a) * r;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.strokeStyle = 'rgba(160, 245, 255, 0.7)';
      ctx.lineWidth = 1.25;
      ctx.stroke();

      for (let i = 0; i < this.particles.length; i += 12) {
        const p = this.particles[i];
        const wobble = this.waveAmp * this.n1(p.a * 1.5 + t * 0.002 + this.noiseSeed);
        const r = baseR + wobble;
        const x = cx + Math.cos(p.a) * r;
        const y = cy + Math.sin(p.a) * r;
        ctx.beginPath();
        ctx.arc(x, y, 1.2, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(200, 255, 240, 0.9)';
        ctx.fill();
      }
    }

    frame = (tm) => {
      if (!this.running) return;
      const t = tm - this.t0;
      const w = this.c.clientWidth;
      const h = this.c.clientHeight;
      const cx = w / 2;
      const cy = h / 2;

      this.ctx.clearRect(0, 0, w, h);

      const liveR = this.baseR + Math.sin(t * 0.0023) * 4;
      this.drawOrbGlow(cx, cy, liveR, t);
      this.drawWaveRing(cx, cy, liveR, t);

      this.raf = requestAnimationFrame(this.frame);
    }

    start() {
      if (this.running) return;
      this.running = true;
      this.raf = requestAnimationFrame(this.frame);
    }

    destroy() {
      this.running = false;
      if (this.raf) cancelAnimationFrame(this.raf);
      if (this.ro) this.ro.disconnect();
      this.ctx.clearRect(0, 0, this.c.clientWidth, this.c.clientHeight);
    }
  }

  window.PeakPilot.attachOrb = attachOrb;
  window.PeakPilot.detachOrb = detachOrb;

  const _origShow = window.showAnalyzingModal;
  window.showAnalyzingModal = function(isOpen) {
    if (typeof _origShow === 'function') _origShow(isOpen);
    if (isOpen) {
      setTimeout(() => window.PeakPilot.attachOrb(), 0);
    } else {
      window.PeakPilot.detachOrb();
    }
  };

  window.setAnalyzeState = function(text) {
    const el = document.getElementById('pp-state');
    if (el) el.textContent = text;
  };

  window.setAnalyzeProgress = function(pct) {
    const bar = document.querySelector('.pp-progress .bar');
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  };
})();
