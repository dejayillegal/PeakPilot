import os
import uuid
import threading
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, send_from_directory, abort, make_response

from .pipeline import run_pipeline, init_progress, read_json, atomic_write_json, UPLOAD_KEY

MAX_UPLOAD_MB = 512


def create_app():
    app = Flask(__name__, static_folder='../static', template_folder='../templates')

    # Core config
    base = os.environ.get('UPLOAD_FOLDER', '/tmp/peakpilot')
    os.makedirs(base, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = base
    app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024

    # Routes
    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/healthz')
    def healthz():
        # Simple tool check
        import shutil, subprocess
        ffmpeg_ok = shutil.which('ffmpeg') is not None
        ffprobe_ok = shutil.which('ffprobe') is not None
        return jsonify({
            'ok': True,
            'time_utc': datetime.now(timezone.utc).isoformat(),
            'ffmpeg': ffmpeg_ok,
            'ffprobe': ffprobe_ok,
            'upload_dir': app.config['UPLOAD_FOLDER']
        }), 200

    @app.post('/start')
    def start():
        if UPLOAD_KEY not in request.files:
            return jsonify({'error': 'No file field named "audio"'}), 400
        f = request.files[UPLOAD_KEY]
        if not f.filename:
            return jsonify({'error': 'Empty filename'}), 400

        session = uuid.uuid4().hex[:12]
        sess_dir = os.path.join(app.config['UPLOAD_FOLDER'], session)
        up_dir = os.path.join(sess_dir, 'uploads')
        out_dir = os.path.join(sess_dir, 'outputs')
        os.makedirs(up_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)

        # Save upload
        in_path = os.path.join(up_dir, f.filename)
        f.save(in_path)

        # Seed progress BEFORE thread (fixes "Starting… forever")
        progress_path = os.path.join(sess_dir, 'progress.json')
        init = init_progress()
        atomic_write_json(progress_path, init)

        # Kick pipeline thread (daemon)
        t = threading.Thread(
            target=run_pipeline,
            args=(session, sess_dir, in_path),
            daemon=True
        )
        t.start()

        return jsonify({'session': session}), 200

    @app.get('/progress/<session>')
    def progress(session):
        sess_dir = os.path.join(app.config['UPLOAD_FOLDER'], session)
        progress_path = os.path.join(sess_dir, 'progress.json')
        if not os.path.exists(progress_path):
            return jsonify({'error': 'Session not found'}), 404
        data = read_json(progress_path)
        resp = make_response(jsonify(data))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp

    @app.get('/download/<session>/<path:filename>')
    def download(session, filename):
        sess_dir = os.path.join(app.config['UPLOAD_FOLDER'], session)
        out_dir = os.path.join(sess_dir, 'outputs')
        if not os.path.commonpath([out_dir, os.path.join(out_dir, filename)]) == out_dir:
            abort(400)
        if not os.path.exists(os.path.join(out_dir, filename)):
            abort(404)
        return send_from_directory(out_dir, filename, as_attachment=True)

    return app
