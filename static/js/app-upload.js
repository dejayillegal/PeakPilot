(() => {
  // Helpers
  const $ = (s, el = document) => el.querySelector(s);
  const byId = id => document.getElementById(id);
  const fmtBytes = b => {
    if (!Number.isFinite(b) || b <= 0) return "0 B";
    const k = 1024, u = ["B","KB","MB","GB"];
    const i = Math.min(Math.floor(Math.log(b)/Math.log(k)), u.length-1);
    return (b/Math.pow(k,i)).toFixed(i ? 2 : 0) + " " + u[i];
  };
  const uuid = () => (crypto?.randomUUID?.() || Math.random().toString(16).slice(2)+Date.now().toString(16));

  // DOM
  const dz = byId("drop");
  const input = byId("file");
  const pick = byId("pick");
  const analyzeBtn = byId("pp-analyze");           // optional, enable on upload OK
  const info = $(".pp-fileinfo");                   // optional, for filename + progress UI
  const meta = info ? $(".pp-filemeta", info) : null;
  const bar = info ? $(".pp-fileprog .bar", info) : null;
  const err = byId("pp-error");                     // optional inline error

  if (!dz || !input) return; // nothing to do on pages without the dropzone

  // Session
  window.PeakPilot = window.PeakPilot || {};
  const state = {
    session: window.PeakPilot.session || uuid(),
    xhr: null,
    uploading: false,
    uploaded: false
  };
  window.PeakPilot.session = state.session;

  // Config
  const MAX_SIZE = 512 * 1024 * 1024; // 512MB
  const ALLOWED_EXT = new Set([".wav",".mp3",".flac",".aiff",".aif",".aac",".m4a",".ogg",".oga",".opus"]);

  // Accessibility status region (inline, invisible to sighted users)
  let status = byId("pp-upload-status");
  if (!status) {
    status = document.createElement("div");
    status.id = "pp-upload-status";
    status.className = "sr-only";
    status.setAttribute("aria-live","polite");
    dz.appendChild(status);
  }

  function setError(msg) {
    if (err) { err.textContent = msg || ""; err.hidden = !msg; }
    status.textContent = msg || "";
  }

  function setProgress(pct) {
    if (bar) {
      bar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    } else {
      // Fallback: animate dropzone background "progress"
      dz.style.setProperty("--dz-progress", `${Math.max(0, Math.min(100, pct))}%`);
      dz.dataset.progress = String(Math.floor(pct));
    }
  }

  function setMetaText(text) {
    if (meta) meta.textContent = text;
    status.textContent = text;
  }

  function disableAnalyze() { analyzeBtn && analyzeBtn.setAttribute("disabled","disabled"); }
  function enableAnalyze() { analyzeBtn && analyzeBtn.removeAttribute("disabled"); }

  function resetUI() {
    setProgress(0);
    dz.classList.remove("over","ok","uploading");
    dz.removeAttribute("aria-busy");
    if (info) info.dataset.state = "";
    state.uploading = false;
    state.uploaded = false;
    disableAnalyze();
  }

  function startUI(filename, size) {
    setError("");
    dz.classList.add("uploading");
    dz.setAttribute("aria-busy","true");
    if (info) info.dataset.state = "uploading";
    setMetaText(`${filename} • ${fmtBytes(size)}`);
    setProgress(0);
    disableAnalyze();
  }

  function doneUI() {
    dz.classList.remove("uploading");
    dz.removeAttribute("aria-busy");
    dz.classList.add("ok");
    if (info) info.dataset.state = "uploaded";
    setProgress(100);
    enableAnalyze();
  }

  function isAllowed(file) {
    if (!file) return false;
    if (file.size > MAX_SIZE) { setError(`File too large (${fmtBytes(file.size)}). Max 512 MB.`); return false; }
    const name = file.name || "";
    const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
    if (ALLOWED_EXT.has(ext)) return true;
    // Accept if MIME says audio/* even when extension is missing/odd
    if (file.type && file.type.startsWith("audio/")) return true;
    setError("Unsupported file type.");
    return false;
  }

  function abortInFlight() {
    if (state.xhr && state.uploading) {
      try { state.xhr.abort(); } catch {}
    }
  }

  async function uploadFile(file) {
    if (!isAllowed(file)) return;
    abortInFlight();
    startUI(file.name, file.size);
    state.uploading = true;

    const form = new FormData();
    form.append("session", state.session);
    form.append("reset", "1");
    form.append("file", file, file.name);

    const xhr = new XMLHttpRequest();
    state.xhr = xhr;

    xhr.open("POST", "/upload", true);

    xhr.upload.onprogress = (evt) => {
      if (!evt.lengthComputable) return;
      const pct = (evt.loaded / evt.total) * 100;
      setProgress(pct);
    };

    xhr.onload = () => {
      let res = {};
      try { res = JSON.parse(xhr.responseText || "{}"); } catch {}
      if (xhr.status >= 200 && xhr.status < 300 && res.ok) {
        state.session = res.session || state.session;
        window.PeakPilot.session = state.session;
        state.uploading = false;
        state.uploaded = true;
        doneUI();
      } else {
        const msg = res.error || `Upload error (${xhr.status})`;
        setError(msg);
        resetUI();
      }
    };

    xhr.onerror = () => {
      setError("Network error during upload.");
      resetUI();
    };

    xhr.send(form);
  }

  // Pick button
  if (pick) {
    pick.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      input.click();
    });
  }

  // Hidden input
  input.addEventListener("change", () => {
    const f = input.files && input.files[0];
    if (f) uploadFile(f);
  });

  // Keyboard: Enter/Space on dropzone opens input
  dz.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });

  // Drag-n-drop with enter/leave counter to avoid flicker
  let dragCounter = 0;

  const onDragEnter = (e) => {
    e.preventDefault(); e.stopPropagation();
    dragCounter++;
    dz.classList.add("over");
  };
  const onDragOver = (e) => {
    e.preventDefault(); e.stopPropagation();
    e.dataTransfer.dropEffect = "copy";
  };
  const onDragLeave = (e) => {
    e.preventDefault(); e.stopPropagation();
    dragCounter = Math.max(0, dragCounter - 1);
    if (dragCounter === 0) dz.classList.remove("over");
  };
  const onDrop = (e) => {
    e.preventDefault(); e.stopPropagation();
    dragCounter = 0;
    dz.classList.remove("over");
    const dt = e.dataTransfer;
    if (!dt) return;
    const files = dt.files && dt.files.length ? dt.files : null;
    if (files && files[0]) {
      uploadFile(files[0]); // one file only
    }
  };

  dz.addEventListener("dragenter", onDragEnter);
  dz.addEventListener("dragover", onDragOver);
  dz.addEventListener("dragleave", onDragLeave);
  dz.addEventListener("drop", onDrop);

  // Prevent the browser from opening files when dropped outside the zone
  ["dragover","drop"].forEach(ev => {
    document.addEventListener(ev, (e) => {
      if (!e.target.closest || !e.target.closest("#drop")) {
        e.preventDefault();
      }
    });
  });

  // Public hook: call this if you programmatically want to send a File
  window.PeakPilot.handleUploadFile = uploadFile;
})();
