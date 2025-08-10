"""Mastering engine helpers.

This module runs the heavy lifting using FFmpeg.  It performs a two-pass
loudness normalisation for "club" and "streaming" masters, a simple peak set for
the unlimited premaster and writes all outputs atomically.  Errors from FFmpeg
are surfaced with meaningful messages so the UI can react gracefully.
"""

from __future__ import annotations

import json
import os
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List

import numpy as np
import soundfile as sf
from scipy.signal import resample

from ..util_fs import (
    write_json_atomic,
    write_manifest,
    write_progress,
    sha256_file,
    get_input_path,
)

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def run_ffmpeg(args: List[str]) -> subprocess.CompletedProcess:
    """Run ffmpeg with ``args`` and return the CompletedProcess.

    Raises ``RuntimeError`` with the tail of stderr when ffmpeg exits with
    non‑zero status.
    """
    if not HAVE_FFMPEG:
        raise RuntimeError("ffmpeg not installed")
    proc = subprocess.run([
        "ffmpeg",
        "-y",
        *args,
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or "")[-400:]
        raise RuntimeError(f"ffmpeg failed: {err}")
    return proc


def write_via_tmp(out_path: Path, ffmpeg_args: List[str]) -> subprocess.CompletedProcess:
    """Invoke ffmpeg writing to ``out_path`` via ``.part`` then atomically move."""

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    part = out_path.with_suffix(out_path.suffix + ".part")
    proc = run_ffmpeg([*ffmpeg_args, str(part)])
    if not part.exists() or part.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced no output")
    os.replace(part, out_path)
    return proc


def _parse_ffmpeg_json(text: str) -> Dict:
    idx = text.rfind("{")
    if idx == -1:
        return {}
    try:
        return json.loads(text[idx:])
    except Exception:
        return {}


def _analyze_loudness(inp: str, target_i: float, target_tp: float) -> Dict:
    if not HAVE_FFMPEG:
        data, sr = sf.read(inp)
        peak = float(np.max(np.abs(data)) + 1e-9)
        return {
            "input_i": 0.0,
            "input_tp": 20 * np.log10(peak),
            "input_lra": 0.0,
            "input_thresh": 0.0,
            "target_offset": 0.0,
        }
    af = f"loudnorm=I={target_i}:LRA=11:TP={target_tp}:print_format=json"
    proc = run_ffmpeg(["-i", inp, "-af", af, "-f", "null", "-"])
    return _parse_ffmpeg_json(proc.stderr + proc.stdout)


def _render_loudnorm(
    inp: str,
    out_path: Path,
    target_i: float,
    target_tp: float,
    sr: int,
    meas: Dict,
) -> Dict:
    """Render loudnorm pass using prior ``meas`` measurement."""

    if not HAVE_FFMPEG:
        data, sr_in = sf.read(inp)
        if sr_in != sr:
            n = int(len(data) * sr / sr_in)
            if data.ndim == 1:
                data = resample(data, n)
            else:
                data = np.vstack([resample(data[:, i], n) for i in range(data.shape[1])]).T
        peak = np.max(np.abs(data)) + 1e-9
        gain = (10 ** (target_tp / 20.0)) / peak
        out_data = data * gain
        part = str(out_path) + ".part"
        sf.write(part, out_data, sr, subtype='PCM_24', format='WAV')
        os.replace(part, out_path)
        return {
            "input": {"I": 0.0, "TP": 20 * np.log10(peak), "LRA": 0.0, "threshold": 0.0},
            "output": {"I": target_i, "TP": target_tp, "LRA": 0.0, "threshold": 0.0},
        }

    def build_af(m: Dict) -> str:
        return (
            "loudnorm=I={ti}:LRA=11:TP={tt}:"
            "measured_I={mi}:measured_LRA={ml}:"
            "measured_TP={mtp}:measured_thresh={mth}:"
            "offset={off}:linear=true:print_format=json"
        ).format(
            ti=target_i,
            tt=target_tp,
            mi=m.get("input_i"),
            ml=m.get("input_lra"),
            mtp=m.get("input_tp"),
            mth=m.get("input_thresh"),
            off=m.get("target_offset", 0),
        )

    proc = write_via_tmp(
        out_path,
        [
            "-i",
            inp,
            "-af",
            build_af(meas),
            "-ar",
            str(sr),
            "-c:a",
            "pcm_s24le",
        ],
    )
    out_meta = _parse_ffmpeg_json(proc.stderr + proc.stdout)
    # optional micro correction
    if (
        abs(out_meta.get("output_i", 0) - target_i) > 0.3
        or abs(out_meta.get("output_tp", 0) - target_tp) > 0.2
    ):
        meas2 = _analyze_loudness(str(out_path), target_i, target_tp)
        proc = write_via_tmp(
            out_path,
            [
                "-i",
                str(out_path),
                "-af",
                build_af(meas2),
                "-ar",
                str(sr),
                "-c:a",
                "pcm_s24le",
            ],
        )
        out_meta = _parse_ffmpeg_json(proc.stderr + proc.stdout)

    metrics = {
        "input": {
            "I": float(meas.get("input_i", 0.0)),
            "TP": float(meas.get("input_tp", 0.0)),
            "LRA": float(meas.get("input_lra", 0.0)),
            "threshold": float(meas.get("input_thresh", 0.0)),
        },
        "output": {
            "I": float(out_meta.get("output_i", 0.0)),
            "TP": float(out_meta.get("output_tp", 0.0)),
            "LRA": float(out_meta.get("output_lra", 0.0)),
            "threshold": float(out_meta.get("target_offset", 0.0)),
        },
    }
    return metrics


def _true_peak_dbfs(path: str) -> float:
    if not HAVE_FFMPEG:
        data, _ = sf.read(path)
        return float(20 * np.log10(np.max(np.abs(data)) + 1e-9))
    proc = run_ffmpeg(["-i", path, "-af", "volumedetect", "-f", "null", "-"])
    txt = proc.stderr + proc.stdout
    for line in txt.splitlines():
        if "max_volume" in line:
            try:
                return float(line.split(":")[1].split(" ")[1])
            except Exception:
                pass
    return 0.0


def _set_sample_peak(inp: str, out_path: Path, peak_dbfs: float = -6.0, sr: int = 48000) -> Dict:
    in_peak = _true_peak_dbfs(inp)
    if not HAVE_FFMPEG:
        data, sr_in = sf.read(inp)
        if sr_in != sr:
            n = int(len(data) * sr / sr_in)
            if data.ndim == 1:
                data = resample(data, n)
            else:
                data = np.vstack([resample(data[:, i], n) for i in range(data.shape[1])]).T
        gain = 10 ** ((peak_dbfs - in_peak) / 20.0)
        out_data = np.clip(data * gain, -1.0, 1.0)
        part = str(out_path) + ".part"
        sf.write(part, out_data, sr, subtype='PCM_24', format='WAV')
        os.replace(part, out_path)
    else:
        gain = peak_dbfs - in_peak
        write_via_tmp(
            out_path,
            [
                "-i",
                inp,
                "-af",
                f"volume={gain}dB,alimiter=limit=0.0",
                "-ar",
                str(sr),
                "-c:a",
                "pcm_s24le",
            ],
        )
    out_peak = _true_peak_dbfs(str(out_path))
    return {
        "input": {"peak_dbfs": in_peak},
        "output": {"peak_dbfs": out_peak},
    }


def run_mastering(session_dir: str) -> None:
    """Main thread entry – orchestrates mastering pipeline."""

    session = Path(session_dir)
    input_path = get_input_path(session)
    if not input_path:
        progress = {"status": "error", "pct": 100, "message": "no input file"}
        write_progress(session, progress)
        return
    progress = {
        "status": "starting",
        "pct": 0,
        "message": "Starting…",
        "metrics": {
            "club": {"input": {}, "output": {}},
            "stream": {"input": {}, "output": {}},
            "unlimited": {"input": {}, "output": {}},
        },
    }
    write_progress(session, progress)

    try:
        # generate preview
        if HAVE_FFMPEG:
            write_via_tmp(
                session / "input_preview.wav",
                ["-i", input_path, "-ar", "48000", "-c:a", "pcm_s24le"],
            )
        else:
            data, sr_in = sf.read(input_path)
            if sr_in != 48000:
                n = int(len(data) * 48000 / sr_in)
                if data.ndim == 1:
                    data = resample(data, n)
                else:
                    data = np.vstack([resample(data[:, i], n) for i in range(data.shape[1])]).T
            part = session / "input_preview.wav.part"
            sf.write(part, data, 48000, subtype='PCM_24', format='WAV')
            os.replace(part, session / "input_preview.wav")

        # analysing
        progress.update({"status": "analyzing", "pct": 10, "message": "Measuring loudness…"})
        write_progress(session, progress)
        club_meas = _analyze_loudness(input_path, -7.2, -0.8)
        stream_meas = _analyze_loudness(input_path, -9.5, -1.0)

        # mastering: club
        progress.update({"status": "mastering", "pct": 40, "message": "Rendering masters…"})
        write_progress(session, progress)
        club_out = session / "club_master.wav"
        club_metrics = _render_loudnorm(input_path, club_out, -7.2, -0.8, 48000, club_meas)
        write_json_atomic(session / "club_info.json", club_metrics)
        progress["metrics"]["club"] = club_metrics
        write_progress(session, progress)

        # mastering: streaming
        progress.update({"status": "mastering", "pct": 60, "message": "Rendering masters…"})
        write_progress(session, progress)
        stream_out = session / "stream_master.wav"
        stream_metrics = _render_loudnorm(input_path, stream_out, -9.5, -1.0, 44100, stream_meas)
        write_json_atomic(session / "stream_info.json", stream_metrics)
        progress["metrics"]["stream"] = stream_metrics
        write_progress(session, progress)

        # mastering: unlimited
        progress.update({"status": "mastering", "pct": 80, "message": "Rendering masters…"})
        write_progress(session, progress)
        pre_out = session / "premaster_unlimited.wav"
        pre_metrics = _set_sample_peak(input_path, pre_out, -6.0, 48000)
        write_json_atomic(session / "premaster_unlimited_info.json", pre_metrics)
        progress["metrics"]["unlimited"] = pre_metrics
        write_progress(session, progress)

        # manifest
        progress.update({"status": "finalizing", "pct": 90, "message": "Computing checksums…"})
        write_progress(session, progress)
        files = [
            ("club_master.wav", "audio/wav"),
            ("club_info.json", "application/json"),
            ("stream_master.wav", "audio/wav"),
            ("stream_info.json", "application/json"),
            ("premaster_unlimited.wav", "audio/wav"),
            ("premaster_unlimited_info.json", "application/json"),
            ("input_preview.wav", "audio/wav"),
        ]
        manifest: Dict[str, Dict] = {}
        for fname, mime in files:
            fpath = session / fname
            manifest[fname] = {
                "filename": fname,
                "type": mime,
                "size": fpath.stat().st_size,
                "sha256": sha256_file(fpath),
            }
        write_manifest(session, manifest)

        progress.update({"status": "done", "pct": 100, "message": "Done"})
        write_progress(session, progress)
    except Exception as exc:  # noqa: BLE001 - we want to surface errors
        progress.update({"status": "error", "pct": 100, "message": str(exc)})
        write_progress(session, progress)
        return


__all__ = ["run_mastering"]

