import os
import sys
import time
import numpy as np
import soundfile as sf
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app()
    app.config['TESTING'] = True
    sessions = tmp_path / 'sessions'
    sessions.mkdir()
    monkeypatch.setitem(app.config, 'SESSIONS_DIR', str(sessions))
    return app.test_client()


@pytest.fixture
def sine_file(tmp_path):
    sr = 48000
    t = np.linspace(0, 1.0, sr, False)
    wave = 0.1 * np.sin(2 * np.pi * 440 * t)
    path = tmp_path / 'tone.wav'
    sf.write(path, wave, sr)
    return path


def process_file(client, sine_file):
    with open(sine_file, 'rb') as f:
        r = client.post('/upload', data={'file': (f, 'tone.wav')})
    assert r.status_code == 200
    session = r.get_json()['session']
    client.post('/start', json={'session': session})
    for _ in range(60):
        j = client.get(f'/progress/{session}').get_json()
        if j.get('status') == 'done':
            break
        time.sleep(0.5)
    return session
