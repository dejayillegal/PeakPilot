import hashlib
import io
import json
import time

import numpy as np
import soundfile as sf


def _make_sine():
    sr = 48000
    t = np.linspace(0, 2, sr * 2, False)
    wave = 0.1 * np.sin(2 * np.pi * 1000 * t)
    buf = io.BytesIO()
    sf.write(buf, wave, sr, subtype="PCM_24", format="WAV")
    buf.seek(0)
    return buf


def test_end_to_end_flow(client):
    data = _make_sine()
    r = client.post(
        "/upload",
        data={"file": (data, "tone.wav"), "reset": "1", "session": "sess"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    session = r.get_json()["session"]

    assert client.post("/start", json={"session": session}).status_code == 200

    for _ in range(120):
        j = client.get(f"/progress/{session}").get_json()
        assert j.get("status") != "error", j.get("message")
        if j.get("status") == "done":
            break
        time.sleep(0.5)
    else:
        raise AssertionError("mastering did not complete")

    upload_root = client.application.config["UPLOAD_ROOT"]
    sess_dir = upload_root / session  # tmp_path is pathlib.Path
    manifest_path = sess_dir / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    expected_keys = {
        "club_master.wav",
        "club_info.json",
        "stream_master.wav",
        "stream_info.json",
        "premaster_unlimited.wav",
        "premaster_unlimited_info.json",
        "input_preview.wav",
    }
    assert expected_keys.issubset(manifest.keys())

    for key in expected_keys:
        resp = client.get(f"/download/{session}/{key}")
        assert resp.status_code == 200
        assert resp.data
        h = hashlib.sha256(resp.data).hexdigest()
        assert h == manifest[key]["sha256"]

    # clear session
    assert client.post("/clear", json={"session": session}).status_code == 200
    assert not sess_dir.exists()


def test_checksum_mismatch_returns_409(client):
    data = _make_sine()
    r = client.post("/upload", data={"file": (data, "t.wav")}, content_type="multipart/form-data")
    session = r.get_json()["session"]
    client.post("/start", json={"session": session})
    for _ in range(120):
        if client.get(f"/progress/{session}").get_json().get("status") == "done":
            break
        time.sleep(0.5)
    sess_dir = client.application.config["UPLOAD_ROOT"] / session
    club = sess_dir / "club_master.wav"
    with open(club, "ab") as fh:
        fh.write(b"0")
    resp = client.get(f"/download/{session}/club_master.wav")
    assert resp.status_code == 409
