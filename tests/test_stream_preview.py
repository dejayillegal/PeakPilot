import time
from urllib.parse import quote

def test_stream_input_preview(client, sine_file):
    with open(sine_file, 'rb') as f:
        r = client.post('/start', data={'audio': (f, 'test.wav')}, content_type='multipart/form-data')
    assert r.status_code == 200
    session = r.get_json()['session']
    for _ in range(60):
        pr = client.get(f'/progress/{session}')
        pj = pr.get_json()
        if pj.get('done'):
            break
        time.sleep(0.5)
    assert pj.get('done')

    # plain request
    resp = client.get(f'/stream/{session}/input_preview.wav')
    assert resp.status_code == 200
    assert resp.headers.get('Accept-Ranges') == 'bytes'

    # range request
    resp = client.get(f'/stream/{session}/input_preview.wav', headers={'Range': 'bytes=0-99'})
    assert resp.status_code == 206
    assert resp.headers.get('Content-Range', '').startswith('bytes 0-99/')
    assert len(resp.data) == 100
