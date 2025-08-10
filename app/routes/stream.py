from flask import Blueprint, current_app, request, abort, Response
from pathlib import Path
import os

from app.util_fs import session_root

bp = Blueprint("stream", __name__)


def _open_range(path: Path, range_header: str):
    size = path.stat().st_size
    if not range_header or '=' not in range_header:
        with path.open('rb') as f:
            return 200, f.read(), 0, size - 1, size
    _, rng = range_header.split('=', 1)
    start_s, _, end_s = rng.partition('-')
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else size - 1
    start = max(0, start)
    end = min(size - 1, end)
    length = end - start + 1
    f = path.open('rb')
    f.seek(start)
    return 206, f.read(length), start, end, size


@bp.get("/stream/<session>/<key>")
def stream(session, key):
    root = session_root(current_app.config["UPLOAD_FOLDER"], session)
    p = root / key
    if not p.exists() or p.is_dir():
        abort(404)
    code, chunk, start, end, size = _open_range(p, request.headers.get("Range"))
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "audio/wav",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    }
    if code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return Response(chunk, status=code, headers=headers)
