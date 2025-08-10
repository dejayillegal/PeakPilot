let session = null;
const fileInput = document.getElementById('file');
const analyzeBtn = document.getElementById('analyze');
const progBar = document.querySelector('.pp-fileprog .bar');
const fileInfo = document.querySelector('.pp-fileinfo');

function bytes(n){
  if (n > 1e6) return (n/1e6).toFixed(1)+' MB';
  if (n > 1e3) return (n/1e3).toFixed(1)+' kB';
  return n + ' B';
}

fileInput?.addEventListener('change', e => {
  const file = e.target.files[0];
  if (!file) return;
  const xhr = new XMLHttpRequest();
  const fd = new FormData();
  if (session) fd.append('session', session);
  fd.append('reset','1');
  fd.append('file', file);
  xhr.upload.onprogress = ev => {
    if (ev.lengthComputable) {
      progBar.style.width = (ev.loaded/ev.total*100).toFixed(1)+'%';
    }
  };
  xhr.onload = () => {
    const res = JSON.parse(xhr.responseText || '{}');
    if (res.ok){
      session = res.session;
      fileInfo.textContent = `${res.filename} • ${bytes(res.size)}`;
      fileInfo.dataset.state = 'uploaded';
      analyzeBtn.disabled = false;
    }
  };
  xhr.open('POST','/upload');
  xhr.send(fd);
});

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
  if (!session) return;
  analyzeBtn.disabled = true;
  showAnalyzingModal(true);
  setAnalyzeState('Analyzing…');
  await fetch('/start', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session})});
  timer = setInterval(poll, 1000);
});

