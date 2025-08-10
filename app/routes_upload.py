import uuid
from pathlib import Path

from flask import Blueprint, current_app, request, jsonify
from werkzeug.utils import secure_filename


bp = Blueprint("upload", __name__)

ALLOWED_EXTS = {".wav", ".aiff", ".aif", ".flac", ".mp3"}


def _ext_ok(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTS


@bp.post("/upload")
def upload():
    if "file" not in request.files:
        return jsonify(ok=False, error="No file part"), 400

    f = request.files["file"]
    if f.filename == "":
        return jsonify(ok=False, error="Empty filename"), 400

    if not _ext_ok(f.filename):
        return jsonify(ok=False, error="Unsupported file type"), 415

    session = request.form.get("session") or uuid.uuid4().hex
    root: Path = Path(current_app.config["UPLOAD_ROOT"]) / session
    root.mkdir(parents=True, exist_ok=True)

    ext = Path(f.filename).suffix.lower()
    safe_name = secure_filename(Path(f.filename).name)
    dst = root / f"input{ext}"
    f.save(dst)

    # Persist original name for later use
    (root / "meta.txt").write_text(safe_name, encoding="utf-8")

    return (
        jsonify(
            {
                "ok": True,
                "session": session,
                "filename": safe_name,
                "size": dst.stat().st_size,
            }
        ),
        200,
    )

