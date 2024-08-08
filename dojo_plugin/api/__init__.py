from flask import Blueprint, current_app
from flask_restx import Api

from .v1.belts import belts_namespace
from .v1.bootstrap import bootstrap_namespace
from .v1.discord import discord_namespace
from .v1.docker import docker_namespace
from .v1.dojo import dojo_namespace
from .v1.score import score_namespace
from .v1.scoreboard import scoreboard_namespace
from .v1.ssh_key import ssh_key_namespace
from .v1.workspace_tokens import workspace_tokens_namespace
from .v1.workspace import workspace_namespace


api = Blueprint("pwncollege_api", __name__)

api_v1 = Api(api, version="v1", doc=current_app.config.get("SWAGGER_UI"))
api_v1.add_namespace(belts_namespace, "/belts")
api_v1.add_namespace(bootstrap_namespace, "/bootstrap")
api_v1.add_namespace(discord_namespace, "/discord")
api_v1.add_namespace(docker_namespace, "/docker")
api_v1.add_namespace(dojo_namespace, "/dojo")
api_v1.add_namespace(score_namespace, "/score")
api_v1.add_namespace(scoreboard_namespace, "/scoreboard")
api_v1.add_namespace(ssh_key_namespace, "/ssh_key")
api_v1.add_namespace(workspace_tokens_namespace, "/workspace_tokens")
api_v1.add_namespace(workspace_namespace, "/workspace")
