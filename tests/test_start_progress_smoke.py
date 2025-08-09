import time

def test_start_progress_smoke(client, sine_file):
    with open(sine_file, 'rb') as f:
        data = {'audio': (f, 'test.wav')}
        r = client.post('/start', data=data, content_type='multipart/form-data')
    assert r.status_code == 200
    j = r.get_json()
    session = j['session']

    phase_seen = None
    metrics_seen = False
    for _ in range(30):
        pr = client.get(f"/progress/{session}")
        assert pr.status_code == 200
        pj = pr.get_json()
        if pj['phase'] != 'starting':
            phase_seen = pj['phase']
        if pj['metrics']['club']['input'].get('I') is not None:
            metrics_seen = True
            break
        time.sleep(0.5)
    assert phase_seen is not None
    assert metrics_seen
