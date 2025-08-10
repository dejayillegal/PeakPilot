import os
from flask import Flask

from .routes_main import bp as main_bp
from .routes_upload import bp as upload_bp
from .routes_clear import bp as clear_bp


def create_app():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    template_dir = os.path.join(root_dir, 'templates')
    static_dir = os.path.join(root_dir, 'static')

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
    sessions = os.path.join(root_dir, 'sessions')
    app.config['SESSIONS_DIR'] = sessions
    os.makedirs(sessions, exist_ok=True)

    app.register_blueprint(main_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(clear_bp)
    return app


app = create_app()

__all__ = ['create_app', 'app']
