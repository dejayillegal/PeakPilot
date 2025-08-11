import json, time, hashlib
from urllib.parse import quote

def sha256(data: bytes):
    h = hashlib.sha256(); h.update(data); return h.hexdigest()

def test_outputs_downloadable(client, sine_file):
    with open(sine_file, 'rb') as f:
        r = client.post('/start', data={'audio': (f, 'test.wav')}, content_type='multipart/form-data')
    assert r.status_code == 200
    session = r.get_json()['session']
    # poll until done
    for _ in range(60):
        pr = client.get(f'/progress/{session}')
        pj = pr.get_json()
        if pj.get('done'):
            break
        time.sleep(0.5)
    assert pj.get('done')
    # load manifest from disk
    import os, json
    root = os.path.join(client.application.config['UPLOAD_FOLDER'], session)
    with open(os.path.join(root, 'manifest.json'), 'r', encoding='utf-8') as fh:
        manifest = json.load(fh)
    expected = [
        'input_preview.wav',
        'test__club_master.wav',
        'test__stream_master.wav',
        'test__premaster_unlimited.wav',
        'test__ClubMaster_24b_48k_INFO.txt',
        'test__StreamingMaster_24b_44k1_INFO.txt',
        'test__UnlimitedPremaster_24b_48k_INFO.txt'
    ]
    for key in expected:
        assert key in manifest
        resp = client.get(f'/download/{session}/{quote(key)}')
        assert resp.status_code == 200
        assert sha256(resp.data) == manifest[key]['sha256']
