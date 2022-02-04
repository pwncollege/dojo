import os
import re
import pathlib
import tempfile
import tarfile
import hashlib

import docker
import yaml
from flask import current_app
from itsdangerous.url_safe import URLSafeSerializer
from CTFd.models import db
from CTFd.utils import get_config
from CTFd.utils.user import get_current_user

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
