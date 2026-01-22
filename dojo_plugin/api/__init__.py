import os
from flask import Blueprint, current_app, make_response, request
from ...dojo_plugin import config
from flask_restx import Api

from ..utils.request_logging import log_exception
from .v1.activity import activity_namespace
from .v1.auth import auth_namespace
from .v1.belts import belts_namespace
from .v1.discord import discord_namespace
from .v1.docker import docker_namespace
from .v1.dojos import dojos_namespace
from .v1.feed import feed_namespace
from .v1.score import score_namespace
from .v1.scoreboard import scoreboard_namespace
from .v1.ssh_key import ssh_key_namespace
from .v1.workspace_tokens import workspace_tokens_namespace
from .v1.workspace import workspace_namespace
from .v1.search import search_namespace
from .v1.test_error import test_error_namespace
from .v1.user import user_namespace
from .v1.integration import integration_namespace

api = Blueprint("pwncollege_api", __name__)

# Get CORS origin from environment variable
cors_origin = config.CORS_ORIGINS

# Add CORS headers to all responses only if CORS origin is set
if cors_origin:
    @api.after_request
    def after_request(response):
        response.headers['Access-Control-Allow-Origin'] = cors_origin
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response

    # Handle OPTIONS preflight requests
    @api.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            response = make_response()
            response.headers['Access-Control-Allow-Origin'] = cors_origin
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Max-Age'] = '3600'
            return response


api_v1 = Api(api, version="v1", doc=current_app.config.get("SWAGGER_UI"))

@api_v1.errorhandler(Exception)
def handle_api_exception(error):
    log_exception(error, event_type="api_exception")
    raise


api_v1.add_namespace(activity_namespace, "/activity")
api_v1.add_namespace(auth_namespace, "/auth")
api_v1.add_namespace(user_namespace, "/users")
api_v1.add_namespace(belts_namespace, "/belts")
api_v1.add_namespace(discord_namespace, "/discord")
api_v1.add_namespace(docker_namespace, "/docker")
api_v1.add_namespace(dojos_namespace, "/dojos")
api_v1.add_namespace(feed_namespace, "/feed")
api_v1.add_namespace(score_namespace, "/score")
api_v1.add_namespace(scoreboard_namespace, "/scoreboard")
api_v1.add_namespace(ssh_key_namespace, "/ssh_key")
api_v1.add_namespace(workspace_tokens_namespace, "/workspace_tokens")
api_v1.add_namespace(workspace_namespace, "/workspace")
api_v1.add_namespace(search_namespace, "/search")
api_v1.add_namespace(test_error_namespace, "/test_error")
