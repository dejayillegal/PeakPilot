
# Local Mastering Web App (Mac/Windows/Linux)

Create **Club**, **Streaming**, and **Unlimited Premaster** masters locally via a simple web UI.
- **Club**: 48 kHz / 24-bit, target **−7.5…−6.5 LUFS-I**, **TP ≤ −0.8 dBTP** (center at −7.2 LUFS)
- **Streaming**: 44.1 kHz / 24-bit, target **−10…−9 LUFS-I**, **TP ≤ −1.0 dBTP** (center at −9.5 LUFS)
- **Unlimited Premaster**: 48 kHz / 24-bit, **peaks ≈ −6.0 dBFS** (no limiter)

## Requirements
- Python 3.10+
- **FFmpeg** installed and available in your PATH (macOS: `brew install ffmpeg`)

## Install & Run
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
# Open http://127.0.0.1:5000
```

## Notes
- Uses ffmpeg **two-pass loudnorm** for accurate LUFS/True-Peak on Club/Streaming.
- Accepts **WAV / AIFF / FLAC** inputs. Outputs WAV 24-bit for maximum compatibility.
- Writes `*_INFO.txt` alongside each output with **Integrated LUFS, True Peak, LRA, Duration**.

## Troubleshooting
- If FFmpeg isn't found, install it and restart the app.
- If loudness seems off, the `loudnorm` targets are set to the **center** of the spec range; you can nudge in a DAW if needed.
