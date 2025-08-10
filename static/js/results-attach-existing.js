(() => {
  // ---------- AUDIO CORE ----------
  let AC;
  const getAC = () => (AC ||= new (window.AudioContext || window.webkitAudioContext)());
  const Bus = {
    cur: null,
    claim(p){ if(this.cur && this.cur!==p) this.cur.stop(true); this.cur = p; },
    release(p){ if(this.cur === p) this.cur = null; },
    stopAll(){ if(this.cur) this.cur.stop(true); this.cur = null; }
  };

  // ---------- SPECTRUM (log-freq, dB grid, peak-hold) ----------
  function createSpectrum(canvas){
    const ac = getAC();
    const analyser = ac.createAnalyser();
    analyser.fftSize = 4096;
    analyser.smoothingTimeConstant = 0.82;

    const dpr = Math.max(1, window.devicePixelRatio||1);
    const ro = new ResizeObserver(()=>resize());
    ro.observe(canvas.parentElement);

    function resize(){
      canvas.width  = Math.round((canvas.clientWidth  || 600) * dpr);
      canvas.height = Math.round((canvas.clientHeight || 140) * dpr);
    }
    resize();

    const ctx = canvas.getContext("2d");
    const bins = analyser.frequencyBinCount;
    const data = new Uint8Array(bins);
    const peak = new Float32Array(bins);
    let raf = 0;

    const minF=20, maxF=20000, sr=ac.sampleRate;
    const freqToX = (f,W)=> Math.round(Math.log10(Math.max(minF,f)/minF) / Math.log10(maxF/minF) * W);
    const binFreq = i => i * sr / (2*bins);

    function drawGrid(){
      const W=canvas.width, H=canvas.height;
      ctx.clearRect(0,0,W,H);
      // dB grid
      ctx.save();
      ctx.globalAlpha=0.28; ctx.strokeStyle="rgba(255,255,255,.25)";
      [0,-10,-20,-30,-40,-60].forEach(db=>{
        const y = Math.round((1 - (db+80)/80) * H);
        ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke();
      });
      ctx.restore();
      // X ticks
      ctx.save();
      ctx.globalAlpha=0.25; ctx.strokeStyle="rgba(255,255,255,.22)";
      [20,30,50,100,200,500,1000,2000,5000,10000,20000].forEach(f=>{
        const x=freqToX(f,W);
        ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke();
      });
      ctx.restore();
    }

    function loop(){
      const W=canvas.width, H=canvas.height;
      drawGrid();
      analyser.getByteFrequencyData(data);
      let lastX=0;
      for(let i=1;i<bins;i++){
        const f=binFreq(i), x=freqToX(f,W);
        if(x<=lastX) continue;
        const v = data[i]/255;
        const y = H - Math.pow(v,0.8)*H;
        // bar
        ctx.fillStyle="rgba(120,255,220,.85)";
        ctx.fillRect(x, y, Math.max(1,x-lastX), H-y);
        // peak hold
        peak[i] = Math.max(peak[i]*0.985, v);
        const yP = H - Math.pow(peak[i],0.8)*H;
        ctx.fillStyle="rgba(255,255,255,.9)";
        ctx.fillRect(x, yP-1, Math.max(1,x-lastX), 2);
        lastX=x;
      }
      raf = requestAnimationFrame(loop);
    }

    const start = (node) => { node.connect(analyser).connect(getAC().destination); raf = requestAnimationFrame(loop); };
    const stop  = () => { try{ analyser.disconnect(); }catch{} cancelAnimationFrame(raf); raf=0; };
    const cleanup = () => { stop(); ro.disconnect(); };
    return { start, stop, cleanup, analyser };
  }

  // ---------- WAVEFORM DRAW ----------
  function drawWave(ctx, audio, W, H){
    const mid = H/2;
    // Use a TimeDomain fallback if no buffer: simple cosmetic waveform
    ctx.fillStyle="rgba(120,255,220,0.10)";
    ctx.fillRect(0,0,W,H);
    const g=ctx.createLinearGradient(0,0,W,0);
    g.addColorStop(0,"rgba(80,180,255,0.98)");
    g.addColorStop(1,"rgba(120,255,220,0.98)");
    ctx.strokeStyle=g; ctx.lineWidth=1;
    ctx.beginPath();
    for(let x=0;x<W;x++){
      const y = mid + Math.sin(x/12)*(H*0.18); // placeholder curve until we have PCM
      x?ctx.lineTo(x,y):ctx.moveTo(x,y);
    }
    ctx.stroke();
  }

  // ---------- PLAYER ----------
  class CardPlayer {
    constructor({ card, button, waveCanvas, specCanvas, url }){
      this.card=card; this.btn=button; this.cv=waveCanvas; this.specCanvas=specCanvas; this.url=url;
      this.audio=null; this.srcNode=null; this.spec=null; this._raf=0; this._lastHead=null;
      this.state="idle";
      this._bind();
      this._renderWaveSkeleton();
      this._ensureAudio();
    }
    _bind(){
      this.btn?.addEventListener("click", ()=> this.toggle());
      this.cv.addEventListener("pointerdown", (e)=>{
        if(!this.audio || !this.audio.duration) return;
        const r=this.cv.getBoundingClientRect();
        const p=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));
        this.audio.currentTime = p * this.audio.duration;
        if(this.state!=="playing") this._drawHead(p);
      }, {passive:true});
    }
    _renderWaveSkeleton(){
      const dpr=Math.max(1,window.devicePixelRatio||1);
      const W=Math.round((this.cv.parentElement.clientWidth||600)*dpr);
      const H=Math.round((this.cv.parentElement.clientHeight||86)*dpr);
      this.cv.width=W; this.cv.height=H;
      const ctx=this.cv.getContext("2d",{alpha:true});
      ctx.clearRect(0,0,W,H);
      drawWave(ctx, null, W, H);
      this._drawHead(0);
    }
    _drawHead(p){
      const ctx=this.cv.getContext("2d"); const W=this.cv.width, H=this.cv.height;
      if(this._lastHead!=null) ctx.clearRect(this._lastHead-1,0,3,H);
      const x=Math.floor(p*W);
      ctx.fillStyle="rgba(200,255,240,0.95)";
      ctx.fillRect(x,0,2,H);
      this._lastHead=x;
    }
    async _ensureAudio(){
      // Use inline stream preview if available
      const streamUrl = this.url.replace("/download/","/stream/").replace(/\.wav$/,"_preview.wav");
      const tryUrls = [streamUrl, this.url.replace("/download/","/stream/"), this.url];
      for(const u of tryUrls){
        try{
          const test = await fetch(u, { method:"GET", cache:"no-store" });
          if(!test.ok) continue;
          const a = new Audio(); a.preload="metadata"; a.src = u;
          a.crossOrigin = "anonymous";
          await a.play().then(()=>a.pause()).catch(()=>{}); // warm permissions
          this.audio=a;
          this.btn.removeAttribute("disabled");
          return;
        }catch{}
      }
      // fallback: leave disabled
      this.btn.setAttribute("disabled","disabled");
    }
    _tick(){
      if(!this.audio) return;
      const t=this.audio.currentTime, d=this.audio.duration||1;
      this._drawHead(t/d);
      this._raf = requestAnimationFrame(()=>this._tick());
    }
    play(){
      if(!this.audio) return;
      const ac=getAC(); if(ac.state==="suspended") ac.resume();
      Bus.claim(this);
      // connect graph
      const src = getAC().createMediaElementSource(this.audio);
      const gain = getAC().createGain(); src.connect(gain);
      if(this.specCanvas){ this.spec = createSpectrum(this.specCanvas); this.spec.start(gain); }
      else { gain.connect(getAC().destination); }
      this.srcNode = src;
      this.audio.play();
      this._setBtn(true);
      this.state="playing";
      cancelAnimationFrame(this._raf); this._raf=requestAnimationFrame(()=>this._tick());
      this.audio.onended = ()=> this.stop(true);
    }
    stop(ended=false){
      if(this.audio){ try{ this.audio.pause(); }catch{} }
      cancelAnimationFrame(this._raf); this._raf=0;
      if(this.spec){ this.spec.stop(); this.spec.cleanup(); this.spec=null; }
      try{ this.srcNode && this.srcNode.disconnect(); }catch{}
      this.srcNode=null;
      this._setBtn(false);
      this.state = ended ? "ended" : "paused";
      Bus.release(this);
      if(ended) this._drawHead(0);
    }
    toggle(){ (this.state==="playing") ? this.stop(false) : this.play(); }
    _setBtn(on){
      this.btn.setAttribute("aria-pressed", on?"true":"false");
      this.btn.setAttribute("aria-label", on?"Pause preview":"Play preview");
      this.btn.innerHTML = on
        ? `<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>`
        : `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
    }
  }

  // ---------- AUTO-ATTACH ----------
  function attachExisting(){
    const session = window.PeakPilot?.session || (location.pathname.split('/').find(x=>x.length>=6) || "");
    // Original preview
    const playBtn = document.getElementById('play');
    const wave    = document.getElementById('loudCanvas');
    if (session && playBtn && wave) {
      const orig = `/stream/${session}/input_preview.wav`;
      fetch(orig, {cache:"no-store"}).then(r=>{
        if(r.ok){ new CardPlayer({ card:null, button:playBtn, waveCanvas:wave, specCanvas:null, url: `/download/${session}/input_preview.wav` }); }
      });
    }
    // Master cards
    document.querySelectorAll('.pp-card').forEach(card=>{
      const btn = card.querySelector('.pp-play');
      const wave = card.querySelector('.pp-wave canvas');
      const spec = card.querySelector('.pp-spec canvas');
      const wav = card.querySelector('.pp-downloads [data-key="wav"]');
      if(!btn || !wave || !wav) return;
      const url = wav.getAttribute('href'); if(!url) return;
      new CardPlayer({ card, button: btn, waveCanvas: wave, specCanvas: spec, url });
    });

    // Make only one downloadable element actually download (native)
    document.body.addEventListener('click',(e)=>{
      const a = e.target.closest('a.pp-dl'); if(!a) return;
      a.setAttribute('download','');
    }, true);
  }

  document.addEventListener('DOMContentLoaded', attachExisting);
  document.addEventListener('visibilitychange', ()=>{ if(document.hidden) Bus.stopAll(); });
})();
