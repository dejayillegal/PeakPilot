(function(){
  const body = document.body;
  const saved = localStorage.getItem('theme') || 'dark';
  if(saved==='light') body.classList.add('light');
  const toggle = document.getElementById('themeToggle');
  if(toggle){
    toggle.addEventListener('click', (e)=>{
      e.preventDefault();
      body.classList.toggle('light');
      localStorage.setItem('theme', body.classList.contains('light') ? 'light':'dark');
    });
  }
  const codec = document.getElementById('codec');
  if(codec){
    const stored = localStorage.getItem('codec');
    if(stored) codec.value = stored;
    codec.addEventListener('change', ()=>localStorage.setItem('codec', codec.value));
  }
  const warn = document.getElementById('ffmpegWarning');
  if(warn){
    fetch('/healthz').then(r=>r.json()).then(j=>{ if(!j.ok) warn.style.display='block'; }).catch(()=>{warn.style.display='block';});
  }
})();
