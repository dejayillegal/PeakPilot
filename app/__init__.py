import os
import threading
import secrets
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, render_template, request, jsonify, send_from_directory, abort, make_response, session as flask_session

from .pipeline import run_pipeline, init_progress, read_json, atomic_write_json

ALLOWED = {'.wav', '.aiff', '.aif', '.flac', '.mp3'}
MAX_UPLOAD_MB = 512


def session_id():
    if 'sid' not in flask_session:
        flask_session['sid'] = secrets.token_hex(8)
    return flask_session['sid']


def ensure_dir(p: Path):
    """Create directory *p* if it doesn't exist."""
    try:
        p.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
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


def has_audio(p: Path) -> bool:
    if not p.exists():
        return False
    for x in p.iterdir():
        if x.is_file() and x.suffix.lower() in ALLOWED and x.stat().st_size > 0:
            return True
    return False


def create_app():
    app = Flask(__name__, static_folder='../static', template_folder='../templates')
    app.secret_key = os.environ.get('SECRET_KEY', 'dev')
    app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

    work_dir = resolve_work_dir()
    ensure_dir(work_dir)
    app.config['WORK_DIR'] = str(work_dir)

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/healthz')
    def healthz():
        import shutil
        ffmpeg_ok = shutil.which('ffmpeg') is not None
        ffprobe_ok = shutil.which('ffprobe') is not None
        return jsonify({
            'ok': True,
            'time_utc': datetime.now(timezone.utc).isoformat(),
            'ffmpeg': ffmpeg_ok,
            'ffprobe': ffprobe_ok,
            'upload_dir': str(work_dir)
        }), 200

    @app.post('/upload')
    def upload():
        sid = session_id()
        updir = work_dir / sid / 'uploads'
        ensure_dir(updir)
        f = request.files.get('file')
        if not f or f.filename == '':
            return jsonify({"error": "NO_FILE: Select a file."}), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED:
            return jsonify({"error": "UNSUPPORTED: Use WAV/AIFF/FLAC/MP3."}), 400
        dst = updir / f.filename
        f.save(dst)
        if dst.stat().st_size == 0:
            dst.unlink(missing_ok=True)
            return jsonify({"error": "EMPTY: File is empty."}), 400
        return jsonify({"ok": True})

    @app.post('/start')
    def start():
        sid = session_id()
        sess_dir = work_dir / sid
        updir = sess_dir / 'uploads'
        outdir = sess_dir / 'outputs'
        ensure_dir(outdir)
        if not has_audio(updir):
            return jsonify({"error": "NO_AUDIO: Upload an audio file before analyzing."}), 400
        # pick first audio file
        files = [x for x in updir.iterdir() if x.is_file() and x.suffix.lower() in ALLOWED and x.stat().st_size > 0]
        in_path = files[0]
        progress_path = sess_dir / 'progress.json'
        init = init_progress()
        atomic_write_json(progress_path, init)
        t = threading.Thread(target=run_pipeline, args=(sid, str(sess_dir), str(in_path)), daemon=True)
        t.start()
        return jsonify({"ok": True, "session": sid}), 200

    @app.get('/progress/<session>')
    def progress(session):
        sess_dir = work_dir / session
        progress_path = sess_dir / 'progress.json'
        if not progress_path.exists():
            return jsonify({'error': 'Session not found'}), 404
        data = read_json(progress_path)
        resp = make_response(jsonify(data))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp

    @app.get('/download/<session>/<path:filename>')
    def download(session, filename):
        sess_dir = work_dir / session
        out_dir = sess_dir / 'outputs'
        full = (out_dir / filename).resolve()
        if not full.exists() or not str(full).startswith(str(out_dir)):
            abort(404)
        return send_from_directory(out_dir, filename, as_attachment=True)

    return app
