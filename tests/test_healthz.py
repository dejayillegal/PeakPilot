from app import create_app

def test_healthz(client):
    rv = client.get('/healthz')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['ffmpeg'] is True
    assert data['ffprobe'] is True
