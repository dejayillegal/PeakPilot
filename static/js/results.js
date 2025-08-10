(() => {
  const PlayerBus = {
    cur: null,
    claim(p) {
      if (this.cur && this.cur !== p) this.cur.pause();
      this.cur = p;
    },
    release(p) {
      if (this.cur === p) this.cur = null;
    }
  };

  let AC;
  function getAC() {
    return AC || (AC = new (window.AudioContext || window.webkitAudioContext)());
  }

  class WaveformPlayer {
    constructor(btn, canvas, url) {
      this.btn = btn;
      this.canvas = canvas;
      this.url = url;
      this.buffer = null;
      this.source = null;
      this.start = 0;
      this.offset = 0;
      this.playing = false;
      this.btn.appendChild(iconPlay());
      this.btn.addEventListener('click', () => this.toggle());
      this.ro = new ResizeObserver(() => this.render());
      this.ro.observe(this.canvas);
      this.load();
    }

    async load() {
      try {
        const res = await fetch(this.url, { cache: 'no-store' });
        if (!res.ok) throw new Error(res.status);
        const arr = await res.arrayBuffer();
        this.buffer = await getAC().decodeAudioData(arr);
        this.render();
      } catch (e) {
        console.warn('preview failed', e);
        this.canvas.parentElement.textContent = 'Preview unavailable';
        this.btn.disabled = true;
      }
    }

    render() {
      if (!this.buffer) return;
      const cssW = this.canvas.clientWidth;
      const cssH = this.canvas.clientHeight;
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      const W = Math.max(200, Math.round(cssW * dpr));
      const H = Math.max(40, Math.round(cssH * dpr));
      this.canvas.width = W;
      this.canvas.height = H;
      const ctx = this.canvas.getContext('2d', { alpha: true });
      ctx.clearRect(0, 0, W, H);

      const data = this.buffer.getChannelData(0);
      const samples = data.length;
      const step = Math.ceil(samples / W);
      const amp = H / 2;
      const css = getComputedStyle(document.documentElement);
      const acc1 = css.getPropertyValue('--pp-accent').trim() || '#1ff1e9';
      const acc2 = css.getPropertyValue('--pp-accent-2').trim() || acc1;

      // RMS underlay
      ctx.beginPath();
      for (let x = 0; x < W; x++) {
        let sum = 0, count = 0;
        const start = x * step;
        for (let i = 0; i < step && start + i < samples; i++) {
          const v = data[start + i];
          sum += v * v;
          count++;
        }
        const rms = Math.sqrt(sum / Math.max(1, count));
        const y = amp - rms * amp * 0.9;
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      for (let x = W - 1; x >= 0; x--) {
        let sum = 0, count = 0;
        const start = x * step;
        for (let i = 0; i < step && start + i < samples; i++) {
          const v = data[start + i];
          sum += v * v;
          count++;
        }
        const rms = Math.sqrt(sum / Math.max(1, count));
        const y = amp + rms * amp * 0.9;
        ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = hexToRgba(acc2, 0.12);
      ctx.fill();

      // Peak outline
      const grad = ctx.createLinearGradient(0, 0, W, 0);
      grad.addColorStop(0, acc1);
      grad.addColorStop(1, acc2);
      ctx.strokeStyle = grad;
      ctx.lineWidth = Math.max(1, Math.floor(dpr));
      ctx.beginPath();
      for (let x = 0; x < W; x++) {
        const start = x * step;
        let min = 1, max = -1;
        for (let i = 0; i < step && start + i < samples; i++) {
          const v = data[start + i];
          if (v < min) min = v;
          if (v > max) max = v;
        }
        const y = amp + min * amp;
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      for (let x = W - 1; x >= 0; x--) {
        const start = x * step;
        let min = 1, max = -1;
        for (let i = 0; i < step && start + i < samples; i++) {
          const v = data[start + i];
          if (v < min) min = v;
          if (v > max) max = v;
        }
        const y = amp + max * amp;
        ctx.lineTo(x, y);
      }
      ctx.stroke();

      this.ctx = ctx; this.W = W; this.H = H; this.lastHead = null;
      this.drawHead(0);
    }

    drawHead(p) {
      if (!this.ctx) return;
      if (this.lastHead !== null) this.ctx.clearRect(this.lastHead - 1, 0, 2, this.H);
      const x = Math.floor(p * this.W);
      this.ctx.fillStyle = hexToRgba('#a0f5ff', 0.9);
      this.ctx.fillRect(x, 0, 1, this.H);
      this.lastHead = x;
    }

    toggle() { this.playing ? this.pause() : this.play(); }

    play() {
      if (!this.buffer) return;
      const ac = getAC();
      if (ac.state === 'suspended') ac.resume();
      PlayerBus.claim(this);
      this.source = ac.createBufferSource();
      this.source.buffer = this.buffer;
      this.source.connect(ac.destination);
      this.start = ac.currentTime;
      this.source.start(0, this.offset);
      this.playing = true;
      this.btn.setAttribute('aria-pressed', 'true');
      this.btn.setAttribute('aria-label', 'Pause preview');
      this.btn.innerHTML = ''; this.btn.appendChild(iconPause());
      this.raf = requestAnimationFrame(() => this.tick());
      this.source.onended = () => this.pause(true);
    }

    tick() {
      if (!this.playing) return;
      const now = getAC().currentTime;
      const prog = (now - this.start + this.offset) / this.buffer.duration;
      if (prog >= 1) { this.pause(true); return; }
      this.drawHead(prog);
      this.raf = requestAnimationFrame(() => this.tick());
    }

    pause(ended = false) {
      if (!this.playing) return;
      try { this.source.stop(); } catch {}
      this.source.disconnect();
      const ac = getAC();
      const now = ac.currentTime;
      this.offset = ended ? 0 : this.offset + (now - this.start);
      this.playing = false;
      cancelAnimationFrame(this.raf);
      this.btn.setAttribute('aria-pressed', 'false');
      this.btn.setAttribute('aria-label', 'Play preview');
      this.btn.innerHTML = ''; this.btn.appendChild(iconPlay());
      PlayerBus.release(this);
      this.drawHead(0);
    }
  }

  function svg(path) {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.innerHTML = `<path d="${path}"/>`;
    return s;
  }
  function iconPlay() { return svg('M8 5v14l11-7z'); }
  function iconPause() { return svg('M6 5h4v14H6zm8 0h4v14h-4z'); }
  function iconDownload() { return svg('M5 20h14v-2H5m7-14v9l3.5-3.5 1.42 1.42L12 19l-4.92-4.92L8.5 12.5 12 16V4z'); }
  function hexToRgba(hex, a) {
    hex = hex.trim();
    if (hex.startsWith('#')) hex = hex.slice(1);
    if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
    const num = parseInt(hex, 16);
    const r = (num >> 16) & 255, g = (num >> 8) & 255, b = num & 255;
    return `rgba(${r},${g},${b},${a})`;
  }

  function buildMetricsTable(metrics) {
    const table = document.createElement('table');
    table.className = 'pp-metrics';
    const thead = document.createElement('thead');
    const headTr = document.createElement('tr');
    const empty = document.createElement('th'); empty.className = 'row-label'; headTr.appendChild(empty);
    metrics.labelRow.forEach(lbl => {
      const th = document.createElement('th'); th.textContent = lbl; headTr.appendChild(th);
    });
    thead.appendChild(headTr); table.appendChild(thead);
    const tbody = document.createElement('tbody');
    if (metrics.input) {
      const tr = document.createElement('tr');
      const th = document.createElement('th'); th.textContent = 'Input'; th.className = 'row-label'; tr.appendChild(th);
      metrics.input.forEach(v => { const td = document.createElement('td'); td.className = 'value'; td.textContent = v; tr.appendChild(td); });
      tbody.appendChild(tr);
    }
    if (metrics.output) {
      const tr = document.createElement('tr');
      const th = document.createElement('th'); th.textContent = 'Output'; th.className = 'row-label'; tr.appendChild(th);
      metrics.output.forEach(v => { const td = document.createElement('td'); td.className = 'value'; td.textContent = v; tr.appendChild(td); });
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    return table;
  }

  function buildCard(session, cfg) {
    const art = document.createElement('article');
    art.className = 'pp-card';
    art.id = `card-${cfg.id}`;
    const h3 = document.createElement('h3'); h3.textContent = cfg.title; art.appendChild(h3);

    const wavewrap = document.createElement('div'); wavewrap.className = 'pp-wavewrap';
    const btn = document.createElement('button');
    btn.className = 'pp-play';
    btn.type = 'button';
    btn.setAttribute('aria-pressed', 'false');
    btn.setAttribute('aria-label', 'Play preview');
    wavewrap.appendChild(btn);
    const wave = document.createElement('div'); wave.className = 'pp-wave';
    const canvas = document.createElement('canvas');
    wave.appendChild(canvas); wavewrap.appendChild(wave);
    art.appendChild(wavewrap);

    art.appendChild(buildMetricsTable(cfg.metrics));

    const downloads = document.createElement('div'); downloads.className = 'pp-downloads';
    const wav = document.createElement('a'); wav.className = 'pp-dl'; wav.href = `/download/${session}/${cfg.wavKey}`; wav.appendChild(iconDownload()); wav.appendChild(document.createTextNode(' Download WAV'));
    const info = document.createElement('a'); info.className = 'pp-dl'; info.href = `/download/${session}/${cfg.infoKey}`; info.appendChild(iconDownload()); info.appendChild(document.createTextNode(' Download INFO'));
    downloads.appendChild(wav); downloads.appendChild(info); art.appendChild(downloads);

    new WaveformPlayer(btn, canvas, cfg.processedUrl);
    return art;
  }

  window.renderMasteringResults = function(session, cards, opts = {}) {
    const showCustom = !!opts.showCustom;
    const mount = document.getElementById('pp-results') || (() => {
      const s = document.createElement('section'); s.id = 'pp-results'; s.className = 'pp-results'; s.setAttribute('aria-live', 'polite');
      const ref = document.querySelector('.pp-fileinfo'); (ref?.parentNode || document.body).insertBefore(s, ref?.nextSibling || null);
      return s;
    })();
    mount.innerHTML = '';
    const order = ['club', 'stream', 'unlimited', 'custom'];
    order.forEach(id => {
      if (id === 'custom' && !showCustom) return;
      const cfg = cards.find(c => c.id === id);
      if (cfg) mount.appendChild(buildCard(session, cfg));
    });
  };
})();

