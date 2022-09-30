import contextlib
import functools
import tempfile
import datetime
import pathlib
import tarfile
import hashlib
import inspect
import fcntl
import pytz
import os
import re
import socket

import docker
from flask import current_app, Response, abort
from itsdangerous.url_safe import URLSafeSerializer
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.modes import get_model
from CTFd.utils.helpers import markup
from CTFd.utils.config.pages import build_markdown

from .models import Dojos, DojoMembers, DojoChallenges
from sqlalchemy import String, DateTime, Integer
from sqlalchemy.sql import and_, or_


CHALLENGES_DIR = pathlib.Path("/var/challenges")
DOJOS_DIR = pathlib.Path("/var/dojos")
PLUGIN_DIR = pathlib.Path(__file__).parent
SECCOMP = (PLUGIN_DIR / "seccomp.json").read_text()
USER_FIREWALL_ALLOWED = {
    host: socket.gethostbyname(host)
    for host in pathlib.Path("/var/user_firewall.allowed").read_text().split()
}


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

def get_active_users(active_desktops=False):
    docker_client = docker.from_env()
    containers = docker_client.containers.list(filters=dict(name="user_"), ignore_removed=True)

    def used_desktop(c):
        if c.status != 'running':
            return False

        try:
            return b"accepted" in next(c.get_archive("/tmp/vnc/vncserver.log")[0])
        except StopIteration:
            return False
        except docker.errors.NotFound:
            return False

    if active_desktops:
        containers = [ c for c in containers if used_desktop(c) ]
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

    if options:
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
    return user and (user.type == "admin" or dojo.owner_id == user.id)


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


def dojo_standings(dojo_id=None, fields=None, module_id=None):
    if fields is None:
        fields = []

    Model = get_model()

    dojo_filters = []
    if dojo_id is None:
        dojos = Dojos.query.filter_by(public=True).all()
        dojo_filters.append(or_(*(dojo.challenges_query(module_id=module_id) for dojo in dojos)))
    else:
        dojo = Dojos.query.filter(Dojos.id == dojo_id).first()
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


def dojo_challenges(dojo, module=None, user=None, admin_view=False, solves_before=None):
    """
    Get all active challenges of a dojo, adding a '.solved' and 'solve_date' with data about
    challenges solved by the provided user.

    @param admin_view: whether to show not-yet-assigned challenges
    @param solves_before: only show solves up to this date
    @param user: show solves by this user if solves are before module assignment date
    """
    columns = [
        DojoChallenges.challenge_id, DojoChallenges.description_override, DojoChallenges.level_idx,
        DojoChallenges.provider_dojo_id, DojoChallenges.provider_module,
        DojoChallenges.module, DojoChallenges.module_idx,
        Challenges.name, Challenges.category, Challenges.description, Challenges.id,
        db.func.count(Solves.id).label("solves") # number of solves
    ]
    if user is not None:
        columns.append(db.func.max(Solves.user_id == user.id).label("solved")) # did the user solve the chal?
        columns.append(db.func.substr(
            db.func.max((Solves.user_id == user.id).cast(String)+Solves.date.cast(String)),
            2, 1000
        ).cast(DateTime).label("solve_date")) # _when_ did the user solve the chal?
    else:
        columns.append(db.literal(False).label("solved"))
        columns.append(db.literal(None).label("solve_date"))

    solve_filters = [
        or_(
            DojoChallenges.assigned_date == None,
            False if user is None else Solves.user_id == user.id,
            Solves.date >= DojoChallenges.assigned_date
        )
    ]
    if solves_before:
        solve_filters.append(Solves.date < solves_before)

    # fuck sqlalchemy for making me write this insanity
    challenges = (
        Challenges.query
        .join(DojoChallenges, Challenges.id == DojoChallenges.challenge_id)
        .outerjoin(Solves, and_(Challenges.id == Solves.challenge_id, *solve_filters))
        .filter(dojo.challenges_query(module_id=module["id"] if module else None, include_unassigned=admin_view))
        .add_columns(*columns)
        .group_by(Challenges.id)
        .order_by(DojoChallenges.module_idx, DojoChallenges.level_idx)
    ).all()

    return challenges


# this is a MASSIVE hack and should be replaced with something less insane
_lock_number = [ 0 ]
def multiprocess_lock(func):
    _lock_filename = f"/dev/shm/dojolock-{_lock_number[0]}"
    _lock_number[0] += 1
    open(_lock_filename, "w").close()
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        lf = open(_lock_filename, "r")
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            return func(*args, **kwargs)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
    return wrapper

def dojo_completions():
    all_solves = (
        db.session.query(DojoChallenges.dojo_id.label("dojo_id"))
        .join(Solves, DojoChallenges.challenge_id == Solves.challenge_id)
        .add_columns(db.func.count(Solves.id).label("solves"), Solves.user_id)
        .group_by(Solves.user_id, DojoChallenges.dojo_id)
    ).all()
    all_challenges = (
        db.session.query(Dojos.id.label("dojo_id"))
        .join(DojoChallenges, DojoChallenges.dojo_id == Dojos.id)
        .add_columns(db.func.count(DojoChallenges.challenge_id).label("challenges"))
        .group_by(Dojos.id)
    ).all()

    chal_counts = { d.dojo_id: d.challenges for d in all_challenges }
    completions = { }
    for s in all_solves:
        if s.solves == chal_counts[s.dojo_id]:
            completions.setdefault(s.user_id, []).append(s.dojo_id)
    return completions

def first_bloods():
    first_blood_string = db.func.min(Solves.date.cast(String)+"|"+Solves.user_id.cast(String))
    first_blood_query = (
        db.session.query(Challenges.id.label("challenge_id"))
        .join(Solves, Challenges.id == Solves.challenge_id)
        .add_columns(
            db.func.substring_index(first_blood_string, "|", -1).cast(Integer).label("user_id"),
            db.func.min(Solves.date).label("timestamp")
        ).group_by(Challenges.id)
    ).all()
    return first_blood_query


def belt_challenges():
    # TODO: move this concept into dojo yml

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
            Challenges.id < 1000,
            Challenges.category.in_(categories),
        )
        for color, categories in color_categories.items()
    }
