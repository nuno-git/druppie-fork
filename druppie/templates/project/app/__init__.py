import os

from flask import Flask, jsonify, send_from_directory

from app.database import init_db


def create_app():
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
    app = Flask(__name__)

    from app.routes import api

    app.register_blueprint(api, url_prefix="/api")

    @app.route("/health")
    def health():
        return jsonify(status="ok")

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        if path and os.path.isfile(os.path.join(static_dir, path)):
            return send_from_directory(static_dir, path)
        return send_from_directory(static_dir, "index.html")

    with app.app_context():
        init_db()

    return app
