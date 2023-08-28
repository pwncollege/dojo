import sys
import os
import datetime
from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import urlparse, urlunparse

from flask import Response, request, redirect
from flask.json import JSONEncoder
from itsdangerous.exc import BadSignature
from CTFd.models import db, Challenges
from CTFd.utils.user import get_current_user
from CTFd.plugins import register_admin_plugin_menu_bar
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.plugins.flags import FLAG_CLASSES, BaseFlag, FlagException

from .config import DOJO_HOST, bootstrap
from .utils import unserialize_user_flag
from .pages.dojos import dojos, dojos_override
from .pages.dojo import dojo
from .pages.workspace import workspace, redirect_workspace_referers
from .pages.desktop import desktop
from .pages.sensai import sensai
from .pages.users import users
from .pages.settings import settings_override
from .pages.discord import discord, maybe_award_belt
from .pages.course import course
from .pages.writeups import writeups
from .api import api


# TODO: upgrade to flask 2.1
# https://github.com/pallets/werkzeug/issues/2352
Response.autocorrect_location_header = False


class DojoChallenge(BaseChallenge):
    id = "dojo"
    name = "dojo"
    challenge_model = Challenges


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

        try:
            maybe_award_belt(current_account_id, ignore_challenge_id=current_challenge_id)
        except Exception as e:
            print(f"ERROR: Maybe awarding belt failed: {e}", file=sys.stderr, flush=True)

        return True


def shell_context_processor():
    import CTFd.models as ctfd_models
    import CTFd.plugins.dojo_plugin.models as dojo_models
    result = dict()
    result.update(ctfd_models.__dict__.items())
    result.update(dojo_models.__dict__.items())
    return result


# TODO: CTFd should include "Date" header
def DatedEmailMessage():
    msg = EmailMessage()
    msg["Date"] = formatdate()
    return msg
import CTFd.utils.email.smtp
CTFd.utils.email.smtp.EmailMessage = DatedEmailMessage


def redirect_dojo():
    parsed_url = urlparse(request.url)
    if parsed_url.netloc.split(':')[0] != DOJO_HOST:
        netloc = DOJO_HOST
        if ':' in parsed_url.netloc:
            netloc += ':' + parsed_url.netloc.split(':')[1]
        redirect_url = urlunparse((
            parsed_url.scheme,
            netloc,
            parsed_url.path,
            parsed_url.params,
            parsed_url.query,
            parsed_url.fragment,
        ))
        return redirect(redirect_url, code=301)


def load(app):
    db.create_all()

    CHALLENGE_CLASSES["dojo"] = DojoChallenge
    FLAG_CLASSES["dojo"] = DojoFlag

    app.view_functions["views.settings"] = settings_override
    app.view_functions["challenges.listing"] = dojos_override
    del app.view_functions["scoreboard.listing"]
    del app.view_functions["users.private"]
    del app.view_functions["users.public"]
    del app.view_functions["users.listing"]

    if not app.debug:
        app.before_request(redirect_dojo)

    app.register_blueprint(dojos)
    app.register_blueprint(dojo)
    app.register_blueprint(workspace)
    app.register_blueprint(desktop)
    app.register_blueprint(sensai)
    app.register_blueprint(discord)
    app.register_blueprint(users)
    app.register_blueprint(course)
    app.register_blueprint(writeups)
    app.register_blueprint(api, url_prefix="/pwncollege_api/v1")

    app.before_request(redirect_workspace_referers)

    register_admin_plugin_menu_bar("Dojos", "/admin/dojos")
    register_admin_plugin_menu_bar("Desktops", "/admin/desktops")

    if os.path.basename(sys.argv[0]) != "manage.py":
        bootstrap()

    app.shell_context_processor(shell_context_processor)
