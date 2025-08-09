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
