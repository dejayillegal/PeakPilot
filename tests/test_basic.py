import pytest
import app


@pytest.fixture
def client():
    app.app.config['TESTING'] = True
    with app.app.test_client() as client:
        yield client


def test_allowed_file():
    assert app.allowed_file('test.wav')
    assert app.allowed_file('song.mp3')
    assert not app.allowed_file('bad.txt')


def test_healthz(client):
    rv = client.get('/healthz')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data.get('status') == 'ok'
