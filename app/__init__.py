from flask import Flask
from pathlib import Path
import os, tempfile, logging



def _resolve_writable_dir(preferred: str) -> Path:
    p = Path(preferred)
    try:
        p.mkdir(parents=True, exist_ok=True)
        test = p / ".writetest"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        return p
    except Exception as e:
        logging.warning(
            "UPLOAD_ROOT '%s' not writable (%s). Falling back to tmp.", p, e
        )
        fb = Path(tempfile.gettempdir()) / "peakpilot_sessions"
        fb.mkdir(parents=True, exist_ok=True)
        return fb


def create_app():
    root_dir = Path(__file__).resolve().parent.parent
    template_dir = root_dir / "templates"
    static_dir = root_dir / "static"

    app = Flask(__name__, template_folder=str(template_dir), static_folder=str(static_dir))
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    pref = os.environ.get("UPLOAD_ROOT", "/mnt/data/sessions")
    app.config["UPLOAD_ROOT"] = _resolve_writable_dir(pref)
    app.config["JSON_SORT_KEYS"] = False

    logging.getLogger(__name__).info(
        "Using UPLOAD_ROOT: %s", app.config["UPLOAD_ROOT"]
    )

    # Blueprints
    from .routes_main import bp as main_bp
    from .routes_upload import bp as upload_bp
    try:
        from .routes_clear import bp as clear_bp
    except Exception:
        clear_bp = None

    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp)
    if clear_bp:
        app.register_blueprint(clear_bp)

    return app


__all__ = ["create_app"]
