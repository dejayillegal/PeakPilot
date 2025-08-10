import os
from flask import Blueprint, request, jsonify, current_app

from .util_fs import clear_session

bp = Blueprint('clear', __name__)


@bp.post('/clear')
def clear_route():
    data = request.get_json(silent=True) or request.form
    session = data.get('session') if data else None
    if not session:
        return jsonify({'ok': False, 'error': 'missing session'}), 400
    sess_dir = os.path.join(current_app.config['SESSIONS_DIR'], session)
    clear_session(sess_dir)
    return jsonify({'ok': True})
