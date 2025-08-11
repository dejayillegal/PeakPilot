(() => {
  // ---------- SINGLETONS ----------
  let AC;
  function getAC(){ return (AC ||= new (window.AudioContext||window.webkitAudioContext)()); }

  const Bus = { cur:null, claim(p){ if(this.cur && this.cur!==p) this.cur._hardStop(); this.cur=p; }, release(p){ if(this.cur===p) this.cur=null; }, stopAll(){ if(this.cur) this.cur._hardStop(); this.cur=null; } };
  const DecodeCache = new Map(); // url -> Promise<AudioBuffer>
  async function decodeUrl(url){
    if(!DecodeCache.has(url)){
      const p=(async()=>{ const r=await fetch(url,{cache:"no-store"}); if(!r.ok) throw new Error(`HTTP ${r.status}`); const arr=await r.arrayBuffer(); return getAC().decodeAudioData(arr); })();
      DecodeCache.set(url,p);
    }
    return DecodeCache.get(url);
  }

  const previewFromDownload = (url) => url.replace("/download/","/stream/").replace(/([^/]+)\.wav$/,"$1_preview.wav");

  function setDownloadLink(anchor, url){
    if(!anchor) return;
    if(url){
      anchor.href=url;
      anchor.setAttribute('download','');
      anchor.removeAttribute('aria-disabled');
      anchor.classList.remove('is-disabled');
      anchor.removeAttribute('tabindex');
    }else{
      anchor.removeAttribute('href');
      anchor.removeAttribute('download');
      anchor.setAttribute('aria-disabled','true');
      anchor.classList.add('is-disabled');
      anchor.setAttribute('tabindex','-1');
    }
  }

  // ---------- DRAW HELPERS ----------
  function drawWave(ctx, buffer, W, H){
    const ch=Math.min(2,buffer.numberOfChannels), L=buffer.getChannelData(0), R=ch>1?buffer.getChannelData(1):null;
    const cols=W, step=Math.max(1,Math.floor(L.length/cols)), mid=H/2;

    // RMS underlay
    ctx.beginPath();
    for(let x=0;x<cols;x++){ const s=x*step; let sum=0,cnt=0;
      for(let i=0;i<step && s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, m=(l+r)*.5; sum+=m*m; cnt++; }
      const rms=Math.sqrt(sum/Math.max(1,cnt)); const y=mid - rms*mid*.92; x?ctx.lineTo(x,y):ctx.moveTo(x,y);
    }
    for(let x=cols-1;x>=0;x--){ const s=x*step; let sum=0,cnt=0;
      for(let i=0;i<step && s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, m=(l+r)*.5; sum+=m*m; cnt++; }
      const rms=Math.sqrt(sum/Math.max(1,cnt)); const y=mid + rms*mid*.92; ctx.lineTo(x,y);
    }
    ctx.closePath(); ctx.fillStyle="rgba(120,255,220,0.10)"; ctx.fill();

    // Peak outline neon
    const g=ctx.createLinearGradient(0,0,W,0); g.addColorStop(0,"rgba(80,180,255,0.98)"); g.addColorStop(1,"rgba(120,255,220,0.98)");
    ctx.beginPath();
    for(let x=0;x<cols;x++){ const s=x*step; let minv=1,maxv=-1;
      for(let i=0;i<step && s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, v=(l+r)*.5; if(v<minv)minv=v; if(v>maxv)maxv=v; }
      const yT=mid + minv*mid; x?ctx.lineTo(x,yT):ctx.moveTo(x,yT);
    }
    for(let x=cols-1;x>=0;x--){ const s=x*step; let minv=1,maxv=-1;
      for(let i=0;i<step && s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, v=(l+r)*.5; if(v<minv)minv=v; if(v>maxv)maxv=v; }
      const yB=mid + maxv*mid; ctx.lineTo(x,yB);
    }
    ctx.closePath(); ctx.lineWidth=1; ctx.strokeStyle=g; ctx.stroke();
  }

  function precomputeColumns(buffer, W){
    const L=buffer.getChannelData(0), R=buffer.numberOfChannels>1?buffer.getChannelData(1):null;
    const step=Math.max(1,Math.floor(L.length/W)), cols=W;
    const rms=new Float32Array(cols), peak=new Float32Array(cols);
    for(let x=0;x<cols;x++){
      const s=x*step; let sum=0,c=0, pk=0;
      for(let i=0;i<step && s+i<L.length;i++){
        const l=L[s+i], r=R?R[s+i]:l, m=(l+r)*.5; sum+=m*m; c++; const a=Math.abs(m); if(a>pk) pk=a;
      }
      rms[x]=Math.sqrt(sum/Math.max(1,c)); peak[x]=pk;
    }
    return {rms,peak};
  }

  function drawLoudnessRibbon(ctx, cols, rms){
    const W=ctx.canvas.width, H=ctx.canvas.height;
    const step=Math.max(1,Math.floor(cols/W)); ctx.clearRect(0,0,W,H);
    for(let x=0;x<W;x++){
      // average a small bin
      let sum=0,c=0; for(let i=0;i<step;i++){ const idx=Math.min(cols-1, x*step+i); sum+=rms[idx]; c++; }
      const v=sum/Math.max(1,c); // 0..1 (approx)
      // Simple LUFS-ish mapping: lower rms → blue, near target → green, high → amber
      const lufs = 20*Math.log10(Math.max(1e-6, v)); // not true LUFS; indicative
      let col = (lufs > -9.5) ? "rgba(255,200,120,.95)" : (lufs > -14.5) ? "rgba(120,255,180,.95)" : "rgba(120,180,255,.95)";
      ctx.fillStyle=col; ctx.fillRect(x,0,1,H);
    }
  }

  function drawTPHotspots(ctx, cols, peak, thrAmp){
    const W=ctx.canvas.width, H=ctx.canvas.height;
    ctx.save(); ctx.fillStyle="rgba(255, 120, 120, .55)";
    const step=Math.max(1,Math.floor(cols/W));
    for(let x=0;x<W;x++){
      let hot=false; for(let i=0;i<step;i++){ const idx=Math.min(cols-1, x*step+i); if(peak[idx]>=thrAmp){ hot=true; break; } }
      if(hot) ctx.fillRect(x,0,1,H);
    }
    ctx.restore();
  }

  function drawSpectrum(ctx, analyser){
    const W=ctx.canvas.width, H=ctx.canvas.height;
    const bins=analyser.frequencyBinCount;
    const data=new Uint8Array(bins); analyser.getByteFrequencyData(data);
    ctx.clearRect(0,0,W,H);
    // Log scale mapping: 20Hz..20kHz
    const minF=20, maxF=20000, sampleRate=getAC().sampleRate;
    const binToFreq=(i)=> i*bins ? i*sampleRate/(2*bins) : 0;
    const freqToX=(f)=> { const lf=Math.log10(Math.max(minF,f)/minF)/Math.log10(maxF/minF); return Math.round(lf*W); };

    // Grid dB lines
    ctx.save();
    ctx.globalAlpha=0.28; ctx.strokeStyle="rgba(255,255,255,.25)"; ctx.lineWidth=1;
    const dbLines=[0,-10,-20,-30,-40,-60];
    dbLines.forEach(db=>{
      const y = Math.round((1 - (db+80)/80) * H); // 0dB near top; -80 bottom
      ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke();
    });
    ctx.restore();

    // Bars
    ctx.fillStyle="rgba(120,255,220,.9)";
    // draw approx log-domain bars
    let lastX=0;
    for(let i=1;i<bins;i++){
      const f=binToFreq(i), x=freqToX(f);
      if(x<=lastX) continue;
      const v=data[i]/255; // 0..1
      const y=H - Math.pow(v, 0.8)*H;
      ctx.fillRect(x, y, Math.max(1, x-lastX), H-y);
      lastX=x;
    }
  }

  // ---------- PLAYER ----------
  class TrackPlayer {
    constructor({ button, waveCanvas, ribbonCanvas, specCanvas, url, onDrawOverlay }){
      this.btn=button; this.cv=waveCanvas; this.ribbon=ribbonCanvas; this.spec=specCanvas; this.url=url; this.onDrawOverlay=onDrawOverlay||(()=>{});
      this.state="idle"; this.offset=0; this.buf=null; this._gen=0; this._raf=0; this._node=null; this._gain=null; this._start=0;
      this._analyser=null; this._specRAF=0;
      this._ctx=null; this._cols=null; this._W=0; this._H=0; this._lastX=null;
      this._bindUI();
      this._rObs=new ResizeObserver(()=>this.render()); this._rObs.observe(this.cv.parentElement);
      this.load();
    }
    _bindUI(){
      this.btn?.addEventListener("click", ()=>this.toggle());
      this.cv.addEventListener("pointerdown",(e)=>{
        if(!this.buf) return;
        const r=this.cv.getBoundingClientRect(); const p=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)); const t=p*this.buf.duration;
        (this.state==="playing") ? (this.offset=t, this._restartAtOffset()) : (this.offset=t, this._drawHead(p));
      }, {passive:true});
    }
    async load(){
      try{
        this.state="loading";
        try{
          this.buf=await decodeUrl(this.url);
        }catch{
          const dl=this.url.replace("/stream/","/download/").replace(/_preview\.wav$/,".wav");
          this.buf=await decodeUrl(dl);
          this.url=dl;
        }
        this.state="ready"; this.btn?.removeAttribute("disabled"); this.render();
      }catch(e){
        this.state="error"; this.btn?.setAttribute("disabled","disabled");
        this.cv.replaceWith(document.createTextNode("Preview unavailable"));
        if(this.ribbon) this.ribbon.replaceWith(document.createTextNode(""));
        if(this.spec)   this.spec.replaceWith(document.createTextNode(""));
      }
    }
    render(){
      if(!this.buf||!this.cv) return;
      const dpr=Math.max(1,window.devicePixelRatio||1);
      const cssW=this.cv.parentElement.clientWidth||600, cssH=this.cv.parentElement.clientHeight||86;
      const W=Math.round(cssW*dpr), H=Math.round(cssH*dpr);
      this.cv.width=W; this.cv.height=H;
      const ctx=this.cv.getContext("2d",{alpha:true}); ctx.clearRect(0,0,W,H);
      drawWave(ctx,this.buf,W,H); this.cv.classList.add("wave-neon");
      this._ctx=ctx; this._W=W; this._H=H; this._lastX=null;

      // Precompute for ribbon & TP ticks
      this._cols = precomputeColumns(this.buf, W);
      // Draw overlay (TP hotspots)
      this.onDrawOverlay(this);
      // draw initial head
      this._drawHead(this.offset/(this.buf.duration||1));

      // Ribbon
      if(this.ribbon){
        const rctx=this.ribbon.getContext("2d",{alpha:true});
        this.ribbon.width=W; this.ribbon.height=Math.round((this.ribbon.clientHeight||10)*dpr);
        drawLoudnessRibbon(rctx, W, this._cols.rms);
      }
    }
    _drawTPHot(){
      if(!this._ctx || !this._cols) return;
      // highlight peaks above ~ -1.5 dBFS → amp thr
      const thrAmp = Math.pow(10, (-1.5)/20);
      const tmp = document.createElement("canvas");
      tmp.width=this._W; tmp.height=6;
      const tctx=tmp.getContext("2d"); drawTPHotspots(tctx, this._W, this._cols.peak, thrAmp);
      // paint at the top as a tick belt
      this._ctx.drawImage(tmp, 0, 0, this._W, 6);
    }
    _drawHead(p){
      if(!this._ctx) return;
      const x=Math.floor(p*this._W);
      if(this._lastX!==null) this._ctx.clearRect(this._lastX-1,0,3,this._H);
      this._ctx.fillStyle="rgba(200,255,240,0.95)"; this._ctx.fillRect(x,0,2,this._H);
      this._lastX=x;
    }
    _ensureAnalyser(connectNode){
      const ac=getAC();
      this._analyser=ac.createAnalyser();
      this._analyser.fftSize=2048; this._analyser.smoothingTimeConstant=0.82;
      connectNode.connect(this._analyser).connect(ac.destination);
      const specDraw = ()=>{
        if(!this._analyser || !this.spec) return;
        const dpr=Math.max(1,window.devicePixelRatio||1);
        const W=Math.round((this.spec.clientWidth||600)*dpr), H=Math.round((this.spec.clientHeight||140)*dpr);
        this.spec.width=W; this.spec.height=H;
        const sctx=this.spec.getContext("2d",{alpha:true});
        drawSpectrum(sctx, this._analyser);
        this._specRAF=requestAnimationFrame(specDraw);
      };
      cancelAnimationFrame(this._specRAF); this._specRAF=requestAnimationFrame(specDraw);
    }
    _killAnalyser(){
      if(this._analyser){ try{ this._analyser.disconnect(); }catch{} this._analyser=null; }
      cancelAnimationFrame(this._specRAF); this._specRAF=0;
      if(this.spec){ const ctx=this.spec.getContext("2d",{alpha:true}); ctx.clearRect(0,0,this.spec.width,this.spec.height); }
    }
    play(){
      if(!this.buf) return;
      const ac=getAC(); if(ac.state==="suspended") ac.resume();
      Bus.claim(this);
      const gen=++this._gen;

      const node=ac.createBufferSource(); const gain=ac.createGain();
      node.buffer=this.buf;
      // If spectrum is present, route through analyser → destination; else directly
      if(this.spec){
        this._ensureAnalyser(gain);
        node.connect(gain);
      } else {
        node.connect(gain).connect(ac.destination);
      }

      this._node=node; this._gain=gain; this._start=ac.currentTime;
      node.start(0,this.offset||0);

      this._setBtn(true); this.state="playing";
      const tick=()=>{
        if(gen!==this._gen || this.state!=="playing") return;
        const now=ac.currentTime; const elapsed=now-this._start+(this.offset||0);
        if(elapsed>=this.buf.duration-1e-3){ this.pause(true); this._drawHead(0); return; }
        this._drawHead(elapsed/this.buf.duration);
        this._raf=requestAnimationFrame(tick);
      };
      this._raf=requestAnimationFrame(tick);
      node.onended=()=>{ if(gen!==this._gen) return; this.pause(true); };
    }
    pause(ended=false){
      if(this.state!=="playing") return;
      const ac=getAC(); const elapsed=ac.currentTime-this._start+(this.offset||0);
      this.offset = ended ? 0 : Math.min(elapsed, this.buf?.duration||elapsed);
      this._hardStop(); this.state=ended?"ended":"paused"; this._setBtn(false); Bus.release(this);
    }
    _hardStop(){
      const gen=++this._gen;
      try{ this._node&&this._node.stop(); }catch{}
      try{ this._node&&this._node.disconnect(); }catch{}
      try{ this._gain&&this._gain.disconnect(); }catch{}
      this._node=null; this._gain=null;
      cancelAnimationFrame(this._raf); this._raf=0;
      this._killAnalyser();
      if(this.buf) this._drawHead((this.offset||0)/(this.buf.duration||1));
    }
    _restartAtOffset(){ this._hardStop(); this.state="ready"; this.play(); }
    _setBtn(on){
      if(!this.btn) return;
      this.btn.setAttribute("aria-pressed", on?"true":"false");
      this.btn.setAttribute("aria-label", on?"Pause preview":"Play preview");
      this.btn.innerHTML = on
        ? `<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>`
        : `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
    }
  }

  // ---------- RESULTS RENDERER ----------
  function pickResultsMount(){
    const hero=document.getElementById('masterCanvases');
    const legacy=document.getElementById('pp-results');
    if(hero){ if(legacy) legacy.innerHTML=''; return hero; }
    return legacy;
  }

  const MasterCards=new Map(); // id -> { el, btn, wave, ribbon, spec, pill, wavKey, infoKey, ready, player }

  function escapeHtml(s){ return String(s).replace(/[&<>"]/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c])); }

  function buildCard({ id, title, wavKey, infoKey }){
    const art=document.createElement('article'); art.className='pp-card'; art.id=`card-${id}`;
    art.innerHTML=`
      <h3>${escapeHtml(title)}</h3>
      <div class="pp-statepill" data-state="queued">Queued</div>
      <div class="pp-wavewrap">
        <button class="pp-play" type="button" aria-pressed="false" aria-label="Play preview" disabled>
          <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
        </button>
        <div class="pp-wave"><canvas></canvas></div>
      </div>
      <div class="pp-ribbon"><canvas></canvas></div>
      <div class="pp-spec"><canvas></canvas><div class="axis"></div><div class="legend">Spectrum (dB)</div></div>
      <table class="pp-metrics"><thead></thead><tbody></tbody></table>
      <div class="pp-downloads">
        <a class="pp-dl" data-key="wav"  aria-disabled="true" tabindex="-1"><span class="emo">🎼</span> <span>Download WAV</span></a>
        <a class="pp-dl" data-key="info" aria-disabled="true" tabindex="-1"><span class="emo">📝</span> <span>Download INFO</span></a>
      </div>
    `;
    // register
    MasterCards.set(id, {
      id, el: art,
      btn: art.querySelector('.pp-play'),
      wave: art.querySelector('.pp-wave canvas'),
      ribbon: art.querySelector('.pp-ribbon canvas'),
      spec: art.querySelector('.pp-spec canvas'),
      pill: art.querySelector('.pp-statepill'),
      linkWav: art.querySelector('.pp-dl[data-key="wav"]'),
      linkInfo: art.querySelector('.pp-dl[data-key="info"]'),
      wavKey, infoKey, procUrl:null, ready:false, player:null
    });
    return art;
  }

  function renderMetricsTable(art, cfg){
    const thead=art.querySelector('thead'), tbody=art.querySelector('tbody');
    thead.innerHTML=""; tbody.innerHTML="";
    const head=document.createElement('tr'); const blank=document.createElement('th'); blank.className='row-label'; head.appendChild(blank);
    const thIn=document.createElement('th'); thIn.textContent='Input'; head.appendChild(thIn);
    const thOut=document.createElement('th'); thOut.textContent='Output'; head.appendChild(thOut);
    thead.appendChild(head);
    const m = cfg.metrics || {};
    function fmt(v){ return (v===null||v===undefined) ? '—' : Number(v).toFixed(2); }
    function addRow(label,a,b){ const tr=document.createElement('tr'); const th=document.createElement('th'); th.textContent=label; th.className='row-label'; tr.appendChild(th); const td1=document.createElement('td'); td1.className='value'; td1.textContent=fmt(a); tr.appendChild(td1); const td2=document.createElement('td'); td2.className='value'; td2.textContent=fmt(b); tr.appendChild(td2); tbody.appendChild(tr); }
    if(cfg.id==='unlimited'){
      addRow('Peak dBFS', m.input?.peak_dbfs, m.output?.peak_dbfs);
      return;
    }
    addRow('LUFS-I', m.input?.lufs_integrated, m.output?.lufs_integrated);
    addRow('TP (dBTP)', m.input?.true_peak_db, m.output?.true_peak_db);
    addRow('LRA (LU)', m.input?.lra, m.output?.lra);
  }

  function wireDownloadShield(container){
    container.addEventListener('click',(e)=>{
      const a=e.target.closest('a.pp-dl'); if(!a) return;
      if(a.getAttribute('aria-disabled')==='true'){ e.preventDefault(); e.stopPropagation(); return; }
      e.stopPropagation(); a.setAttribute('download','');
    });
  }

  // Public API: render inside hero (fallback to legacy)
  window.renderMasteringResultsInHero = function(session, cards, { showCustom=false } = {}){
    const mount=pickResultsMount(); if(!mount) return;
    mount.innerHTML='';
    for(const c of cards){
      if(c.id==='custom' && !showCustom) continue;
      const art=buildCard({ id:c.id, title:c.title, wavKey:c.wavKey, infoKey:c.infoKey });
      renderMetricsTable(art, c);
      mount.appendChild(art);
      const card=MasterCards.get(c.id);
      card.procUrl = c.processedUrl || null;
      setDownloadLink(card.linkWav, c.downloadWav);
      setDownloadLink(card.linkInfo, c.downloadInfo);
    }
    wireDownloadShield(mount);
  };

  // Polling hook: update per-master progress & activate when done
  window.updateMasterCardsProgress = function(progress){
    const m = progress?.masters || {};
    const metrics = progress?.metrics || {};
    if (m.streaming && !m.stream)   m.stream   = m.streaming;
    if (m.premaster && !m.unlimited) m.unlimited = m.premaster;
    if (m.premaster_unlimited && !m.unlimited) m.unlimited = m.premaster_unlimited;
    for(const [id, card] of MasterCards){
      const st = m[id]; if(!st) continue;
      card.pill.dataset.state=st.state||'queued';
      card.pill.textContent = st.state==='rendering' ? `Rendering… ${st.pct|0}%`
                            : st.state==='finalizing' ? 'Finalizing…'
                            : st.state==='done' ? 'Ready'
                            : st.state==='error' ? 'Error'
                            : 'Queued';

      const cfg = { id, metrics: { input: metrics.input || {}, output: metrics[id] || {} } };
      renderMetricsTable(card.el, cfg);

      if(st.state==='done' && !card.ready){
        const baseDl=`/download/${window.PeakPilot.session}/`;
        const dlUrl= baseDl+encodeURIComponent(card.wavKey);
        setDownloadLink(card.linkWav, dlUrl);
        setDownloadLink(card.linkInfo, baseDl+encodeURIComponent(card.infoKey));
        card.btn.removeAttribute('disabled');

        const playUrl = card.procUrl;
        if(!playUrl){
          card.wave.replaceWith(document.createTextNode("Preview unavailable"));
          if(card.ribbon) card.ribbon.replaceWith(document.createTextNode(""));
          if(card.spec)   card.spec.replaceWith(document.createTextNode(""));
          card.btn.setAttribute('disabled','disabled');
          card.ready=true;
        }else{
          const player = new TrackPlayer({
            button: card.btn,
            waveCanvas: card.wave,
            ribbonCanvas: card.ribbon,
            specCanvas: card.spec,
            url: playUrl,
            onDrawOverlay: (pl)=> pl._drawTPHot()
          });
          card.player=player; card.ready=true;
        }
      }
    }
    (async () => {
      const s = window.PeakPilot?.session;
      if (!s) return;
      for (const [id, card] of MasterCards) {
        if (card.ready) continue;
        const base = `/download/${s}/`;
        const dlUrl  = base + encodeURIComponent(card.wavKey);
        try {
          const r = await fetch(dlUrl, { method:"HEAD", cache:"no-store" });
          if (r.ok) {
            setDownloadLink(card.linkWav, dlUrl);
            setDownloadLink(card.linkInfo, base + encodeURIComponent(card.infoKey));
            card.btn.removeAttribute('disabled');
            const playUrl = card.procUrl || previewFromDownload(dlUrl);
            if(playUrl){
              const player = new TrackPlayer({ button:card.btn, waveCanvas:card.wave, ribbonCanvas:card.ribbon, specCanvas:card.spec, url: playUrl, onDrawOverlay:(pl)=>pl._drawTPHot() });
              card.player = player; card.ready = true;
              console.warn(`[PP] Enabled ${id} via file presence (progress missing)`);
            }
          }
        } catch {}
      }
    })();
  };

  // Original preview hookup (called once after session available)
  window.attachOriginalPlayer = async function(){
    const btn=document.getElementById('play'); const wave=document.getElementById('loudCanvas');
    if(!btn || !wave) return;
    const base=`/stream/${window.PeakPilot.session}/`; const url=base+encodeURIComponent("input_preview.wav");
    // Make a ribbon+spec for original as well (create under #preview)
    let ribbon=document.querySelector('#preview .pp-ribbon canvas'); let spec=document.querySelector('#preview .pp-spec canvas');
    if(!ribbon){
      const host=document.getElementById('waveWrap'); if(host){
        const rb=document.createElement('div'); rb.className='pp-ribbon'; rb.innerHTML='<canvas></canvas>'; host.after(rb);
        const sp=document.createElement('div'); sp.className='pp-spec'; sp.innerHTML='<canvas></canvas><div class="axis"></div><div class="legend">Spectrum (dB)</div>'; rb.after(sp);
        ribbon=rb.querySelector('canvas'); spec=sp.querySelector('canvas');
      }
    }
    const player=new TrackPlayer({ button: btn, waveCanvas: wave, ribbonCanvas: ribbon, specCanvas: spec, url, onDrawOverlay:(pl)=>pl._drawTPHot() });
    (window.PeakPilot.players ||= {}).original=player;
  };

  // Export for other scripts
  window.PeakPilot = window.PeakPilot || {};
  window.PeakPilot.PlayerBus = Bus;

  document.addEventListener('DOMContentLoaded', ()=>{ /* no-op; consumers call the APIs above */ });
})();
