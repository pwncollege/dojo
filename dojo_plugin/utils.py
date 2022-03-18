import os
import re
import pathlib
import datetime
import tempfile
import tarfile
import hashlib

import docker
import yaml
from flask import current_app
from itsdangerous.url_safe import URLSafeSerializer
from sqlalchemy.sql import or_, and_
from CTFd.models import db, Solves, Challenges
from CTFd.utils import get_config
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model

from .models import PrivateDojos, PrivateDojoMembers, PrivateDojoActives


CHALLENGES_DIR = pathlib.Path("/var/challenges")
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


def serialize_user_flag(account_id, challenge_id, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]
    serializer = URLSafeSerializer(secret)
    data = [account_id, challenge_id]
    user_flag = serializer.dumps(data)[::-1]
    return user_flag


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


def user_dojos(user_id):
    members = db.session.query(PrivateDojoMembers.dojo_id).filter(PrivateDojoMembers.user_id == user_id)
    return PrivateDojos.query.filter(PrivateDojos.id.in_(members.subquery())).all()


def active_dojo_id(user_id):
    active = PrivateDojoActives.query.filter_by(user_id=user_id).first()
    if not active:
        return None
    return active.dojo_id


def dojo_modules(dojo_id=None):
    if dojo_id is not None:
        dojo = PrivateDojos.query.filter(PrivateDojos.id == dojo_id).first()
        if dojo and dojo.data:
            return yaml.safe_load(dojo.data)
    return yaml.safe_load(get_config("modules"))


def dojo_standings(dojo_id=None, fields=None):
    if fields is None:
        fields = []

    Model = get_model()

    private_dojo_filters = []
    if dojo_id is not None:
        modules = dojo_modules(dojo_id)
        challenges_filter = or_(*(
            and_(Challenges.category == module_challenge["category"],
                 Challenges.name.in_(module_challenge["names"]))
            if module_challenge.get("names") else
            Challenges.category == module_challenge["category"]
            for module in modules
            for module_challenge in module.get("challenges", [])
        ))
        private_dojo_filters.append(challenges_filter)

        members = db.session.query(PrivateDojoMembers.user_id).filter_by(dojo_id=dojo_id)
        private_dojo_filters.append(Solves.account_id.in_(members.subquery()))

    standings_query = (
        db.session.query(*fields)
        .join(Challenges)
        .join(Model, Model.id == Solves.account_id)
        .filter(Challenges.value != 0, Model.banned == False, Model.hidden == False,
                *private_dojo_filters)
    )

    return standings_query


def validate_dojo_data(data):
    try:
        data = yaml.safe_load(data)
    except yaml.error.YAMLError as e:
        assert False, f"YAML Error:\n{e}"

    if data is None:
        return

    def type_assert(object_, type_, name):
        assert isinstance(object_, type_), f"YAML Type Error: {name} expected type `{type_.__name__}`, got `{type(object_).__name__}`"

    type_assert(data, list, "outer most")

    for module in data:
        type_assert(module, dict, "module")

        def type_check(name, type_, required=True, container=module):
            if required and name not in container:
                assert False, f"YAML Required Error: missing field `{name}`"
            if name not in container:
                return
            value = container.get(name)
            if isinstance(type_, str):
                match = isinstance(value, str) and re.fullmatch(type_, value)
                assert match, f"YAML Type Error: field `{name}` must be of type `{type_}`"
            else:
                type_assert(value, type_, f"field `{name}`")

        type_check("name", "[\S ]{1,50}", required=True)
        type_check("permalink", "\w+", required=True)

        type_check("challenges", list, required=False)
        for challenge in module.get("challenges", []):
            type_assert(challenge, dict, "challenge")
            type_check("category", "\w+", required=True, container=challenge)

            type_check("names", list, required=False, container=challenge)
            for name in challenge.get("names", []):
                type_assert(name, str, "challenge name")

        type_check("deadline", datetime.datetime, required=False)
        type_check("late", float, required=False)

        type_check("lectures", list, required=False)
        for lecture in module.get("lectures", []):
            type_assert(lecture, dict, "lecture")
            type_check("name", "[\S ]{1,100}", required=True, container=lecture)
            type_check("video", "[\w-]+", required=True, container=lecture)
            type_check("playlist", "[\w-]+", required=True, container=lecture)
            type_check("slides", "[\w-]+", required=True, container=lecture)


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
