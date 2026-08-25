import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask
from werkzeug.routing import BaseConverter

from models import db
from btrfs_volume import check_volume_storage, BTRFSVolume
from volume_server import volume_server
from volume_driver import volume_driver
from utils import file_lock


STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/data"))


class VolumeConverter(BaseConverter):
    def to_python(self, value):
        return BTRFSVolume(value)

    def to_url(self, value):
        return value.name


@file_lock("/run/homefs.lock")
def create_app():
    check_volume_storage()

    app = Flask(__name__)

    homefs_db_path = STORAGE_ROOT / "homefs.db"
    with closing(sqlite3.connect(homefs_db_path, timeout=30)) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if journal_mode != "wal":
            raise RuntimeError(f"Failed to enable WAL for {homefs_db_path}: {journal_mode}")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{homefs_db_path}"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"timeout": 30}}

    db.init_app(app)

    with app.app_context():
        db.create_all()

    app.url_map.converters["volume"] = VolumeConverter

    app.register_blueprint(volume_driver, url_prefix="/")
    app.register_blueprint(volume_server, url_prefix="/volume")

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    return app
