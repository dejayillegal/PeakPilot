(()=>{
  // ---------- AUDIO SINGLETON ----------
  let AC;
  function getAC(){ return (AC ||= new (window.AudioContext||window.webkitAudioContext)()); }

  const Bus = {
    cur:null,
    claim(p){ if(this.cur && this.cur!==p) this.cur._hardStop(); this.cur=p; },
    release(p){ if(this.cur===p) this.cur=null; },
    stopAll(){ if(this.cur) this.cur._hardStop(); this.cur=null; }
  };

  const DecodeCache = new Map(); // url -> Promise<AudioBuffer>
  async function decodeUrl(url){
    if(!DecodeCache.has(url)){
      const p=(async()=>{
        const r=await fetch(url,{cache:"no-store"});
        if(!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
        const arr=await r.arrayBuffer();
        return getAC().decodeAudioData(arr);
      })();
      DecodeCache.set(url,p);
    }
    return DecodeCache.get(url);
  }

  // ---------- DRAW HELPERS ----------
  function drawWave(ctx, buffer, W, H){
    const ch=Math.min(2,buffer.numberOfChannels),
          L=buffer.getChannelData(0),
          R=ch>1?buffer.getChannelData(1):null;
    const cols=W, step=Math.max(1,Math.floor(L.length/cols)), mid=H/2;

    // RMS underlay
    ctx.beginPath();
    for(let x=0;x<cols;x++){
      const s=x*step; let sum=0,cnt=0;
      for(let i=0;i<step && s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, m=(l+r)*.5; sum+=m*m; cnt++; }
      const rms=Math.sqrt(sum/Math.max(1,cnt));
      const y=mid - rms*mid*.92; x?ctx.lineTo(x,y):ctx.moveTo(x,y);
    }
    for(let x=cols-1;x>=0;x--){
      const s=x*step; let sum=0,cnt=0;
      for(let i=0;i<step && s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, m=(l+r)*.5; sum+=m*m; cnt++; }
      const rms=Math.sqrt(sum/Math.max(1,cnt));
      const y=mid + rms*mid*.92; ctx.lineTo(x,y);
    }
    ctx.closePath();
    ctx.fillStyle="rgba(120,255,220,0.10)";
    ctx.fill();

    // Peak outline neon
    const g=ctx.createLinearGradient(0,0,W,0);
    g.addColorStop(0,"rgba(80,180,255,0.98)");
    g.addColorStop(1,"rgba(120,255,220,0.98)");
    ctx.beginPath();
    for(let x=0;x<cols;x++){
      const s=x*step; let minv=1,maxv=-1;
      for(let i=0;i<step && s+i<L.length;i++){
        const l=L[s+i], r=R?R[s+i]:l, v=(l+r)*.5; if(v<minv)minv=v; if(v>maxv)maxv=v;
      }
      const yT=mid + minv*mid; x?ctx.lineTo(x,yT):ctx.moveTo(x,yT);
    }
    for(let x=cols-1;x>=0;x--){
      const s=x*step; let minv=1,maxv=-1;
      for(let i=0;i<step && s+i<L.length;i++){
        const l=L[s+i], r=R?R[s+i]:l, v=(l+r)*.5; if(v<minv)minv=v; if(v>maxv)maxv=v;
      }
      const yB=mid + maxv*mid; ctx.lineTo(x,yB);
    }
    ctx.closePath();
    ctx.lineWidth=1; ctx.strokeStyle=g; ctx.stroke();
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

  // Advanced spectrum with log frequency axis, dB grid, band labels, and peak-hold
  function spectrumDrawer(specCanvas){
    const ctx = specCanvas.getContext('2d', {alpha:true});
    const AC = getAC();
    const analyser = AC.createAnalyser();
    analyser.fftSize = 4096;
    analyser.smoothingTimeConstant = 0.82;

    const bins = analyser.frequencyBinCount;
    const data = new Uint8Array(bins);
    const peak = new Float32Array(bins).fill(0);
    let raf = 0;

    const dpr = Math.max(1, window.devicePixelRatio||1);
    function resize(){
      const W = Math.round((specCanvas.clientWidth||600)*dpr);
      const H = Math.round((specCanvas.clientHeight||140)*dpr);
      specCanvas.width = W; specCanvas.height = H;
    }
    const ro = new ResizeObserver(resize); ro.observe(specCanvas.parentElement); resize();

    const minF = 20, maxF = 20000, sr = AC.sampleRate;
    const freqToX = (f,W)=> Math.round(Math.log10(Math.max(minF,f)/minF) / Math.log10(maxF/minF) * W);
    const binFreq = i => i*sr/(2*bins);

    function drawGrid(){
      const W = specCanvas.width, H = specCanvas.height;
      ctx.clearRect(0,0,W,H);
      // dB grid lines
      ctx.save();
      ctx.globalAlpha = 0.28;
      ctx.strokeStyle = "rgba(255,255,255,.25)";
      ctx.lineWidth = 1;
      const dbLines = [0,-10,-20,-30,-40,-60];
      dbLines.forEach(db=>{
        const y = Math.round((1 - (db+80)/80) * H);
        ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke();
      });
      ctx.restore();

      // X tick marks
      const freqs = [20,30,50,100,200,500,1000,2000,5000,10000,20000];
      ctx.save();
      ctx.globalAlpha=0.25; ctx.strokeStyle="rgba(255,255,255,.22)";
      freqs.forEach(f=>{
        const x = freqToX(f, W);
        ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke();
      });
      ctx.restore();

      // Band labels (Low, Low‑Mid, Mid, High‑Mid, High)
      const bands = [
        {name:"Low",     f1:20,   f2:120},
        {name:"Low‑Mid", f1:120,  f2:300},
        {name:"Mid",     f1:300,  f2:1500},
        {name:"High‑Mid",f1:1500, f2:6000},
        {name:"High",    f1:6000, f2:20000},
      ];
      bands.forEach(b=>{
        const x1=freqToX(b.f1, specCanvas.width);
        const x2=freqToX(b.f2, specCanvas.width);
        const xm=(x1+x2)/2;
        // Create/position label divs once
        if(!specCanvas.dataset.labels){
          specCanvas.dataset.labels = "1";
          const host = specCanvas.parentElement;
          bands.forEach(bb=>{
            const el=document.createElement('div');
            el.className='axis-label';
            el.textContent=bb.name;
            el.dataset.band=bb.name;
            host.appendChild(el);
          });
        }
        const el = specCanvas.parentElement.querySelector(`.axis-label[data-band="${b.name}"]`);
        if(el){
          el.style.top = "10px";
          el.style.left = `${(xm/specCanvas.width)*100}%`;
        }
      });

      // Y labels
      const yLabels = [0,-10,-20,-30,-40,-60];
      yLabels.forEach(db=>{
        const y = Math.round((1 - (db+80)/80) * specCanvas.height);
        let el = specCanvas.parentElement.querySelector(`.axis-label.y[data-db="${db}"]`);
        if(!el){
          el = document.createElement('div');
          el.className = 'axis-label y';
          el.dataset.db = db;
          el.style.left = '6px';
          specCanvas.parentElement.appendChild(el);
        }
        el.textContent = `${db} dB`;
        el.style.top = `${(y/specCanvas.height)*100}%`;
      });
    }

    function draw(){
      const W = specCanvas.width, H = specCanvas.height;
      drawGrid();
      analyser.getByteFrequencyData(data);

      // draw bars (log scale), with peak hold overlay
      ctx.globalAlpha = 1;
      let lastX = 0;
      for(let i=1;i<bins;i++){
        const f = binFreq(i), x = freqToX(f, W);
        if(x<=lastX) continue;
        const v = data[i]/255; // 0..1
        const dbNorm = Math.pow(v, 0.8);
        const y = H - dbNorm*H;
        // bar
        ctx.fillStyle = "rgba(120,255,220,.85)";
        ctx.fillRect(x, y, Math.max(1, x-lastX), H-y);

        // peak hold update
        peak[i] = Math.max(peak[i]*0.985, v); // slow decay
        const yPeak = H - Math.pow(peak[i], 0.8)*H;
        ctx.fillStyle = "rgba(255,255,255,.9)";
        ctx.fillRect(x, yPeak-1, Math.max(1, x-lastX), 2);

        lastX = x;
      }
      raf = requestAnimationFrame(draw);
    }

    function connect(node){ node.connect(analyser).connect(getAC().destination); draw(); }
    function disconnect(){ cancelAnimationFrame(raf); raf=0; try{ analyser.disconnect(); }catch{} }

    return { analyser, connect, disconnect, cleanup(){ disconnect(); ro.disconnect(); } };
  }

  // ---------- PLAYER ----------
  class TrackPlayer {
    constructor({ button, waveCanvas, specCanvas, url }){
      this.btn=button; this.cv=waveCanvas; this.spec=specCanvas; this.url=url;
      this.state="idle"; this.offset=0; this.buf=null; this._gen=0; this._raf=0; this._node=null; this._gain=null; this._start=0;
      this._spec=null; this._ctx=null; this._W=0; this._H=0; this._lastX=null; this._cols=null;
      this._bindUI(); this._observe(); this.load();
    }
    _bindUI(){
      this.btn?.addEventListener("click", ()=>this.toggle());
      this.cv.addEventListener("pointerdown",(e)=>{
        if(!this.buf) return;
        const r=this.cv.getBoundingClientRect();
        const p=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));
        const t=p*this.buf.duration;
        (this.state==="playing") ? (this.offset=t, this._restartAtOffset())
                                 : (this.offset=t, this._drawHead(p));
      }, {passive:true});
    }
    _observe(){ this._ro=new ResizeObserver(()=>this.render()); this._ro.observe(this.cv.parentElement); }
    async load(){
      try{
        this.state="loading";
        this.buf=await decodeUrl(this.url);
        this.state="ready"; this.btn?.removeAttribute("disabled"); this.render();
      }catch(e){
        this.state="error"; this.btn?.setAttribute("disabled","disabled");
        this.cv.replaceWith(document.createTextNode("Preview unavailable"));
        if(this.spec) this.spec.replaceWith(document.createTextNode(""));
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
      this._drawHead(this.offset/(this.buf.duration||1));
    }
    _drawHead(p){
      if(!this._ctx) return;
      const x=Math.floor(p*this._W);
      if(this._lastX!==null) this._ctx.clearRect(this._lastX-1,0,3,this._H);
      this._ctx.fillStyle="rgba(200,255,240,0.95)";
      this._ctx.fillRect(x,0,2,this._H);
      this._lastX=x;
    }
    _setupSpectrum(chainGain){
      if(!this.spec) return null;
      const spec = spectrumDrawer(this.spec);
      spec.connect(chainGain);
      this._spec = spec;
      return spec;
    }
    _teardownSpectrum(){ if(this._spec){ this._spec.cleanup(); this._spec=null; } }
    play(){
      if(!this.buf) return;
      const ac=getAC(); if(ac.state==="suspended") ac.resume();
      Bus.claim(this);
      const gen=++this._gen;

      const node=ac.createBufferSource(); const gain=ac.createGain();
      node.buffer=this.buf;

      // Spectrum taps into the chain here
      const spec = this._setupSpectrum(gain);
      if(!spec) node.connect(gain).connect(ac.destination);
      else node.connect(gain); // spec.connect() already chained to destination

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
      try{ this._node && this._node.stop(); }catch{}
      try{ this._node && this._node.disconnect(); }catch{}
      try{ this._gain && this._gain.disconnect(); }catch{}
      this._node=null; this._gain=null;
      cancelAnimationFrame(this._raf); this._raf=0;
      this._teardownSpectrum();
      if(this.buf) this._drawHead((this.offset||0)/(this.buf.duration||1));
    }
    _restartAtOffset(){ this._hardStop(); this.state="ready"; this.play(); }
    toggle(){ if(this.state==="playing") this.pause(false); else this.play(); }
    _setBtn(on){
      if(!this.btn) return;
      this.btn.setAttribute("aria-pressed", on?"true":"false");
      this.btn.setAttribute("aria-label", on?"Pause preview":"Play preview");
      this.btn.innerHTML = on
        ? `<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>`
        : `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
    }
  }

  // ---------- AUTO-ATTACH FOR EXISTING CARDS ----------
  async function attachPlayersForExistingCards(){
    // Handle original preview if present
    const session = (window.PeakPilot && window.PeakPilot.session) || (location.pathname.split('/').find(x=>x.length>=6) || '');
    try {
      const playBtn = document.getElementById('play');
      const wave = document.getElementById('loudCanvas');
      if (playBtn && wave && session) {
        const url = `/download/${session}/input_preview.wav`;
        // Try a HEAD/GET to avoid greying out unnecessarily
        const r = await fetch(url, {cache:"no-store"});
        if (r.ok) {
          new TrackPlayer({ button: playBtn, waveCanvas: wave, specCanvas: null, url });
        }
      }
    } catch {}

    // For each pp-card in the DOM now, attach a player
    document.querySelectorAll('.pp-card').forEach(card=>{
      const btn = card.querySelector('.pp-play');
      const wave = card.querySelector('.pp-wave canvas');
      const spec = card.querySelector('.pp-spec canvas');
      const wavLink = card.querySelector('.pp-downloads a.pp-dl[data-key="wav"], .pp-downloads a[data-key="wav"]');
      if(!btn || !wave || !wavLink) return;
      const url = wavLink.getAttribute('href');
      if(!url) return;
      btn.removeAttribute('disabled');
      new TrackPlayer({ button: btn, waveCanvas: wave, specCanvas: spec, url });
    });

    // Shield downloads from SPA handlers, but keep native downloads
    document.body.addEventListener('click', (e)=>{
      const a = e.target.closest('a.pp-dl');
      if(!a) return;
      a.setAttribute('download','');
    }, true);
  }

  document.addEventListener('DOMContentLoaded', attachPlayersForExistingCards);
  document.addEventListener('visibilitychange', ()=>{ if(document.hidden) Bus.stopAll(); });
})();
