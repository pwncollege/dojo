import datetime
import docker
import pytz

from flask import Blueprint, render_template, redirect, abort
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators.visibility import check_challenge_visibility
from CTFd.utils.helpers import get_infos
from CTFd.cache import cache

from ..utils import render_markdown, module_visible, module_challenges_visible, is_dojo_admin
from ..utils.dojo import dojo_route, get_current_dojo_challenge
from ..models import Dojos, DojoUsers

dojo = Blueprint("pwncollege_dojo", __name__)


@cache.memoize(timeout=60)
def get_stats(dojo):
    docker_client = docker.from_env()
    filters = {
        "name": "user_",
        "label": f"dojo={dojo.reference_id}"
    }
    containers = docker_client.containers.list(filters=filters, ignore_removed=True)

    now = datetime.datetime.now()
    active = 0.0
    for container in containers:
        created = container.attrs["Created"].split(".")[0]
        uptime = now - datetime.datetime.fromisoformat(created)
        hours = max(uptime.seconds // (60 * 60), 1)
        active += 1 / hours

    # TODO: users and solves query is slow, so we'll just leave it out for now
    # TODO: we need to index tables for this to be fast
    return {
        "active": int(active),
        "users": "-", # int(dojo.solves().group_by(Solves.user_id).count()),
        "challenges": int(len(dojo.challenges)),
        "solves": "-", # int(dojo.solves().count()),
    }


@dojo.route("/<dojo>/")
@dojo_route
@check_challenge_visibility
def listing(dojo):
    infos = get_infos()
    user = get_current_user()
    dojo_user = DojoUsers.query.filter_by(dojo=dojo, user=user).first()
    stats = get_stats(dojo)
    return render_template(
        "dojo.html",
        dojo=dojo,
        user=user,
        dojo_user=dojo_user,
        stats=stats,
        infos=infos,
    )


@dojo.route("/<dojo>/<module>")
@dojo_route
@check_challenge_visibility
def view_module(dojo, module):
    user = get_current_user()
    user_solves = set(solve.challenge_id for solve in (
        module.solves(user=user, ignore_visibility=True, ignore_admins=False) if user else []
    ))
    total_solves = dict(module.solves(ignore_visibility=True)
                        .group_by(Solves.challenge_id)
                        .with_entities(Solves.challenge_id, db.func.count()))
    current_dojo_challenge = get_current_dojo_challenge()
    return render_template(
        "module.html",
        dojo=dojo,
        module=module,
        challenges=[ c for c in module.challenges if c.visible() or is_dojo_admin(user, dojo) ],
        user_solves=user_solves,
        total_solves=total_solves,
        user=user,
        current_dojo_challenge=current_dojo_challenge,
    )
