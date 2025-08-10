import os
import json
import numpy as np
from sklearn.linear_model import Ridge

MODEL_DIR = '/tmp/peakpilot/models'
MODEL_PATH = os.path.join(MODEL_DIR, 'micro_adjust_v1.json')

# Very tiny deterministic model: a linear regressor trained on synthetic feature ranges
# Predicts small deltas for (I, TP, LRA) then the pipeline clamps them again.

def _train_or_load():
    os.makedirs(MODEL_DIR, exist_ok=True)
    if os.path.exists(MODEL_PATH):
        with open(MODEL_PATH, 'r') as f:
            return json.load(f)
    # Synthetic training: encourage slight softening for hot/peaky mixes
    rng = np.random.RandomState(42)
    X = []
    yI = []
    yTP = []
    yLRA = []
    for I in np.linspace(-16, -6, 50):
        for TP in np.linspace(-3.0, 0.0, 25):
            for LRA in np.linspace(2, 12, 10):
                crest = rng.uniform(6, 18)
                flat = rng.uniform(0.1, 0.6)
                X.append([I, TP, LRA, crest, flat])
                # Heuristic targets
                dI = np.clip((-9.0 - I) * 0.08, -0.8, 0.8)
                dTP = np.clip((-1.0 - TP) * 0.1, -0.2, 0.2)
                dL = np.clip((8.0 - LRA) * 0.04, -0.2, 0.2)
                yI.append(dI)
                yTP.append(dTP)
                yLRA.append(dL)
    X = np.array(X)
    models = [Ridge(alpha=1.0).fit(X, np.array(y)) for y in (yI, yTP, yLRA)]
    blob = {
        'coef': [m.coef_.tolist() for m in models],
        'inter': [float(m.intercept_) for m in models]
    }
    with open(MODEL_PATH, 'w') as f:
        json.dump(blob, f)
    return blob

MODEL = _train_or_load()


def _predict_deltas(feat_vec):
    coefs = MODEL['coef']
    inter = MODEL['inter']
    dI = float(np.dot(coefs[0], feat_vec) + inter[0])
    dTP = float(np.dot(coefs[1], feat_vec) + inter[1])
    dL = float(np.dot(coefs[2], feat_vec) + inter[2])
    return dI, dTP, dL


def analyze_and_predict(context, ln1):
    # Build tiny feature vector from available pass-1 loudnorm + rough heuristics
    I = float(ln1.get('input_i', -14.0))
    TP = float(ln1.get('input_tp', -2.0))
    LRA = float(ln1.get('input_lra', 8.0))
    # crude helpers (no external DSP): crest ~ -TP - I (loose), flatness proxy from LRA
    crest = max(0.0, -TP - I)
    flat = 1.0 / max(1.0, LRA)
    feat = [I, TP, LRA, crest, flat]
    dI, dTP, dL = _predict_deltas(feat)
    # Clamp again defensively
    dI = max(-0.8, min(0.8, dI))
    dTP = max(-0.2, min(0.2, dTP))
    dL = max(-0.2, min(0.2, dL))
    return {'dI': dI, 'dTP': dTP, 'dLRA': dL}
