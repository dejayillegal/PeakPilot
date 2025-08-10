import pytest


def test_index_page(client):
    resp = client.get('/')
    assert resp.status_code == 200
    html = resp.data.decode()
    assert 'PeakPilot' in html
    assert '<div id="masterCanvases"' in html
    assert '<button id="play"' in html and 'pp-play' in html
    if 'id="metrics"' in html:
        assert 'hidden' in html or 'aria-hidden="true"' in html
