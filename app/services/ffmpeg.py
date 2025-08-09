import json
import subprocess
from pathlib import Path
from typing import Dict

from .loudness import loudnorm_scan, measure_sample_peak_dbfs
from ..models import specs


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def ffmpeg_version() -> str | None:
    try:
        proc = run(["ffmpeg", "-version"])
    except FileNotFoundError:
        return None
    if proc.returncode == 0:
        return proc.stdout.splitlines()[0]
    return None


def two_pass_loudnorm(in_path: Path, spec: specs.LoudnormSpec, out_path: Path) -> Dict:
    m = loudnorm_scan(in_path)
    if not m:
        raise RuntimeError("Failed to measure loudness")
    params = {
        "I": spec.I,
        "TP": spec.TP,
        "LRA": spec.LRA,
        "measured_I": m.get("input_i"),
        "measured_TP": m.get("input_tp"),
        "measured_LRA": m.get("input_lra"),
        "measured_thresh": m.get("input_thresh"),
        "offset": m.get("target_offset"),
        "linear": "true",
        "dual_mono": "true",
        "print_format": "json",
    }
    filt = "loudnorm=" + ":".join(f"{k}={v}" for k, v in params.items())
    cmd2 = [
        "ffmpeg",
        "-y",
        "-nostats",
        "-hide_banner",
        "-i",
        str(in_path),
        "-filter:a",
        filt,
        "-ar",
        str(spec.sr),
        "-af",
        "aresample=resampler=soxr",
        "-c:a",
        "pcm_s24le",
        str(out_path),
    ]
    proc = run(cmd2)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    post = loudnorm_scan(out_path) or {}
    duration = probe_duration(out_path)
    return {
        "integrated_lufs": post.get("input_i"),
        "true_peak_dbTP": post.get("input_tp"),
        "lra": post.get("input_lra"),
        "duration_s": duration,
    }


def probe_duration(path: Path) -> str:
    proc = run([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    if proc.returncode == 0:
        return proc.stdout.strip()
    return ""


def unlimited_premaster(in_path: Path, out_path: Path) -> Dict:
    peak = measure_sample_peak_dbfs(in_path)
    gain_db = -6.0 if peak is None else -6.0 - peak
    cmd = [
        "ffmpeg",
        "-y",
        "-nostats",
        "-hide_banner",
        "-i",
        str(in_path),
        "-filter:a",
        f"volume={gain_db:.3f}dB",
        "-ar",
        "48000",
        "-af",
        "aresample=resampler=soxr",
        "-c:a",
        "pcm_s24le",
        str(out_path),
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    post = loudnorm_scan(out_path) or {}
    dur = probe_duration(out_path)
    peak_post = measure_sample_peak_dbfs(out_path)
    return {
        "sample_peak_dbfs": peak_post,
        "integrated_lufs": post.get("input_i"),
        "true_peak_dbTP": post.get("input_tp"),
        "lra": post.get("input_lra"),
        "duration_s": dur,
    }
