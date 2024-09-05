import sys
import os
import datetime

from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import urlparse, urlunparse

from flask import Response, request, redirect, current_app
from flask.json import JSONEncoder
from itsdangerous.exc import BadSignature
from marshmallow_sqlalchemy import field_for
from CTFd.models import db, Challenges, Users
from CTFd.utils.user import get_current_user
from CTFd.plugins import register_admin_plugin_menu_bar
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.plugins.flags import FLAG_CLASSES, BaseFlag, FlagException

from .models import Dojos, DojoChallenges, Belts, Emojis
from .config import DOJO_HOST, bootstrap
from .utils import unserialize_user_flag, render_markdown
from .utils.awards import update_awards
from .pages.dojos import dojos, dojos_override
from .pages.dojo import dojo
from .pages.workspace import workspace
from .pages.sensai import sensai
from .pages.users import users
from .pages.settings import settings_override
from .pages.discord import discord
from .pages.course import course
from .pages.canvas import sync_canvas_user, canvas
from .pages.writeups import writeups
from .pages.belts import belts
from .pages.index import static_html_override
from .api import api


class DojoChallenge(BaseChallenge):
    id = "dojo"
    name = "dojo"
    challenge_model = Challenges

    @classmethod
    def solve(cls, user, team, challenge, request):
        super().solve(user, team, challenge, request)
        update_awards(user)
        sync_canvas_user(user.id, challenge.id)


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


# Patch CTFd to allow users to hide their profiles
import CTFd.schemas.users
CTFd.schemas.users.UserSchema.hidden = field_for(Users, "hidden")
CTFd.schemas.users.UserSchema.views["self"].append("hidden")


def redirect_dojo():
    if "X-Forwarded-For" in request.headers:
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

    app.view_functions["views.static_html"] = static_html_override
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
    app.register_blueprint(sensai)
    app.register_blueprint(discord)
    app.register_blueprint(users)
    app.register_blueprint(course)
    app.register_blueprint(canvas)
    app.register_blueprint(writeups)
    app.register_blueprint(belts)
    app.register_blueprint(api, url_prefix="/pwncollege_api/v1")

    app.jinja_env.filters["markdown"] = render_markdown

    register_admin_plugin_menu_bar("Dojos", "/admin/dojos")
    register_admin_plugin_menu_bar("Desktops", "/admin/desktops")

    if os.path.basename(sys.argv[0]) != "manage.py":
        bootstrap()

    app.shell_context_processor(shell_context_processor)
