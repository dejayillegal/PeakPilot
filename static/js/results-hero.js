(() => {
  window.PeakPilot = window.PeakPilot || {};
  const bus = window.PeakPilot.PlayerBus || (window.PeakPilot.PlayerBus = {
    cur:null,
    claim(p){ if(this.cur && this.cur!==p) this.cur.pause?.(); this.cur=p; },
    release(p){ if(this.cur===p) this.cur=null; }
  });
  let AC = window.PeakPilot._ac;
  function getAC(){
    return AC || (AC = window.PeakPilot._ac = new (window.AudioContext||window.webkitAudioContext)());
  }

  const MasterCards = new Map(); // id -> {el, btn, pill, linkWav, linkInfo, wavKey, infoKey, ready:false, player:null}

  function registerCard(id, artEl, wavKey, infoKey){
    MasterCards.set(id, {
      id,
      el: artEl,
      btn: artEl.querySelector('.pp-play'),
      pill: artEl.querySelector('.pp-statepill'),
      linkWav: artEl.querySelector('.pp-dl[data-key="wav"]'),
      linkInfo: artEl.querySelector('.pp-dl[data-key="info"]'),
      wavKey, infoKey,
      ready:false,
      player:null
    });
  }

  function updateMasterProgress(progress){
    const m = progress.masters || {};
    // render cards on first progress tick
    if(MasterCards.size===0 && window.PeakPilot.session){
      const defs = window.PeakPilot.masterCards || [
        {id:'club', title:'Club (48k/24, target −7.2 LUFS, −0.8 dBTP)', wavKey:'club_master.wav', infoKey:'ClubMaster_24b_48k_INFO.txt', metrics:{labelRow:['LUFS-I','TP','LRA','Thresh'], input:[], output:[]}},
        {id:'stream', title:'Streaming (44.1k/24, target −9.5 LUFS, −1.0 dBTP)', wavKey:'stream_master.wav', infoKey:'StreamingMaster_24b_44k1_INFO.txt', metrics:{labelRow:['LUFS-I','TP','LRA','Thresh'], input:[], output:[]}},
        {id:'unlimited', title:'Unlimited Premaster (48k/24, peak −6 dBFS)', wavKey:'premaster_unlimited.wav', infoKey:'UnlimitedPremaster_24b_48k_INFO.txt', metrics:{labelRow:['Peak dBFS'], input:[], output:[]}},
        {id:'custom', title:'Custom', wavKey:'custom_master.wav', infoKey:'CustomMaster_INFO.txt', metrics:{labelRow:['LUFS-I','TP','LRA','Thresh'], input:[], output:[]}},
      ];
      window.renderMasteringResultsInHero(window.PeakPilot.session, defs, {showCustom:false});
    }
    for(const id of ['club','stream','unlimited','custom']){
      const card = MasterCards.get(id);
      if(!card) continue;
      const st = m[id];
      if(!st) continue;
      card.pill.dataset.state = st.state || 'queued';
      card.pill.textContent = st.state === 'rendering' ? `Rendering… ${st.pct|0}%`
                        : st.state === 'finalizing' ? 'Finalizing…'
                        : st.state === 'done' ? 'Ready'
                        : st.state === 'error' ? 'Error'
                        : 'Queued';
      if(st.state === 'done' && !card.ready){
        card.btn.removeAttribute('disabled');
        const base = `/download/${window.PeakPilot.session}/`;
        card.linkWav.href = base + encodeURIComponent(card.wavKey);
        card.linkInfo.href = base + encodeURIComponent(card.infoKey);
        card.linkWav.removeAttribute('aria-disabled');
        card.linkInfo.removeAttribute('aria-disabled');
        card.linkWav.removeAttribute('tabindex');
        card.linkInfo.removeAttribute('tabindex');
        if(!card.player) card.player = new MasterWavePlayer(card.btn, card.el.querySelector('canvas'), base + encodeURIComponent(card.wavKey));
        card.ready = true;
      }
    }
    const zip = document.querySelector('#masterCanvases .pp-downloads .pp-dl:not([data-key])') || document.querySelector('#pp-results .pp-downloads .pp-dl:not([data-key])');
    if(zip && progress.status==='done'){
      if(zip.getAttribute('aria-disabled')==='true'){
        const base=`/download/${window.PeakPilot.session}/`;
        zip.href=base+encodeURIComponent('Masters_AND_INFO.zip');
        zip.removeAttribute('aria-disabled');
        zip.removeAttribute('tabindex');
      }
    }
  }

  window.updateMasterProgress = updateMasterProgress;

  class MasterWavePlayer {
    constructor(btn, canvas, url){
      this.btn=btn; this.canvas=canvas; this.url=url;
      this.buffer=null; this.source=null; this.start=0; this.offset=0; this.playing=false;
      this.btn.addEventListener('click', ()=>this.toggle());
      this.canvas.addEventListener('pointerdown', e=>this.seek(e));
      this.ro = new ResizeObserver(()=>this.render());
      this.ro.observe(canvas);
      this.load();
    }
    async load(){
      try{
        const r = await fetch(this.url, {cache:'no-store'});
        if(!r.ok) throw new Error(r.status);
        const arr = await r.arrayBuffer();
        this.buffer = await getAC().decodeAudioData(arr);
        this.render();
      }catch(e){
        if(!this._retried){ this._retried=1; setTimeout(()=>this.load(),2000); return; }
        this.canvas.parentElement.textContent = 'Preview unavailable';
        this.btn.disabled = true;
      }
    }
    render(){
      if(!this.buffer) return;
      const cssW = this.canvas.clientWidth;
      const cssH = this.canvas.clientHeight;
      const dpr = Math.max(1, window.devicePixelRatio||1);
      const W = Math.max(200, Math.round(cssW*dpr));
      const H = Math.max(40, Math.round(cssH*dpr));
      this.canvas.width=W; this.canvas.height=H;
      const ctx = this.canvas.getContext('2d', {alpha:true});
      ctx.clearRect(0,0,W,H);
      const data = this.buffer.getChannelData(0);
      const samples=data.length;
      const step=Math.ceil(samples/W);
      const amp=H/2;
      const css=getComputedStyle(document.documentElement);
      const acc1 = css.getPropertyValue('--pp-accent').trim() || '#1ff1e9';
      const acc2 = css.getPropertyValue('--pp-accent-2').trim() || acc1;
      ctx.beginPath();
      for(let x=0;x<W;x++){
        let sum=0,count=0; const start=x*step;
        for(let i=0;i<step&&start+i<samples;i++){ const v=data[start+i]; sum+=v*v; count++; }
        const rms=Math.sqrt(sum/Math.max(1,count));
        const y=amp - rms*amp*0.9;
        x?ctx.lineTo(x,y):ctx.moveTo(x,y);
      }
      for(let x=W-1;x>=0;x--){
        let sum=0,count=0; const start=x*step;
        for(let i=0;i<step&&start+i<samples;i++){ const v=data[start+i]; sum+=v*v; count++; }
        const rms=Math.sqrt(sum/Math.max(1,count));
        const y=amp + rms*amp*0.9;
        ctx.lineTo(x,y);
      }
      ctx.closePath();
      ctx.fillStyle = hexToRgba(acc2,0.12);
      ctx.fill();
      const grad = ctx.createLinearGradient(0,0,W,0);
      grad.addColorStop(0,acc1); grad.addColorStop(1,acc2);
      ctx.strokeStyle = grad;
      ctx.lineWidth = Math.max(1, Math.floor(dpr));
      ctx.beginPath();
      for(let x=0;x<W;x++){
        const start=x*step; let min=1,max=-1;
        for(let i=0;i<step&&start+i<samples;i++){ const v=data[start+i]; if(v<min)min=v; if(v>max)max=v; }
        const y=amp + min*amp; x?ctx.lineTo(x,y):ctx.moveTo(x,y);
      }
      for(let x=W-1;x>=0;x--){
        const start=x*step; let min=1,max=-1;
        for(let i=0;i<step&&start+i<samples;i++){ const v=data[start+i]; if(v<min)min=v; if(v>max)max=v; }
        const y=amp + max*amp; ctx.lineTo(x,y);
      }
      ctx.stroke();
      this.ctx=ctx; this.W=W; this.H=H; this.lastHead=null; this.drawHead(0);
    }
    drawHead(p){
      if(!this.ctx) return;
      if(this.lastHead!==null) this.ctx.clearRect(this.lastHead-1,0,2,this.H);
      const x=Math.floor(p*this.W);
      this.ctx.fillStyle=hexToRgba('#a0f5ff',0.9);
      this.ctx.fillRect(x,0,1,this.H);
      this.lastHead=x;
    }
    seek(e){
      if(!this.buffer) return;
      const rect=this.canvas.getBoundingClientRect();
      const p=Math.max(0, Math.min(1, (e.clientX-rect.left)/rect.width));
      this.offset=p*this.buffer.duration;
      if(this.playing){ this.play(); } else { this.drawHead(p); }
    }
    toggle(){ this.playing?this.pause():this.play(); }
    play(){
      if(!this.buffer) return;
      const ac=getAC(); if(ac.state==='suspended') ac.resume();
      bus.claim(this);
      this.source=ac.createBufferSource();
      this.source.buffer=this.buffer;
      this.source.connect(ac.destination);
      this.start=ac.currentTime;
      this.source.start(0,this.offset);
      this.playing=true;
      this.btn.setAttribute('aria-pressed','true');
      this.btn.setAttribute('aria-label','Pause preview');
      this.btn.innerHTML='<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>';
      this.raf=requestAnimationFrame(()=>this.tick());
      this.source.onended=()=>this.pause(true);
    }
    tick(){
      if(!this.playing) return;
      const now=getAC().currentTime;
      const prog=(now-this.start+this.offset)/this.buffer.duration;
      if(prog>=1){ this.pause(true); return; }
      this.drawHead(prog);
      this.raf=requestAnimationFrame(()=>this.tick());
    }
    pause(ended=false){
      if(!this.playing) return;
      try{ this.source.stop(); }catch{}
      this.source.disconnect();
      const ac=getAC();
      const now=ac.currentTime;
      this.offset=ended?0:this.offset+(now-this.start);
      this.playing=false;
      cancelAnimationFrame(this.raf);
      this.btn.setAttribute('aria-pressed','false');
      this.btn.setAttribute('aria-label','Play preview');
      this.btn.innerHTML='<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>';
      bus.release(this);
      this.drawHead(0);
    }
  }

  function hexToRgba(hex,a){
    hex=hex.trim();
    if(hex.startsWith('#')) hex=hex.slice(1);
    if(hex.length===3) hex=hex.split('').map(c=>c+c).join('');
    const num=parseInt(hex,16); const r=(num>>16)&255, g=(num>>8)&255, b=num&255;
    return `rgba(${r},${g},${b},${a})`;
  }

  function buildMetricsTable(metrics){
    const table=document.createElement('table');
    table.className='pp-metrics';
    const thead=document.createElement('thead');
    const headTr=document.createElement('tr');
    const empty=document.createElement('th'); empty.className='row-label'; headTr.appendChild(empty);
    metrics.labelRow.forEach(lbl=>{ const th=document.createElement('th'); th.textContent=lbl; headTr.appendChild(th); });
    thead.appendChild(headTr); table.appendChild(thead);
    const tbody=document.createElement('tbody');
    if(metrics.input){
      const tr=document.createElement('tr');
      const th=document.createElement('th'); th.textContent='Input'; th.className='row-label'; tr.appendChild(th);
      metrics.input.forEach(v=>{ const td=document.createElement('td'); td.className='value'; td.textContent=v; tr.appendChild(td); });
      tbody.appendChild(tr);
    }
    if(metrics.output){
      const tr=document.createElement('tr');
      const th=document.createElement('th'); th.textContent='Output'; th.className='row-label'; tr.appendChild(th);
      metrics.output.forEach(v=>{ const td=document.createElement('td'); td.className='value'; td.textContent=v; tr.appendChild(td); });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    return table;
  }

  function buildCard(session, cfg){
    const art=document.createElement('article');
    art.className='pp-card';
    art.id=`card-${cfg.id}`;
    art.innerHTML=`<h3>${cfg.title}</h3>
      <div class="pp-statepill" data-state="queued">Queued</div>
      <div class="pp-wavewrap">
        <button class="pp-play" type="button" aria-pressed="false" aria-label="Play preview" disabled>
          <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
        </button>
        <div class="pp-wave"><canvas></canvas></div>
      </div>`;
    art.appendChild(buildMetricsTable(cfg.metrics));
    const downloads=document.createElement('div'); downloads.className='pp-downloads';
    downloads.innerHTML=`<a class="pp-dl" data-key="wav" aria-disabled="true" tabindex="-1"><span class="emo">🎼</span> <span>Download WAV</span></a>
      <a class="pp-dl" data-key="info" aria-disabled="true" tabindex="-1"><span class="emo">📝</span> <span>Download INFO</span></a>`;
    art.appendChild(downloads);
    registerCard(cfg.id, art, cfg.wavKey, cfg.infoKey);
    return art;
  }

  function wireDownloadShield(container){
    container.addEventListener('click', e=>{
      const a=e.target.closest('a.pp-dl');
      if(!a) return;
      if(a.getAttribute('aria-disabled')==='true'){ e.preventDefault(); e.stopPropagation(); return; }
      e.stopPropagation();
      a.setAttribute('download','');
    });
  }

  window.renderMasteringResultsInHero = function(session, cards, opts={}){
    const hero=document.getElementById('masterCanvases');
    const legacy=document.getElementById('pp-results');
    const mount = hero || legacy;
    if(!mount) return;
    if(hero && legacy) legacy.innerHTML='';
    mount.innerHTML='';
    MasterCards.clear();
    const order=['club','stream','unlimited','custom'];
    order.forEach(id=>{ if(id==='custom' && !opts.showCustom) return; const cfg=cards.find(c=>c.id===id); if(cfg) mount.appendChild(buildCard(session,cfg)); });
    const zipRow=document.createElement('div'); zipRow.className='pp-downloads';
    const zip=document.createElement('a'); zip.className='pp-dl'; zip.setAttribute('aria-disabled','true'); zip.setAttribute('tabindex','-1'); zip.innerHTML='<span class="emo">📦</span> <span>Download Masters + INFO (ZIP)</span>';
    zipRow.appendChild(zip); mount.appendChild(zipRow);
    wireDownloadShield(mount);
    if(window.PeakPilot.lastProgress) updateMasterProgress(window.PeakPilot.lastProgress);
  };

  window.drawPeakHighlightsOnOriginal = function(canvas, buffer, threshDb){
    if(!canvas || !buffer) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width; const H = canvas.height;
    const data = buffer.getChannelData(0);
    const step = Math.ceil(data.length / W);
    ctx.save();
    ctx.fillStyle = 'rgba(255,80,80,0.3)';
    for(let x=0;x<W;x++){
      const start=x*step; let peak=0;
      for(let i=0;i<step && start+i<data.length;i++){ const v=Math.abs(data[start+i]); if(v>peak) peak=v; }
      const db=20*Math.log10(peak+1e-9);
      if(db>threshDb) ctx.fillRect(x,0,1,H);
    }
    ctx.restore();
  };

  const _origUpdateMetrics = window.updateMetrics;
  window.updateMetrics = function(j){
    if(typeof _origUpdateMetrics === 'function') _origUpdateMetrics(j);
    window.PeakPilot.lastProgress = j;
    updateMasterProgress(j);
  };

  window.PeakPilot.getAC = getAC;
})();
