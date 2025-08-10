from time import sleep
import io
from app.__init__ import create_app


def test_invalid_file_sets_error():
    app = create_app()
    with app.test_client() as c:
        data = { 'audio': ( io.BytesIO(b'not an audio'), 'bad.txt') }
        r = c.post('/start', data=data, content_type='multipart/form-data')
        assert r.status_code == 200
        session = r.get_json()['session']
        saw_error = False
        for _ in range(10):
            pr = c.get(f'/progress/{session}')
            js = pr.get_json()
            if js.get('done') and js.get('phase')=='error' and js.get('error'):
                saw_error = True
                break
            sleep(0.8)
        assert saw_error
