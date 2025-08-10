from app.__init__ import create_app


def test_start_without_audio_returns_400(tmp_path, monkeypatch):
    monkeypatch.setenv('WORK_DIR', str(tmp_path/'work'))
    app = create_app()
    with app.test_client() as client:
        rv = client.post('/start')
        assert rv.status_code == 400
        assert 'Missing session' in rv.get_json().get('error', '')
