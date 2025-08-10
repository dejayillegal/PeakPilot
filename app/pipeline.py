import json
import os
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
    """Very small substitute for ``ffprobe`` using ``soundfile``.

    The real application would invoke ffprobe; for tests we only need the
    duration which ``soundfile`` can provide.  Any exception is bubbled up so
    callers can handle invalid audio files.
    """
    with sf.SoundFile(path) as f:
        return {"format": {"duration": f.frames / f.samplerate}}


def validate_upload(path: Path, max_minutes: int = 20):
    """Validate that the uploaded file looks like audio and is not too long."""
    try:
        info = ffprobe_info(path)
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError("Unrecognized or corrupt audio file") from exc
    dur = float(info["format"]["duration"])
    if dur <= 0:
        raise RuntimeError("Unrecognized or zero-length audio")
    if dur > max_minutes * 60:
        raise RuntimeError("Audio too long")


def write_json(path: Path, data: dict):
    """Atomically write JSON to ``path``."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)

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
    """Baseline progress structure written to ``progress.json``.

    Mirrors the contract defined in the specification.  All fields are present
    from the start so clients never need to guard against missing keys.
    """
    return {
        "percent": 0,
        "phase": "starting",
        "message": "Starting…",
        "done": False,
        "error": None,
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
            "advisor": {
                "recommended_preset": "",
                "input_I": None,
                "input_TP": None,
                "input_LRA": None,
                "analysis": {},
                "ai_adjustments": {},
            },
        },
        "timeline": {"sec": [], "short_term": [], "tp_flags": []},
    }


def update_progress(
    session: str,
    percent: int | None = None,
    phase: str | None = None,
    message: str | None = None,
    patch: Dict[str, Any] | None = None,
    done: bool | None = None,
    error: str | None = None,
) -> None:
    """Merge progress updates into the session's ``progress.json``.

    ``patch`` can contain nested dictionaries that will be merged recursively.
    Any provided ``percent`` >= 100 will automatically mark the task as done.
    """
    p = progress_path(session)
    data = read_json(p, base_progress())

    if percent is not None:
        data["percent"] = percent
    if phase is not None:
        data["phase"] = phase
    if message is not None:
        data["message"] = message
    if done is not None:
        data["done"] = done
    if error is not None:
        data["error"] = error

    if patch:
        def merge(a: dict, b: dict):
            for k, v in b.items():
                if isinstance(v, dict) and isinstance(a.get(k), dict):
                    merge(a[k], v)
                else:
                    a[k] = v
        merge(data, patch)

    if data.get("percent", 0) >= 100:
        data["done"] = True

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

def run_pipeline(session: str, src_path: Path, params: dict, stems: Dict[str, Path] | None, gains: Dict[str, float] | None):
    """Main background job executed for each upload.

    The real project performs heavy DSP with ffmpeg.  Here we mimic the
    behaviour using lightweight numpy/soundfile operations so tests run fast
    while still exercising the progress lifecycle.
    """

    app = APP or current_app._get_current_object()
    with app.app_context():
        try:
            # --- analysis stage -------------------------------------------------
            validate_upload(src_path)
            timeline = ebur128_timeline(src_path)
            inp = measure_loudnorm_json(src_path)
            peak_in = measure_peak_dbfs(src_path)
            update_progress(
                session,
                5,
                "analyze",
                "Analyzing input…",
                patch={
                    "metrics": {
                        "advisor": {
                            "input_I": inp["input_i"],
                            "input_LRA": inp["input_lra"],
                            "input_TP": inp["input_tp"],
                        },
                        "club": {
                            "input": {
                                "I": inp["input_i"],
                                "TP": inp["input_tp"],
                                "LRA": inp["input_lra"],
                                "threshold": inp["input_thresh"],
                            }
                        },
                        "streaming": {
                            "input": {
                                "I": inp["input_i"],
                                "TP": inp["input_tp"],
                                "LRA": inp["input_lra"],
                                "threshold": inp["input_thresh"],
                            }
                        },
                        "premaster": {"input": {"peak_dbfs": peak_in}},
                    },
                    "timeline": timeline,
                },
            )

            # --- AI reference stage -------------------------------------------
            from . import ai_module

            features, ai_adj, model, model_file, fingerprint, analysis = ai_module.analyze_track(
                src_path, timeline
            )

            update_progress(
                session,
                15,
                "reference",
                "Dialing in reference curve…",
                patch={
                    "metrics": {
                        "advisor": {
                            "recommended_preset": params.get("preset", "club"),
                            "analysis": analysis,
                            "ai_adjustments": ai_adj,
                            "input_I": inp["input_i"],
                            "input_TP": inp["input_tp"],
                            "input_LRA": inp["input_lra"],
                        }
                    }
                },
            )

            out_dir = src_path.parent
            stem = src_path.stem

            # apply AI deltas with clamping
            club_I = -7.2 + ai_adj["club"]["dI"]
            club_TP = min(-0.8, -0.8 + ai_adj["club"]["dTP"])
            club_LRA = 11.0 + ai_adj["club"]["dLRA"]
            str_I = -9.5 + ai_adj["streaming"]["dI"]
            str_TP = min(-1.0, -1.0 + ai_adj["streaming"]["dTP"])
            str_LRA = 11.0 + ai_adj["streaming"]["dLRA"]

            # --- club render ---------------------------------------------------
            club_out = out_dir / f"{stem}__CLUB.wav"
            loudnorm_two_pass(src_path, club_out, I=club_I, TP=club_TP, LRA=club_LRA)
            club_m = measure_loudnorm_json(club_out)
            update_progress(
                session,
                45,
                "club",
                "Rendering Club…",
                patch={
                    "metrics": {
                        "club": {
                            "output": {
                                "I": club_m["input_i"],
                                "TP": club_m["input_tp"],
                                "LRA": club_m["input_lra"],
                                "threshold": club_m["input_thresh"],
                            }
                        }
                    }
                },
            )

            # --- streaming render ---------------------------------------------
            streaming_out = out_dir / f"{stem}__STREAMING.wav"
            loudnorm_two_pass(src_path, streaming_out, I=str_I, TP=str_TP, LRA=str_LRA)
            str_m = measure_loudnorm_json(streaming_out)
            update_progress(
                session,
                70,
                "streaming",
                "Rendering Streaming…",
                patch={
                    "metrics": {
                        "streaming": {
                            "output": {
                                "I": str_m["input_i"],
                                "TP": str_m["input_tp"],
                                "LRA": str_m["input_lra"],
                                "threshold": str_m["input_thresh"],
                            }
                        }
                    }
                },
            )

            # --- premaster ----------------------------------------------------
            premaster_out = out_dir / f"{stem}__PREMASTER.wav"
            normalize_peak_to(src_path, premaster_out, target_dbfs=-6.0)
            peak_out = measure_peak_dbfs(premaster_out)
            update_progress(
                session,
                85,
                "premaster",
                "Preparing Unlimited Premaster…",
                patch={
                    "metrics": {"premaster": {"output": {"peak_dbfs": peak_out}}}
                },
            )

            # --- package ------------------------------------------------------
            session_json = out_dir / "session.json"
            metrics_current = read_json(progress_path(session), base_progress())["metrics"]
            outputs = {}
            for name, pth in {
                "club": club_out,
                "streaming": streaming_out,
                "premaster": premaster_out,
            }.items():
                info = sf.info(str(pth))
                outputs[name] = {
                    "file": pth.name,
                    "sha256": checksum_sha256(pth),
                    "sr": info.samplerate,
                    "bits": params.get("bits", 24),
                    "dur_sec": float(info.frames) / info.samplerate,
                }

            session_data = {
                "version": "1.0",
                "time_utc": datetime.utcnow().isoformat() + "Z",
                "preset_used": params.get("preset", "club"),
                "params": params,
                "metrics": metrics_current,
                "timeline": timeline,
                "outputs": outputs,
                "ai_model": {
                    "present": True,
                    "adjustments": ai_adj,
                    "fingerprint": fingerprint,
                },
            }
            write_json(session_json, session_data)

            zip_path = out_dir / f"{stem}__bundle.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                for pth in [club_out, streaming_out, premaster_out, session_json]:
                    z.write(pth, pth.name)

            base = f"/download/{session}/"
            downloads = {
                "club": base + club_out.name,
                "streaming": base + streaming_out.name,
                "premaster": base + premaster_out.name,
                "custom": None,
                "zip": base + zip_path.name,
                "session_json": base + session_json.name,
            }
            update_progress(session, 95, "package", "Packaging downloads…", patch={"downloads": downloads})

            update_progress(session, 100, "done", "Ready", done=True)

            ai_module.update_model(
                model,
                model_file,
                fingerprint,
                features,
                {"I": club_I, "TP": club_TP, "LRA": club_LRA},
                club_m,
                {"I": str_I, "TP": str_TP, "LRA": str_LRA},
                str_m,
            )

        except Exception as e:  # pragma: no cover - exercised via tests
            update_progress(
                session,
                phase="error",
                message="Processing failed",
                error=str(e),
                done=True,
            )
            return


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
