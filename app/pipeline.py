import json
import os
import re
import math
import time
import zipfile
import hashlib
import shutil
import tempfile
import subprocess
from datetime import datetime, timezone

from .ai_module import analyze_and_predict

UPLOAD_KEY = 'audio'
TIMEOUT_SEC = 90  # per ffmpeg/ffprobe call; tuned low for tests, HF can lift via env

# ---------------------
# Progress I/O (atomic)
# ---------------------

def init_progress():
    return {
        "percent": 0,
        "phase": "starting",
        "message": "Starting…",
        "done": False,
        "error": None,
        "downloads": {
            "club": None, "streaming": None, "premaster": None,
            "custom": None, "zip": None, "session_json": None
        },
        "metrics": {
            "club": {"input": {}, "output": {}},
            "streaming": {"input": {}, "output": {}},
            "premaster": {"input": {}, "output": {}},
            "custom": {"input": {}, "output": {}},
            "advisor": {
                "recommended_preset": "",
                "input_I": None, "input_TP": None, "input_LRA": None,
                "analysis": {}, "ai_adjustments": {}
            }
        },
        "timeline": {"sec": [], "short_term": [], "tp_flags": []}
    }


def atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def update_progress(sess_dir, **patch):
    ppath = os.path.join(sess_dir, 'progress.json')
    data = read_json(ppath)
    # shallow merge for simple fields
    for k, v in patch.items():
        if k in ("metrics", "downloads", "timeline"):
            # deep-ish merge
            if k not in data:
                data[k] = v
            else:
                _merge(data[k], v)
        else:
            data[k] = v
    atomic_write_json(ppath, data)


def _merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict):
            if k not in dst or not isinstance(dst[k], dict):
                dst[k] = {}
            _merge(dst[k], v)
        else:
            dst[k] = v

# ---------------------
# Subprocess helpers
# ---------------------

def run_cmd(cmd, timeout=TIMEOUT_SEC):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"Command timed out: {' '.join(cmd[:3])} …")
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd[:3])}\n{err}")
    return out, err

# ---------------------
# Media helpers
# ---------------------

def sniff_upload(path):
    # ffprobe basic checks
    out, _ = run_cmd([
        'ffprobe', '-v', 'error', '-show_format', '-show_streams', '-print_format', 'json', path
    ])
    meta = json.loads(out)
    if not meta.get('streams'):
        raise ValueError('File has no media streams')
    astreams = [s for s in meta['streams'] if s.get('codec_type') == 'audio']
    if not astreams:
        raise ValueError('No audio stream detected')
    dur = float(meta['format'].get('duration', 0.0) or 0.0)
    if dur <= 0:
        raise ValueError('Zero/unknown duration')
    if dur > 20 * 60:
        raise ValueError('Duration exceeds 20 minutes limit')
    return {
        'duration': dur,
        'channels': astreams[0].get('channels', 2),
        'sr': astreams[0].get('sample_rate')
    }


def measure_loudnorm_json(path):
    # Pass-1 loudnorm prints JSON to stderr
    _, err = run_cmd([
        'ffmpeg', '-hide_banner', '-nostats', '-i', path,
        '-filter_complex', 'loudnorm=I=-23:TP=-2:LRA=11:print_format=json',
        '-f', 'null', '-'
    ])
    # Extract JSON blob between { }
    m = re.search(r"\{[\s\S]*?\}\s*$", err)
    if not m:
        raise RuntimeError('Could not parse loudnorm JSON')
    data = json.loads(m.group(0))
    # normalize keys -> snake_case expected by client
    return {
        'input_i': float(data.get('input_i', 'nan')),
        'input_lra': float(data.get('input_lra', 'nan')),
        'input_tp': float(data.get('input_tp', 'nan')),
        'input_thresh': float(data.get('input_thresh', 'nan')),
        'target_offset': float(data.get('target_offset', 'nan'))
    }


def ebur128_timeline(path):
    # verbose frame log with true peak
    _, err = run_cmd([
        'ffmpeg', '-hide_banner', '-nostats', '-i', path,
        '-filter_complex', 'ebur128=peak=true:framelog=verbose',
        '-f', 'null', '-'
    ], timeout=max(TIMEOUT_SEC, 120))
    # Parse lines like: t: 5.000000 M: -18.6 S: -17.9 I: -23.4 LRA: 7.2 Peak: -1.23
    sec_bins = {}
    tp_flags = set()
    for line in err.splitlines():
        if 'Parsed_ebur128' not in line or 't:' not in line:
            continue
        try:
            t = float(_after(line, 't:'))
            S = float(_after(line, 'S:')) if 'S:' in line else None
            peak = float(_after(line, 'Peak:')) if 'Peak:' in line else None
        except Exception:
            continue
        s = int(t)
        if S is not None:
            sec_bins.setdefault(s, []).append(S)
        if peak is not None and peak > -1.0:  # flag near 0 dBTP
            tp_flags.add(s)
    secs = sorted(sec_bins.keys())
    st = [sum(sec_bins[s])/len(sec_bins[s]) for s in secs]
    flags = [1 if s in tp_flags else 0 for s in secs]
    return {'sec': secs, 'short_term': st, 'tp_flags': flags}


def _after(line, key):
    # returns float after key up to next space or comma
    i = line.index(key) + len(key)
    j = i
    while j < len(line) and line[j] in ' \t':
        j += 1
    k = j
    while k < len(line) and line[k] not in ' ,\n\r':
        k += 1
    return line[j:k]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_output(path):
    out, _ = run_cmd(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-print_format', 'json', path])
    meta = json.loads(out)
    a = [s for s in meta['streams'] if s.get('codec_type') == 'audio'][0]
    fmt = meta['format']
    sr = int(a.get('sample_rate', '0') or 0)
    ch = int(a.get('channels', 0) or 0)
    dur = float(fmt.get('duration', 0.0) or 0.0)
    # Estimate bits from sample_fmt if available
    sample_fmt = a.get('sample_fmt') or ''
    bits = 24 if 's24' in sample_fmt else (32 if 's32' in sample_fmt or 'fltp' in sample_fmt else (16 if 's16' in sample_fmt else None))

    # Re-measure LUFS/TP via pass-1 loudnorm
    ln = measure_loudnorm_json(path)
    ln.update({'sr': sr, 'bits': bits, 'channels': ch, 'dur_sec': dur})
    ln['sha256'] = sha256_file(path)
    return ln


# ---------------------
# Rendering stages
# ---------------------

def two_pass_loudnorm(input_path, out_path, target_I, target_TP, sr, bits, ai_hint=None):
    # Pass-1
    ln1 = measure_loudnorm_json(input_path)

    # AI micro-adjustments (clamped)
    adj = {'dI': 0.0, 'dTP': 0.0, 'dLRA': 0.0}
    if ai_hint:
        adj = analyze_and_predict(ai_hint, ln1)
    I = target_I + max(-0.8, min(0.8, adj.get('dI', 0.0)))
    TP_cap = -0.8 if target_TP <= -0.8 else -1.0
    TP = target_TP + max(-0.2, min(0.2, adj.get('dTP', 0.0)))
    TP = min(TP, TP_cap)

    # Pass-2
    lnfilt = (
        f"loudnorm=I={I}:TP={TP}:LRA=11:measured_I={ln1['input_i']}:"\
        f"measured_LRA={ln1['input_lra']}:measured_TP={ln1['input_tp']}:"\
        f"measured_thresh={ln1['input_thresh']}:offset={ln1['target_offset']}:"\
        f"linear=true:print_format=summary"
    )
    # WAV 24-bit target
    acodec = 'pcm_s24le' if bits == 24 else 'pcm_s16le'
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-nostats', '-i', input_path,
        '-filter_complex', lnfilt,
        '-ar', str(sr), '-acodec', acodec,
        out_path
    ]
    run_cmd(cmd)

    # Verify
    ver = verify_output(out_path)
    return ln1, ver


def premaster_unlimited(input_path, out_path, sr=48000, bits=24, peak_dbfs=-6.0):
    # Measure peak with volumedetect
    _, err = run_cmd([
        'ffmpeg', '-hide_banner', '-nostats', '-i', input_path,
        '-filter_complex', 'volumedetect', '-f', 'null', '-'
    ])
    m = re.search(r"max_volume:\s*([-+]?\d+\.\d+) dB", err)
    maxv = float(m.group(1)) if m else 0.0
    # Gain needed so that new max reaches peak_dbfs (negative)
    gain_db = peak_dbfs - maxv
    # Apply gain only, no limiter
    acodec = 'pcm_s24le' if bits == 24 else 'pcm_s16le'
    run_cmd([
        'ffmpeg', '-y', '-hide_banner', '-nostats', '-i', input_path,
        '-filter_complex', f"volume={gain_db}dB",
        '-ar', str(sr), '-acodec', acodec,
        out_path
    ])
    ver = verify_output(out_path)
    # For premaster, record peaks
    ver['premaster_peak_dbfs'] = peak_dbfs
    return {'max_volume': maxv}, ver


# ---------------------
# Pipeline orchestration
# ---------------------

def run_pipeline(session, sess_dir, input_path):
    ppath = os.path.join(sess_dir, 'progress.json')
    try:
        update_progress(sess_dir, percent=5, phase='analyze', message='Analyzing input…')
        sniff = sniff_upload(input_path)
        ln_input = measure_loudnorm_json(input_path)
        timeline = ebur128_timeline(input_path)

        advisor = {
            'recommended_preset': 'club',
            'input_I': ln_input['input_i'],
            'input_TP': ln_input['input_tp'],
            'input_LRA': ln_input['input_lra'],
            'analysis': {},
            'ai_adjustments': {}
        }
        ai_adj = analyze_and_predict({'sr': sniff['sr'], 'dur': sniff['duration']}, ln_input)
        advisor['ai_adjustments'] = ai_adj
        update_progress(sess_dir, metrics={'advisor': advisor}, timeline=timeline)

        # Reference stage (UI flavor)
        update_progress(sess_dir, percent=15, phase='reference', message='Dialing in reference curve…')

        out_dir = os.path.join(sess_dir, 'outputs')
        os.makedirs(out_dir, exist_ok=True)

        # --- Club Master ---
        update_progress(sess_dir, phase='club', message='Rendering Club…', percent=45)
        club_path = os.path.join(out_dir, 'club_master.wav')
        ln1, ver = two_pass_loudnorm(input_path, club_path, target_I=-7.2, target_TP=-0.8, sr=48000, bits=24, ai_hint={'mode': 'club'})
        update_progress(
            sess_dir,
            downloads={'club': os.path.basename(club_path)},
            metrics={'club': {'input': ln1, 'output': ver}}
        )

        # --- Streaming Master ---
        update_progress(sess_dir, phase='streaming', message='Rendering Streaming…', percent=70)
        streaming_path = os.path.join(out_dir, 'streaming_master.wav')
        ln1s, vers = two_pass_loudnorm(input_path, streaming_path, target_I=-9.5, target_TP=-1.0, sr=44100, bits=24, ai_hint={'mode': 'streaming'})
        update_progress(
            sess_dir,
            downloads={'streaming': os.path.basename(streaming_path)},
            metrics={'streaming': {'input': ln1s, 'output': vers}}
        )

        # --- Unlimited Premaster ---
        update_progress(sess_dir, phase='premaster', message='Preparing Unlimited Premaster…', percent=85)
        premaster_path = os.path.join(out_dir, 'premaster_unlimited.wav')
        pin, pov = premaster_unlimited(input_path, premaster_path, sr=48000, bits=24, peak_dbfs=-6.0)
        update_progress(
            sess_dir,
            downloads={'premaster': os.path.basename(premaster_path)},
            metrics={'premaster': {'input': pin, 'output': pov}}
        )

        # --- Package ---
        update_progress(sess_dir, phase='package', message='Packaging downloads…', percent=95)
        # session.json
        sess_json_path = os.path.join(out_dir, 'session.json')
        # Build outputs summary for bundle
        m = read_json(ppath)
        outputs = {}
        for key in ('club', 'streaming', 'premaster'):
            fname = m['downloads'].get(key)
            if fname:
                ver = m['metrics'][key]['output']
                outputs[key] = {
                    'file': fname,
                    'sha256': ver.get('sha256'),
                    'sr': ver.get('sr'),
                    'bits': ver.get('bits'),
                    'dur_sec': ver.get('dur_sec')
                }
        sess_obj = {
            'version': '1.0',
            'time_utc': datetime.now(timezone.utc).isoformat(),
            'preset_used': 'club, streaming, premaster',
            'params': {},
            'metrics': m['metrics'],
            'timeline': m['timeline'],
            'outputs': outputs,
            'ai_model': {
                'present': True,
                'adjustments': m['metrics']['advisor'].get('ai_adjustments', {}),
                'fingerprint': 'tiny-sklearn-v1'
            }
        }
        atomic_write_json(sess_json_path, sess_obj)
        update_progress(sess_dir, downloads={'session_json': os.path.basename(sess_json_path)})

        # Zip
        zip_path = os.path.join(out_dir, 'peakpilot_session.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for f in ('club_master.wav', 'streaming_master.wav', 'premaster_unlimited.wav', 'session.json'):
                p = os.path.join(out_dir, f)
                if os.path.exists(p):
                    z.write(p, arcname=f)
        update_progress(sess_dir, downloads={'zip': os.path.basename(zip_path)})

        # Done
        update_progress(sess_dir, percent=100, phase='done', message='Ready', done=True)

    except Exception as e:
        update_progress(sess_dir, phase='error', message='A processing error occurred', error=str(e), done=True, percent=100)
