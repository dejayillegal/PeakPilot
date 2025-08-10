import os, uuid, threading, json
from flask import Flask, request, jsonify, send_from_directory, render_template, make_response

from .pipeline import run_pipeline, new_session_dir, write_json_atomic, progress_path, ffprobe_ok


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["UPLOAD_FOLDER"] = "/tmp/peakpilot"
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "ffmpeg": ffprobe_ok("ffmpeg"), "ffprobe": ffprobe_ok("ffprobe")})

    @app.post("/start")
    def start():
        f = request.files.get("audio")
        if not f:
            return jsonify({"error": "No audio file provided (form field must be 'audio')."}), 400

        session = uuid.uuid4().hex[:12]
        sess_dir = new_session_dir(app.config["UPLOAD_FOLDER"], session)
        src_path = os.path.join(sess_dir, "upload")
        f.save(src_path)

        seed = {
            "percent": 1,
            "phase": "starting",
            "message": "Starting…",
            "done": False,
            "error": None,
            "downloads": {"club": None, "streaming": None, "premaster": None, "custom": None, "zip": None, "session_json": None},
            "metrics": {
                "club": {"input": {}, "output": {}},
                "streaming": {"input": {}, "output": {}},
                "premaster": {"input": {}, "output": {}},
                "custom": {"input": {}, "output": {}},
                "advisor": {
                    "recommended_preset": "",
                    "input_I": None,
                    "input_TP": None,
                    "input_LRA": None,
                    "analysis": {},
                    "ai_adjustments": {},
                },
            },
            "timeline": {"sec": [], "short_term": [], "tp_flags": []},
        }
        write_json_atomic(progress_path(sess_dir), seed)

        params = request.form.to_dict(flat=True)
        stems = {}
        gains = {}
        t = threading.Thread(target=run_pipeline, args=(session, sess_dir, src_path, params, stems, gains), daemon=True)
        t.start()

        return jsonify({"session": session, "progress_url": f"/progress/{session}"})

    @app.get("/progress/<session>")
    def progress(session):
        p = progress_path(os.path.join(app.config["UPLOAD_FOLDER"], session))
        if not os.path.exists(p):
            resp = make_response(json.dumps({"percent": 1, "phase": "starting", "message": "Starting…", "done": False, "error": None}), 200)
        else:
            with open(p, "r", encoding="utf-8") as fh:
                resp = make_response(fh.read(), 200)
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp

    @app.get("/download/<session>/<path:filename>")
    def download(session, filename):
        sess_dir = os.path.join(app.config["UPLOAD_FOLDER"], session)
        safe = os.path.abspath(sess_dir)
        if not os.path.abspath(os.path.join(sess_dir, filename)).startswith(safe):
            return jsonify({"error": "Invalid path"}), 400
        return send_from_directory(sess_dir, filename, as_attachment=True)

    return app


app = create_app()

__all__ = ["create_app", "app"]

