import os, re, json, uuid, zipfile, subprocess, hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Any, List

from flask import current_app, url_for

# Expose version so session.json can record it
APP_VERSION = "1.4.0"

# ---- Service Presets ----
ALLOWED_EXTS = {"wav","mp3","flac","aiff","aif","aac","m4a","ogg","oga","opus"}

PRESETS = {
    "spotify":    {"I": -14.0, "TP": -1.0,  "sr": 44100, "bits": 24, "dither": None},
    "apple":      {"I": -16.0, "TP": -1.0,  "sr": 44100, "bits": 24, "dither": None},
    "youtube":    {"I": -13.0, "TP": -1.0,  "sr": 48000, "bits": 24, "dither": None},
    "soundcloud": {"I": -12.0, "TP": -1.0,  "sr": 48000, "bits": 24, "dither": None},
    "club":       {"I":  -7.2, "TP": -0.8,  "sr": 48000, "bits": 24, "dither": None},
    "cd16":       {"I":  -9.5, "TP": -1.0,  "sr": 44100, "bits": 16, "dither": "triangular"}
}


# ---------- Utility ----------
def allowed_file(name: str) -> bool:
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED_EXTS


def run(cmd: List[str], timeout: int | None = None) -> Tuple[int, str, str]:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    return p.returncode, p.stdout or "", p.stderr or ""


def ensure_ffmpeg():
    c1, _, _ = run(["ffmpeg", "-hide_banner", "-version"])
    c2, _, _ = run(["ffprobe", "-hide_banner", "-version"])
    if c1 != 0 or c2 != 0:
        raise RuntimeError("FFmpeg/ffprobe not found")


def new_session_dir() -> Tuple[str, Path]:
    sid = f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    base = Path(current_app.config["UPLOAD_FOLDER"])
    d = base / sid
    d.mkdir(parents=True, exist_ok=True)
    return sid, d


def progress_path(session: str) -> Path:
    return Path(current_app.config["UPLOAD_FOLDER"]) / session / "progress.json"


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data))


def read_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text()) if path.exists() else default


def base_progress() -> dict:
    return {
        "percent": 0,
        "phase": "starting",
        "message": "Starting…",
        "done": False,
        "preset": "club",
        "options": {"trim": True, "pad_ms": 100, "smart_limiter": False, "bits": 24, "dither": None},
        "downloads": {"club": None, "streaming": None, "premaster": None, "custom": None, "zip": None, "session_json": None},
        "metrics": {
            "club": {"input": {}, "output": {}},
            "streaming": {"input": {}, "output": {}},
            "premaster": {"input": {}, "output": {}},
            "custom": {"input": {}, "output": {}},
            "advisor": {},
        },
        "timeline": {"sec": [], "short_term": [], "tp_flags": []},
    }


def update_progress(session: str, patch: dict):
    p = progress_path(session)
    data = read_json(p, base_progress())
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k].update(v)
        else:
            data[k] = v
    data["done"] = data.get("percent", 0) >= 100
    write_json(p, data)


def checksum_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------- Analysis ----------
def extract_json_block(text: str) -> Dict[str, Any]:
    start = text.rfind("{")
    if start == -1:
        raise ValueError("No JSON block found")
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("Unmatched JSON braces")


def measure_loudnorm_json(path: Path, I=-14.0, TP=-1.0, LRA=11.0) -> Dict[str, float]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(path),
        "-filter:a",
        f"loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    code, out, err = run(cmd, timeout=900)
    if code != 0:
        raise RuntimeError(f"loudnorm measure failed: {err}")
    data = extract_json_block(err)
    outd = {}
    for k, v in data.items():
        try:
            outd[k] = float(v)
        except Exception:
            outd[k] = v
    return outd


def measure_peak_dbfs(path: Path) -> float:
    code, out, err = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(path),
            "-filter:a",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        timeout=600,
    )
    if code != 0:
        raise RuntimeError(f"volumedetect failed: {err}")
    m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", err)
    if not m:
        raise RuntimeError("Could not parse max_volume")
    return float(m.group(1))


def ebur128_timeline(path: Path) -> dict:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-filter_complex",
        "ebur128=peak=true:framelog=verbose",
        "-f",
        "null",
        "-",
    ]
    code, out, err = run(cmd, timeout=1800)
    if code != 0:
        return {"sec": [], "short_term": [], "tp_flags": []}
    sec, st, tp = [], [], []
    for line in err.splitlines():
        mt = re.search(r"\bt:\s*([0-9.]+)", line)
        ms = re.search(r"\bS:\s*(-?\d+(?:\.\d+)?)", line)
        mp = re.search(r"\btp:\s*(-?\d+(?:\.\d+)?)", line)
        if mt and ms:
            t = float(mt.group(1))
            sec.append(int(t))
            st.append(float(ms.group(1)))
            tp.append(1 if (mp and float(mp.group(1)) > -1.0) else 0)
    return {"sec": sec, "short_term": st, "tp_flags": tp}


# ---------- Processing stages ----------
def loudnorm_two_pass(
    in_path: Path,
    out_path: Path,
    I: float,
    TP: float,
    LRA: float,
    sr: int,
    bits: int,
    dither: str | None,
    smart_limiter: bool,
):
    # pass 1 analyze
    m = measure_loudnorm_json(in_path, I=I, TP=TP, LRA=LRA)

    # optional smart limiter chain
    limiter_pre = ["-ar", "192000"] if smart_limiter else []
    limiter_post = ["-filter:a", f"alimiter=limit={TP}:level=in:asc=1"] if smart_limiter else []

    # bit depth + dither
    codec = ["-c:a", "pcm_s24le"] if bits == 24 else ["-c:a", "pcm_s16le"]
    dither_args = []
    if bits == 16 and dither:
        dither_args = ["-af", f"aresample={sr}:dither_method={dither}"]

    # pass 2 apply
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(in_path),
        *limiter_pre,
        "-ar",
        str(sr),
        *codec,
        "-filter:a",
        (
            "loudnorm="
            f"I={I}:TP={TP}:LRA={LRA}:"
            f"measured_I={m.get('input_i')}:measured_TP={m.get('input_tp')}:"
            f"measured_LRA={m.get('input_lra')}:measured_thresh={m.get('input_thresh')}:"
            f"offset={m.get('target_offset')}:linear=true:print_format=summary"
        ),
        *limiter_post,
        *dither_args,
        str(out_path),
    ]
    code, out, err = run(cmd, timeout=2400)
    if code != 0:
        raise RuntimeError(f"loudnorm pass-2 failed: {err}")
    return m


def normalize_peak_to(
    in_path: Path,
    out_path: Path,
    target_dbfs: float,
    sr=48000,
    bits=24,
    dither: str | None = None,
):
    peak = measure_peak_dbfs(in_path)
    gain = target_dbfs - peak
    codec = ["-c:a", "pcm_s24le"] if bits == 24 else ["-c:a", "pcm_s16le"]
    dither_args = []
    if bits == 16 and dither:
        dither_args = ["-af", f"aresample={sr}:dither_method={dither}"]
    code, out, err = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(in_path),
            "-ar",
            str(sr),
            *codec,
            "-filter:a",
            f"volume={gain}dB",
            *dither_args,
            str(out_path),
        ],
        timeout=1200,
    )
    if code != 0:
        raise RuntimeError(f"peak normalize failed: {err}")
    return peak


def trim_and_pad(
    in_path: Path,
    out_path: Path,
    trim: bool,
    pad_ms: int,
    sr: int,
    bits: int,
):
    filters = []
    if trim:
        filters.append(
            "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.2:stop_periods=1:stop_threshold=-50dB:stop_silence=0.3"
        )
    if pad_ms and pad_ms > 0:
        pad_s = pad_ms / 1000.0
        filters.append(f"apad=pad_dur={pad_s}")
        filters.append(f"adelay={pad_ms}|{pad_ms}")
    af = ",".join(filters) if filters else "anull"
    codec = ["-c:a", "pcm_s24le"] if bits == 24 else ["-c:a", "pcm_s16le"]
    code, out, err = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(in_path),
            "-ar",
            str(sr),
            *codec,
            "-af",
            af,
            str(out_path),
        ],
        timeout=1200,
    )
    if code != 0:
        raise RuntimeError(f"trim/pad failed: {err}")


def ffprobe_info(path: Path) -> dict:
    code, out, err = run(
        [
            "ffprobe",
            "-hide_banner",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        timeout=60,
    )
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err}")
    return json.loads(out)


def validate_upload(path: Path, max_minutes: int = 20):
    info = ffprobe_info(path)
    dur = float(info.get("format", {}).get("duration", "0") or 0)
    if dur <= 0:
        raise RuntimeError("Unrecognized or zero-length audio")
    if dur > max_minutes * 60:
        raise RuntimeError(f"Audio too long (> {max_minutes} minutes)")


def recommend_preset(input_I: float, input_LRA: float, input_TP: float) -> str:
    if input_I <= -12 and input_LRA <= 8:
        return "spotify"
    if input_I <= -14:
        return "apple"
    if input_I > -10:
        return "club"
    return "youtube"


def mix_stems_to_wav(
    stems: Dict[str, Path],
    gains: Dict[str, float],
    out_path: Path,
    sr=48000,
    bits=24,
):
    inputs, vols, labels = [], [], []
    roles = ["vocals", "drums", "bass", "other"]
    for i, role in enumerate(roles):
        p = stems.get(role)
        if p:
            inputs += ["-i", str(p)]
            g = max(0.0, float(gains.get(role, 1.0)))
            vols.append(f"[{i}:a]volume={g}[a{i}]")
            labels.append(f"[a{i}]")
    if not inputs:
        raise RuntimeError("No stems provided")
    amix = f"{''.join(labels)}amix=inputs={len(labels)}:normalize=1[aout]"
    codec = ["-c:a", "pcm_s24le"] if bits == 24 else ["-c:a", "pcm_s16le"]
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(vols + [amix]),
        "-map",
        "[aout]",
        "-ar",
        str(sr),
        *codec,
        str(out_path),
    ]
    code, out, err = run(cmd, timeout=1800)
    if code != 0:
        raise RuntimeError(f"stem mix failed: {err}")


# ---------- Pipeline ----------
def run_pipeline(app, session: str, src_path: Path, params: dict, stems: Dict[str, Path] | None, stem_gains: Dict[str, float] | None):
    """Main processing pipeline executed in a worker thread."""
    from .ai_module import analyze_track, update_model

    with app.app_context():
        ensure_ffmpeg()
        validate_upload(src_path)

        preset_key = params.get("preset", "club")
        preset = PRESETS.get(preset_key, PRESETS["club"])
        bits = int(params.get("bits", preset["bits"]))
        dither = params.get("dither") or preset.get("dither")
        trim_flag = bool(params.get("trim", True))
        pad_ms = int(params.get("pad_ms", 100))
        smart_limiter = bool(params.get("smart_limiter", False))

        work_input = src_path
        if stems:
            mix = src_path.parent / f"{src_path.stem}__mixfromstems.wav"
            mix_stems_to_wav(stems, stem_gains or {}, mix, sr=preset["sr"], bits=24)
            work_input = mix

        update_progress(session, {"percent": 8, "phase": "analyze", "message": "Analyzing input…"})
        inp = measure_loudnorm_json(work_input, I=preset["I"], TP=preset["TP"], LRA=11.0)
        advisor = recommend_preset(inp.get("input_i", -12), inp.get("input_lra", 8), inp.get("input_tp", -3))
        timeline = ebur128_timeline(work_input)

        features, ai_adj, model, model_path, fingerprint, analysis_info = analyze_track(work_input, timeline)

        update_progress(
            session,
            {
                "metrics": {
                    "advisor": {
                        "recommended": advisor,
                        "input_I": inp.get("input_i"),
                        "input_LRA": inp.get("input_lra"),
                        "input_TP": inp.get("input_tp"),
                        "analysis": analysis_info,
                        "ai_adjustments": ai_adj,
                    }
                },
                "timeline": timeline,
            },
        )

        stem = re.sub(r"\s+", "_", work_input.stem)
        out_dir = work_input.parent

        club_I = -7.2 + ai_adj["club"]["dI"]
        club_TP = -0.8 + ai_adj["club"]["dTP"]
        club_LRA = 11.0 + ai_adj["club"]["dLRA"]

        str_I = -9.5 + ai_adj["streaming"]["dI"]
        str_TP = -1.0 + ai_adj["streaming"]["dTP"]
        str_LRA = 11.0 + ai_adj["streaming"]["dLRA"]

        club_out = out_dir / f"{stem}__CLUB__48k24__-7.2LUFS__-0.8TP.wav"
        update_progress(session, {"percent": 15, "phase": "club", "message": "Club: analyzing/applying"})
        club_in = loudnorm_two_pass(
            work_input,
            club_out,
            I=club_I,
            TP=club_TP,
            LRA=club_LRA,
            sr=48000,
            bits=24,
            dither=None,
            smart_limiter=smart_limiter,
        )
        club_out_m = measure_loudnorm_json(club_out, I=club_I, TP=club_TP, LRA=club_LRA)
        update_progress(
            session,
            {
                "percent": 35,
                "metrics": {
                    "club": {
                        "input": {
                            "I": club_in.get("input_i"),
                            "TP": club_in.get("input_tp"),
                            "LRA": club_in.get("input_lra"),
                            "threshold": club_in.get("input_thresh"),
                        },
                        "output": {
                            "I": club_out_m.get("input_i"),
                            "TP": club_out_m.get("input_tp"),
                            "LRA": club_out_m.get("input_lra"),
                            "threshold": club_out_m.get("input_thresh"),
                        },
                    }
                },
            },
        )

        streaming_out = out_dir / f"{stem}__STREAMING__44k1_24__-9.5LUFS__-1.0TP.wav"
        update_progress(session, {"percent": 45, "phase": "streaming", "message": "Streaming: analyzing/applying"})
        str_in = loudnorm_two_pass(
            work_input,
            streaming_out,
            I=str_I,
            TP=str_TP,
            LRA=str_LRA,
            sr=44100,
            bits=24,
            dither=None,
            smart_limiter=smart_limiter,
        )
        str_out_m = measure_loudnorm_json(streaming_out, I=str_I, TP=str_TP, LRA=str_LRA)
        update_progress(
            session,
            {
                "percent": 65,
                "metrics": {
                    "streaming": {
                        "input": {
                            "I": str_in.get("input_i"),
                            "TP": str_in.get("input_tp"),
                            "LRA": str_in.get("input_lra"),
                            "threshold": str_in.get("input_thresh"),
                        },
                        "output": {
                            "I": str_out_m.get("input_i"),
                            "TP": str_out_m.get("input_tp"),
                            "LRA": str_out_m.get("input_lra"),
                            "threshold": str_out_m.get("input_thresh"),
                        },
                    }
                },
            },
        )

        from .ai_module import update_model  # ensure import inside context

        update_model(
            model,
            model_path,
            fingerprint,
            features,
            club_targets={"I": club_I, "TP": club_TP, "LRA": club_LRA},
            club_measured=club_out_m,
            str_targets={"I": str_I, "TP": str_TP, "LRA": str_LRA},
            str_measured=str_out_m,
        )

        update_progress(session, {"percent": 75, "phase": "premaster-prep", "message": "Premaster: preparing"})
        tmp_48k24 = out_dir / f"{stem}__tmp48k24.wav"
        c, o, e = run(
            [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-i",
                str(work_input),
                "-ar",
                "48000",
                "-c:a",
                "pcm_s24le",
                str(tmp_48k24),
            ],
            timeout=1200,
        )
        if c != 0:
            raise RuntimeError(f"resample failed: {e}")

        in_peak = measure_peak_dbfs(tmp_48k24)
        update_progress(session, {"percent": 85, "phase": "premaster-apply", "message": "Premaster: matching peak to −6 dBFS"})
        premaster_out = out_dir / f"{stem}__UNLIMITED_PREMASTER__48k{bits}__-6dBFS_PEAK.wav"
        _ = normalize_peak_to(tmp_48k24, premaster_out, target_dbfs=-6.0, sr=48000, bits=bits, dither=dither)
        out_peak = measure_peak_dbfs(premaster_out)
        try:
            tmp_48k24.unlink()
        except Exception:
            pass
        update_progress(
            session,
            {"percent": 92, "metrics": {"premaster": {"input": {"peak_dbfs": in_peak}, "output": {"peak_dbfs": out_peak}}}},
        )

        if params.get("do_trim_pad", True):
            padded = out_dir / f"{stem}__UNLIMITED_PREMASTER__48k{bits}__-6dBFS_PEAK__tp.wav"
            trim_and_pad(premaster_out, padded, trim=trim_flag, pad_ms=pad_ms, sr=48000, bits=bits)
            premaster_out = padded

        custom_out = None
        if preset_key and preset_key not in {"club", "cd16"}:
            custom_out = out_dir / f"{stem}__{preset_key.upper()}__{preset['sr']//1000}k_{preset['bits']}__{preset['I']}LUFS__{preset['TP']}TP.wav"
            update_progress(session, {"percent": 94, "phase": "custom", "message": f"{preset_key.title()}: analyzing/applying"})
            cust_in = loudnorm_two_pass(
                work_input,
                custom_out,
                I=preset["I"],
                TP=preset["TP"],
                LRA=11.0,
                sr=preset["sr"],
                bits=preset["bits"],
                dither=preset.get("dither"),
                smart_limiter=smart_limiter,
            )
            cust_out = measure_loudnorm_json(custom_out, I=preset["I"], TP=preset["TP"], LRA=11.0)
            update_progress(
                session,
                {
                    "metrics": {
                        "custom": {
                            "input": {
                                "I": cust_in.get("input_i"),
                                "TP": cust_in.get("input_tp"),
                                "LRA": cust_in.get("input_lra"),
                                "threshold": cust_in.get("input_thresh"),
                            },
                            "output": {
                                "I": cust_out.get("input_i"),
                                "TP": cust_out.get("input_tp"),
                                "LRA": cust_out.get("input_lra"),
                                "threshold": cust_out.get("input_thresh"),
                            },
                        }
                    }
                },
            )

        update_progress(session, {"percent": 97, "phase": "pack", "message": "Packaging"})
        session_json = {
            "version": APP_VERSION,
            "time_utc": datetime.utcnow().isoformat() + "Z",
            "preset_used": preset_key,
            "params": params,
            "metrics": read_json(progress_path(session), base_progress()).get("metrics", {}),
            "timeline": read_json(progress_path(session), base_progress()).get("timeline", {}),
            "outputs": {
                "club": {"file": Path(club_out).name, "sha256": checksum_sha256(club_out)},
                "streaming": {"file": Path(streaming_out).name, "sha256": checksum_sha256(streaming_out)},
                "premaster": {"file": Path(premaster_out).name, "sha256": checksum_sha256(premaster_out)},
            },
            "ai_model": {"present": True, "adjustments": ai_adj, "fingerprint": fingerprint},
        }
        if custom_out:
            session_json["outputs"]["custom"] = {"file": Path(custom_out).name, "sha256": checksum_sha256(custom_out)}
        sess_json_path = out_dir / "session.json"
        write_json(sess_json_path, session_json)

        zip_path = out_dir / f"{stem}__PeakPilot_Masters.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(club_out, arcname=Path(club_out).name)
            zf.write(streaming_out, arcname=Path(streaming_out).name)
            zf.write(premaster_out, arcname=Path(premaster_out).name)
            if custom_out:
                zf.write(custom_out, arcname=Path(custom_out).name)
            zf.write(sess_json_path, arcname=sess_json_path.name)

        downloads = {
            "club": url_for("download_file", session=session, filename=Path(club_out).name, _external=True),
            "streaming": url_for("download_file", session=session, filename=Path(streaming_out).name, _external=True),
            "premaster": url_for("download_file", session=session, filename=Path(premaster_out).name, _external=True),
            "custom": url_for("download_file", session=session, filename=Path(custom_out).name, _external=True) if custom_out else None,
            "zip": url_for("download_file", session=session, filename=zip_path.name, _external=True),
            "session_json": url_for("download_file", session=session, filename=sess_json_path.name, _external=True),
        }
        update_progress(session, {"percent": 100, "phase": "done", "message": "Done", "downloads": downloads})


__all__ = [
    "ALLOWED_EXTS",
    "PRESETS",
    "allowed_file",
    "new_session_dir",
    "progress_path",
    "write_json",
    "read_json",
    "base_progress",
    "update_progress",
    "run_pipeline",
]

