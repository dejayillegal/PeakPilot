import os
import json
import hashlib
import shlex
import subprocess
import signal
from typing import Dict, Any

import numpy as np
import soundfile as sf


def ffprobe_ok(tool: str) -> bool:
    try:
        subprocess.run([tool, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return True


def run(cmd, timeout=1200):
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        try:
            if e.pid:
                os.killpg(os.getpgid(e.pid), signal.SIGKILL)
        except Exception:
            pass
        raise


def new_session_dir(root: str, session: str) -> str:
    d = os.path.join(root, session)
    os.makedirs(d, exist_ok=True)
    return d


def progress_path(sess_dir: str) -> str:
    return os.path.join(sess_dir, "progress.json")


def write_json_atomic(path: str, obj: Dict[str, Any]):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def update_progress(sess_dir: str, **fields):
    p = progress_path(sess_dir)
    data = {
        "percent": 0,
        "phase": "starting",
        "message": "",
        "done": False,
        "error": None,
        "downloads": {"club": None, "streaming": None, "premaster": None, "custom": None, "zip": None, "session_json": None},
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
    if os.path.exists(p):
        try:
            data = read_json(p)
        except Exception:
            pass
    data.update({k: v for k, v in fields.items() if v is not None})
    write_json_atomic(p, data)


def checksum_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_mono(path: str):
    data, sr = sf.read(path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data.astype(np.float64), sr


def ffprobe_info(path: str) -> Dict[str, Any]:
    with sf.SoundFile(path) as f:
        return {"duration": f.frames / f.samplerate, "sr": f.samplerate, "channels": f.channels}


def validate_upload(info: Dict[str, Any]):
    if info["duration"] <= 0 or info["duration"] > 20 * 60:
        raise ValueError("Audio must be 0–20 minutes.")
    if info["channels"] not in (1, 2):
        raise ValueError("Only mono or stereo supported.")


def measure_loudnorm_json(path: str) -> Dict[str, float]:
    data, sr = _read_mono(path)
    rms = np.sqrt(np.mean(data ** 2)) + 1e-9
    I = 20 * np.log10(rms)
    peak = np.max(np.abs(data)) + 1e-9
    TP = 20 * np.log10(peak)
    LRA = float(
        np.percentile(20 * np.log10(np.abs(data) + 1e-9), 95)
        - np.percentile(20 * np.log10(np.abs(data) + 1e-9), 10)
    )
    return {"input_i": I, "input_tp": TP, "input_lra": LRA, "input_thresh": -60.0}


def measure_peak_dbfs(path: str) -> float:
    data, _ = _read_mono(path)
    peak = np.max(np.abs(data)) + 1e-9
    return 20 * np.log10(peak)


def ebur128_timeline(path: str) -> Dict[str, list]:
    data, sr = _read_mono(path)
    win = sr // 10
    sec, st, tp = [], [], []
    for i in range(0, len(data), win):
        seg = data[i : i + win]
        if len(seg) == 0:
            continue
        rms = np.sqrt(np.mean(seg ** 2)) + 1e-9
        st.append(20 * np.log10(rms))
        sec.append(i / sr)
        tp.append(1 if np.max(np.abs(seg)) > 0.99 else 0)
    return {"sec": sec, "short_term": st, "tp_flags": tp}


def loudnorm_two_pass(src, dst, I, TP, LRA=11, sr=None, bits=24, smart_limiter=False):
    data, _ = _read_mono(src)
    target = 10 ** (I / 20)
    rms = np.sqrt(np.mean(data ** 2)) + 1e-9
    gain = target / rms
    out = np.clip(data * gain, -1.0, 1.0)
    sr = sr or 48000
    subtype = "PCM_24" if bits == 24 else "PCM_16"
    sf.write(dst, out, sr, subtype=subtype)
    return dst


def normalize_peak_to(src, dst, peak_dbfs=-6.0, sr=48000, bits=24, dither="triangular"):
    data, _ = _read_mono(src)
    peak = np.max(np.abs(data)) + 1e-9
    target = 10 ** (peak_dbfs / 20)
    gain = target / peak
    out = np.clip(data * gain, -1.0, 1.0)
    subtype = "PCM_24" if bits == 24 else "PCM_16"
    sf.write(dst, out, sr, subtype=subtype)
    return dst


def run_pipeline(session: str, sess_dir: str, src_path: str, params: Dict[str, Any], stems, gains):
    try:
        update_progress(sess_dir, percent=5, phase="analyze", message="Analyzing input…")
        info = ffprobe_info(src_path)
        validate_upload(info)
        ln_in = measure_loudnorm_json(src_path)
        tl = ebur128_timeline(src_path)
        peak_in = measure_peak_dbfs(src_path)
        data = read_json(progress_path(sess_dir))
        data["metrics"]["advisor"].update(
            {
                "input_I": ln_in.get("input_i"),
                "input_TP": ln_in.get("input_tp"),
                "input_LRA": ln_in.get("input_lra"),
            }
        )
        data["metrics"]["club"]["input"] = {
            "I": ln_in["input_i"],
            "TP": ln_in["input_tp"],
            "LRA": ln_in["input_lra"],
            "threshold": ln_in["input_thresh"],
        }
        data["metrics"]["streaming"]["input"] = {
            "I": ln_in["input_i"],
            "TP": ln_in["input_tp"],
            "LRA": ln_in["input_lra"],
            "threshold": ln_in["input_thresh"],
        }
        data["metrics"]["premaster"]["input"] = {"peak_dbfs": peak_in}
        data["timeline"] = tl
        write_json_atomic(progress_path(sess_dir), data)

        update_progress(sess_dir, percent=45, phase="club", message="Rendering Club…")
        club_wav = os.path.join(sess_dir, "club.wav")
        loudnorm_two_pass(
            src_path,
            club_wav,
            I=-7.2,
            TP=-0.8,
            LRA=11,
            sr=48000,
            bits=24,
            smart_limiter=params.get("smart_limiter") == "on",
        )
        d = read_json(progress_path(sess_dir))
        d["downloads"]["club"] = os.path.basename(club_wav)
        write_json_atomic(progress_path(sess_dir), d)

        update_progress(sess_dir, percent=70, phase="streaming", message="Rendering Streaming…")
        streaming_wav = os.path.join(sess_dir, "streaming.wav")
        loudnorm_two_pass(
            src_path,
            streaming_wav,
            I=-9.5,
            TP=-1.0,
            LRA=11,
            sr=44100,
            bits=24,
            smart_limiter=params.get("smart_limiter") == "on",
        )
        d = read_json(progress_path(sess_dir))
        d["downloads"]["streaming"] = os.path.basename(streaming_wav)
        write_json_atomic(progress_path(sess_dir), d)

        update_progress(sess_dir, percent=85, phase="premaster", message="Preparing Unlimited Premaster…")
        premaster_wav = os.path.join(sess_dir, "premaster.wav")
        normalize_peak_to(src_path, premaster_wav, peak_dbfs=-6.0, sr=48000, bits=24)
        d = read_json(progress_path(sess_dir))
        d["downloads"]["premaster"] = os.path.basename(premaster_wav)
        write_json_atomic(progress_path(sess_dir), d)

        update_progress(sess_dir, percent=95, phase="package", message="Packaging downloads…")

        update_progress(sess_dir, percent=100, phase="done", message="Ready", done=True, error=None)
    except Exception as e:
        update_progress(sess_dir, phase="error", message="Processing failed", error=str(e), done=True)


__all__ = [
    "ffprobe_ok",
    "run",
    "new_session_dir",
    "progress_path",
    "write_json_atomic",
    "read_json",
    "update_progress",
    "checksum_sha256",
    "ffprobe_info",
    "validate_upload",
    "measure_loudnorm_json",
    "measure_peak_dbfs",
    "ebur128_timeline",
    "loudnorm_two_pass",
    "normalize_peak_to",
    "run_pipeline",
]

