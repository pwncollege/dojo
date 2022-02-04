import sys
import os

from itsdangerous.exc import BadSignature
from CTFd.models import db
from CTFd.utils.user import get_current_user
from CTFd.utils.plugins import override_template
from CTFd.plugins import register_plugin_assets_directory, register_admin_plugin_menu_bar
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.plugins.flags import FLAG_CLASSES, BaseFlag, FlagException

from .config import bootstrap
from .models import DojoChallenges
from .utils import unserialize_user_flag
from .pages.challenges import challenges_listing, challenges
from .pages.scoreboard import scoreboard_listing
from .pages.workspace import workspace
from .pages.settings import settings
from .pages.discord import discord
from .pages.grades import grades
from .pages.writeups import writeups
from .api import api


class DojoChallenge(BaseChallenge):
    id = "dojo"
    name = "dojo"
    challenge_model = DojoChallenges


class DojoFlag(BaseFlag):
    name = "dojo"

    @staticmethod
    def compare(chal_key_obj, provided):
        current_account_id = get_current_user().account_id
        current_challenge_id = chal_key_obj.challenge_id

        try:
            account_id, challenge_id = unserialize_user_flag(provided)
        except BadSignature:
            return False

        if account_id != current_account_id:
            raise FlagException("This flag is not yours!")

        if challenge_id != current_challenge_id:
            raise FlagException("This flag is not for this challenge!")

        return True


def load(app):
    dir_path = os.path.dirname(os.path.realpath(__file__))

    db.create_all()

    register_plugin_assets_directory(
        app, base_path="/plugins/dojo_plugin/assets/"
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
        bootstrap()
