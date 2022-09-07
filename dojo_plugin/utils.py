import contextlib
import functools
import tempfile
import datetime
import pathlib
import tarfile
import hashlib
import inspect
import pytz
import os
import re

import docker
from flask import current_app, Response, abort
from itsdangerous.url_safe import URLSafeSerializer
from sqlalchemy.sql import or_, and_
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.modes import get_model
from CTFd.utils.helpers import markup
from CTFd.utils.config.pages import build_markdown

from .models import Dojos, DojoMembers
from sqlalchemy import String, DateTime
from sqlalchemy.sql import and_, or_


CHALLENGES_DIR = pathlib.Path("/var/challenges")
DOJOS_DIR = pathlib.Path("/var/dojos")
PLUGIN_DIR = pathlib.Path(__file__).parent
SECCOMP = (PLUGIN_DIR / "seccomp.json").read_text()


def get_current_challenge_id():
    user = get_current_user()
    if not user:
        return None

    docker_client = docker.from_env()
    container_name = f"user_{user.id}"

    try:
        container = docker_client.containers.get(container_name)
    except docker.errors.NotFound:
        return

    for env in container.attrs["Config"]["Env"]:
        if env.startswith("CHALLENGE_ID"):
            try:
                challenge_id = int(env[len("CHALLENGE_ID=") :])
                return challenge_id
            except ValueError:
                pass

def get_active_users():
    docker_client = docker.from_env()
    containers = docker_client.containers.list(filters=dict(name="user_"), ignore_removed=True)
    uids = [ c.name.split("_")[-1] for c in containers ]
    users = [ Users.query.filter_by(id=uid).first() for uid in uids ]
    return users

def serialize_user_flag(account_id, challenge_id, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]
    serializer = URLSafeSerializer(secret)
    data = [account_id, challenge_id]
    user_flag = serializer.dumps(data)[::-1]
    return user_flag

def redirect_user_socket(user, socket_path, url_path):
    assert user is not None
    redirect_uri = f"http://unix:/var/homes/nosuid/{random_home_path(user)}/{socket_path}:{url_path}"
    response = Response()
    response.headers["X-Accel-Redirect"] = "/internal/"
    response.headers["redirect_uri"] = redirect_uri
    return response

def render_markdown(s):
    return markup(build_markdown(s))

def unserialize_user_flag(user_flag, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]
    user_flag = re.sub(".+?{(.+)}", r"\1", user_flag)[::-1]
    serializer = URLSafeSerializer(secret)
    account_id, challenge_id = serializer.loads(user_flag)
    return account_id, challenge_id


def challenge_paths(user, challenge, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]

    category_global = CHALLENGES_DIR / challenge.category / "_global"
    challenge_global = CHALLENGES_DIR / challenge.category / challenge.name / "_global"

    if category_global.exists():
        yield from category_global.iterdir()

    if challenge_global.exists():
        yield from challenge_global.iterdir()

    options = sorted(
        option
        for option in (CHALLENGES_DIR / challenge.category / challenge.name).iterdir()
        if not (option.name.startswith(".") or option.name.startswith("_"))
    )

    option_hash = hashlib.sha256(f"{secret}_{user.id}_{challenge.id}".encode()).digest()
    option = options[int.from_bytes(option_hash[:8], "little") % len(options)]
    yield from option.iterdir()


def simple_tar(path, name=None):
    f = tempfile.NamedTemporaryFile()
    t = tarfile.open(mode="w", fileobj=f)
    abs_path = os.path.abspath(path)
    t.add(abs_path, arcname=(name or os.path.basename(path)))
    t.close()
    f.seek(0)
    return f


def random_home_path(user, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]
    return hashlib.sha256(f"{secret}_{user.id}".encode()).hexdigest()[:16]

def dojo_by_id(dojo_id):
    dojo = Dojos.query.filter_by(id=dojo_id).first()
    if not dojo:
        return None
    if dojo.public:
        return dojo

    user = get_current_user()
    if not user:
        return None
    if not DojoMembers.query.filter_by(dojo_id=dojo.id, user_id=user.id).first():
        return None
    return dojo


def module_visible(dojo, module, user):
    return (
        "time_visible" not in module or
        module["time_visible"] <= datetime.datetime.now(pytz.utc) or
        is_dojo_admin(user, dojo)
    )


def module_challenges_visible(dojo, module, user):
    return (
        "time_assigned" not in module or
        module["time_assigned"] <= datetime.datetime.now(pytz.utc) or
        is_dojo_admin(user, dojo)
    )


def is_dojo_admin(user, dojo):
    return is_admin() or (user and dojo.owner_id == user.id)


def dojo_route(func):
    signature = inspect.signature(func)
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound_args = signature.bind(*args, **kwargs)
        bound_args.apply_defaults()
        dojo = bound_args.arguments["dojo"]
        if dojo is not None:
            dojo = dojo_by_id(dojo)
            if not dojo:
                abort(404)
        bound_args.arguments["dojo"] = dojo

        with contextlib.suppress(KeyError):
            module = bound_args.arguments["module"]
            if module is not None:
                module = dojo.module_by_id(module)
                if not module or not module_visible(dojo, module, get_current_user()):
                    abort(404)

            bound_args.arguments["module"] = module

        return func(*bound_args.args, **bound_args.kwargs)
    return wrapper


def user_dojos(user):
    filters = [Dojos.public == True]
    if user:
        members = db.session.query(DojoMembers.dojo_id).filter(DojoMembers.user_id == user.id)
        filters.append(Dojos.id.in_(members.subquery()))
    return Dojos.query.filter(or_(*filters)).all()


def dojo_standings(dojo_id, fields=None, module_id=None):
    if fields is None:
        fields = []

    Model = get_model()
    dojo = Dojos.query.filter(Dojos.id == dojo_id).first()

    dojo_filters = []
    dojo_filters.append(dojo.challenges_query(module_id=module_id))

    if not dojo.public:
        members = db.session.query(DojoMembers.user_id).filter_by(dojo_id=dojo_id)
        dojo_filters.append(Solves.account_id.in_(members.subquery()))

    standings_query = (
        db.session.query(*fields)
        .join(Challenges)
        .join(Model, Model.id == Solves.account_id)
        .filter(Challenges.value != 0, Model.banned == False, Model.hidden == False,
                *dojo_filters)
    )

    return standings_query


def solved_challenges(dojo, module, user, when=None):
    """
    Get all active challenges of a dojo, adding a '.solved' and 'solve_date' with data about
    challenges solved by the provided user.
    """
    user_id = user.id if user else None
    solves = db.func.count(Solves.id).label("solves")
    solved = db.func.max(Solves.user_id == user_id).label("solved")
    solve_date = db.func.substr(
        db.func.max((Solves.user_id == user_id).cast(String)+Solves.date.cast(String)),
        2, 1000
    ).cast(DateTime).label("solve_date")

    solve_filters = [ Solves.challenge_id == Challenges.id ]
    if "time_assigned" in module:
        solve_filters.append(or_(Solves.date >= module["time_assigned"], Solves.user_id == user_id))
    if when:
        solve_filters.append(Solves.date <= when)

    challenges = (
        db.session.query(Challenges.id, Challenges.name, Challenges.category, solves, solve_date, solved)
        .filter(
            Challenges.state == "visible",
            dojo.challenges_query(module["id"], include_unassigned=module_challenges_visible(dojo, module, user))
        )
        .outerjoin(Solves, and_(*solve_filters))
        .group_by(Challenges.id)
    ).all()
    return challenges




def belt_challenges():
    yellow_categories = [
        "embryoio",
        "babysuid",
        "embryoasm",
        "babyshell",
        "babyjail",
        "embryogdb",
        "babyrev",
        "babymem",
        "toddlerone",
    ]

    blue_categories = [
        *yellow_categories,
        "babyrop",
        "babyheap",
        "babyrace",
        "babykernel",
        "toddlertwo",
    ]

    color_categories = {
        "yellow": yellow_categories,
        "blue": blue_categories,
    }

    return {
        color: db.session.query(Challenges.id).filter(
            Challenges.state == "visible",
            Challenges.value > 0,
            Challenges.category.in_(categories),
        )
        for color, categories in color_categories.items()
    }
