import os
import re

from flask import current_app
from itsdangerous.url_safe import URLSafeSerializer
from itsdangerous.exc import BadSignature

from .settings import INSTANCE


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


def challenge_path(account_id, category, challenge):
    account_id = str(account_id)

    def is_safe(segment):
        return segment != "." and segment != ".." and "/" not in segment

    if not is_safe(account_id) or not is_safe(category) or not is_safe(challenge):
        return None

    paths = [
        os.path.join("/", "challenges", account_id, category, challenge),
        os.path.join("/", "challenges", "global", category, challenge),
    ]

    for path in paths:
        if os.path.exists(path):
            return path
