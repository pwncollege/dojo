import os

from flask import Blueprint, current_app
from flask_restx import Api
from CTFd.models import db
from CTFd.forms import Forms
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user
from CTFd.utils.plugins import register_script, override_template
from CTFd.plugins import (
    register_plugin_assets_directory,
    register_user_page_menu_bar,
    register_admin_plugin_menu_bar,
)
from CTFd.plugins.challenges import CHALLENGE_CLASSES
from CTFd.plugins.flags import FLAG_CLASSES

from .bootstrap import bootstrap_namespace, Bootstrap
from .docker_challenge import DockerChallenge, docker_namespace
from .user_flag import UserFlag, user_flag_namespace
from .ssh_key import SSHKeys, SSHKeyForm, ssh_key_settings, ssh_key_namespace
from .scoreboard import scoreboard_listing
from .terminal import terminal, terminal_namespace
from .challenges import challenges_listing, challenges
from .workspace import workspace
from .binary_ninja import binary_ninja_namespace
from .belts import belts_namespace
from .writeups import writeups
from .grades import grades


def load(app):
    dir_path = os.path.dirname(os.path.realpath(__file__))

    db.create_all()

    register_plugin_assets_directory(
        app, base_path="/plugins/pwncollege_plugin/assets/"
    )

    CHALLENGE_CLASSES["docker"] = DockerChallenge

    FLAG_CLASSES["user"] = UserFlag

    ssh_key_template_path = os.path.join(dir_path, "assets", "ssh_key", "settings.html")
    override_template("settings.html", open(ssh_key_template_path).read())
    app.view_functions["views.settings"] = ssh_key_settings
    Forms.keys = {"SSHKeyForm": SSHKeyForm}

    scoreboard_template_path = os.path.join(
        dir_path, "assets", "scoreboard", "scoreboard.html"
    )
    override_template("scoreboard.html", open(scoreboard_template_path).read())
    app.view_functions["scoreboard.listing"] = scoreboard_listing

    blueprint = Blueprint("pwncollege_api", __name__)
    api = Api(blueprint, version="v1", doc=current_app.config.get("SWAGGER_UI"))
    api.add_namespace(bootstrap_namespace, "/bootstrap")
    api.add_namespace(docker_namespace, "/docker")
    api.add_namespace(user_flag_namespace, "/user_flag")
    api.add_namespace(ssh_key_namespace, "/ssh_key")
    api.add_namespace(terminal_namespace, "/terminal")
    api.add_namespace(binary_ninja_namespace, "/binary_ninja")
    api.add_namespace(belts_namespace, "/belts")
    app.register_blueprint(blueprint, url_prefix="/pwncollege_api/v1")

    challenges_template_path = os.path.join(
        dir_path, "assets", "challenges", "challenges.html"
    )
    override_template("challenges.html", open(challenges_template_path).read())
    app.view_functions["challenges.listing"] = challenges_listing
    app.register_blueprint(challenges)

    app.register_blueprint(workspace)

    app.register_blueprint(writeups)
    register_admin_plugin_menu_bar("Writeups", "/admin/writeups")

    Bootstrap.bootstrap()
