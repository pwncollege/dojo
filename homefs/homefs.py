from flask import Flask
from werkzeug.routing import BaseConverter

from volume import setup_volume_storage, Volume
from volume_server import volume_server
from volume_driver import volume_driver


class VolumeConverter(BaseConverter):
    def to_python(self, value):
        return Volume(value)

    def to_url(self, value):
        return value.name


def create_app():
    setup_volume_storage()

    app = Flask(__name__)

    app.url_map.converters["volume"] = VolumeConverter

    app.register_blueprint(volume_driver, url_prefix="/")
    app.register_blueprint(volume_server, url_prefix="/volume")

    return app
