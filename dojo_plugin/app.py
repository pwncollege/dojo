import datetime
import functools
import hashlib
import logging
import os
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from flask import Flask, abort, current_app, redirect, render_template, request, session
from flask.json.tag import TaggedJSONSerializer
from flask.sessions import SessionInterface, SessionMixin
from itsdangerous import BadSignature, want_bytes
from werkzeug.datastructures import CallbackDict
from werkzeug.exceptions import InternalServerError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import safe_join

from . import models
from .config import CTF_NAME, DOJO_HOST, THEME_STATIC, THEME_TEMPLATES
from .models import cache, db, get_config, set_config
from .utils import UserTokenExpiredException, lookup_user_token, registration_visible, render_markdown, sign, unsign
from .utils import listeners  # noqa: F401
from .utils.countries import lookup_country_code
from .utils.dojo import get_current_dojo_challenge
from .utils.events import publish_queued_events
from .utils.query_timer import init_query_timer
from .utils.request_logging import setup_logging, setup_trace_id_tracking, setup_uncaught_error_logging
from .utils.user import authed, generate_nonce, get_current_user_attrs, is_admin, login_user


def build_config(env):
    redis_url = env["REDIS_URL"]
    return {
        "SECRET_KEY": env["SECRET_KEY"],
        "SQLALCHEMY_DATABASE_URI": env["DATABASE_URL"],
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"max_overflow": 20, "pool_pre_ping": True},
        "REDIS_URL": redis_url,
        "CACHE_TYPE": "redis",
        "CACHE_REDIS_URL": redis_url,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "PERMANENT_SESSION_LIFETIME": datetime.timedelta(days=180),
        "REVERSE_PROXY": env.get("REVERSE_PROXY", "false").strip().lower() in ("1", "true", "t", "yes", "y", "on"),
        "TEMPLATES_AUTO_RELOAD": True,
    }


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


def render_error(error):
    if isinstance(error, InternalServerError) and error.description == InternalServerError.description:
        error.description = "An Internal Server Error has occurred"
    return render_template("errors/error.html", code=error.code, error=error.description), error.code


class CachedSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None):
        def on_update(self):
            self.modified = True

        CallbackDict.__init__(self, initial, on_update)
        self.sid = sid
        self.modified = False

    def regenerate(self):
        cache.delete(self.sid)
        self.sid = None
        self.modified = True


class CachingSessionInterface(SessionInterface):
    serializer = TaggedJSONSerializer()
    session_class = CachedSession

    def __init__(self, key_prefix):
        self.key_prefix = key_prefix

    def _generate_sid(self):
        sid = str(uuid4())
        while cache.get(key=self.key_prefix + sid):
            sid = str(uuid4())
        return sid

    def open_session(self, app, request):
        sid = request.cookies.get(app.config["SESSION_COOKIE_NAME"])
        if not sid:
            return self.session_class(sid=self._generate_sid())
        try:
            sid = unsign(sid).decode()
        except BadSignature:
            return self.session_class(sid=self._generate_sid())
        val = cache.get(self.key_prefix + sid)
        if val is not None:
            try:
                return self.session_class(self.serializer.loads(val), sid=sid)
            except Exception:
                pass
        return self.session_class(sid=sid)

    def save_session(self, app, session, response):
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        if not session:
            if session.modified:
                cache.delete(self.key_prefix + session.sid)
                response.delete_cookie(app.config["SESSION_COOKIE_NAME"], domain=domain, path=path)
            return
        if not session.modified:
            return
        if session.sid is None:
            session.sid = self._generate_sid()
        cache.set(key=self.key_prefix + session.sid, value=self.serializer.dumps(dict(session)),
                  timeout=int(app.permanent_session_lifetime.total_seconds()))
        response.set_cookie(app.config["SESSION_COOKIE_NAME"], sign(want_bytes(session.sid)),
                            expires=self.get_expiration_time(app, session), httponly=self.get_cookie_httponly(app),
                            domain=domain, path=path, secure=self.get_cookie_secure(app),
                            samesite=self.get_cookie_samesite(app))


def banned():
    if request.endpoint == "views.themes":
        return
    if authed():
        user = get_current_user_attrs()
        if user and user.banned:
            return render_template("errors/error.html", code=403, error="You have been banned from this CTF"), 403


def authorize_token():
    token = request.headers.get("Authorization")
    if not token or request.content_type != "application/json":
        return
    # dojo workspace / ssh-service bearer tokens are never API access tokens
    if token.startswith("Bearer "):
        return
    try:
        user = lookup_user_token(token.split(" ", 1)[1])
    except UserTokenExpiredException:
        abort(401, description="Your access token has expired")
    except Exception:
        abort(401)
    login_user(user)


def csrf():
    try:
        func = current_app.view_functions[request.endpoint]
    except KeyError:
        abort(404)
    if hasattr(func, "_bypass_csrf") or request.headers.get("Authorization"):
        return
    if not session.get("nonce"):
        session["nonce"] = generate_nonce()
    if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
        return
    token = request.headers.get("CSRF-Token") if request.content_type == "application/json" else request.form.get("nonce")
    if session["nonce"] != token:
        abort(403)


def redirect_dojo():
    if "X-Forwarded-For" in request.headers:
        parsed_url = urlparse(request.url)
        if parsed_url.netloc.split(":")[0] != DOJO_HOST:
            netloc = DOJO_HOST
            if ":" in parsed_url.netloc:
                netloc += ":" + parsed_url.netloc.split(":")[1]
            redirect_url = urlunparse((
                parsed_url.scheme,
                netloc,
                parsed_url.path,
                parsed_url.params,
                parsed_url.query,
                parsed_url.fragment,
            ))
            return redirect(redirect_url, code=301)


@functools.lru_cache(maxsize=1024)
def theme_asset_digest(asset_path, mtime_ns, ctime_ns, size):
    with open(asset_path, "rb") as asset:
        return hashlib.sha256(asset.read()).hexdigest()[:8]


def inject_theme_asset_version(endpoint, values):
    path = values.get("path", "")
    if endpoint != "views.themes" or "v" in values or not path.endswith((".css", ".js")):
        return
    asset_path = safe_join(str(THEME_STATIC), path)
    if asset_path is None:
        return
    try:
        stat_result = os.stat(asset_path)
        values["v"] = theme_asset_digest(asset_path, stat_result.st_mtime_ns, stat_result.st_ctime_ns, stat_result.st_size)
    except OSError:
        return


class _ConfigsWrapper:
    ctf_name = CTF_NAME

    def __getattr__(self, attr):
        return get_config(attr)


Configs = _ConfigsWrapper()


class _SessionWrapper:
    @property
    def id(self):
        return session.get("id", 0)

    @property
    def nonce(self):
        return session.get("nonce")


Session = _SessionWrapper()


def create_app():
    app = Flask("dojo_plugin", static_folder=None, template_folder=THEME_TEMPLATES)
    app.config.update(build_config(os.environ))
    if app.config["REVERSE_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
    app.session_interface = CachingSessionInterface(key_prefix="session")
    db.init_app(app)
    cache.init_app(app)

    with app.app_context():
        from .pages.views import views, challenges
        from .pages.auth import auth
        from .pages.dojos import dojos
        from .pages.dojo import dojo
        from .pages.workspace import workspace
        from .pages.sensai import sensai
        from .pages.discord import discord
        from .pages.users import users
        from .pages.course import course
        from .pages.belts import belts
        from .pages.research import research
        from .pages.feed import feed
        from .pages.test_error import test_error_pages
        from .api import api as pwncollege_api

        init_query_timer()
        logging.getLogger("dojo_plugin").setLevel(logging.INFO)

        for hook in (authorize_token, banned, csrf):
            app.before_request(hook)

        # before_request_handler must stay behind the hooks above
        setup_logging(app)
        setup_trace_id_tracking(app)
        setup_uncaught_error_logging(app)

        if not app.debug:
            app.before_request(redirect_dojo)

        @app.after_request
        def publish_stat_events_after_request(response):
            publish_queued_events()
            return response

        app.url_defaults(inject_theme_asset_version)
        for code in (403, 404, 500, 502):
            app.register_error_handler(code, render_error)

        app.jinja_env.globals.update(
            Configs=Configs, Session=Session, authed=authed, is_admin=is_admin,
            registration_visible=registration_visible, lookup_country_code=lookup_country_code,
        )
        app.jinja_env.filters["markdown"] = render_markdown
        app.jinja_env.filters["isoformat"] = lambda dt: dt.isoformat(timespec="milliseconds") + "Z"
        app.context_processor(context_processor)

        app.register_blueprint(views)
        app.register_blueprint(auth)
        app.register_blueprint(challenges)
        for blueprint in (dojos, dojo, workspace, sensai, discord, users, course, belts, research, feed, test_error_pages):
            app.register_blueprint(blueprint)
        app.register_blueprint(pwncollege_api, url_prefix="/pwncollege_api/v1")

        @app.shell_context_processor
        def shell_context():
            namespace = {name: getattr(models, name) for name in models.__all__}
            namespace.update(app=app, db=db, cache=cache, get_config=get_config, set_config=set_config)
            return namespace

    return app
