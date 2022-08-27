import datetime

import docker
from flask import Blueprint, render_template
from CTFd.models import Users, Solves, Challenges
from CTFd.cache import cache
from CTFd.utils.helpers import get_infos

from ..utils import dojo_route, dojo_by_id


scoreboard = Blueprint("pwncollege_scoreboard", __name__)


@cache.memoize(timeout=60)
def get_stats(dojo_id):
    docker_client = docker.from_env()
    containers = docker_client.containers.list(filters=dict(name="user_"), ignore_removed=True)
    now = datetime.datetime.now()
    active = 0.0
    for container in containers:
        created = container.attrs["Created"].split(".")[0]
        uptime = now - datetime.datetime.fromisoformat(created)
        hours = max(uptime.seconds // (60 * 60), 1)
        active += 1 / hours

    challenge_query = dojo_by_id(dojo_id).challenges_query()

    return {
        "active": int(active),
        "users": int(Users.query.count()),
        "challenges": int(Challenges.query.filter(challenge_query, Challenges.state == "visible").count()),
        "solves": int(Solves.query.join(Challenges, Solves.challenge_id == Challenges.id).filter(challenge_query).count()),
    }


@scoreboard.route("/<dojo>/scoreboard")
@dojo_route
def listing(dojo):
    infos = get_infos()
    stats = get_stats(dojo.id)

    return render_template(
        "scoreboard.html",
        dojo=dojo,
        infos=infos,
        stats=stats,
    )
