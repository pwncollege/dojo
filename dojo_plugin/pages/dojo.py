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

    return {
        "active": int(active),
        "users": int(dojo.solves().group_by(Solves.user_id).count()),
        "challenges": int(len(dojo.challenges)),
        "solves": int(dojo.solves().count()),
    }


@dojo.route("/private-<int:id>/")
@dojo.route("/private-<int:id>/<path:old>")
def old_private_dojo_deprecate(id, old=None):
    # TODO: delete this in June 2023, or if no dojos still have a `deprecated_id`

    for dojo in Dojos.viewable(user=get_current_user()):
        if dojo.deprecated_id == id:
            url = f"https://dojo.pwn.college/{ dojo.reference_id }/"
            break
    else:
        abort(404)

    deprecated = f"""
    <div class="jumbotron">
        <div class="container">
            <h1>Deprecated</h1>
        </div>
    </div>

    <div class="container">
        <p>
            We no longer support <code>/private-ID/</code> dojo routes.
            <br>
            Do not worry though, everything you're trying to access still exists, it just has moved!
            <br>
            You can now access this dojo through: <a href="{url}">{url}</a>
        </p>
    </div>
    """
    return render_template("base.html", content=deprecated)

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
        render_markdown=render_markdown,
    )


@dojo.route("/<dojo>/<module>")
@dojo_route
@check_challenge_visibility
def view_module(dojo, module):
    user = get_current_user()
    user_solves = set(solve.challenge_id for solve in module.solves(user=user, ignore_visibility=True)) if user else set()
    total_solves = dict(module.solves()
                        .group_by(Solves.challenge_id)
                        .with_entities(Solves.challenge_id, db.func.count()))
    current_dojo_challenge = get_current_dojo_challenge()
    return render_template(
        "module.html",
        dojo=dojo,
        module=module,
        user_solves=user_solves,
        total_solves=total_solves,
        user=user,
        current_dojo_challenge=current_dojo_challenge,
        render_markdown=render_markdown,
    )
