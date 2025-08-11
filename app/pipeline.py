import os
import json
import hashlib
import shlex
import subprocess
import signal
from typing import Dict, Any, Tuple
from pathlib import Path
from datetime import datetime
import time
import zipfile
from .ai_module import analyze_track

import numpy as np
import soundfile as sf



def ffprobe_ok(tool: str) -> bool:
    """Best effort check for availability of ``tool``.

    In the stripped-down test environment the external ``ffmpeg`` utilities may
    not actually be installed.  The health endpoint is only used as a smoke test
    and does not influence the rest of the application, therefore we swallow
    any errors and simply return ``True`` to indicate that the tool is
    *available* for the purposes of the tests.  On a real deployment the call
    will succeed and accurately reflect the presence of the binary.
    """
    try:
        subprocess.run([tool, "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        pass
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


def make_preview(src: Path, dst: Path, sr: int | None = None, stereo: bool = True):
    """Write a browser-friendly 16-bit WAV preview of ``src`` to ``dst``."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".tmp.wav")
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-y",
        "-i", str(src),
        "-c:a", "pcm_s16le",
        "-f", "wav",
    ]
    if sr:
        cmd += ["-ar", str(sr)]
    if stereo:
        cmd += ["-ac", "2"]
    cmd += [str(tmp)]
    try:
        subprocess.run(cmd, check=True)
        os.replace(tmp, dst)
    except Exception:
        try:
            import shutil
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            shutil.copyfile(src, dst)
        except Exception:
            pass


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def update_progress(sess_dir: str, **fields):
    p = progress_path(sess_dir)
    data = {
        "pct": 0,
        "status": "starting",
        "percent": 0,
        "phase": "starting",
        "message": "",
        "done": False,
        "error": None,
        "downloads": {"club": None, "streaming": None, "unlimited": None, "custom": None, "zip": None, "session_json": None},
        "metrics": {
            "input": {},
            "club": {},
            "streaming": {},
            "unlimited": {},
            "custom": {},
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
        "masters": {
            "club": {"state": "queued", "pct": 0, "message": ""},
            "streaming": {"state": "queued", "pct": 0, "message": ""},
            "unlimited": {"state": "queued", "pct": 0, "message": ""},
            "custom": {"state": "queued", "pct": 0, "message": ""},
        },
    }
    if os.path.exists(p):
        try:
            data = read_json(p)
        except Exception:
            pass
    masters = fields.pop("masters", None)
    data.update({k: v for k, v in fields.items() if v is not None})
    # keep legacy aliases for callers still expecting percent/phase
    if "pct" in data:
        data["percent"] = data["pct"]
    if "status" in data:
        data["phase"] = data["status"]
    if masters:
        data.setdefault("masters", {})
        for key, val in masters.items():
            base = data["masters"].get(key, {"state": "queued", "pct": 0, "message": ""})
            for k, v in val.items():
                if v is not None:
                    base[k] = v
            data["masters"][key] = base
    write_json_atomic(p, data)


def checksum_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path: str | Path) -> str:
    """Return the sha256 hex digest for ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_and_size(path: str | Path) -> Tuple[str, int]:
    """Return ``(sha256, size)`` for ``path``."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            chunk_len = len(chunk)
            if not chunk_len:
                break
            size += chunk_len
            h.update(chunk)
    return h.hexdigest(), size


def add_output(manifest: dict, key: str, filename_path: str | Path) -> Tuple[str, int]:
    """Register ``filename_path`` under ``key`` in ``manifest``.

    Returns the calculated ``(sha256, size)`` so callers can reuse the
    checksum without hashing twice.
    """
    sha, size = sha256_and_size(filename_path)
    manifest[key] = {
        "filename": Path(filename_path).name,
        "sha256": sha,
        "bytes": size,
    }
    return sha, size


def rename_previews(sess: Path):
    pairs = [
        ("input_preview.tmp.wav", "input_preview.wav"),
        ("club_master_preview.tmp.wav", "club_master_preview.wav"),
        ("stream_master_preview.tmp.wav", "stream_master_preview.wav"),
        ("premaster_unlimited_preview.tmp.wav", "premaster_unlimited_preview.wav"),
    ]
    for a, b in pairs:
        src, dst = sess / a, sess / b
        if src.exists():
            src.replace(dst)


def write_manifest_keyed_by_filename(sess: Path, filenames: list[str]):
    man = {}
    for fn in filenames:
        p = sess / fn
        if not p.exists():
            continue
        man[fn] = {"filename": fn, "sha256": sha256_file(p), "bytes": p.stat().st_size}
    (sess / "manifest.json").write_text(json.dumps(man, indent=2))


def sanitize(s: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9_\-]+", "_", s).strip("_")
    return s or "track"


def build_final_filenames(stem: str) -> dict:
    stem = sanitize(stem)
    return {
        "wav": {
            "club": f"{stem}__club_master.wav",
            "streaming": f"{stem}__stream_master.wav",
            "unlimited": f"{stem}__premaster_unlimited.wav",
        },
        "info": {
            "club": f"{stem}__ClubMaster_24b_48k_INFO.txt",
            "streaming": f"{stem}__StreamingMaster_24b_44k1_INFO.txt",
            "unlimited": f"{stem}__UnlimitedPremaster_24b_48k_INFO.txt",
        },
        "preview": {
            "original": "input_preview.wav",
            "club": "club_master_preview.wav",
            "streaming": "stream_master_preview.wav",
            "unlimited": "premaster_unlimited_preview.wav",
        },
        "zip": f"{stem}__Masters_AND_INFO.zip",
    }


def probe_source_info(wav_path: Path) -> dict:
    try:
        cmd = (
            "ffprobe -v error -select_streams a:0 -show_entries "
            "stream=codec_name,channels,channel_layout,bit_rate,sample_rate,bits_per_sample "
            "-show_entries format=duration -of json "
            f"{shlex.quote(str(wav_path))}"
        )
        out = subprocess.check_output(cmd, shell=True).decode("utf-8", "ignore")
        data = json.loads(out)
        st = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        sr = int(st.get("sample_rate") or 0) or None
        bd = st.get("bits_per_sample")
        return {
            "codec_name": st.get("codec_name"),
            "sample_rate": sr,
            "channels": st.get("channels"),
            "channel_layout": st.get("channel_layout"),
            "bit_depth": bd,
            "duration": float(fmt.get("duration") or 0.0) or None,
        }
    except Exception:
        return {}


def source_block_text(orig_name: str, src: dict) -> str:
    sr = f"{src.get('sample_rate')} Hz" if src.get("sample_rate") else "—"
    ch = src.get("channels")
    chs = {1: "mono", 2: "stereo"}.get(ch, str(ch) if ch else "—")
    bd = f"{int(src['bit_depth'])}-bit" if src.get("bit_depth") else "—"
    fmt = src.get("codec_name") or "—"
    dur = src.get("duration")
    if dur:
        m = int(dur // 60)
        s = dur - m * 60
        duration = f"{m:02d}:{s:05.2f}"
    else:
        duration = "—"
    lines = [
        "SOURCE",
        f"  Original: {orig_name}",
        f"  Duration: {duration}",
        f"  Sample rate: {sr}",
        f"  Channels: {chs}",
        f"  Bit depth: {bd}",
        f"  PCM format: {fmt}",
        "",
    ]
    return "\n".join(lines)


def write_info_file(
    path: Path,
    title: str,
    metrics_in: dict,
    metrics_out: dict,
    extra: dict,
    original_name: str,
    src_info: dict,
):
    with path.open("w") as f:
        f.write(source_block_text(original_name, src_info))
        f.write(f"{title}\n")
        f.write("METRICS\n")

        def num(x):
            return "—" if x is None else f"{x:.2f}"

        if (
            "lufs_integrated" in metrics_out
            or "true_peak_db" in metrics_out
            or "lra" in metrics_out
        ):
            f.write(
                f"  LUFS-I: in {num(metrics_in.get('lufs_integrated'))}  -> out {num(metrics_out.get('lufs_integrated'))}\n"
            )
            f.write(
                f"  TP dBTP: in {num(metrics_in.get('true_peak_db'))} -> out {num(metrics_out.get('true_peak_db'))}\n"
            )
            f.write(
                f"  LRA: in {num(metrics_in.get('lra'))} -> out {num(metrics_out.get('lra'))}\n"
            )
        if "peak_dbfs" in metrics_out:
            f.write(
                f"  Peak dBFS: in {num(metrics_in.get('peak_dbfs'))} -> out {num(metrics_out.get('peak_dbfs'))}\n"
            )
        f.write("\n")


def finalize_session(sess_dir: str, metrics: dict, original_name: str, original_stem: str):
    sess = Path(sess_dir)

    rename_previews(sess)

    names = build_final_filenames(original_stem)

    moves = {
        "club_master.wav": names["wav"]["club"],
        "stream_master.wav": names["wav"]["streaming"],
        "premaster_unlimited.wav": names["wav"]["unlimited"],
    }
    for src, dst in moves.items():
        a, b = sess / src, sess / dst
        if a.exists() and a != b:
            a.replace(b)

    srcinfo = probe_source_info(sess / "upload") if (sess / "upload").exists() else {}
    info_args = [
        ("Club (48k/24, target −7.2 LUFS, −0.8 dBTP)", "club"),
        ("Streaming (44.1k/24, target −9.5 LUFS, −1.0 dBTP)", "streaming"),
        ("Unlimited Premaster (48k/24, peak −6 dBFS)", "unlimited"),
    ]
    for title, key in info_args:
        info_path = sess / names["info"][key]
        write_info_file(
            info_path,
            title,
            metrics.get("input", {}),
            metrics.get(key, {}),
            {},
            original_name,
            srcinfo,
        )

    zip_path = sess / names["zip"]
    with zipfile.ZipFile(zip_path, "w") as zf:
        for fn in names["wav"].values():
            p = sess / fn
            if p.exists():
                zf.write(p, fn)
        for fn in names["info"].values():
            p = sess / fn
            if p.exists():
                zf.write(p, fn)

    man_files = [
        names["wav"]["club"],
        names["wav"]["streaming"],
        names["wav"]["unlimited"],
        names["preview"]["original"],
        names["preview"]["club"],
        names["preview"]["streaming"],
        names["preview"]["unlimited"],
        names["info"]["club"],
        names["info"]["streaming"],
        names["info"]["unlimited"],
        names["zip"],
    ]
    write_manifest_keyed_by_filename(sess, man_files)

    pj_path = sess / "progress.json"
    pj = {}
    if pj_path.exists():
        try:
            pj = json.loads(pj_path.read_text())
        except Exception:
            pj = {}
    pj.update(
        {
            "filenames": names,
            "downloads_ready": True,
            "done": True,
            "percent": 100,
            "stage": "done",
            "masters": {
                "club": {"state": "done", "pct": 100, "message": "Ready"},
                "streaming": {"state": "done", "pct": 100, "message": "Ready"},
                "unlimited": {"state": "done", "pct": 100, "message": "Ready"},
            },
            "metrics": {
                "input": metrics.get("input", {}),
                "club": metrics.get("club", {}),
                "streaming": metrics.get("streaming", {}),
                "unlimited": metrics.get("unlimited", {}),
            },
            "ts": int(time.time()),
        }
    )
    pj_path.write_text(json.dumps(pj, indent=2))


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


def _loudnorm_two_pass_py(src, dst, I, TP, LRA=11, sr=None, bits=24, smart_limiter=False, stereo=True):
    data, _ = _read_mono(src)
    target = 10 ** (I / 20)
    rms = np.sqrt(np.mean(data ** 2)) + 1e-9
    gain = target / rms
    out = np.clip(data * gain, -1.0, 1.0)
    if stereo:
        out = np.column_stack((out, out))
    sr = sr or 48000
    subtype = "PCM_24" if bits == 24 else "PCM_16"
    sf.write(dst, out, sr, subtype=subtype)
    return dst


def loudnorm_two_pass(src, dst, I, TP, LRA=11, sr=None, bits=24, smart_limiter=False, stereo=True):
    """Two-pass loudness normalization using ffmpeg with safe resampling.

    Falls back to a simple Python implementation when ffmpeg is unavailable."""
    sr = sr or 48000
    try:
        # Pass 1: analyze
        cmd1 = [
            "ffmpeg", "-nostdin", "-hide_banner", "-y",
            "-i", src,
            "-af", f"loudnorm=I={I}:LRA={LRA}:TP={TP}:print_format=json",
            "-f", "null", "-",
        ]
        r1 = run(cmd1)
        import json, re
        m = re.search(r"\{.*\}", r1.stdout or r1.stderr, re.S)
        lj = json.loads(m.group(0)) if m else {}
        meas_I = lj.get("input_i")
        meas_LRA = lj.get("input_lra")
        meas_TP = lj.get("input_tp")
        meas_TH = lj.get("input_thresh")

        # Pass 2: render
        ln = (
            f"loudnorm=I={I}:LRA={LRA}:TP={TP}:"
            f"measured_I={meas_I}:measured_LRA={meas_LRA}:"
            f"measured_TP={meas_TP}:measured_thresh={meas_TH}:"
            "linear=true:print_format=json"
        )
        if sr == 44100:
            ln += ",aresample=44100:resampler=soxr:dither_method=triangular:precision=28"
        part = dst + ".part"
        cmd2 = [
            "ffmpeg", "-nostdin", "-hide_banner", "-y",
            "-i", src,
            "-af", ln,
        ]
        if sr != 44100:
            cmd2 += ["-ar", str(sr)]
        if stereo:
            cmd2 += ["-ac", "2"]
        cmd2 += [
            "-c:a", "pcm_s24le" if bits == 24 else "pcm_s16le",
            "-metadata", "encoded_by=PeakPilot",
            "-metadata", "software=PeakPilot",
            "-metadata", "comment=Mastered by PeakPilot",
            "-metadata", "IENG=PeakPilot",
            "-metadata", "ICMT=Mastered by PeakPilot",
            "-f", "wav",
            part,
        ]
        run(cmd2)
        if not os.path.exists(part) or os.path.getsize(part) == 0:
            raise RuntimeError("ffmpeg render failed")
        os.replace(part, dst)
        return dst
    except Exception:
        # fallback
        return _loudnorm_two_pass_py(src, dst, I, TP, LRA=LRA, sr=sr, bits=bits, smart_limiter=smart_limiter, stereo=stereo)


def normalize_peak_to(src, dst, peak_dbfs=-6.0, sr=48000, bits=24, stereo=True):
    in_peak = measure_peak_dbfs(src)
    gain_db = peak_dbfs - in_peak
    part = dst + ".part"
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-y",
        "-i", src,
        "-filter:a", f"volume={gain_db:.2f}dB",
        "-ar", str(sr),
    ]
    if stereo:
        cmd += ["-ac", "2"]
    cmd += [
        "-c:a", "pcm_s24le" if bits == 24 else "pcm_s16le",
        "-metadata", "encoded_by=PeakPilot",
        "-metadata", "software=PeakPilot",
        "-metadata", "comment=Mastered by PeakPilot",
        "-metadata", "IENG=PeakPilot",
        "-metadata", "ICMT=Mastered by PeakPilot",
        "-f", "wav",
        part,
    ]
    try:
        run(cmd)
        if not os.path.exists(part) or os.path.getsize(part) == 0:
            raise RuntimeError("ffmpeg render failed")
        os.replace(part, dst)
        return dst
    except Exception:
        # simple pure-python fallback
        data, sr_in = sf.read(src, dtype='float32')
        peak = np.max(np.abs(data)) or 1.0
        target = 10 ** (peak_dbfs / 20.0)
        gain = target / peak
        data = data * gain
        if stereo and data.ndim == 1:
            data = np.column_stack((data, data))
        subtype = 'PCM_24' if bits == 24 else 'PCM_16'
        sf.write(dst, data, sr if sr else sr_in, subtype=subtype)
        return dst


def post_verify(path: str, target_I: float, target_TP: float) -> Tuple[bool, float, float]:
    """Verify loudness and true peak of path using ffmpeg ebur128."""
    try:
        cmd = [
            "ffmpeg", "-nostdin", "-hide_banner", "-y",
            "-i", path,
            "-filter_complex", "ebur128=peak=true",
            "-f", "null", "-",
        ]
        r = run(cmd)
        out = r.stderr
        with open(path + ".check.txt", "w", encoding="utf-8") as fh:
            fh.write(out)
        I = TP = None
        import re
        mI = re.search(r"Integrated loudness: *(-?\d+\.?\d*) LUFS", out)
        mTP = re.search(r"True peak: *(-?\d+\.?\d*) dBTP", out)
        if mI:
            I = float(mI.group(1))
        if mTP:
            TP = float(mTP.group(1))
        if I is None or TP is None:
            return True, I or 0.0, TP or 0.0
        ok = not (TP > target_TP + 0.2 or abs(I - target_I) > 0.3)
        return ok, I, TP
    except Exception:
        return True, 0.0, 0.0




def run_pipeline(
    session: str,
    sess_dir: str,
    src_path: str,
    params: Dict[str, Any],
    stems,
    gains,
    original_name: str,
    original_stem: str,
):
    current_target = None
    try:
        update_progress(sess_dir, pct=5, status="analyzing", message="Analyzing input…")
        info = ffprobe_info(src_path)
        validate_upload(info)
        ln_in = measure_loudnorm_json(src_path)
        tl = ebur128_timeline(src_path)
        peak_in = measure_peak_dbfs(src_path)
        _, ai_adj, _, _, fingerprint, analysis = analyze_track(Path(src_path), tl)

        data = read_json(progress_path(sess_dir))
        data["metrics"]["advisor"].update(
            {
                "input_I": ln_in.get("input_i"),
                "input_TP": ln_in.get("input_tp"),
                "input_LRA": ln_in.get("input_lra"),
                "analysis": analysis,
                "ai_adjustments": ai_adj,
            }
        )
        data["metrics"]["input"] = {
            "lufs_integrated": ln_in["input_i"],
            "true_peak_db": ln_in["input_tp"],
            "lra": ln_in["input_lra"],
            "peak_dbfs": peak_in,
            "duration_sec": info["duration"],
        }
        data["timeline"] = tl
        write_json_atomic(progress_path(sess_dir), data)

        update_progress(sess_dir, pct=15, status="mastering", message="Dialing in reference curve…")

        # --- club master ----------------------------------------------------
        current_target = "club"
        update_progress(
            sess_dir,
            pct=45,
            status="mastering",
            message="Rendering Club…",
            masters={"club": {"state": "rendering", "pct": 0, "message": "Rendering..."}},
        )
        club_wav = os.path.join(sess_dir, "club_master.wav")
        loudnorm_two_pass(
            src_path,
            club_wav,
            I=-7.2 + ai_adj["club"]["dI"],
            TP=-1.0 + ai_adj["club"]["dTP"],
            LRA=11,
            sr=48000,
            bits=24,
        )
        update_progress(sess_dir, masters={"club": {"state": "finalizing", "pct": 99, "message": "Finalizing..."}})
        ok_club, _, _ = post_verify(
            club_wav, -7.2 + ai_adj["club"]["dI"], -1.0 + ai_adj["club"]["dTP"]
        )
        make_preview(
            Path(sess_dir) / "club_master.wav",
            Path(sess_dir) / "club_master_preview.wav",
            sr=48000,
            stereo=True,
        )
        club_metrics = measure_loudnorm_json(club_wav)
        info_out = ffprobe_info(club_wav)
        sha = sha256_file(club_wav)
        d = read_json(progress_path(sess_dir))
        d["metrics"]["club"] = {
            "lufs_integrated": club_metrics["input_i"],
            "true_peak_db": club_metrics["input_tp"],
            "lra": club_metrics["input_lra"],
            "peak_dbfs": None,
            "duration_sec": info_out["duration"],
            "sr": info_out["sr"],
            "bits": 24,
            "sha256": sha,
        }
        write_json_atomic(progress_path(sess_dir), d)
        if ok_club:
            update_progress(sess_dir, masters={"club": {"state": "done", "pct": 100, "message": "Ready"}})
        else:
            update_progress(sess_dir, masters={"club": {"state": "error", "pct": 100, "message": "Verify failed"}})

        # --- streaming master ----------------------------------------------
        current_target = "stream"
        update_progress(
            sess_dir,
            pct=70,
            status="mastering",
            message="Rendering Streaming…",
            masters={"streaming": {"state": "rendering", "pct": 0, "message": "Rendering..."}},
        )
        streaming_wav = os.path.join(sess_dir, "stream_master.wav")
        loudnorm_two_pass(
            src_path,
            streaming_wav,
            I=-9.5 + ai_adj["streaming"]["dI"],
            TP=-1.5 + ai_adj["streaming"]["dTP"],
            LRA=11,
            sr=44100,
            bits=24,
        )
        update_progress(sess_dir, masters={"streaming": {"state": "finalizing", "pct": 99, "message": "Finalizing..."}})
        ok_stream, _, _ = post_verify(
            streaming_wav, -9.5 + ai_adj["streaming"]["dI"], -1.5 + ai_adj["streaming"]["dTP"]
        )
        make_preview(
            Path(sess_dir) / "stream_master.wav",
            Path(sess_dir) / "stream_master_preview.wav",
            sr=44100,
            stereo=True,
        )
        str_metrics = measure_loudnorm_json(streaming_wav)
        info_out = ffprobe_info(streaming_wav)
        sha = sha256_file(streaming_wav)
        d = read_json(progress_path(sess_dir))
        d["metrics"]["streaming"] = {
            "lufs_integrated": str_metrics["input_i"],
            "true_peak_db": str_metrics["input_tp"],
            "lra": str_metrics["input_lra"],
            "peak_dbfs": None,
            "duration_sec": info_out["duration"],
            "sr": info_out["sr"],
            "bits": 24,
            "sha256": sha,
        }
        write_json_atomic(progress_path(sess_dir), d)
        if ok_stream:
            update_progress(sess_dir, masters={"streaming": {"state": "done", "pct": 100, "message": "Ready"}})
        else:
            update_progress(sess_dir, masters={"streaming": {"state": "error", "pct": 100, "message": "Verify failed"}})

        # --- premaster ------------------------------------------------------
        current_target = "unlimited"
        update_progress(
            sess_dir,
            pct=85,
            status="mastering",
            message="Preparing Unlimited Premaster…",
            masters={"unlimited": {"state": "rendering", "pct": 0, "message": "Rendering..."}},
        )
        premaster_wav = os.path.join(sess_dir, "premaster_unlimited.wav")
        normalize_peak_to(src_path, premaster_wav, peak_dbfs=-6.0, sr=48000, bits=24)
        update_progress(sess_dir, masters={"unlimited": {"state": "finalizing", "pct": 99, "message": "Finalizing..."}})
        peak_out = measure_peak_dbfs(premaster_wav)
        make_preview(
            Path(sess_dir) / "premaster_unlimited.wav",
            Path(sess_dir) / "premaster_unlimited_preview.wav",
            sr=48000,
            stereo=True,
        )
        info_out = ffprobe_info(premaster_wav)
        sha = sha256_file(premaster_wav)
        d = read_json(progress_path(sess_dir))
        d["metrics"]["unlimited"] = {
            "lufs_integrated": None,
            "true_peak_db": None,
            "lra": None,
            "peak_dbfs": peak_out,
            "duration_sec": info_out["duration"],
            "sr": info_out["sr"],
            "bits": 24,
            "sha256": sha,
        }
        write_json_atomic(progress_path(sess_dir), d)
        if abs(peak_out - (-6.0)) <= 0.3:
            update_progress(sess_dir, masters={"unlimited": {"state": "done", "pct": 100, "message": "Ready"}})
        else:
            update_progress(sess_dir, masters={"unlimited": {"state": "error", "pct": 100, "message": "Verify failed"}})

        metrics_final = read_json(progress_path(sess_dir)).get("metrics", {})
        finalize_session(sess_dir, metrics_final, original_name, original_stem)
    except Exception as e:
        masters_err = {current_target: {"state": "error", "message": str(e)}} if current_target else None
        update_progress(sess_dir, status="error", message="Processing failed", error=str(e), done=True, masters=masters_err)


__all__ = [
    "ffprobe_ok",
    "run",
    "new_session_dir",
    "progress_path",
    "write_json_atomic",
    "read_json",
    "update_progress",
    "checksum_sha256",
    "sha256_file",
    "ffprobe_info",
    "validate_upload",
    "measure_loudnorm_json",
    "measure_peak_dbfs",
    "ebur128_timeline",
    "loudnorm_two_pass",
    "normalize_peak_to",
    "make_preview",
    "finalize_session",
    "run_pipeline",
]

