(() => {
  // --- Global player registry to ensure only one plays at a time ---
  const PlayerBus = {
    players: new Set(),
    playing: null,
    register(p) { this.players.add(p); },
    unregister(p) { this.players.delete(p); if (this.playing === p) this.playing = null; },
    requestPlay(p) {
      if (this.playing && this.playing !== p) this.playing.pause();
      this.playing = p;
    },
    notifyPause(p) {
      if (this.playing === p) this.playing = null;
    }
  };

  // One shared AudioContext for the page
  let AC = null;
  function getAudioContext() {
    if (!AC) AC = new (window.AudioContext || window.webkitAudioContext)();
    return AC;
  }

  class WaveformPlayer {
    constructor({ container, audioUrl, accent = { a: "#50b4ff", b: "#78ffdc" } }) {
      this.root = container;
      this.url = audioUrl;
      this.canvas = document.createElement("canvas");
      this.canvas.setAttribute("aria-hidden", "true");
      this.canvas.style.width = "100%";
      this.canvas.style.height = "100%";
      this.root.appendChild(this.canvas);

      this.btn = container.parentElement.querySelector(".pp-play");
      this.svgPlay = iconPlay();
      this.svgPause = iconPause();
      this.btn.innerHTML = ""; this.btn.appendChild(this.svgPlay);
      this.btn.setAttribute("aria-pressed", "false");
      this.btn.setAttribute("aria-label", "Play preview");

      this.buffer = null;
      this.node = null;
      this.gain = null;
      this.startTime = 0;
      this.offset = 0;
      this.playing = false;
      this.gradient = accent;

      this._resize = this.resize.bind(this);
      this._onBtn = this.toggle.bind(this);
      this.ro = new ResizeObserver(this._resize);
      this.ro.observe(this.root);

      PlayerBus.register(this);
      this.init().catch(err => console.error("Waveform init failed:", err));
    }

    async init() {
      const ac = getAudioContext();

      // Fetch & decode
      const res = await fetch(this.url, { cache: "no-store" });
      if (!res.ok) throw new Error(`Fetch failed ${res.status}`);
      const arr = await res.arrayBuffer();
      this.buffer = await ac.decodeAudioData(arr);

      // Pre-render
      this.renderWaveform();

      // Wire button
      this.btn.addEventListener("click", this._onBtn, false);
    }

    resize() { this.renderWaveform(); }

    renderWaveform() {
      if (!this.buffer) return;
      const cs = getComputedStyle(this.root);
      const cssW = parseFloat(cs.width);
      const cssH = parseFloat(cs.height);
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      const W = Math.max(200, Math.round(cssW * dpr));
      const H = Math.max(40, Math.round(cssH * dpr));
      const ctx = this.canvas.getContext("2d", { alpha: true });

      this.canvas.width = W;
      this.canvas.height = H;

      // Background (subtle glass) already via CSS; just draw waveform
      ctx.clearRect(0, 0, W, H);

      const ch = Math.min(2, this.buffer.numberOfChannels);
      const dataL = this.buffer.getChannelData(0);
      const dataR = ch > 1 ? this.buffer.getChannelData(1) : null;

      // Downsample to one column per pixel
      const samples = dataL.length;
      const step = Math.ceil(samples / W);
      const amp = H / 2;

      // Envelope calculation (min/max) with light RMS fill
      const grad = ctx.createLinearGradient(0, 0, W, 0);
      grad.addColorStop(0, "rgba(80,180,255,0.95)");
      grad.addColorStop(1, "rgba(120,255,220,0.95)");

      ctx.lineWidth = Math.max(1, Math.floor(dpr));
      ctx.strokeStyle = grad;

      // RMS underlay
      ctx.beginPath();
      for (let x = 0; x < W; x++) {
        const start = x * step;
        let sum = 0, count = 0;
        for (let i = 0; i < step && (start + i) < samples; i++) {
          const l = dataL[start + i];
          const r = dataR ? dataR[start + i] : l;
          const m = (l + r) * 0.5;
          sum += m * m;
          count++;
        }
        const rms = Math.sqrt(sum / Math.max(1, count));
        const y = amp - rms * amp * 0.9;
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      for (let x = W - 1; x >= 0; x--) {
        const start = x * step;
        let sum = 0, count = 0;
        for (let i = 0; i < step && (start + i) < samples; i++) {
          const l = dataL[start + i];
          const r = dataR ? dataR[start + i] : l;
          const m = (l + r) * 0.5;
          sum += m * m;
          count++;
        }
        const rms = Math.sqrt(sum / Math.max(1, count));
        const y = amp + rms * amp * 0.9;
        if (x === W - 1) ctx.lineTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = "rgba(120,255,220,0.12)";
      ctx.fill();

      // Peak outline
      ctx.beginPath();
      for (let x = 0; x < W; x++) {
        const start = x * step;
        let minv = 1, maxv = -1;
        for (let i = 0; i < step && (start + i) < samples; i++) {
          const l = dataL[start + i];
          const r = dataR ? dataR[start + i] : l;
          const v = (l + r) * 0.5;
          if (v < minv) minv = v;
          if (v > maxv) maxv = v;
        }
        const yTop = amp + minv * amp;
        if (x === 0) ctx.moveTo(x, yTop); else ctx.lineTo(x, yTop);
      }
      for (let x = W - 1; x >= 0; x--) {
        const start = x * step;
        let minv = 1, maxv = -1;
        for (let i = 0; i < step && (start + i) < samples; i++) {
          const l = dataL[start + i];
          const r = dataR ? dataR[start + i] : l;
          const v = (l + r) * 0.5;
          if (v < minv) minv = v;
          if (v > maxv) maxv = v;
        }
        const yBot = amp + maxv * amp;
        if (x === W - 1) ctx.lineTo(x, yBot); else ctx.lineTo(x, yBot);
      }
      ctx.closePath();
      ctx.stroke();

      // Playhead overlay (updated during playback)
      this.playheadCtx = ctx; this.playheadW = W; this.playheadH = H;
      this.lastHeadX = null;
      this.drawPlayhead(0); // reset
    }

    drawPlayhead(progress01) {
      const ctx = this.playheadCtx;
      if (!ctx) return;
      // Re-render waveform first? not needed—just draw head after a light clear column
      const x = Math.floor(progress01 * this.playheadW);
      if (this.lastHeadX !== null) {
        ctx.clearRect(this.lastHeadX - 1, 0, 3, this.playheadH);
      }
      // Head
      ctx.fillStyle = "rgba(160,245,255,0.9)";
      ctx.fillRect(x, 0, 2, this.playheadH);
      this.lastHeadX = x;
    }

    _tick = () => {
      if (!this.playing || !this.buffer) return;
      const now = getAudioContext().currentTime;
      const elapsed = now - this.startTime + this.offset;
      const dur = this.buffer.duration;
      if (elapsed >= dur) {
        this.pause(true);
        this.drawPlayhead(0);
        return;
      }
      this.drawPlayhead(Math.max(0, Math.min(1, elapsed / dur)));
      this.raf = requestAnimationFrame(this._tick);
    }

    play() {
      if (!this.buffer) return;
      const ac = getAudioContext();
      if (ac.state === "suspended") ac.resume();

      PlayerBus.requestPlay(this);

      // create nodes
      this.gain = ac.createGain();
      this.node = ac.createBufferSource();
      this.node.buffer = this.buffer;
      this.node.connect(this.gain).connect(ac.destination);

      const now = ac.currentTime;
      this.startTime = now;
      this.node.start(0, this.offset);
      this.playing = true;
      this.btn.setAttribute("aria-pressed", "true");
      this.btn.setAttribute("aria-label", "Pause preview");
      this.btn.innerHTML = ""; this.btn.appendChild(this.svgPause);
      this.raf = requestAnimationFrame(this._tick);

      this.node.onended = () => this.pause(true);
    }

    pause(ended = false) {
      if (!this.playing) return;
      try { this.node && this.node.stop(); } catch {}
      if (this.node) { this.node.disconnect(); this.node = null; }
      if (this.gain) { this.gain.disconnect(); this.gain = null; }

      const ac = getAudioContext();
      const now = ac.currentTime;
      if (!ended) this.offset += (now - this.startTime);
      else this.offset = 0;

      this.playing = false;
      cancelAnimationFrame(this.raf);
      this.btn.setAttribute("aria-pressed", "false");
      this.btn.setAttribute("aria-label", "Play preview");
      this.btn.innerHTML = ""; this.btn.appendChild(this.svgPlay);
      PlayerBus.notifyPause(this);
    }

    toggle() { this.playing ? this.pause() : this.play(); }

    destroy() {
      this.pause();
      this.btn.removeEventListener("click", this._onBtn, false);
      this.ro.disconnect();
      PlayerBus.unregister(this);
      this.root.innerHTML = "";
    }
  }

  function iconPlay() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg","svg");
    svg.setAttribute("viewBox","0 0 24 24");
    svg.innerHTML = `<path d="M8 5v14l11-7z"/>`;
    return svg;
  }
  function iconPause() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg","svg");
    svg.setAttribute("viewBox","0 0 24 24");
    svg.innerHTML = `<path d="M6 5h4v14H6zm8 0h4v14h-4z"/>`;
    return svg;
  }

  // Build one card DOM
  function buildCard({ id, title, audioUrl, metrics }) {
    const card = document.createElement("article");
    card.className = "pp-card";
    card.id = `card-${id}`;
    card.innerHTML = `
      <h3>${escapeHtml(title)}</h3>
      <div class="pp-wavewrap">
        <button class="pp-play" type="button" aria-pressed="false" aria-label="Play preview"></button>
        <div class="pp-wave"></div>
      </div>
      <table class="pp-metrics" role="table" aria-label="${escapeHtml(id)} metrics">
        <thead></thead>
        <tbody></tbody>
      </table>
    `;

    // Waveform player
    const wave = card.querySelector(".pp-wave");
    new WaveformPlayer({ container: wave, audioUrl });

    // Metrics table
    const thead = card.querySelector("thead");
    const tbody = card.querySelector("tbody");
    renderMetricsTable(thead, tbody, metrics);

    return card;
  }

  function renderMetricsTable(thead, tbody, metrics) {
    thead.innerHTML = "";
    tbody.innerHTML = "";

    // header row
    const headTr = document.createElement("tr");
    const thEmpty = document.createElement("th");
    thEmpty.textContent = ""; thEmpty.className = "row-label";
    headTr.appendChild(thEmpty);
    metrics.labelRow.forEach(lbl => {
      const th = document.createElement("th");
      th.textContent = lbl; headTr.appendChild(th);
    });
    thead.appendChild(headTr);

    // input row (when present)
    if (metrics.input && metrics.input.length) {
      const trI = document.createElement("tr");
      const thI = document.createElement("th");
      thI.textContent = "Input"; thI.className = "row-label";
      trI.appendChild(thI);
      metrics.input.forEach(val => {
        const td = document.createElement("td");
        td.className = "value";
        td.textContent = val;
        trI.appendChild(td);
      });
      tbody.appendChild(trI);
    }

    // output row
    if (metrics.output && metrics.output.length) {
      const trO = document.createElement("tr");
      const thO = document.createElement("th");
      thO.textContent = "Output"; thO.className = "row-label";
      trO.appendChild(thO);
      metrics.output.forEach(val => {
        const td = document.createElement("td");
        td.className = "value";
        td.textContent = val;
        trO.appendChild(td);
      });
      tbody.appendChild(trO);
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
    }[c]));
  }

  // Public API
  window.renderMasteringResults = function(session, cards) {
    const mount = document.getElementById("pp-results");
    if (!mount) return;
    mount.innerHTML = "";
    cards.forEach(c => mount.appendChild(buildCard(c)));
  };
})();
