---
title: PeakPilot
emoji: 🎚️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

Notes
The server writes incremental progress and metrics to /tmp/peakpilot/<session>/progress.json. The UI polls /progress/<session> every second.

session.json includes version, selected preset, metrics, timeline arrays, and output checksums. It’s included in the ZIP and also separately downloadable.

Gain-matched A/B relies on integrated loudness values returned in progress JSON; the client computes per-preview volume multipliers and applies them when loading each source.

Timeline overlay is drawn on a canvas under the waveform using 1 Hz short-term LUFS and TP hotspots.

# PeakPilot

Local web UI for creating Club, Streaming, and Unlimited Premaster renders using ffmpeg.

## Features
- Multi-file processing queue with per-job UUID directories
- Two-pass loudnorm for Club (−7.2 LUFS, TP −0.8) and Streaming (−9.5 LUFS, TP −1.0)
- Unlimited premaster with peaks ≈ −6 dBFS
- INFO files and downloadable ZIP per job
- Theme toggle, advanced settings, `/healthz` endpoint

## Requirements
- Python 3.10+
- FFmpeg installed and available in your PATH

## Run
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```
Visit `http://127.0.0.1:5000`.

## Tests
```bash
pytest
```

## Docker
```bash
docker build -t peakpilot .
docker run -p 5000:5000 peakpilot
```

## Deploy (HF Spaces + Pages)

Backend: HF Space (Docker). Env: HOST=0.0.0.0, PORT=7860, ALLOWED_ORIGIN=https://dejayillegal.github.io/PeakPilot.

Frontend: GitHub Pages from /docs. /docs/config.js points to your Space.

Wake on access: Pages auto-polls /healthz (first request may take 5–20 s).

Local dev: python app.py → http://127.0.0.1:5000 (set /docs/config.js to localhost for dev).
