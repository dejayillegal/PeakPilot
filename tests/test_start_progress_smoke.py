import io
import io
import numpy as np
import soundfile as sf
from time import sleep
from app.__init__ import create_app


def _sine_wav_bytes(sr=48000, dur=0.8, freq=440.0):
    t = np.linspace(0, dur, int(sr*dur), endpoint=False)
    x = 0.2*np.sin(2*np.pi*freq*t).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, x, sr, format='WAV', subtype='PCM_16')
    buf.seek(0)
    return buf


def test_start_and_poll_progress(tmp_path, monkeypatch):
    monkeypatch.setenv('WORK_DIR', str(tmp_path/'work'))
    app = create_app()
    with app.test_client() as c:
        data = { 'file': ( _sine_wav_bytes(), 'test.wav') }
        u = c.post('/upload', data=data, content_type='multipart/form-data')
        assert u.status_code == 200
        r = c.post('/start')
        assert r.status_code == 200
        session = r.get_json()['session']
        advanced = False
        for _ in range(12):
            pr = c.get(f'/progress/{session}')
            js = pr.get_json()
            if js.get('phase') not in ('starting','analyze') or js.get('downloads',{}).get('club') or js.get('done'):
                advanced = True
                break
            sleep(1)
        assert advanced
