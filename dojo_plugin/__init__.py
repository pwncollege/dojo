import datetime
import logging
import sys
import os

from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import urlparse, urlunparse

from flask import Response, request, redirect, current_app
from itsdangerous.exc import BadSignature
from marshmallow_sqlalchemy import field_for
from CTFd.models import db, Challenges, Users, Solves
from CTFd.utils.user import get_current_user
from CTFd.plugins import register_admin_plugin_menu_bar
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.plugins.flags import FLAG_CLASSES, BaseFlag, FlagException

from .models import Dojos, DojoChallenges, Belts, Emojis
from .config import DOJO_HOST, bootstrap
from .utils import unserialize_user_flag, render_markdown
from .utils.dojo import get_current_dojo_challenge
from .utils.awards import update_awards
from .utils.feed import publish_challenge_solve
from .utils.query_timer import init_query_timer
from .utils.request_logging import setup_logging, setup_trace_id_tracking, setup_uncaught_error_logging
from .pages.dojos import dojos, dojos_override
from .pages.dojo import dojo
from .pages.workspace import workspace
from .pages.sensai import sensai
from .pages.users import users
from .pages.settings import settings_override
from .pages.discord import discord
from .pages.course import course
from .pages.belts import belts
from .pages.research import research
from .pages.feed import feed
from .pages.index import static_html_override
from .pages.test_error import test_error_pages
from .api import api
from .api.v1.scoreboard import _publish_queued_events


class DojoChallenge(BaseChallenge):
    id = "dojo"
    name = "dojo"
    challenge_model = Challenges

    @classmethod
    def solve(cls, user, team, challenge, request):
        super().solve(user, team, challenge, request)
        update_awards(user)

        dojo_challenge = DojoChallenges.query.filter_by(challenge_id=challenge.id).first()
        if dojo_challenge:
            dojo = dojo_challenge.module.dojo
            if dojo.official or dojo.data.get("type") == "public":
                module = dojo_challenge.module
                points = challenge.value
                first_blood = Solves.query.filter_by(challenge_id=challenge.id).count() == 1
                publish_challenge_solve(user, dojo_challenge, dojo, module, points, first_blood)


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


def context_processor():
    challenge = get_current_dojo_challenge()
    if not challenge:
        return dict(current_dojo_challenge=None, current_dojo_custom_js=None)
    return dict(
        current_dojo_challenge=dict(
            dojo_id=challenge.dojo.reference_id,
            module_id=challenge.module.id,
            challenge_id=challenge.id,
        ),
        current_challenge_id=challenge.challenge_id,
        current_dojo_custom_js=challenge.dojo.custom_js,
    )


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


def handle_authorization(default_handler):
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        return
    default_handler()


def load(app):
    db.create_all()

    init_query_timer()

    logging.getLogger(__name__).setLevel(logging.INFO)

    setup_logging(app)
    setup_trace_id_tracking(app)
    setup_uncaught_error_logging(app)

    @app.after_request
    def publish_stat_events_after_request(response):
        _publish_queued_events()
        return response

    app.permanent_session_lifetime = datetime.timedelta(days=180)

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
    app.register_blueprint(belts)
    app.register_blueprint(research)
    app.register_blueprint(feed)
    app.register_blueprint(test_error_pages)
    app.register_blueprint(api, url_prefix="/pwncollege_api/v1")

    app.jinja_env.filters["markdown"] = render_markdown

    register_admin_plugin_menu_bar("Dojos", "/admin/dojos")
    register_admin_plugin_menu_bar("Desktops", "/admin/desktops")

    before_request_funcs = app.before_request_funcs[None]
    tokens_handler = next(func for func in before_request_funcs if func.__name__ == "tokens")
    before_request_funcs[before_request_funcs.index(tokens_handler)] = lambda: handle_authorization(tokens_handler)

    if os.path.basename(sys.argv[0]) != "manage.py":
        bootstrap()

    app.context_processor(context_processor)
    app.shell_context_processor(shell_context_processor)
