const analyzeBtn = document.getElementById('pp-analyze');

function showAnalyzingModal(open){
  const modal = document.getElementById('modal');
  if (!modal) return;
  modal.classList.toggle('hidden', !open);
}

function setAnalyzeProgress(p){
  document.querySelector('.pp-progress .bar').style.width = p+'%';
}

function setAnalyzeState(msg){
  const el = document.getElementById('pp-state');
  if (el) el.textContent = msg;
}

async function poll(){
  const session = window.PeakPilot?.session;
  if (!session) return;
  const r = await fetch(`/progress/${session}`, {cache:'no-store'});
  const j = await r.json();
  setAnalyzeProgress(j.pct || 0);
  if (j.status === 'analyzing') setAnalyzeState('Measuring loudness…');
  if (j.status === 'mastering') setAnalyzeState('Rendering masters…');
  if (j.status === 'finalizing') setAnalyzeState('Computing checksums…');
  if (j.status === 'done'){ showAnalyzingModal(false); clearInterval(timer); }
}
let timer;

analyzeBtn?.addEventListener('click', async () => {
  const session = window.PeakPilot?.session;
  if (!session) return;
  analyzeBtn.disabled = true;
  showAnalyzingModal(true);
  setAnalyzeState('Analyzing…');
  await fetch('/start', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session})});
  timer = setInterval(poll, 1000);
});

