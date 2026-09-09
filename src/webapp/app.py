"""Flask app-factory.

Resolvet template/static-mappen relatief aan sys._MEIPASS wanneer
gefrozen (PyInstaller) - Flask's automatische pad-detectie werkt niet
in een --onefile exe, dit is een bekende valkuil (zie packaging-stap
in het implementatieplan).
"""

import sys
from pathlib import Path

from flask import Flask

from ..version import get_version


def _webapp_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "src" / "webapp"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def create_app() -> Flask:
    base = _webapp_dir()
    app = Flask(
        __name__,
        template_folder=str(base / "templates"),
        static_folder=str(base / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB, ruim voor grote plattegrond-PDF's

    from .routes import bp

    app.register_blueprint(bp)

    @app.context_processor
    def inject_version():
        return {"app_version": get_version()}

    return app
