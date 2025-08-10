(() => {
  const canvas = document.getElementById('orb');
  if (!canvas) return;
  let ctx = null;
  let raf = null;
  let ro = null;

  function resize() {
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
  }

  function draw(ts) {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);
    const t = (ts / 1000) % (Math.PI * 2);
    const r = Math.min(w, h) / 2 - 4;
    ctx.lineWidth = 2;
    ctx.strokeStyle = 'rgba(0,0,0,0.35)';
    ctx.beginPath();
    ctx.arc(w / 2, h / 2, r, t, t + Math.PI * 1.5);
    ctx.stroke();
    raf = requestAnimationFrame(draw);
  }

  function start() {
    stop();
    ctx = canvas.getContext('2d', { alpha: true });
    resize();
    raf = requestAnimationFrame(draw);
    ro = new ResizeObserver(() => requestAnimationFrame(resize));
    ro.observe(canvas);
  }

  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = null;
    if (ro) ro.disconnect();
    ro = null;
    ctx = null;
  }

  function toggle(open) {
    if (open) start(); else stop();
  }

  const prev = window.showAnalyzingModal;
  window.showAnalyzingModal = function (open) {
    toggle(open);
    if (prev) prev(open);
  };

  const mo = new MutationObserver(() => {
    const v = document.body.dataset.analyzing;
    toggle(v === '1' || v === 'true');
  });
  mo.observe(document.body, { attributes: true, attributeFilter: ['data-analyzing'] });
})();

