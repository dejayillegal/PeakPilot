import os, uuid, threading, json
from flask import Flask, request, jsonify, render_template, make_response, send_file
from pathlib import Path
import shutil
from werkzeug.utils import secure_filename

from .pipeline import run_pipeline, new_session_dir, write_json_atomic, progress_path, ffprobe_ok, make_preview
def create_app():
    """Create and configure the Flask application.

    The project keeps its ``templates`` and ``static`` directories at the
    repository root rather than inside the ``app`` package.  When running the
    application Flask would look for these directories relative to the package
    and consequently fail to locate them, raising ``TemplateNotFound`` for
    ``index.html``.

    Determine the project root and point Flask at the correct directories so
    that template rendering and static file serving work in both development and
    production environments.
    """

    # Locate repository root (parent directory of this file's package)
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    template_dir = os.path.join(root_dir, "templates")
    static_dir = os.path.join(root_dir, "static")

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
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

        orig_name = f.filename or "upload"
        stem = Path(orig_name).stem
        import re
        safe_stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", stem).strip("_")
        if not safe_stem:
            safe_stem = "track"

        session = uuid.uuid4().hex[:12]
        sess_dir = new_session_dir(app.config["UPLOAD_FOLDER"], session)
        src_path = os.path.join(sess_dir, "upload")
        f.save(src_path)

        try:
            make_preview(Path(src_path), Path(sess_dir) / "input_preview.wav", sr=48000, stereo=True)
        except Exception:
            shutil.copyfile(src_path, os.path.join(sess_dir, "input_preview.wav"))

        seed = {
            "pct": 0,
            "status": "starting",
            "percent": 0,
            "phase": "starting",
            "message": "Starting…",
            "done": False,
            "error": None,
            "downloads": {"club": None, "streaming": None, "unlimited": None, "custom": None, "zip": None, "session_json": None},
            "metrics": {
                "input": {},
                "club": {},
                "streaming": {},
                "unlimited": {},
                "custom": {},
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
            "masters": {
                "club": {"state": "queued", "pct": 0, "message": ""},
                "streaming": {"state": "queued", "pct": 0, "message": ""},
                "unlimited": {"state": "queued", "pct": 0, "message": ""},
                "custom": {"state": "queued", "pct": 0, "message": ""},
            },
            "original_stem": safe_stem,
        }
        write_json_atomic(progress_path(sess_dir), seed)

        params = request.form.to_dict(flat=True)
        stems = {}
        gains = {}
        t = threading.Thread(
            target=run_pipeline,
            args=(session, sess_dir, src_path, params, stems, gains, orig_name, safe_stem),
            daemon=True,
        )
        t.start()

        return jsonify({"session": session, "progress_url": f"/progress/{session}"})

    @app.get("/progress/<session>")
    def progress(session):
        p = progress_path(os.path.join(app.config["UPLOAD_FOLDER"], session))
        if not os.path.exists(p):
            resp = make_response(
                json.dumps(
                    {
                        "pct": 0,
                        "status": "starting",
                        "percent": 0,
                        "phase": "starting",
                        "message": "Starting…",
                        "done": False,
                        "error": None,
                        "masters": {
                            "club": {"state": "queued", "pct": 0, "message": ""},
                            "streaming": {"state": "queued", "pct": 0, "message": ""},
                            "unlimited": {"state": "queued", "pct": 0, "message": ""},
                            "custom": {"state": "queued", "pct": 0, "message": ""},
                        },
                    }
                ),
                200,
            )
        else:
            with open(p, "r", encoding="utf-8") as fh:
                resp = make_response(fh.read(), 200)
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp

    from .util_fs import session_root

    @app.get("/download/<session>/<key>")
    def download(session, key):
        sess_dir = session_root(app.config["UPLOAD_FOLDER"], secure_filename(session))
        man_path = sess_dir / "manifest.json"
        if not man_path.exists():
            return ("No manifest", 404)
        man = json.loads(man_path.read_text())
        meta = man.get(key)
        if not meta:
            meta = next((v for v in man.values() if v.get("filename") == key), None)
        if not meta:
            return ("Unknown file key", 404)
        p = sess_dir / meta["filename"]
        if not p.exists():
            return ("File missing", 404)
        return send_file(p, mimetype="application/octet-stream", as_attachment=True, download_name=meta["filename"])

    from .routes.stream import bp as stream_bp
    app.register_blueprint(stream_bp)

    return app


app = create_app()

__all__ = ["create_app", "app"]

