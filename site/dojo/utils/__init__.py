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
import cmarkgfm
import docker
import docker.errors
from cmarkgfm.cmark import Options
from flask import current_app, Response, Markup, abort, g
from itsdangerous import Signer
from itsdangerous.url_safe import URLSafeSerializer, URLSafeTimedSerializer
from pybluemonday import UGCPolicy
from sqlalchemy import String, Integer
from sqlalchemy.sql import or_
from bleach.css_sanitizer import CSSSanitizer

from ..config import CTF_NAME, WORKSPACE_NODES, MAC_HOSTNAME, MAC_USERNAME
from ..models import db, Solves, Tokens, Users, get_config, Dojos, DojoMembers, DojoAdmins, DojoChallenges, WorkspaceTokens
from . import mac_docker
from .user import get_current_user

ID_REGEX = "^[A-Za-z0-9_.-]+$"
def id_regex(s):
    return re.match(ID_REGEX, s) and ".." not in s


def parse_positive_int(value, maximum=2**31 - 1):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        try:
            parsed = int(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if 0 < parsed <= maximum else None


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


def serialize(data):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"]).dumps(data)


def unserialize(data, max_age=432000):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"]).loads(data, max_age=max_age)


def sign(data):
    return Signer(current_app.config["SECRET_KEY"]).sign(data)


def unsign(data):
    return Signer(current_app.config["SECRET_KEY"]).unsign(data)


def user_node(user):
    return list(WORKSPACE_NODES)[user.id % len(WORKSPACE_NODES)] if WORKSPACE_NODES else None


def user_docker_client(user, image_name=None):
    if image_name and image_name.startswith("mac:"):
        return mac_docker.MacDockerClient(hostname=MAC_HOSTNAME,
                                          username=MAC_USERNAME,
                                          key_path="/var/mac/key")

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


def safe_format(fmt, **kwargs):
    return re.sub(r"\{?\{([^{}]*)\}\}?", lambda m: kwargs.get(m.group(1).strip(), m.group(0)), fmt)


def build_markdown(md, sanitize=False):
    html = cmarkgfm.markdown_to_html_with_extensions(
        md, extensions=["autolink", "table", "strikethrough"], options=Options.CMARK_OPT_UNSAFE)
    html = safe_format(html, ctf_name=CTF_NAME, ctf_description=CTF_NAME)
    if sanitize or get_config("html_sanitization"):
        html = sanitize_html(html)
    return html


# Copied from lxml:
# https://github.com/lxml/lxml/blob/e986a9cb5d54827c59aefa8803bc90954d67221e/src/lxml/html/defs.py#L38
SAFE_ATTRS = (
    'abbr', 'accept', 'accept-charset', 'accesskey', 'action', 'align',
    'alt', 'axis', 'border', 'cellpadding', 'cellspacing', 'char', 'charoff',
    'charset', 'checked', 'cite', 'class', 'clear', 'cols', 'colspan',
    'color', 'compact', 'coords', 'datetime', 'dir', 'disabled', 'enctype',
    'for', 'frame', 'headers', 'height', 'href', 'hreflang', 'hspace', 'id',
    'ismap', 'label', 'lang', 'longdesc', 'maxlength', 'media', 'method',
    'multiple', 'name', 'nohref', 'noshade', 'nowrap', 'prompt', 'readonly',
    'rel', 'rev', 'rows', 'rowspan', 'rules', 'scope', 'selected', 'shape',
    'size', 'span', 'src', 'start', 'summary', 'tabindex', 'target', 'title',
    'type', 'usemap', 'valign', 'value', 'vspace', 'width'
)

ALLOWED_TAGS = {
    "title": [],
    "meta": ["name", "content", "property"],
    "form": ["method", "action"],
    "button": ["name", "type", "value", "disabled"],
    "input": ["name", "type", "value", "placeholder"],
    "select": ["name", "value", "placeholder"],
    "option": ["value"],
    "textarea": ["name", "value", "placeholder"],
    "label": ["for"],
    "blink": [],
    "marquee": [],
    "audio": ["autoplay", "controls", "crossorigin", "loop", "muted", "preload", "src"],
    "video": ["autoplay", "buffered", "controls", "crossorigin", "loop", "muted", "playsinline", "poster", "preload",
              "src"],
    "source": ["src", "type"],
    "iframe": ["width", "height", "src", "frameborder", "allow", "allowfullscreen"],
}

SANITIZER = UGCPolicy()
for element, attrs in ALLOWED_TAGS.items():
    SANITIZER.AllowElements(element)
    SANITIZER.AllowAttrs(*attrs).OnElements(element)
SANITIZER.AllowAttrs(*SAFE_ATTRS).Globally()
SANITIZER.AllowAttrs("class", "style").Globally()
SANITIZER.AllowStyling()
SANITIZER.AllowStandardAttributes()
SANITIZER.AllowStandardURLs()
SANITIZER.AllowDataAttributes()
SANITIZER.AllowDataURIImages()
SANITIZER.AllowRelativeURLs(True)
SANITIZER.RequireNoFollowOnFullyQualifiedLinks(True)
SANITIZER.RequireNoFollowOnLinks(True)
SANITIZER.RequireNoReferrerOnFullyQualifiedLinks(True)
SANITIZER.RequireNoReferrerOnLinks(True)
SANITIZER.AllowComments()


def sanitize_html(html):
    return SANITIZER.sanitize(html)


def _filter_code_class(tag, name, value):
    if name == "class":
        classes = value.split()
        allowed = [c for c in classes if c.startswith("language-")]
        return " ".join(allowed) if allowed else None
    return None


def render_markdown(s):
    raw_html = build_markdown(s or "")
    if "dojo" in g and (g.dojo.official or g.dojo.privileged):
        return Markup(raw_html)

    markdown_tags = [
        "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "br", "hr", "blockquote",
        "b", "strong", "i", "em", "tt", "del", "code", "pre", "sub", "sup",
        "a", "img",
        "span", "div",
        "ul", "ol", "li", "dt", "dd",
        "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
        "details", "summary",
    ]
    markdown_attrs = {
        "*": ["id"],
        "img": ["src", "alt", "title"],
        "a": ["href", "alt", "title"],
        "p": ["data-hide"],
        "code": _filter_code_class,
    }
    clean_html = bleach.clean(raw_html, tags=markdown_tags, attributes=markdown_attrs)
    return Markup(clean_html)

def sanitize_survey(data):
    allowed_tags = [
        "h1", "h2", "h3", "h4", "h5", "h6",
        "b", "i", "strong", "em", "tt",
        "p", "br",
        "span", "div", "blockquote", "code", "pre", "hr",
        "ul", "ol", "li", "dd", "dt",
        "sub", "sup",
        "style", "input", "label", "button"
    ]

    allowed_attrs = {
        "*": ["class", "style", "data-form-submit"],
        "input": ["type", "name", "checked", "value", "placeholder", "readonly"],
        "label": ["for"],
        "button": ["type"],
    }

    allowed_css = bleach.css_sanitizer.ALLOWED_CSS_PROPERTIES.union([
        "transition", "transform"
    ])

    return bleach.clean(data, tags=allowed_tags, attributes=allowed_attrs, css_sanitizer=CSSSanitizer(allowed_css_properties=allowed_css))

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


class UserNotFoundException(Exception):
    pass


class UserTokenExpiredException(Exception):
    pass


def generate_user_token(user, expiration=None, description=None):
    value = "ctfd_" + os.urandom(32).hex()
    while Tokens.query.filter_by(value=value).first():
        value = "ctfd_" + os.urandom(32).hex()
    token = Tokens(user_id=user.id, expiration=expiration, description=description, value=value)
    db.session.add(token)
    db.session.commit()
    return token


def lookup_user_token(token):
    token = Tokens.query.filter_by(value=token).first()
    if not token:
        raise UserNotFoundException
    if datetime.datetime.utcnow() >= token.expiration:
        raise UserTokenExpiredException
    return token.user


# https://github.com/CTFd/CTFd/blob/3.6.0/CTFd/utils/security/auth.py#L51-L59
def lookup_workspace_token(token):
    token = WorkspaceTokens.query.filter_by(value=token).first()
    if token:
        if datetime.datetime.utcnow() >= token.expiration:
            raise UserTokenExpiredException
        return token.user
    else:
        raise UserNotFoundException
    return None


# https://github.com/CTFd/CTFd/blob/3.6.0/CTFd/utils/security/auth.py#L37-L48
def generate_workspace_token(user, expiration=None):
    temp_token = True
    while temp_token is not None:
        value = "workspace_" + os.urandom(32).hex()
        temp_token = WorkspaceTokens.query.filter_by(value=value).first()

    token = WorkspaceTokens(
        user_id=user.id, expiration=expiration, value=value
    )
    db.session.add(token)
    db.session.commit()
    return token


def iso_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat()


def is_challenge_locked(dojo_challenge: DojoChallenges, user: Users) -> bool:
    if all((dojo_challenge.progression_locked, dojo_challenge.challenge_index != 0, not dojo_challenge.dojo.is_admin())):
        previous_dojo_challenge = dojo_challenge.module.challenges[dojo_challenge.challenge_index - 1]
        return not (Solves.query.filter_by(user=user, challenge=dojo_challenge.challenge).first() or
                Solves.query.filter_by(user=user, challenge=previous_dojo_challenge.challenge).first())
    return False


def registration_visible():
    return get_config("registration_visibility", "public") == "public"


# based on https://stackoverflow.com/questions/36408496/python-logging-handler-to-append-to-list
class ListHandler(logging.Handler): # Inherit from logging.Handler
    def __init__(self, log_list):
        logging.Handler.__init__(self)
        self.log_list = log_list

    def emit(self, record):
        self.log_list.append(record.levelname + ": " + record.getMessage())

class HTMLHandler(logging.Handler): # Inherit from logging.Handler
    def __init__(self, start_tag="<code>", end_tag="</code>", join_tag="<br>"):
        logging.Handler.__init__(self)
        self.html = ""
        self.start_tag = start_tag
        self.end_tag = end_tag
        self.join_tag = join_tag

    def reset(self):
        self.html = ""

    def emit(self, record):
        if self.html:
            self.html += self.join_tag
        self.html += f"{self.start_tag}<b>{record.levelname}</b>: {sanitize_html(record.getMessage())}{self.end_tag}"
