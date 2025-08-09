import uuid
from flask import Flask

import settings
from .routes import bp


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(settings)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "dev-" + uuid.uuid4().hex
    app.register_blueprint(bp)
    return app
