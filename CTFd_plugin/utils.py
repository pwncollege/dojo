import os
import re
import pathlib
import tempfile
import tarfile
import hashlib

from flask import current_app
from itsdangerous.url_safe import URLSafeSerializer
from itsdangerous.exc import BadSignature

CHALLENGES_DIR = pathlib.Path("/var/challenges")


def serialize_user_flag(account_id, challenge_id, challenge_data=None, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]

    serializer = URLSafeSerializer(secret)

    data = [account_id, challenge_id]
    if challenge_data is not None:
        data.append(challenge_data)

    user_flag = serializer.dumps(data)[::-1]

    return user_flag


def unserialize_user_flag(user_flag, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]

    user_flag = re.sub(".+?{(.+)}", r"\1", user_flag)[::-1]

    serializer = URLSafeSerializer(secret)

    data = serializer.loads(user_flag)
    data.append(None)

    account_id, challenge_id, challenge_data, *_ = data

    return account_id, challenge_id, challenge_data


def challenge_paths(user, challenge, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]

    category_global = CHALLENGES_DIR / challenge.category / "_global"
    challenge_global = CHALLENGES_DIR / challenge.category / challenge.name / "_global"

    if category_global.exists():
        yield from category_global.iterdir()

    if challenge_global.exists():
        yield from category_global.iterdir()

    options = [
        option
        for option in (CHALLENGES_DIR / challenge.category / challenge.name).iterdir()
        if not (option.name.startswith(".") or option.name.startswith("_"))
    ]

    option = options[hash((user.id, challenge.id, secret)) % len(options)]
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
