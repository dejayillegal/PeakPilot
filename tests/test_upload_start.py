import os
import json
import time


def test_upload_saves_file(client, sine_file):
    with open(sine_file, 'rb') as f:
        r = client.post('/upload', data={'file': (f, 'tone.wav')})
    assert r.status_code == 200
    j = r.get_json()
    assert j['ok'] and j['session']
    sess_dir = os.path.join(client.application.config['SESSIONS_DIR'], j['session'])
    assert os.path.exists(os.path.join(sess_dir, 'meta.txt'))


def test_start_creates_outputs_and_manifest(client, sine_file):
    with open(sine_file, 'rb') as f:
        r = client.post('/upload', data={'file': (f, 'tone.wav')})
    session = r.get_json()['session']
    client.post('/start', json={'session': session})
    # poll
    for _ in range(60):
        j = client.get(f'/progress/{session}').get_json()
        if j.get('status') == 'done':
            break
        time.sleep(0.5)
    sess_dir = os.path.join(client.application.config['SESSIONS_DIR'], session)
    expected = ['club_master.wav', 'club_info.json', 'stream_master.wav', 'stream_info.json', 'premaster_unlimited.wav', 'premaster_unlimited_info.json', 'manifest.json']
    for fname in expected:
        assert os.path.exists(os.path.join(sess_dir, fname))
