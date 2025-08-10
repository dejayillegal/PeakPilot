title: PeakPilot
emoji: 🎚️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# PeakPilot

PeakPilot is a small Flask + Gunicorn app that masters an uploaded track into three versions using FFmpeg:

- **Club** – 48 kHz/24-bit, target −7.2 LUFS and −0.8 dBTP
- **Streaming** – 44.1 kHz/24-bit, target −9.5 LUFS and −1.0 dBTP
- **Unlimited Premaster** – 48 kHz/24-bit with peaks around −6 dBFS

Uploads are stored in per‑session folders under `sessions/`. Processing progress is written to `progress.json` so the frontend can poll `/progress/<session>` once per second. When finished a `manifest.json` lists every downloadable file with size and SHA256 so `/download/<session>/<key>` can verify integrity before sending.

## API

- `POST /upload` – multipart form with `file`. Optional `session` and `reset=1` to replace an existing upload. Returns `{ok, session, filename, size}`.
- `POST /start` – JSON `{session}`. Launches background mastering thread.
- `GET /progress/<session>` – current progress JSON.
- `GET /download/<session>/<key>` – serves a file listed in `manifest.json` after verifying the SHA256.
- `POST /clear` – JSON `{session}`. Deletes the entire session folder.
- `GET /healthz` – simple readiness check for FFmpeg/ffprobe.

## Requirements

- Python 3.11+
- FFmpeg/ffprobe available in `PATH`

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run with Gunicorn on port 7860:

```bash
gunicorn -w 2 -k gthread -t 300 -b 0.0.0.0:7860 app.__init__:create_app()
```

## Tests

```bash
pytest
```
