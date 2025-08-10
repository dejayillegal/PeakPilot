import time

def test_progress_error_lifecycle(client, tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"notawav")
    with open(bad, "rb") as f:
        r = client.post("/start", data={"audio": (f, "bad.wav")}, content_type="multipart/form-data")
    assert r.status_code == 200
    session = r.get_json()["session"]

    done = False
    for _ in range(20):
        pr = client.get(f"/progress/{session}")
        assert pr.status_code == 200
        pj = pr.get_json()
        assert "done" in pj and "error" in pj
        if pj["done"]:
            done = True
            assert pj["phase"] == "error"
            assert pj["error"]
            break
        time.sleep(0.2)
    assert done
