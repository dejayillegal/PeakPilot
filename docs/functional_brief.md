# PeakPilot Functional Brief

PeakPilot is a lightweight mastering front-end designed for offline use in Hugging Face Spaces.

## Flow
1. **Upload** audio via drag-and-drop.
2. **Analyze** – server measures loudness/peaks and extracts features. A tiny AI model suggests micro‑adjustments.
3. **Master** – renders Club, Streaming and Unlimited Premaster versions (plus optional custom preset).
4. **Preview & Download** – gain-matched A/B player with waveform and loudness timeline. All renders and `session.json` are downloadable individually or as a ZIP.

## Safety
- `ffprobe` validation and duration limit (20 min).
- Each render verified and checksummed (`sha256`).
- Temporary files atomically renamed only after successful ffmpeg passes.

## AI Module
- Extracts spectral/dynamic features (RMS, centroid, rolloff, 32‑band energy, etc.).
- `SGDRegressor` predicts small deltas to loudness/peak targets (clamped). Learns per‑track over repeated runs and stores models under `/tmp/peakpilot/models/`.
- Adjustments never exceed TP safety limits (−0.8 dBTP Club, −1.0 dBTP Streaming).

## Endpoints
- `/start` – begin job (multipart form).
- `/progress/<session>` – poll for JSON status.
- `/download/<session>/<file>` – retrieve renders or session bundle.
- `/healthz` – readiness probe.

