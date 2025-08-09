import json
from pathlib import Path
from typing import Dict, Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, stft
from sklearn.linear_model import SGDRegressor
import joblib

def checksum_sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1<<20), b""):
            h.update(chunk)
    return h.hexdigest()

# feature extraction

def _extract_features(path: Path, timeline: Dict[str, Any]) -> tuple[np.ndarray, Dict[str, float]]:
    data, sr = sf.read(str(path))
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr != 48000:
        data = resample_poly(data, 48000, sr)
        sr = 48000
    # STFT
    f, t, Z = stft(data, fs=sr, nperseg=4096, noverlap=4096-2048, padded=False)
    mag = np.abs(Z) + 1e-9
    rms = np.sqrt(np.mean(data**2))
    peak = np.max(np.abs(data))
    crest = peak / (rms + 1e-9)
    centroid = (f[:, None] * mag).sum(axis=0) / mag.sum(axis=0)
    rolloff = []
    flat = []
    bw = []
    zcr = []
    for i in range(mag.shape[1]):
        spec = mag[:, i]
        energy = spec**2
        cumsum = np.cumsum(energy)
        idx = np.searchsorted(cumsum, 0.95*cumsum[-1])
        rolloff.append(f[min(idx, len(f)-1)])
        c = centroid[i]
        bw.append(np.sqrt(((f-c)**2 * energy).sum()/energy.sum()))
        geo = np.exp(np.mean(np.log(spec)))
        flat.append(geo/np.mean(spec))
        start = i*2048
        frame = data[start:start+4096]
        if len(frame)>1:
            zcr.append(((frame[:-1]*frame[1:])<0).sum()/len(frame))
    band_means = []
    edges = np.linspace(0, mag.shape[0], 33, dtype=int)
    for b in range(32):
        band_means.append(float(mag[edges[b]:edges[b+1], :].mean()))
    tl = timeline.get("short_term") or [0.0]
    tl_arr = np.array(tl)
    tl_stats = [float(np.mean(tl_arr)), float(np.percentile(tl_arr,5)),
                float(np.percentile(tl_arr,50)), float(np.percentile(tl_arr,95)), float(np.std(tl_arr))]
    feats = np.array([rms, peak, crest,
                      float(np.mean(centroid)), float(np.mean(rolloff)),
                      float(np.mean(flat)), float(np.mean(bw)), float(np.mean(zcr)),
                      np.mean(np.abs(np.diff(np.sqrt((Z**2).mean(axis=0)))))
                      ] + tl_stats + band_means, dtype=float)
    analysis = {
        "centroid_mean": float(np.mean(centroid)),
        "crest_factor_mean": float(crest),
        "rolloff95_mean": float(np.mean(rolloff)),
    }
    return feats, analysis


def _model_path(base_dir: Path, fingerprint: str) -> Path:
    model_dir = base_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir / f"{fingerprint}.joblib"


def analyze_track(path: Path, timeline: Dict[str, Any]):
    base = Path(path).parent.parent
    checksum = checksum_sha256(path)
    dur = len(timeline.get("sec", []))
    fingerprint = f"{checksum}-{dur}"
    features, analysis = _extract_features(path, timeline)
    model_file = _model_path(base, fingerprint)
    if model_file.exists():
        model = joblib.load(model_file)
    else:
        model = SGDRegressor(max_iter=1, learning_rate="constant", eta0=0.01)
        model.partial_fit([features], [[0,0,0,0,0,0]])
        joblib.dump(model, model_file)
    pred = model.predict([features])[0]
    ai_adj = {
        "club": {
            "dI": float(np.clip(pred[0], -0.8, 0.8)),
            "dTP": float(np.clip(pred[1], -0.2, 0.0)),
            "dLRA": float(np.clip(pred[2], -0.8, 0.8)),
        },
        "streaming": {
            "dI": float(np.clip(pred[3], -0.8, 0.8)),
            "dTP": float(np.clip(pred[4], -0.2, 0.0)),
            "dLRA": float(np.clip(pred[5], -0.8, 0.8)),
        },
    }
    return features, ai_adj, model, model_file, fingerprint, analysis


def update_model(model: SGDRegressor, model_file: Path, fingerprint: str, features: np.ndarray,
                 club_targets: Dict[str,float], club_measured: Dict[str,float],
                 str_targets: Dict[str,float], str_measured: Dict[str,float]):
    err = [
        club_targets["I"] - club_measured.get("input_i", club_targets["I"]),
        club_targets["TP"] - club_measured.get("input_tp", club_targets["TP"]),
        club_targets["LRA"] - club_measured.get("input_lra", club_targets["LRA"]),
        str_targets["I"] - str_measured.get("input_i", str_targets["I"]),
        str_targets["TP"] - str_measured.get("input_tp", str_targets["TP"]),
        str_targets["LRA"] - str_measured.get("input_lra", str_targets["LRA"]),
    ]
    model.partial_fit([features], [err])
    joblib.dump(model, model_file)
