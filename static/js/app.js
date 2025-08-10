(() => {
  const qs = (s, el = document) => el.querySelector(s);
  const byId = id => document.getElementById(id);
  const fmtBytes = b => {
    if (b === 0 || !Number.isFinite(b)) return "0 B";
    const k = 1024, sizes = ["B","KB","MB","GB"];
    const i = Math.min(Math.floor(Math.log(b)/Math.log(k)), sizes.length-1);
    return (b/Math.pow(k,i)).toFixed(i ? 2 : 0) + " " + sizes[i];
  };
  const enable = el => el.removeAttribute("disabled");
  const disable = el => el.setAttribute("disabled", "disabled");

  const fileInput = byId("pp-file");
  const chooseBtn = byId("pp-choose");
  const analyzeBtn = byId("pp-analyze");
  const info = qs(".pp-fileinfo");
  const meta = qs(".pp-filemeta", info);
  const bar = qs(".pp-fileprog .bar", info);
  const err = byId("pp-error");

  const state = {
    session: null,
    uploaded: false,
    uploading: false,
    filename: null,
    size: 0
  };

  function setError(msg) {
    err.textContent = msg || "";
    err.hidden = !msg;
  }

  function setProgress(pct) {
    bar.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  }

  chooseBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    setError("");
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    state.uploaded = false;
    state.uploading = true;
    disable(analyzeBtn);
    info.dataset.state = "uploading";
    setProgress(0);
    meta.textContent = `${file.name} • ${fmtBytes(file.size)}`;

    uploadFile(file).catch(e => {
      setError(e.message || "Upload failed");
      resetUploadUI();
    });
  });

  async function uploadFile(file) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      if (!state.session) state.session = crypto.randomUUID();
      form.append("session", state.session);
      form.append("file", file, file.name);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/upload", true);

      xhr.upload.onprogress = (evt) => {
        if (!evt.lengthComputable) return;
        const pct = (evt.loaded / evt.total) * 100;
        setProgress(pct);
      };

      xhr.onload = () => {
        try {
          const res = JSON.parse(xhr.responseText || "{}");
          if (xhr.status >= 200 && xhr.status < 300 && res.ok) {
            state.uploaded = true;
            state.uploading = false;
            state.filename = res.filename;
            state.size = res.size;
            info.dataset.state = "uploaded";
            setProgress(100);
            enable(analyzeBtn);
            resolve(res);
          } else {
            reject(new Error(res.error || `Upload error (${xhr.status})`));
          }
        } catch {
          reject(new Error(`Upload error (${xhr.status})`));
        }
      };

      xhr.onerror = () => reject(new Error("Network error during upload"));
      xhr.send(form);
    });
  }

  function resetUploadUI() {
    state.uploaded = false;
    state.uploading = false;
    info.dataset.state = "";
    setProgress(0);
    disable(analyzeBtn);
  }

  analyzeBtn.addEventListener("click", async () => {
    setError("");
    if (!state.uploaded || !state.session) {
      setError("Please upload a file first.");
      return;
    }
    disable(analyzeBtn);
    showAnalyzingModal(true);

    try {
      const r = await fetch("/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: state.session })
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Failed to start processing");
      pollProgress(state.session);
    } catch (e) {
      showAnalyzingModal(false);
      setError(e.message);
      enable(analyzeBtn);
    }
  });

  function showAnalyzingModal(isOpen) {
    document.body.dataset.analyzing = isOpen ? "true" : "false";
  }

  function pollProgress(session) {
    const iv = setInterval(async () => {
      try {
        const r = await fetch(`/progress/${session}`);
        const j = await r.json();
        if (j.done) {
          clearInterval(iv);
          showAnalyzingModal(false);
          if (j.error || j.phase === "error") {
            setError(j.error || "Processing failed");
          }
          enable(analyzeBtn);
        }
      } catch (e) {
        clearInterval(iv);
        showAnalyzingModal(false);
        setError("Lost connection while polling progress");
        enable(analyzeBtn);
      }
    }, 900);
  }
})();

