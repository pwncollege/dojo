import os
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

    homefs_db_path= STORAGE_ROOT / "homefs.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{homefs_db_path}"

    db.init_app(app)

    with app.app_context():
        db.create_all()

    app.url_map.converters["volume"] = VolumeConverter

    app.register_blueprint(volume_driver, url_prefix="/")
    app.register_blueprint(volume_server, url_prefix="/volume")

    return app
