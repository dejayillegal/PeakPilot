import os
import threading
from pathlib import Path
from datetime import datetime, timezone

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    abort,
    make_response,
)

from .pipeline import run_pipeline, init_progress, read_json, atomic_write_json


def ensure_dir(p: Path) -> None:
    """Create directory *p* if it doesn't exist."""
    try:
        p.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:  # pragma: no cover - unexpected on CI
        raise RuntimeError(f"Cannot create directory: {p}") from exc


def resolve_work_dir() -> Path:
    """Resolve the working directory used for uploads and outputs."""
    root = Path(__file__).resolve().parent.parent
    env = os.environ.get("WORK_DIR")
    if env:
        p = Path(env).expanduser()
        if not p.is_absolute():
            p = root / p
    else:
        p = Path("/tmp/peakpilot")
    return p


def create_app() -> Flask:
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB limit
    app.config["JSON_SORT_KEYS"] = False

    work_dir = resolve_work_dir()
    ensure_dir(work_dir)
    sessions_root = work_dir / "sessions"
    ensure_dir(sessions_root)
    app.config["UPLOAD_ROOT"] = sessions_root
    app.config["WORK_DIR"] = str(work_dir)

    @app.get("/")
    def index():  # pragma: no cover - trivial
        return render_template("index.html")

    @app.get("/healthz")
    def healthz():  # pragma: no cover - simple
        import shutil

        ffmpeg_ok = shutil.which("ffmpeg") is not None
        ffprobe_ok = shutil.which("ffprobe") is not None
        return (
            jsonify(
                {
                    "ok": True,
                    "time_utc": datetime.now(timezone.utc).isoformat(),
                    "ffmpeg": ffmpeg_ok,
                    "ffprobe": ffprobe_ok,
                    "upload_dir": str(sessions_root),
                }
            ),
            200,
        )

    @app.post("/start")
    def start():
        data = request.get_json(silent=True) or {}
        session = data.get("session")
        if not session:
            return jsonify(error="Missing session"), 400

        sess_dir = sessions_root / session
        if not sess_dir.exists():
            return jsonify(error="Unknown session"), 400

<<<<<<< HEAD
        files = list(sess_dir.glob("input.*"))
        if not files:
            return jsonify(error="No uploaded file for this session"), 400
=======
        seed = {
            "percent": 0,
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
>>>>>>> 7dab702 (Refine processing pipeline and progress reporting)

        in_path = files[0]
        outdir = sess_dir / "outputs"
        ensure_dir(outdir)

        progress_path = sess_dir / "progress.json"
        init = init_progress()
        atomic_write_json(progress_path, init)

        t = threading.Thread(
            target=run_pipeline, args=(session, str(sess_dir), str(in_path)), daemon=True
        )
        t.start()
        return jsonify({"ok": True, "session": session}), 200

    @app.get("/progress/<session>")
<<<<<<< HEAD
    def progress(session: str):
        sess_dir = sessions_root / session
        progress_path = sess_dir / "progress.json"
        if not progress_path.exists():
            return jsonify({"error": "Session not found"}), 404
        data = read_json(progress_path)
        resp = make_response(jsonify(data))
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
=======
    def progress(session):
        p = progress_path(os.path.join(app.config["UPLOAD_FOLDER"], session))
        if not os.path.exists(p):
            resp = make_response(
                json.dumps(
                    {
                        "percent": 0,
                        "phase": "starting",
                        "message": "Starting…",
                        "done": False,
                        "error": None,
                    }
                ),
                200,
            )
        else:
            with open(p, "r", encoding="utf-8") as fh:
                resp = make_response(fh.read(), 200)
        resp.headers["Content-Type"] = "application/json"
        resp.headers["Cache-Control"] = "no-store, max-age=0"
>>>>>>> 7dab702 (Refine processing pipeline and progress reporting)
        return resp

    @app.get("/download/<session>/<path:filename>")
    def download(session: str, filename: str):
        sess_dir = sessions_root / session
        out_dir = sess_dir / "outputs"
        full = (out_dir / filename).resolve()
        if not full.exists() or not str(full).startswith(str(out_dir)):
            abort(404)
        return send_from_directory(out_dir, filename, as_attachment=True)

    # Register upload blueprint
    from .routes_upload import bp as upload_bp

    app.register_blueprint(upload_bp)

    return app


