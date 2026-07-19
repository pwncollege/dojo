import datetime
import logging
import sys
import os

from email.message import EmailMessage
from email.utils import formatdate
from urllib.parse import urlparse, urlunparse

from flask import Response, abort, current_app, g, redirect, request
from itsdangerous.exc import BadSignature
from marshmallow_sqlalchemy import field_for
from CTFd.models import db, Challenges, Users, Solves
from CTFd.utils.user import get_current_user
from CTFd.plugins import register_admin_plugin_menu_bar
from CTFd.plugins.challenges import CHALLENGE_CLASSES, BaseChallenge
from CTFd.plugins.flags import FLAG_CLASSES, BaseFlag, FlagException

from .models import Dojos, DojoModules, DojoChallenges, Belts, Emojis
from .config import DOJO_HOST, bootstrap
from .utils import get_current_container, unserialize_user_flag, render_markdown
from .utils.challenge_references import (
    lock_challenge_references,
    missing_challenge_ids,
)
from .utils.dojo import (
    DOJOS_TMP_DIR,
    drain_pending_dojo_update_recalculations,
    get_current_dojo_challenge,
    lock_dojo_reference_ids_for_update,
    recover_pending_dojo_updates,
)
from .utils.checkout import checkout_barrier
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
from .utils.events import publish_queued_events
from .utils import listeners


class DojoChallenge(BaseChallenge):
    id = "dojo"
    name = "dojo"
    challenge_model = Challenges

    @classmethod
    def submission_route(cls, challenge, user):
        dojo_challenge = getattr(g, "_solving_dojo_challenge", None)
        if dojo_challenge is not None:
            return {
                "dojo_id": dojo_challenge.dojo_id,
                "dojo_reference_id": dojo_challenge.dojo.reference_id,
                "module_index": dojo_challenge.module_index,
                "module_id": dojo_challenge.module.id,
                "challenge_index": dojo_challenge.challenge_index,
                "challenge_id": dojo_challenge.id,
            }

        container = get_current_container(user)
        if container is not None:
            labels = container.labels
            route = {
                "dojo_reference_id": labels.get("dojo.dojo_id"),
                "module_id": labels.get("dojo.module_id"),
                "challenge_id": labels.get("dojo.challenge_id"),
            }
            if not all(route.values()):
                abort(404)
            return route

        with db.session.no_autoflush:
            associations = (
                DojoChallenges.query
                .filter_by(challenge_id=challenge.id)
                .populate_existing()
                .all()
            )
        if len(associations) != 1:
            abort(404)
        dojo_challenge = associations[0]
        return {
            "dojo_id": dojo_challenge.dojo_id,
            "dojo_reference_id": dojo_challenge.dojo.reference_id,
            "module_index": dojo_challenge.module_index,
            "module_id": dojo_challenge.module.id,
            "challenge_index": dojo_challenge.challenge_index,
            "challenge_id": dojo_challenge.id,
        }

    @classmethod
    def lock_submission_challenge(cls, challenge, user=None):
        submitted_challenge_id = challenge.id
        route = cls.submission_route(challenge, user)

        routed_dojo = Dojos.from_id(route["dojo_reference_id"]).one_or_none()
        if routed_dojo is None:
            abort(404)
        lock_dojo_reference_ids_for_update({routed_dojo.id})
        routed_dojo = Dojos.lock_ids_for_update({routed_dojo.dojo_id}).get(
            routed_dojo.dojo_id
        )
        if (
            routed_dojo is None or
            routed_dojo.reference_id != route["dojo_reference_id"] or
            (
                route.get("dojo_id") is not None and
                routed_dojo.dojo_id != route["dojo_id"]
            )
        ):
            abort(404)

        module_query = DojoModules.query.filter_by(
            dojo_id=routed_dojo.dojo_id,
            id=route["module_id"],
        )
        if route.get("module_index") is not None:
            module_query = module_query.filter_by(
                module_index=route["module_index"]
            )
        routed_module = module_query.populate_existing().one_or_none()
        if routed_module is None:
            abort(404)

        challenge_query = DojoChallenges.query.filter_by(
            dojo_id=routed_dojo.dojo_id,
            module_index=routed_module.module_index,
            id=route["challenge_id"],
        )
        if route.get("challenge_index") is not None:
            challenge_query = challenge_query.filter_by(
                challenge_index=route["challenge_index"]
            )
        dojo_challenge = (
            challenge_query
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )
        if (
            dojo_challenge is None or
            dojo_challenge.challenge_id != submitted_challenge_id
        ):
            abort(404)

        challenge = (
            Challenges.query
            .filter_by(id=submitted_challenge_id, type="dojo")
            .populate_existing()
            .with_for_update()
            .one_or_none()
        )
        if challenge is None:
            abort(404)
        if not dojo_challenge.path_override and (
            challenge.category != routed_dojo.hex_dojo_id or
            challenge.name != f"{routed_module.id}:{dojo_challenge.id}"
        ):
            abort(404)
        g._solving_dojo_challenge = dojo_challenge
        return challenge, dojo_challenge

    @classmethod
    def attempt(cls, challenge, request):
        challenge, _ = cls.lock_submission_challenge(
            challenge,
            get_current_user(),
        )
        return super().attempt(challenge, request)

    @classmethod
    def solve(cls, user, team, challenge, request):
        challenge, dojo_challenge = cls.lock_submission_challenge(
            challenge,
            user,
        )
        existing_solve = Solves.query.filter_by(
            challenge_id=challenge.id,
            user_id=user.id,
        ).first()
        if existing_solve is None and team is not None:
            existing_solve = Solves.query.filter_by(
                challenge_id=challenge.id,
                team_id=team.id,
            ).first()
        if existing_solve is not None:
            db.session.commit()
            return

        super().solve(user, team, challenge, request)
        update_awards(user)

        dojo_challenge = (
            dojo_challenge or
            DojoChallenges.query.filter_by(challenge_id=challenge.id).first()
        )
        if dojo_challenge:
            dojo = dojo_challenge.module.dojo
            if dojo.official or dojo.data.get("type") == "public":
                module = dojo_challenge.module
                points = challenge.value
                first_blood = Solves.query.filter_by(challenge_id=challenge.id).count() == 1
                publish_challenge_solve(user, dojo_challenge, dojo, module, points, first_blood)

    @classmethod
    def fail(cls, user, team, challenge, request):
        challenge, _ = cls.lock_submission_challenge(challenge, user)
        return super().fail(user, team, challenge, request)


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
    recover_pending_dojo_updates()
    drain_pending_dojo_update_recalculations()

    init_query_timer()

    logging.getLogger(__name__).setLevel(logging.INFO)

    setup_logging(app)
    setup_trace_id_tracking(app)
    setup_uncaught_error_logging(app)

    @app.before_request
    def recover_interrupted_dojo_updates():
        path_parts = request.path.strip("/").split("/")
        checkout_update_request = (
            len(path_parts) in {3, 4} and
            path_parts[0] == "dojo" and
            path_parts[2] == "update"
        )
        try:
            if checkout_update_request:
                recover_pending_dojo_updates()
                drain_pending_dojo_update_recalculations()
                return
            barrier_context = checkout_barrier(
                DOJOS_TMP_DIR,
                exclusive=False,
            )
            barrier_context.__enter__()
            g._dojo_checkout_barrier = barrier_context
            recover_pending_dojo_updates(barrier_held=True)
            drain_pending_dojo_update_recalculations(barrier_held=True)
        except Exception:
            db.session.rollback()
            logging.getLogger(__name__).exception(
                "Failed to recover interrupted dojo update"
            )
            abort(503)

    @app.teardown_request
    def release_checkout_barrier(error):
        barrier_context = getattr(g, "_dojo_checkout_barrier", None)
        if barrier_context is not None:
            del g._dojo_checkout_barrier
            barrier_context.__exit__(
                type(error) if error is not None else None,
                error,
                error.__traceback__ if error is not None else None,
            )

    @app.before_request
    def serialize_challenge_requirement_updates():
        path_parts = request.path.strip("/").split("/")
        if not (
            request.method == "PATCH" and
            len(path_parts) == 4 and
            path_parts[:3] == ["api", "v1", "challenges"] and
            path_parts[3].isdigit()
        ):
            return
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or "requirements" not in data:
            return

        lock_challenge_references()
        requirements = data["requirements"]
        prerequisites = (
            requirements.get("prerequisites", [])
            if isinstance(requirements, dict) else
            requirements
        )
        missing_prerequisites = (
            missing_challenge_ids(prerequisites)
            if isinstance(prerequisites, list) else
            [prerequisites]
        )
        if missing_prerequisites:
            return {
                "success": False,
                "errors": {
                    "requirements": [
                        "Challenge prerequisites must reference existing challenges"
                    ]
                },
            }, 400

    @app.after_request
    def publish_stat_events_after_request(response):
        publish_queued_events()
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
