from flask import Blueprint, current_app
from flask_restx import Api

from .v1.bootstrap import bootstrap_namespace
from .v1.docker import docker_namespace
from .v1.scoreboard import scoreboard_namespace
from .v1.ssh_key import ssh_key_namespace
from .v1.private_dojo import private_dojo_namespace
from .v1.belts import belts_namespace


api = Blueprint("pwncollege_api", __name__)

api_v1 = Api(api, version="v1", doc=current_app.config.get("SWAGGER_UI"))
api_v1.add_namespace(bootstrap_namespace, "/bootstrap")
api_v1.add_namespace(docker_namespace, "/docker")
api_v1.add_namespace(scoreboard_namespace, "/scoreboard")
api_v1.add_namespace(ssh_key_namespace, "/ssh_key")
api_v1.add_namespace(private_dojo_namespace, "/private_dojo")
api_v1.add_namespace(belts_namespace, "/belts")
