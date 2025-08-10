import os
import threading
from pathlib import Path
from flask import (
    Flask,
    request,
    render_template,
    jsonify,
    url_for,
    send_from_directory,
    current_app,
)
from werkzeug.utils import secure_filename

from .pipeline import (
    ALLOWED_EXTS,
    PRESETS,
    allowed_file,
    new_session_dir,
    progress_path,
    write_json,
    read_json,
    base_progress,
    update_progress,
    run_pipeline,
    ensure_ffmpeg,
    init_app,
)


def create_app():
    base_dir = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        static_folder=str(base_dir / "static"),
        template_folder=str(base_dir / "templates"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512 MB
    app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", "/tmp/peakpilot")
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    init_app(app)

    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html", presets=list(PRESETS.keys()))

    @app.route("/start", methods=["POST"])
    def start():
        f = request.files.get("audio")
        if not f or f.filename == "":
            return jsonify({"error": "No file"}), 400
        if not allowed_file(f.filename):
            return jsonify({"error": "Unsupported type"}), 400

        session, d = new_session_dir()
        src = d / secure_filename(f.filename)
        f.save(str(src))

        stems, gains = {}, {}
        for role in ["vocals", "drums", "bass", "other"]:
            sf = request.files.get(f"stems[{role}]")
            if sf and sf.filename:
                p = d / secure_filename(sf.filename)
                sf.save(str(p))
                stems[role] = p
                gains[role] = float(request.form.get(f"gains[{role}]", "1.0"))

        params = {
            "preset": request.form.get("preset", "club"),
            "bits": int(request.form.get("bits", PRESETS.get(request.form.get("preset", "club"), PRESETS["club"])["bits"])),
            "dither": request.form.get("dither") or None,
            "trim": request.form.get("trim", "true").lower() == "true",
            "pad_ms": int(request.form.get("pad_ms", "100")),
            "smart_limiter": request.form.get("smart_limiter", "false").lower() == "true",
            "do_trim_pad": request.form.get("do_trim_pad", "true").lower() == "true",
        }

        write_json(progress_path(session), base_progress())
        update_progress(
            session,
            1,
            "queued",
            "Queued",
            patch={
                "preset": params["preset"],
                "options": {
                    "trim": params["trim"],
                    "pad_ms": params["pad_ms"],
                    "smart_limiter": params["smart_limiter"],
                    "bits": params["bits"],
                    "dither": params["dither"],
                },
            },
        )

        t = threading.Thread(
            target=run_pipeline,
            args=(session, src, params, stems if stems else None, gains if gains else None),
            daemon=True,
        )
        t.start()

        return jsonify({"session": session, "progress_url": url_for("progress", session=session, _external=True)})

    @app.route("/progress/<session>", methods=["GET"])
    def progress(session: str):
        resp = jsonify(read_json(progress_path(session), base_progress()))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/download/<session>/<path:file>", methods=["GET"])
    def download_file(session: str, file: str):
        d = Path(current_app.config["UPLOAD_FOLDER"]) / session
        if not d.exists():
            return "Not found", 404
        return send_from_directory(str(d), file, as_attachment=True)

    @app.route("/healthz", methods=["GET"])
    def healthz():
        ffmpeg_ok, ffprobe_ok = ensure_ffmpeg()
        return jsonify({"status": "ok", "ffmpeg": ffmpeg_ok, "ffprobe": ffprobe_ok})

    return app


# instantiate for convenience
app = create_app()

__all__ = ["create_app", "app", "allowed_file", "PRESETS"]

