import os
import json
import subprocess
import shutil
from typing import Dict

import numpy as np
import soundfile as sf
from scipy.signal import resample

from ..util_fs import (
    write_progress,
    write_json_atomic,
    sha256_file,
    write_manifest,
)

HAVE_FFMPEG = shutil.which('ffmpeg') is not None


def _parse_last_json(text: str) -> Dict:
    idx = text.rfind('{')
    if idx == -1:
        return {}
    try:
        return json.loads(text[idx:])
    except json.JSONDecodeError:
        return {}


def _loudnorm_pass(inp: str, out: str, target_i: float, target_tp: float, sr: int) -> Dict:
    if not HAVE_FFMPEG:
        data, in_sr = sf.read(inp)
        if in_sr != sr:
            n = int(len(data) * sr / in_sr)
            if data.ndim == 1:
                data = resample(data, n)
            else:
                data = np.vstack([resample(data[:, i], n) for i in range(data.shape[1])]).T
        peak = np.max(np.abs(data)) + 1e-9
        gain = (10 ** (target_tp / 20.0)) / peak
        data = data * gain
        sf.write(out, data, sr, subtype='PCM_24', format='WAV')
        m = {'I': 0.0, 'TP': target_tp, 'LRA': 0.0, 'threshold': 0.0}
        return {'input': m, 'output': m}

    cmd = [
        'ffmpeg', '-i', inp,
        '-af', f'loudnorm=I={target_i}:LRA=11:TP={target_tp}:print_format=json',
        '-f', 'null', '-'
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    meta = _parse_last_json(proc.stderr + proc.stdout)
    af = (
        'loudnorm=I={ti}:LRA=11:TP={tt}:measured_I={mi}:measured_LRA={ml}:'
        'measured_TP={mtp}:measured_thresh={mth}:linear=true:print_format=json'
    ).format(
        ti=target_i, tt=target_tp, mi=meta.get('input_i'), ml=meta.get('input_lra'),
        mtp=meta.get('input_tp'), mth=meta.get('input_thresh')
    )
    if sr == 44100:
        af += ',aresample=44100:dither_method=triangular'
    else:
        af += f',aresample={sr}'
    tmp = out + '.tmp'
    cmd = ['ffmpeg', '-y', '-i', inp, '-af', af, '-ar', str(sr), '-c:a', 'pcm_s24le', tmp]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out_meta = _parse_last_json(proc.stderr + proc.stdout)
    os.replace(tmp, out)
    return {
        'input': {
            'I': float(meta.get('input_i', 0)),
            'TP': float(meta.get('input_tp', 0)),
            'LRA': float(meta.get('input_lra', 0)),
            'threshold': float(meta.get('input_thresh', 0)),
        },
        'output': {
            'I': float(out_meta.get('output_i', 0)),
            'TP': float(out_meta.get('output_tp', 0)),
            'LRA': float(out_meta.get('output_lra', 0)),
            'threshold': float(out_meta.get('target_offset', 0)),
        }
    }


def _volumedetect(path: str) -> float:
    if not HAVE_FFMPEG:
        data, _ = sf.read(path)
        return 20 * np.log10(np.max(np.abs(data)) + 1e-9)
    cmd = ['ffmpeg', '-i', path, '-af', 'volumedetect', '-f', 'null', '-']
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = proc.stderr + proc.stdout
    mv = 0.0
    for line in text.splitlines():
        if 'max_volume' in line:
            try:
                mv = float(line.split(':')[1].split(' ')[1])
            except Exception:
                pass
    return mv


def run_mastering(session_dir: str, input_path: str) -> None:
    progress = {
        'status': 'starting',
        'pct': 0,
        'message': 'Starting…',
        'metrics': {
            'club': {'input': {}, 'output': {}},
            'stream': {'input': {}, 'output': {}},
            'unlimited': {'input': {}, 'output': {}},
        },
    }
    write_progress(session_dir, progress)

    try:
        # Club
        progress.update({'status': 'analyzing', 'pct': 10, 'message': 'Measuring loudness…'})
        write_progress(session_dir, progress)
        club_out = os.path.join(session_dir, 'club_master.wav')
        club_metrics = _loudnorm_pass(input_path, club_out, -7.2, -0.8, 48000)
        write_json_atomic(os.path.join(session_dir, 'club_info.json'), club_metrics)
        progress['metrics']['club'] = club_metrics
        write_progress(session_dir, progress)

        # Streaming
        progress.update({'status': 'mastering', 'pct': 40, 'message': 'Rendering masters…'})
        write_progress(session_dir, progress)
        stream_out = os.path.join(session_dir, 'stream_master.wav')
        stream_metrics = _loudnorm_pass(input_path, stream_out, -9.5, -1.0, 44100)
        write_json_atomic(os.path.join(session_dir, 'stream_info.json'), stream_metrics)
        progress['metrics']['stream'] = stream_metrics
        write_progress(session_dir, progress)

        # Unlimited premaster
        progress.update({'status': 'mastering', 'pct': 70, 'message': 'Rendering masters…'})
        write_progress(session_dir, progress)
        pre_out = os.path.join(session_dir, 'premaster_unlimited.wav')
        peak = _volumedetect(input_path)
        gain = -6.0 - peak
        tmp = pre_out + '.tmp'
        if HAVE_FFMPEG:
            af = f"volume={gain}dB,alimiter=limit=0.0:level=-6.0"
            cmd = ['ffmpeg', '-y', '-i', input_path, '-af', af, '-ar', '48000', '-c:a', 'pcm_s24le', tmp]
            subprocess.run(cmd, check=True)
        else:
            data, sr_in = sf.read(input_path)
            if sr_in != 48000:
                n = int(len(data) * 48000 / sr_in)
                if data.ndim == 1:
                    data = resample(data, n)
                else:
                    data = np.vstack([resample(data[:, i], n) for i in range(data.shape[1])]).T
            data = data * (10 ** (gain / 20.0))
            data = np.clip(data, -1.0, 1.0)
            sf.write(tmp, data, 48000, subtype='PCM_24', format='WAV')
        os.replace(tmp, pre_out)
        out_peak = _volumedetect(pre_out)
        pre_metrics = {'input': {'peak_dbfs': peak}, 'output': {'peak_dbfs': out_peak}}
        write_json_atomic(os.path.join(session_dir, 'premaster_unlimited_info.json'), pre_metrics)
        progress['metrics']['unlimited'] = pre_metrics
        write_progress(session_dir, progress)

        # Finalize manifest
        progress.update({'status': 'finalizing', 'pct': 90, 'message': 'Computing checksums…'})
        write_progress(session_dir, progress)
        files = [
            ('club_master.wav', 'audio/wav'),
            ('club_info.json', 'application/json'),
            ('stream_master.wav', 'audio/wav'),
            ('stream_info.json', 'application/json'),
            ('premaster_unlimited.wav', 'audio/wav'),
            ('premaster_unlimited_info.json', 'application/json'),
        ]
        manifest = {}
        for fname, mime in files:
            fpath = os.path.join(session_dir, fname)
            manifest[fname] = {
                'filename': fname,
                'type': mime,
                'size': os.path.getsize(fpath),
                'sha256': sha256_file(fpath),
            }
        write_manifest(session_dir, manifest)

        progress.update({'status': 'done', 'pct': 100, 'message': 'Done'})
        write_progress(session_dir, progress)
    except Exception as exc:
        progress.update({'status': 'error', 'pct': 100, 'message': str(exc)})
        write_progress(session_dir, progress)
        raise
