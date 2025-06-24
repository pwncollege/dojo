import datetime
import hashlib
import hmac
import io
import logging
import os
import pytz
import re
import tarfile
import tempfile

import bleach
import docker
import docker.errors
from flask import current_app, Response, Markup, abort, g
from itsdangerous.url_safe import URLSafeSerializer
from CTFd.exceptions import UserNotFoundException, UserTokenExpiredException
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.encoding import hexencode
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model
from CTFd.utils.config.pages import build_markdown
from CTFd.utils.security.sanitize import sanitize_html
from sqlalchemy import String, Integer
from sqlalchemy.sql import or_

from ..config import WORKSPACE_NODES
from ..models import Dojos, DojoMembers, DojoAdmins, DojoChallenges, WorkspaceTokens
from . import mac_docker

ID_REGEX = "^[A-Za-z0-9_.-]+$"
def id_regex(s):
    return re.match(ID_REGEX, s) and ".." not in s


def force_cache_updates():
    return bool(os.environ.get("CACHE_WARMER"))


def container_name(user):
    return f"user_{user.id}"


def container_password(container, *args):
    key = container.labels["dojo.auth_token"].encode()
    message = "-".join(args).encode()
    return hmac.HMAC(key, message, "sha256").hexdigest()


def get_current_container(user=None):
    user = user or get_current_user()
    if not user:
        return None

    docker_client = user_docker_client(user)

    try:
        return docker_client.containers.get(container_name(user))
    except docker.errors.NotFound:
        return None


def get_all_containers(dojo=None):
    filters = dict(status="running", label="dojo.dojo_id")
    if dojo:
        filters["label"] = f"dojo.dojo_id={dojo.reference_id}"

    return [
        container
        for docker_client in all_docker_clients()
        for container in docker_client.containers.list(filters=filters, ignore_removed=True)
    ]


def serialize_user_flag(account_id, challenge_id, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]
    serializer = URLSafeSerializer(secret)
    data = [account_id, challenge_id]
    user_flag = serializer.dumps(data)[::-1]
    return user_flag


def user_node(user):
    return list(WORKSPACE_NODES.keys())[user.id % len(WORKSPACE_NODES)] if WORKSPACE_NODES else None


def user_docker_client(user, image_name=None):
    if image_name and image_name.startswith("mac:"):
        return mac_docker.MacDockerClient()

    node_id = user_node(user)
    return (docker.DockerClient(base_url=f"tcp://192.168.42.{node_id + 1}:2375", tls=False)
            if node_id is not None else docker.from_env())


def all_docker_clients():
    return [docker.DockerClient(base_url=f"tcp://192.168.42.{node_id + 1}:2375", tls=False)
            for node_id in WORKSPACE_NODES] if WORKSPACE_NODES else [docker.from_env()]


def user_ipv4(user):
    # Full Subnet: 10.0.0.0/8
    #           NODE            SERVICE_ID
    # 00001010  0000  00000000000000000000
    # SERVICE_IDs 0-255 are reserved for core services

    node_id = user_node(user) or 0
    service_id = user.id + 256
    assert node_id < 2**4
    assert service_id < 2**20
    return ".".join([
        "10",
        f"{(node_id << 4) | ((service_id >> 16) & 0xff)}",
        f"{(service_id >> 8) & 0xff}",
        f"{(service_id >> 0) & 0xff}",
    ])


def redirect_internal(redirect_uri, auth=None):
    response = Response()
    if auth:
        response.headers["X-Accel-Redirect"] = "@forward"
        response.headers["redirect_auth"] = auth
    else:
        response.headers["X-Accel-Redirect"] = "/internal/"
    response.headers["redirect_uri"] = redirect_uri
    return response


def redirect_user_socket(user, port, url_path):
    assert user is not None
    return redirect_internal(f"http://{user_ipv4(user)}:{port}/{url_path}")


def render_markdown(s):
    raw_html = build_markdown(s or "")
    if "dojo" in g and (g.dojo.official or g.dojo.privileged):
        return Markup(raw_html)

    markdown_tags = [
        "h1", "h2", "h3", "h4", "h5", "h6",
        "b", "i", "strong", "em", "tt",
        "p", "br",
        "span", "div", "blockquote", "code", "pre", "hr",
        "ul", "ol", "li", "dd", "dt",
        "img",
        "a",
        "sub", "sup",
    ]
    markdown_attrs = {
        "*": ["id"],
        "img": ["src", "alt", "title"],
        "a": ["href", "alt", "title"],
        "p": ["data-hide"]
    }
    clean_html = bleach.clean(raw_html, tags=markdown_tags, attributes=markdown_attrs)
    return Markup(clean_html)


def unserialize_user_flag(user_flag, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]
    user_flag = re.sub(".+?{(.+)}", r"\1", user_flag)[::-1]
    serializer = URLSafeSerializer(secret)
    account_id, challenge_id = serializer.loads(user_flag)
    return account_id, challenge_id


def resolved_tar(dir, *, root_dir, filter=None):
    tar_buffer = io.BytesIO()
    tar = tarfile.open(fileobj=tar_buffer, mode='w')
    resolved_root_dir = root_dir.resolve()
    for path in dir.rglob("*"):
        if filter is not None and not filter(path):
            continue
        relative_path = path.relative_to(dir)
        if path.is_symlink():
            resolved_path = path.resolve()
            assert resolved_path.is_relative_to(resolved_root_dir), f"The symlink {path} points outside of the root directory"
            tar.add(resolved_path, arcname=relative_path)
        else:
            tar.add(path, arcname=relative_path, recursive=False)
    tar_buffer.seek(0)
    return tar_buffer


# https://github.com/CTFd/CTFd/blob/3.6.0/CTFd/utils/security/auth.py#L51-L59
def lookup_workspace_token(token):
    token = WorkspaceTokens.query.filter_by(value=token).first()
    if token:
        if datetime.datetime.utcnow() >= token.expiration:
            raise UserTokenExpiredException
        return token.user
    else:
        raise UserNotFoundException


# https://github.com/CTFd/CTFd/blob/3.6.0/CTFd/utils/security/auth.py#L37-L48
def generate_workspace_token(user, expiration=None):
    temp_token = True
    while temp_token is not None:
        value = "workspace_" + hexencode(os.urandom(32))
        temp_token = WorkspaceTokens.query.filter_by(value=value).first()

    token = WorkspaceTokens(
        user_id=user.id, expiration=expiration, value=value
    )
    db.session.add(token)
    db.session.commit()
    return token


def is_challenge_locked(dojo_challenge: DojoChallenges, user: Users) -> bool:
    if all((dojo_challenge.progression_locked, dojo_challenge.challenge_index != 0, not dojo_challenge.dojo.is_admin())):
        previous_dojo_challenge = dojo_challenge.module.challenges[dojo_challenge.challenge_index - 1]
        return not (Solves.query.filter_by(user=user, challenge=dojo_challenge.challenge).first() or
                Solves.query.filter_by(user=user, challenge=previous_dojo_challenge.challenge).first())
    return False