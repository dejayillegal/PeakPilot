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

const progressWrap = document.getElementById('progressWrap');
const bar = document.getElementById('bar');
const phase = document.getElementById('phase');
const percent = document.getElementById('percent');
const messages = document.getElementById('messages');

const preview = document.getElementById('preview');
const playBtn = document.getElementById('play');
const curEl = document.getElementById('cur');
const durEl = document.getElementById('dur');
const previewSource = document.getElementById('previewSource');
const abOrig = document.getElementById('abOriginal');
const abProc = document.getElementById('abProcessed');

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
const loudCanvas = document.getElementById('loudCanvas');
const loudCtx = loudCanvas.getContext('2d');

let polling = null;
let wave = null;
let lastMessage = "";
let lastMetrics = null;

let currentLabel = 'Original';
let currentGain = 1.0;   // for A/B gain-match

// --- utils ---
function t(sec){
  if(!isFinite(sec)) return "0:00";
  const m = Math.floor(sec/60), s = Math.floor(sec%60);
  return `${m}:${s.toString().padStart(2,'0')}`;
}
function appendMessage(msg){ if(!msg || msg === lastMessage) return; lastMessage = msg; const li = document.createElement('li'); li.textContent = msg; messages.appendChild(li); }
function setProgress(p, ph, msg){ progressWrap.classList.remove('hidden'); bar.style.width = (p||0) + '%'; percent.textContent = (p||0) + '%'; phase.textContent = ph || ''; if (msg) appendMessage(msg); }
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
  wave.on('finish', ()=>{ playBtn.textContent = 'Play'; });
}

function loadIntoWave(srcUrl, label, matchGain=null){
  currentLabel = label;
  if (matchGain != null) currentGain = matchGain;
  preview.classList.remove('hidden');
  previewSource.textContent = 'Preview: ' + label;
  makeWaveform();
  wave.load(srcUrl);
  playBtn.textContent = 'Play';
}

function gainForI(I, targetRef){
  if (I == null || !isFinite(I)) return 1.0;
  const deltaDb = targetRef - I;             // positive means boost, negative means cut
  const lin = Math.pow(10, deltaDb/20);
  return Math.max(0.1, Math.min(2.5, lin));  // clamp sane range
}

function updateMetrics(j){
  lastMetrics = j;
  metricsPanel.classList.remove('hidden');
  // Club
  const ci = j.metrics?.club?.input || {}, co = j.metrics?.club?.output || {};
  setIf('club_in_I', ci.I); setIf('club_in_TP', ci.TP); setIf('club_in_LRA', ci.LRA); setIf('club_in_TH', ci.threshold);
  setIf('club_out_I', co.I); setIf('club_out_TP', co.TP); setIf('club_out_LRA', co.LRA); setIf('club_out_TH', co.threshold);
  // Streaming
  const si = j.metrics?.streaming?.input || {}, so = j.metrics?.streaming?.output || {};
  setIf('str_in_I', si.I); setIf('str_in_TP', si.TP); setIf('str_in_LRA', si.LRA); setIf('str_in_TH', si.threshold);
  setIf('str_out_I', so.I); setIf('str_out_TP', so.TP); setIf('str_out_LRA', so.LRA); setIf('str_out_TH', so.threshold);
  // Premaster
  const pi = j.metrics?.premaster?.input || {}, po = j.metrics?.premaster?.output || {};
  setIf('pre_in_P', pi.peak_dbfs); setIf('pre_out_P', po.peak_dbfs);
  // Custom
  const ci2 = j.metrics?.custom?.input || {}, co2 = j.metrics?.custom?.output || {};
  setIf('cus_in_I', ci2.I); setIf('cus_in_TP', ci2.TP); setIf('cus_in_LRA', ci2.LRA); setIf('cus_in_TH', ci2.threshold);
  setIf('cus_out_I', co2.I); setIf('cus_out_TP', co2.TP); setIf('cus_out_LRA', co2.LRA); setIf('cus_out_TH', co2.threshold);

  drawTimelineOverlay(j.timeline);
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

async function startJob(file){
  // local preview immediately
  const blobUrl = URL.createObjectURL(file);
  loadIntoWave(blobUrl, 'Original', 1.0);

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
  poll(progress_url, blobUrl);
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

async function poll(url, originalBlobUrl){
  clearInterval(polling);
  polling = setInterval(async ()=>{
    try{
      const r = await fetch(url, { cache: 'no-store' });
      const j = await r.json();

      setProgress(j.percent, j.phase, j.message);
      updateMetrics(j);

      if (j.done) {
        clearInterval(polling);
        result.classList.remove('hidden');
        dlClub.href = j.downloads.club;
        dlStreaming.href = j.downloads.streaming;
        dlPremaster.href = j.downloads.premaster;
        dlZip.href = j.downloads.zip;
        dlSession.href = j.downloads.session_json;

        if (j.downloads.custom){
          dlCustom.href = j.downloads.custom;
          dlCustom.style.display = '';
          pvCustom.style.display = '';
        }

        // A/B wiring with gain-match
        const gains = setABGains(j);

        pvClub.onclick = ()=> loadIntoWave(j.downloads.club, 'Club', gains.club);
        pvStreaming.onclick = ()=> loadIntoWave(j.downloads.streaming, 'Streaming', gains.streaming);
        pvPremaster.onclick = ()=> loadIntoWave(j.downloads.premaster, 'Unlimited Premaster', gains.premaster || 1.0);
        if (j.downloads.custom) pvCustom.onclick = ()=> loadIntoWave(j.downloads.custom, 'Custom', gains.custom);

        abOrig.onclick = ()=> loadIntoWave(originalBlobUrl, 'Original', gains.original || 1.0);
        abProc.onclick = ()=> loadIntoWave(j.downloads.club || j.downloads.streaming, 'Processed', (gains.club || gains.streaming || 1.0));
      }
    }catch(e){ /* ignore transient errors */ }
  }, 1000);
}

// UI wiring
pick?.addEventListener('click', ()=> fileInput.click());
drop?.addEventListener('click', ()=> fileInput.click());
fileInput?.addEventListener('change', ()=> { const f = fileInput.files[0]; if (f){ messages.innerHTML=''; startJob(f); }});
['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e=>{ e.preventDefault(); drop.classList.add('drag'); }));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e=>{ e.preventDefault(); drop.classList.remove('drag'); }));
drop.addEventListener('drop', e=>{ e.preventDefault(); const f = e.dataTransfer.files[0]; if (f){ messages.innerHTML=''; startJob(f); }});

// Player
playBtn?.addEventListener('click', ()=>{ if(!wave) return; if (wave.isPlaying()){ wave.pause(); playBtn.textContent='Play'; } else { wave.play(); playBtn.textContent='Pause'; }});
window.addEventListener('resize', ()=> drawTimelineOverlay(lastMetrics?.timeline || null));
