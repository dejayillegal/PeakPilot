import uuid
import os
import subprocess
from flask import Flask, jsonify

import settings
from .routes import bp


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(settings)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "dev-" + uuid.uuid4().hex
    app.register_blueprint(bp)
    
    @app.route("/healthz")
    def healthz():
        try:
            out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
            ver = out.stdout.splitlines()[0] if out.returncode == 0 and out.stdout else "missing"
        except Exception:
            ver = "missing"
        return jsonify(ok=True, ffmpeg=ver)

    @app.after_request
    def add_cors(resp):
        allow = os.getenv("ALLOWED_ORIGIN", "*")
        resp.headers["Access-Control-Allow-Origin"] = allow
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        return resp

    return app
