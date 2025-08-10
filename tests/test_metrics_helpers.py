import io
import numpy as np
import soundfile as sf
from app.__init__ import create_app
from app.pipeline import measure_loudnorm_json, ebur128_timeline


def _tone(tmp_path, name='tone.wav'):
    import os
    sr=44100; dur=0.6; t = np.linspace(0,dur,int(sr*dur),endpoint=False)
    x = 0.1*np.sin(2*np.pi*440*t).astype('float32')
    p = os.path.join(tmp_path, name)
    sf.write(p, x, sr, subtype='PCM_16')
    return p


def test_measure_and_timeline(tmp_path):
    p = _tone(tmp_path)
    ln = measure_loudnorm_json(p)
    for k in ('input_i','input_lra','input_tp','input_thresh','target_offset'):
        assert k in ln
    tl = ebur128_timeline(p)
    assert isinstance(tl['sec'], list) and isinstance(tl['short_term'], list) and isinstance(tl['tp_flags'], list)
