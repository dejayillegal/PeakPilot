import pytest

from app import create_app
from app.utils import fs


@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_allowed_file():
    assert fs.allowed_file('test.wav')
    assert not fs.allowed_file('bad.mp3')


def test_healthz(client):
    rv = client.get('/healthz')
    assert rv.status_code == 200
    data = rv.get_json()
    assert 'ok' in data
