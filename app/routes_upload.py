import os
from flask import Blueprint, request, jsonify, current_app

from .util_fs import (
    generate_session,
    ensure_session,
    clear_session,
    save_upload,
)

bp = Blueprint('upload', __name__)


@bp.post('/upload')
def upload():
    file = request.files.get('file')
    if not file:
        return jsonify({'ok': False, 'error': 'no file'}), 400

    session = request.form.get('session') or generate_session()
    reset = request.form.get('reset') == '1'
    base = current_app.config['UPLOAD_ROOT']
    sess_dir = ensure_session(base, session)
    if reset:
        clear_session(sess_dir)
        sess_dir = ensure_session(base, session)

    try:
        path, size = save_upload(file, sess_dir)
    except ValueError:
        return jsonify({'ok': False, 'error': 'unsupported file type'}), 400

    # remove old outputs
    for fname in os.listdir(sess_dir):
        if fname.startswith(('club_', 'stream_', 'premaster')) or fname.endswith('_info.json') or fname == 'manifest.json':
            os.remove(os.path.join(sess_dir, fname))

    return jsonify({'ok': True, 'session': session, 'filename': file.filename, 'size': size})
