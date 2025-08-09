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

session.json includes version, selected preset, metrics, timeline arrays, AI adjustment info, and output checksums. It’s included in the ZIP and also separately downloadable.

Gain-matched A/B relies on integrated loudness values returned in progress JSON; the client computes per-preview volume multipliers and applies them when loading each source.

Timeline overlay is drawn on a canvas under the waveform using 1 Hz short-term LUFS and TP hotspots.

# PeakPilot

Local web UI for creating Club, Streaming, and Unlimited Premaster renders using ffmpeg. A lightweight AI module analyzes each track and fine-tunes loudness/peak targets for improved accuracy.

## Features
- Two-pass loudnorm for Club (−7.2 LUFS, TP −0.8) and Streaming (−9.5 LUFS, TP −1.0) with adaptive micro‑adjustments
- Unlimited premaster with peaks ≈ −6 dBFS
- Gain-matched A/B preview with waveform and loudness timeline overlay
- Per-job session.json with checksums and metrics; downloadable ZIP bundle
- `/healthz` endpoint for container readiness

## Requirements
- Python 3.11+
- FFmpeg/ffprobe available in PATH

Install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run with gunicorn (port 7860):
```bash
gunicorn -w 2 -k gthread -t 300 -b 0.0.0.0:7860 app.__init__:create_app()
```

## Tests
```bash
pytest
```

## Docker
```bash
docker build -t peakpilot .
docker run -p 7860:7860 peakpilot
```

## Deploy (HF Spaces + Pages)

Backend: HF Space (Docker). Env: HOST=0.0.0.0, PORT=7860, ALLOWED_ORIGIN=https://dejayillegal.github.io/PeakPilot.

Frontend: GitHub Pages from /docs. /docs/config.js points to your Space.

Wake on access: Pages auto-polls /healthz (first request may take 5–20 s).

Local dev: run the gunicorn command above and set /docs/config.js to localhost for dev.
