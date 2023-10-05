import contextlib
import functools
import json
import tempfile
import datetime
import logging
import pathlib
import tarfile
import hashlib
import inspect
import socket
import fcntl
import pytz
import os
import re

import docker
import bleach
from flask import current_app, Response, Markup, abort
from itsdangerous.url_safe import URLSafeSerializer
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model
from CTFd.utils.config.pages import build_markdown
from CTFd.utils.security.sanitize import sanitize_html
from sqlalchemy import String, Integer
from sqlalchemy.sql import or_


PLUGIN_DIR = pathlib.Path(__file__).parent.parent
CHALLENGES_DIR = pathlib.Path("/var/challenges")
DOJOS_DIR = pathlib.Path("/var/dojos")
DATA_DIR = pathlib.Path("/var/data")

INDEX_HTML = pathlib.Path("/var/index.html").read_text()

def create_seccomp():
    seccomp = json.load(pathlib.Path("/etc/docker/seccomp.json").open())

    seccomp["syscalls"].append({
        "names": [
            "clone",
            "sethostname",
            "setns",
            "unshare",
        ],
        "action": "SCMP_ACT_ALLOW",
    })

    READ_IMPLIES_EXEC = 0x0400000
    ADDR_NO_RANDOMIZE = 0x0040000

    existing_personality_values = []
    for syscalls in seccomp["syscalls"]:
        if "personality" not in syscalls["names"]:
            continue
        if syscalls["action"] != "SCMP_ACT_ALLOW":
            continue
        assert len(syscalls["args"]) == 1
        arg = syscalls["args"][0]
        assert list(arg.keys()) == ["index", "value", "op"]
        assert arg["index"] == 0, arg
        assert arg["op"] == "SCMP_CMP_EQ"
        existing_personality_values.append(arg["value"])

    new_personality_values = []
    for new_flag in [READ_IMPLIES_EXEC, ADDR_NO_RANDOMIZE]:
        for value in [0, *existing_personality_values]:
            new_value = value | new_flag
            if new_value not in existing_personality_values:
                new_personality_values.append(new_value)
                existing_personality_values.append(new_value)

    for new_value in new_personality_values:
        seccomp["syscalls"].append({
            "names": ["personality"],
            "action": "SCMP_ACT_ALLOW",
            "args": [
                {
                    "index": 0,
                    "value": new_value,
                    "op": "SCMP_CMP_EQ",
                },
            ],
        })

    return json.dumps(seccomp)
SECCOMP = create_seccomp()

USER_FIREWALL_ALLOWED = {
    host: socket.gethostbyname(host)
    for host in pathlib.Path("/var/user_firewall.allowed").read_text().split()
}

ID_REGEX = "^[A-Za-z0-9_.-]+$"
def id_regex(s):
    return re.match(ID_REGEX, s) and ".." not in s


def get_current_container(user=None):
    user = user or get_current_user()
    if not user:
        return None

    docker_client = docker.from_env()
    container_name = f"user_{user.id}"

    try:
        return docker_client.containers.get(container_name)
    except docker.errors.NotFound:
        return None


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

def redirect_internal(redirect_uri, auth=None):
    response = Response()
    if auth:
        response.headers["X-Accel-Redirect"] = "@forward"
        response.headers["redirect_auth"] = auth
    else:
        response.headers["X-Accel-Redirect"] = "/internal/"
    response.headers["redirect_uri"] = redirect_uri
    return response

def redirect_user_socket(user, socket_path, url_path):
    assert user is not None
    return redirect_internal(f"http://unix:/var/homes/nosuid/{random_home_path(user)}/{socket_path}:{url_path}")

def render_markdown(s):
    raw_html = build_markdown(s or "")
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
    return user and dojo and dojo.is_admin(user)


def user_dojos(user):
    filters = [Dojos.official == True]
    if user:
        members = db.session.query(DojoMembers.dojo_id).filter(DojoMembers.user_id == user.id)
        filters.append(Dojos.id.in_(members.subquery()))
        admins = db.session.query(DojoAdmins.dojo_id).filter(DojoAdmins.user_id == user.id)
        filters.append(Dojos.id.in_(admins.subquery()))
    return Dojos.query.filter(or_(*filters)).all()


def dojo_standings(dojo_id=None, fields=None, module_id=None):
    if fields is None:
        fields = []

    Model = get_model()

    dojo_filters = []
    if dojo_id is None:
        dojos = Dojos.query.filter_by(official=True).all()
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


def load_dojo(dojo_id, dojo_spec, user=None, dojo_dir=None, commit=True, log=logging.getLogger(__name__), initial_join_code=None):
    log.info("Initiating dojo load.")

    dojo = Dojos.query.filter_by(id=dojo_id).first()
    if not dojo:
        dojo = Dojos(id=dojo_id, owner_id=None if not user else user.id, data=dojo_spec)
        dojo.join_code = initial_join_code
        log.info("Dojo is new, adding.")
        db.session.add(dojo)
    elif dojo.data == dojo_spec:
        # make sure the previous load was fully successful (e.g., all the imports worked and weren't fixed since then)
        num_loaded_chals = DojoChallenges.query.filter_by(dojo_id=dojo_id).count()
        num_spec_chals = sum(len(module.get("challenges", [])) for module in dojo.config.get("modules", []))

        if num_loaded_chals == num_spec_chals:
            log.warning("Dojo is unchanged, aborting update.")
            return
    else:
        dojo.data = dojo_spec
        db.session.add(dojo)

    if dojo.config.get("dojo_spec", None) != "v2":
        log.warning("Incorrect dojo spec version (dojo_spec attribute). Should be 'v2'")

    dojo.apply_spec(dojo_log=log, dojo_dir=dojo_dir)

    if commit:
        log.info("Committing database changes!")
        db.session.commit()
    else:
        log.info("Rolling back database changes!")
        db.session.rollback()


def dojo_completions():
    all_solves = (
        db.session.query(DojoChallenges.dojo_id.label("dojo_id"))
        .join(Solves, DojoChallenges.challenge_id == Solves.challenge_id)
        .add_columns(
            db.func.count(Solves.id).label("solves"),
            Solves.user_id,
            db.func.max(Solves.date).label("last_solve"),
            db.func.min(Solves.date).label("first_solve"),
        )
        .group_by(Solves.user_id, DojoChallenges.dojo_id)
        .order_by("last_solve")
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
            completions.setdefault(s.user_id, []).append({
                "dojo": s.dojo_id, "last_solve": s.last_solve, "first_solve": s.first_solve
            })
    return completions

def first_bloods():
    first_blood_string = db.func.min(Solves.date.cast(String)+"|"+Solves.user_id.cast(String))
    first_blood_query = (
        db.session.query(Challenges.id.label("challenge_id"))
        .join(Solves, Challenges.id == Solves.challenge_id)
        .add_columns(
            db.func.substring_index(first_blood_string, "|", -1).cast(Integer).label("user_id"),
            db.func.min(Solves.date).label("timestamp")
        )
        .group_by(Challenges.id)
        .order_by("timestamp")
    ).all()
    return first_blood_query

def daily_solve_counts():
    counts = (
        db.session.query(
            Solves.user_id, db.func.count(Solves.challenge_id).label("solves"),
            db.func.year(Solves.date).label("year"),
            db.func.month(Solves.date).label("month"),
            db.func.day(Solves.date).label("day")
        )
        .join(Challenges, Challenges.id == Solves.challenge_id)
        .filter(~Challenges.category.contains("embryo"))
        .group_by("year", "month", "day", Solves.user_id)
    ).all()
    return counts


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


from ..models import Dojos, DojoMembers, DojoAdmins, DojoChallenges
