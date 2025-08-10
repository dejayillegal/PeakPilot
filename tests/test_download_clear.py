import os
import time
import json


def run_and_wait(client, sine_file):
    with open(sine_file, 'rb') as f:
        r = client.post('/upload', data={'file': (f, 'tone.wav')})
    session = r.get_json()['session']
    client.post('/start', json={'session': session})
    for _ in range(60):
        j = client.get(f'/progress/{session}').get_json()
        if j.get('status') == 'done':
            break
        time.sleep(0.5)
    return session


def test_download_and_checksum(client, sine_file):
    session = run_and_wait(client, sine_file)
    sess_dir = os.path.join(client.application.config['SESSIONS_DIR'], session)
    with open(os.path.join(sess_dir, 'manifest.json')) as fh:
        manifest = json.load(fh)
    for key, meta in manifest.items():
        r = client.get(f'/download/{session}/{key}')
        assert r.status_code == 200
        assert int(r.headers['Content-Length']) == meta['size']
    # unknown key
    assert client.get(f'/download/{session}/nope.wav').status_code == 404
    # tamper
    club_path = os.path.join(sess_dir, 'club_master.wav')
    with open(club_path, 'ab') as fh:
        fh.write(b'corrupt')
    r = client.get(f'/download/{session}/club_master.wav')
    assert r.status_code == 409


def test_clear_removes_session(client, sine_file):
    session = run_and_wait(client, sine_file)
    sess_dir = os.path.join(client.application.config['SESSIONS_DIR'], session)
    assert os.path.isdir(sess_dir)
    r = client.post('/clear', json={'session': session})
    assert r.status_code == 200
    assert not os.path.exists(sess_dir)
