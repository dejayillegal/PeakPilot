function renderMasteringResults(session, cards){
  const root = document.getElementById('pp-results');
  if (!root) return;
  root.innerHTML = '';
  cards.forEach(card => {
    const div = document.createElement('div');
    div.className = 'pp-card';
    const h3 = document.createElement('h3');
    h3.textContent = card.title;
    div.appendChild(h3);
    const btn = document.createElement('button');
    btn.className = 'pp-play';
    btn.setAttribute('aria-label','Play');
    const audio = new Audio(card.processedUrl);
    btn.addEventListener('click', ()=>{
      if (audio.paused){
        document.querySelectorAll('#pp-results audio').forEach(a=>{ if(!a.paused) a.pause(); });
        audio.play();
      } else {
        audio.pause();
      }
    });
    div.appendChild(btn);
    div.appendChild(audio);
    const dlW = document.createElement('a');
    dlW.textContent = 'WAV';
    dlW.href = `/download/${session}/${card.wavKey}`;
    dlW.download = card.wavKey;
    div.appendChild(dlW);
    const dlI = document.createElement('a');
    dlI.textContent = 'INFO';
    dlI.href = `/download/${session}/${card.infoKey}`;
    dlI.download = card.infoKey;
    div.appendChild(dlI);
    root.appendChild(div);
  });
}
window.renderMasteringResults = renderMasteringResults;
