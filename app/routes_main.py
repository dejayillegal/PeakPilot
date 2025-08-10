import os
import json
import threading
import shutil
from flask import Blueprint, current_app, jsonify, request, send_file, render_template

from .util_fs import (
    ensure_session,
    progress_path,
    write_progress,
    safe_join,
    load_manifest,
    sha256_file,
    get_input_path,
)
from .engine.mastering import run_mastering

bp = Blueprint('main', __name__)


@bp.get('/')
def index():
    return render_template('index.html')


@bp.post('/start')
def start():
    data = request.get_json(silent=True) or {}
    session = data.get('session')
    if not session:
        return jsonify({'ok': False, 'error': 'missing session'}), 400
    base = current_app.config['UPLOAD_ROOT']
    sess_dir = ensure_session(base, session)
    input_path = get_input_path(sess_dir)
    if not input_path:
        return jsonify({'ok': False, 'error': 'no input file'}), 400

    progress = {
        'status': 'starting',
        'pct': 0,
        'message': 'Starting…',
        'metrics': {
            'club': {'input': {}, 'output': {}},
            'stream': {'input': {}, 'output': {}},
            'unlimited': {'input': {}, 'output': {}},
        },
    }
    write_progress(sess_dir, progress)

    t = threading.Thread(target=run_mastering, args=(sess_dir, input_path), daemon=True)
    t.start()
    return jsonify({'ok': True})


@bp.get('/progress/<session>')
def progress(session):
    path = progress_path(os.path.join(current_app.config['UPLOAD_ROOT'], session))
    if not os.path.exists(path):
        return jsonify({'status': 'starting', 'pct': 0, 'message': 'Starting…', 'metrics': {}})
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    return jsonify(data)


@bp.get('/download/<session>/<key>')
def download(session, key):
    sess_dir = os.path.join(current_app.config['UPLOAD_ROOT'], session)
    manifest = load_manifest(sess_dir)
    if key not in manifest:
        return ('', 404)
    meta = manifest[key]
    try:
        path = safe_join(sess_dir, meta['filename'])
    except ValueError:
        return ('', 400)
    if sha256_file(path) != meta['sha256']:
        return jsonify({'error': 'checksum mismatch'}), 409
    return send_file(path, as_attachment=True, download_name=meta['filename'], mimetype=meta['type'])


@bp.get('/healthz')
def healthz():
    return jsonify({
        'status': 'ok',
        'ffmpeg': shutil.which('ffmpeg') is not None,
        'ffprobe': shutil.which('ffprobe') is not None,
    })
