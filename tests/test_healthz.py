from app.__init__ import create_app

def test_healthz():
    app = create_app()
    with app.test_client() as c:
        r = c.get('/healthz')
        assert r.status_code == 200
        js = r.get_json()
        assert isinstance(js.get('ffmpeg'), bool)
        assert isinstance(js.get('ffprobe'), bool)
