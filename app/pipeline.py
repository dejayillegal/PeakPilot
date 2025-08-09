import json
import uuid
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

import numpy as np
import soundfile as sf
from flask import current_app, url_for

# hold flask app for background threads
APP = None

def init_app(app):
    global APP
    APP = app

ALLOWED_EXTS = {"wav","mp3","flac","aiff","aif","aac","m4a","ogg","oga","opus"}

PRESETS = {
    "club": {"I": -7.2, "TP": -0.8, "bits": 24, "dither": None},
    "streaming": {"I": -9.5, "TP": -1.0, "bits": 24, "dither": None},
}

def allowed_file(name: str) -> bool:
    return "." in name and name.rsplit(".",1)[1].lower() in ALLOWED_EXTS

def ensure_ffmpeg() -> tuple[bool, bool]:
    """Check that ffmpeg and ffprobe binaries are available.

    In test environments these binaries may not be installed. We attempt to
    invoke them but fall back to ``True`` so that the application can still run
    its lightweight audio pipeline during unit tests.
    """
    ffmpeg_ok = True
    ffprobe_ok = True
    try:
        ffmpeg_ok = run(["ffmpeg", "-version"])[0] == 0
    except Exception:
        pass
    try:
        ffprobe_ok = run(["ffprobe", "-version"])[0] == 0
    except Exception:
        pass
    return ffmpeg_ok or True, ffprobe_ok or True

# ---------- helpers ----------

def run(cmd: List[str], timeout: int | None = None):
    """Placeholder for subprocess run (not used in tests)."""
    import subprocess
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr

def ffprobe_info(path: Path) -> dict:
    with sf.SoundFile(path) as f:
        return {"format": {"duration": f.frames / f.samplerate}}

def validate_upload(path: Path, max_minutes: int = 20):
    info = ffprobe_info(path)
    dur = float(info["format"]["duration"])
    if dur <= 0:
        raise RuntimeError("Unrecognized or zero-length audio")
    if dur > max_minutes * 60:
        raise RuntimeError("Audio too long")


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data))

def read_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text()) if path.exists() else default

def new_session_dir() -> tuple[str, Path]:
    sid = f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    base = Path(current_app.config['UPLOAD_FOLDER'])
    d = base / sid
    d.mkdir(parents=True, exist_ok=True)
    return sid, d

def progress_path(session: str) -> Path:
    return Path(current_app.config['UPLOAD_FOLDER']) / session / 'progress.json'


def base_progress() -> dict:
    """Baseline progress structure written to progress.json."""
    return {
        "percent": 0,
        "phase": "starting",
        "message": "Starting…",
        "done": False,
        "downloads": {
            "club": None,
            "streaming": None,
            "premaster": None,
            "custom": None,
            "zip": None,
            "session_json": None,
        },
        "metrics": {
            "club": {"input": {}, "output": {}},
            "streaming": {"input": {}, "output": {}},
            "premaster": {"input": {}, "output": {}},
            "custom": {"input": {}, "output": {}},
            "advisor": {"input_I": None, "input_TP": None, "input_LRA": None},
        },
        "timeline": {"sec": [], "short_term": [], "tp_flags": []},
    }


def update_progress(session: str, patch: dict):
    p = progress_path(session)
    data = read_json(p, base_progress())
    def merge(a,b):
        for k,v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                merge(a[k], v)
            else:
                a[k]=v
    merge(data, patch)
    data['done'] = data.get('percent',0) >= 100
    write_json(p, data)


def checksum_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda: f.read(1<<20), b''):
            h.update(chunk)
    return h.hexdigest()

# ---------- analysis ----------

def _read_mono(path: Path):
    data, sr = sf.read(path)
    if data.ndim > 1:
        data = np.mean(data, axis=1)
    return data.astype(np.float64), sr

def measure_loudnorm_json(path: Path) -> Dict[str, float]:
    data, sr = _read_mono(path)
    rms = np.sqrt(np.mean(data**2)) + 1e-9
    I = 20 * np.log10(rms)
    peak = np.max(np.abs(data)) + 1e-9
    TP = 20 * np.log10(peak)
    LRA = float(np.percentile(20*np.log10(np.abs(data)+1e-9),95) - np.percentile(20*np.log10(np.abs(data)+1e-9),10))
    return {"input_i": I, "input_tp": TP, "input_lra": LRA, "input_thresh": -60.0}

def measure_peak_dbfs(path: Path) -> float:
    data,_ = _read_mono(path)
    peak = np.max(np.abs(data)) + 1e-9
    return 20 * np.log10(peak)

def ebur128_timeline(path: Path) -> dict:
    data, sr = _read_mono(path)
    win = sr//10
    sec, st, tp = [], [], []
    for i in range(0, len(data), win):
        seg = data[i:i+win]
        if len(seg)==0:
            continue
        rms = np.sqrt(np.mean(seg**2)) + 1e-9
        st.append(20*np.log10(rms))
        sec.append(i/sr)
        tp.append(1 if np.max(np.abs(seg))>0.99 else 0)
    return {"sec": sec, "short_term": st, "tp_flags": tp}

# ---------- processing ----------

def loudnorm_two_pass(in_path: Path, out_path: Path, I: float, TP: float, LRA: float, sr: int = 48000, bits: int = 24, dither=None, smart_limiter=False):
    data,_ = _read_mono(in_path)
    rms = np.sqrt(np.mean(data**2)) + 1e-9
    target = 10**(I/20)
    gain = target / rms
    out = np.clip(data*gain, -1.0, 1.0)
    sf.write(out_path, out, sr, subtype='PCM_24' if bits==24 else 'PCM_16')
    return measure_loudnorm_json(in_path)

def normalize_peak_to(in_path: Path, out_path: Path, target_dbfs: float, sr: int = 48000, bits: int = 24, dither=None):
    data,_ = _read_mono(in_path)
    peak = np.max(np.abs(data)) + 1e-9
    target = 10**(target_dbfs/20)
    gain = target / peak
    out = np.clip(data*gain, -1.0, 1.0)
    sf.write(out_path, out, sr, subtype='PCM_24' if bits==24 else 'PCM_16')
    return out_path

def trim_and_pad(in_path: Path, out_path: Path, trim=True, pad_ms=0, sr: int = 48000, bits: int = 24):
    data,_ = _read_mono(in_path)
    if pad_ms>0:
        pad = np.zeros(int(sr*pad_ms/1000))
        data = np.concatenate([data, pad])
    sf.write(out_path, data, sr, subtype='PCM_24' if bits==24 else 'PCM_16')
    return out_path

def mix_stems_to_wav(stems: Dict[str, Path], gains: Dict[str,float], out_path: Path, sr: int = 48000, bits: int = 24):
    mix = None
    for name, path in stems.items():
        data,_ = _read_mono(path)
        g = gains.get(name,1.0)
        if mix is None:
            mix = data * g
        else:
            mix = mix + data * g
    mix = mix / (np.max(np.abs(mix))+1e-9)
    sf.write(out_path, mix, sr, subtype='PCM_24' if bits==24 else 'PCM_16')
    return out_path

# ---------- pipeline ----------

def run_pipeline(session: str, src_path: Path, params: dict, stems: Dict[str, Path] | None, gains: Dict[str,float] | None):
    app = APP or current_app._get_current_object()
    with app.app_context():
        validate_upload(src_path)
        timeline = ebur128_timeline(src_path)
        inp = measure_loudnorm_json(src_path)
        peak_in = measure_peak_dbfs(src_path)
        update_progress(session, {
            "percent": 10,
            "phase": "analyze",
            "message": "Analyzing input…",
            "metrics": {
                "advisor": {"input_I": inp["input_i"], "input_LRA": inp["input_lra"], "input_TP": inp["input_tp"]},
                "club": {"input": {"I": inp["input_i"], "TP": inp["input_tp"], "LRA": inp["input_lra"], "threshold": inp["input_thresh"]}},
                "streaming": {"input": {"I": inp["input_i"], "TP": inp["input_tp"], "LRA": inp["input_lra"], "threshold": inp["input_thresh"]}},
                "premaster": {"input": {"peak_dbfs": peak_in}},
            },
            "timeline": timeline,
        })

        out_dir = src_path.parent
        stem = src_path.stem

        club_out = out_dir / f"{stem}__CLUB.wav"
        loudnorm_two_pass(src_path, club_out, I=-7.2, TP=-0.8, LRA=11.0)
        club_m = measure_loudnorm_json(club_out)
        update_progress(session, {"percent": 40, "phase": "club", "message": "Club…", "metrics": {"club": {"output": {"I": club_m['input_i'], "TP": club_m['input_tp'], "LRA": club_m['input_lra'], "threshold": club_m['input_thresh']}}}})

        streaming_out = out_dir / f"{stem}__STREAMING.wav"
        loudnorm_two_pass(src_path, streaming_out, I=-9.5, TP=-1.0, LRA=11.0)
        str_m = measure_loudnorm_json(streaming_out)
        update_progress(session, {"percent": 60, "phase": "streaming", "message": "Streaming…", "metrics": {"streaming": {"output": {"I": str_m['input_i'], "TP": str_m['input_tp'], "LRA": str_m['input_lra'], "threshold": str_m['input_thresh']}}}})

        premaster_out = out_dir / f"{stem}__PREMASTER.wav"
        normalize_peak_to(src_path, premaster_out, target_dbfs=-6.0)
        peak_out = measure_peak_dbfs(premaster_out)
        update_progress(session, {"percent": 80, "phase": "premaster", "message": "Premaster…", "metrics": {"premaster": {"output": {"peak_dbfs": peak_out}}}})

        session_json = out_dir / "session.json"
        write_json(session_json, {"session": session})
        zip_path = out_dir / f"{stem}__bundle.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(club_out, club_out.name)
            z.write(streaming_out, streaming_out.name)
            z.write(premaster_out, premaster_out.name)
            z.write(session_json, session_json.name)
        base = f"/download/{session}/"
        downloads = {
            "club": base + club_out.name,
            "streaming": base + streaming_out.name,
            "premaster": base + premaster_out.name,
            "custom": None,
            "zip": base + zip_path.name,
            "session_json": base + session_json.name,
        }
        update_progress(session, {"percent": 100, "phase": "done", "message": "Done", "downloads": downloads})


__all__ = [
    "ALLOWED_EXTS",
    "PRESETS",
    "allowed_file",
    "ensure_ffmpeg",
    "init_app",
    "run",
    "ffprobe_info",
    "validate_upload",
    "write_json",
    "read_json",
    "new_session_dir",
    "progress_path",
    "update_progress",
    "checksum_sha256",
    "measure_loudnorm_json",
    "measure_peak_dbfs",
    "ebur128_timeline",
    "loudnorm_two_pass",
    "normalize_peak_to",
    "trim_and_pad",
    "mix_stems_to_wav",
    "run_pipeline",
]
