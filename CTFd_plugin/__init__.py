import sys
import os

from CTFd.models import db
from CTFd.utils.plugins import override_template
from CTFd.plugins import register_plugin_assets_directory, register_admin_plugin_menu_bar
from CTFd.plugins.challenges import CHALLENGE_CLASSES
from CTFd.plugins.flags import FLAG_CLASSES

from .api.v1.bootstrap import Bootstrap
from .challenges import challenges_listing, challenges
from .api.v1.scoreboard import scoreboard_listing
from .api.v1.challenge import DojoChallenge
from .flag import DojoFlag
from .discord import discord
from .settings import settings
from .workspace import workspace
from .grades import grades
from .writeups import writeups
from .api import api


def load(app):
    dir_path = os.path.dirname(os.path.realpath(__file__))

    db.create_all()

    register_plugin_assets_directory(
        app, base_path="/plugins/pwncollege_plugin/assets/"
    )

    CHALLENGE_CLASSES["dojo"] = DojoChallenge
    FLAG_CLASSES["dojo"] = DojoFlag

    settings_template_path = os.path.join(dir_path, "assets", "settings", "settings.html")
    override_template("settings.html", open(settings_template_path).read())
    app.view_functions["views.settings"] = settings

    scoreboard_template_path = os.path.join(
        dir_path, "assets", "scoreboard", "scoreboard.html"
    )
    override_template("scoreboard.html", open(scoreboard_template_path).read())
    app.view_functions["scoreboard.listing"] = scoreboard_listing

    app.register_blueprint(api, url_prefix="/pwncollege_api/v1")

    challenges_template_path = os.path.join(
        dir_path, "assets", "challenges", "challenges.html"
    )
    override_template("challenges.html", open(challenges_template_path).read())
    app.view_functions["challenges.listing"] = challenges_listing
    app.register_blueprint(challenges)

    app.register_blueprint(discord)

    app.register_blueprint(workspace)

    app.register_blueprint(grades)
    register_admin_plugin_menu_bar("Grades", "/admin/grades")

    app.register_blueprint(writeups)
    register_admin_plugin_menu_bar("Writeups", "/admin/writeups")

    if os.path.basename(sys.argv[0]) != "manage.py":
        Bootstrap.bootstrap()
