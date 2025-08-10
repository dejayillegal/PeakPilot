(() => {
  const bus = { cur:null, claim(p){ if(this.cur && this.cur!==p) this.cur.pause(); this.cur=p; }, release(p){ if(this.cur===p) this.cur=null; } };
  let AC; const getAC = () => AC || (AC = new (window.AudioContext||window.webkitAudioContext)());

  class SimpleWave {
    constructor({mount, url}) {
      this.mount = mount; this.url = url;
      this.btn = document.createElement("button");
      this.btn.className = "pp-play"; this.btn.setAttribute("aria-label","Play preview"); this.btn.setAttribute("aria-pressed","false");
      this.btn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
      const wrap = document.createElement("div"); wrap.className = "pp-wave"; this.canvas = document.createElement("canvas"); wrap.appendChild(this.canvas);
      const row = document.createElement("div"); row.className = "pp-wavewrap"; row.appendChild(this.btn); row.appendChild(wrap);
      mount.innerHTML = ""; mount.appendChild(row);

      this._onBtn = () => this.toggle(); this.btn.addEventListener("click", this._onBtn);
      this.ro = new ResizeObserver(()=>this.render()); this.ro.observe(wrap);
      this.init();
    }
    async init(){
      try {
        const res = await fetch(this.url, { cache:"no-store" });
        if(!res.ok) throw new Error("preview fetch failed");
        this.buf = await getAC().decodeAudioData(await res.arrayBuffer());
        this.render(); this.btn.removeAttribute("disabled");
      } catch {
        const msg = document.createTextNode("Preview unavailable");
        this.canvas.replaceWith(msg); this.btn.setAttribute("disabled","disabled");
      }
    }
    render(){
      if(!this.buf || !this.canvas) return;
      const ctx = this.canvas.getContext("2d",{alpha:true});
      const dpr = Math.max(1, window.devicePixelRatio||1);
      const cssW = this.canvas.parentElement.clientWidth || 360, cssH = this.canvas.parentElement.clientHeight || 72;
      const W = Math.round(cssW*dpr), H = Math.round(cssH*dpr);
      this.canvas.width=W; this.canvas.height=H;
      ctx.clearRect(0,0,W,H);
      drawWave(ctx, this.buf, W, H, { strokeGrad:["rgba(80,180,255,.98)","rgba(120,255,220,.98)"], fill:"rgba(120,255,220,.10)" });
      this._ctx=ctx; this._W=W; this._H=H; this._lastX=null; this.drawHead(0);
    }
    drawHead(p){ if(!this._ctx) return; const x=Math.floor(p*this._W); if(this._lastX!==null) this._ctx.clearRect(this._lastX-1,0,3,this._H); this._ctx.fillStyle="rgba(200,255,240,.9)"; this._ctx.fillRect(x,0,2,this._H); this._lastX=x; }
    _tick = () => { if(!this.playing) return; const now=getAC().currentTime; const elapsed=now-this.start+this.offset; if(elapsed>=this.buf.duration){ this.pause(true); this.drawHead(0); return; } this.drawHead(elapsed/this.buf.duration); this.raf=requestAnimationFrame(this._tick); }
    play(){ if(!this.buf) return; const ac=getAC(); if(ac.state==="suspended") ac.resume(); bus.claim(this); this.node=ac.createBufferSource(); this.gain=ac.createGain(); this.node.buffer=this.buf; this.node.connect(this.gain).connect(ac.destination); this.start=ac.currentTime; this.node.start(0,this.offset||0); this.playing=true; this.btn.setAttribute("aria-pressed","true"); this.btn.setAttribute("aria-label","Pause preview"); this.btn.innerHTML=`<svg viewBox="0 0 24 24"><path d="M6 5h4v14H6zm8 0h4v14h-4z"/></svg>`; this.raf=requestAnimationFrame(this._tick); this.node.onended=()=>this.pause(true); }
    pause(ended=false){ if(!this.playing) return; try{ this.node&&this.node.stop(); }catch{} this.node&&this.node.disconnect(); this.gain&&this.gain.disconnect(); const ac=getAC(); if(!ended) this.offset=(this.offset||0)+(ac.currentTime-this.start); else this.offset=0; this.playing=false; cancelAnimationFrame(this.raf); this.btn.setAttribute("aria-pressed","false"); this.btn.setAttribute("aria-label","Play preview"); this.btn.innerHTML=`<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`; bus.release(this); }
    toggle(){ this.playing?this.pause():this.play(); }
  }

  function drawWave(ctx, buffer, W, H, { stroke, strokeGrad, fill }){
    const ch=Math.min(2, buffer.numberOfChannels), L=buffer.getChannelData(0), R=ch>1?buffer.getChannelData(1):null;
    const cols=W, step=Math.max(1, Math.floor(L.length/cols)), mid=H/2;
    if(strokeGrad){ const g=ctx.createLinearGradient(0,0,W,0); g.addColorStop(0,strokeGrad[0]); g.addColorStop(1,strokeGrad[1]); stroke=g; }
    // RMS fill
    ctx.beginPath();
    for(let x=0;x<cols;x++){ const s=x*step; let sum=0,c=0; for(let i=0;i<step&&s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, m=(l+r)*.5; sum+=m*m; c++; } const rms=Math.sqrt(sum/Math.max(1,c)); const y=mid - rms*mid*.9; x?ctx.lineTo(x,y):ctx.moveTo(x,y); }
    for(let x=cols-1;x>=0;x--){ const s=x*step; let sum=0,c=0; for(let i=0;i<step&&s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, m=(l+r)*.5; sum+=m*m; c++; } const rms=Math.sqrt(sum/Math.max(1,c)); const y=mid + rms*mid*.9; ctx.lineTo(x,y); }
    ctx.closePath(); if(fill){ ctx.fillStyle=fill; ctx.fill(); }
    // Peak outline
    ctx.beginPath();
    for(let x=0;x<cols;x++){ const s=x*step; let minv=1,maxv=-1; for(let i=0;i<step&&s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, v=(l+r)*.5; if(v<minv)minv=v; if(v>maxv)maxv=v; } const y=mid + minv*mid; x?ctx.lineTo(x,y):ctx.moveTo(x,y); }
    for(let x=cols-1;x>=0;x--){ const s=x*step; let minv=1,maxv=-1; for(let i=0;i<step&&s+i<L.length;i++){ const l=L[s+i], r=R?R[s+i]:l, v=(l+r)*.5; if(v<minv)minv=v; if(v>maxv)maxv=v; } const y=mid + maxv*mid; ctx.lineTo(x,y); }
    ctx.closePath(); ctx.lineWidth=1; ctx.strokeStyle=stroke||"rgba(255,255,255,.9)"; ctx.stroke();
  }

  // Public API: render uploaded audio in the canvases area
  window.renderUploadedAudioCanvas = function(session){
    const host = document.querySelector('.canvases[part="canvases"]');
    if(!host) return;
    const mount = document.createElement("div");
    host.innerHTML=""; host.appendChild(mount);
    const url = `/download/${session}/input_preview.wav`;
    new SimpleWave({ mount, url });
  };
})();
