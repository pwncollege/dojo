import datetime
import docker
import pytz

from flask import Blueprint, render_template, redirect
from CTFd.models import Solves, Challenges, Users
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators.visibility import check_challenge_visibility
from CTFd.utils.helpers import get_infos
from CTFd.cache import cache

from ..utils import get_current_challenge_id, dojo_route, dojo_by_id, render_markdown, module_visible, module_challenges_visible, dojo_challenges
from .grades import module_grade_report

dojo = Blueprint("pwncollege_dojo", __name__)


@cache.memoize(timeout=60)
def get_stats(dojo_id):
    docker_client = docker.from_env()
    containers = docker_client.containers.list(filters=dict(name="user_"), ignore_removed=True)
    now = datetime.datetime.now()
    active = 0.0
    for container in containers:
        if not any(e == f"DOJO_ID={dojo_id}" for e in container.attrs['Config']['Env']):
            continue

        created = container.attrs["Created"].split(".")[0]
        uptime = now - datetime.datetime.fromisoformat(created)
        hours = max(uptime.seconds // (60 * 60), 1)
        active += 1 / hours

    dojo = dojo_by_id(dojo_id)
    challenge_query = dojo.challenges_query()
    time_query = Solves.date > dojo.config["time_created"] if "time_created" in dojo.config else True

    return {
        "active": int(active),
        "users": int(Users.query.join(Solves, Solves.user_id == Users.id).join(Challenges, Solves.challenge_id == Challenges.id).filter(challenge_query, time_query).group_by(Users.id).count()),
        "challenges": int(Challenges.query.filter(challenge_query, Challenges.state == "visible").count()),
        "solves": int(Solves.query.join(Challenges, Solves.challenge_id == Challenges.id).filter(challenge_query, time_query).count()),
    }

@dojo.route("/<dojo>/")
@dojo_route
@check_challenge_visibility
def listing(dojo):
    infos = get_infos()
    stats = get_stats(dojo.id)
    user = get_current_user()
    for module in dojo.modules:
        challenges = dojo_challenges(dojo, module, user)
        stats[module["id"]] = {
            "count": len(challenges),
            "solved": sum(1 for challenge in challenges if challenge.solved),
        }
        stats[module["id"]]["active"] = (
            "time_assigned" in module and "time_due" in module and
            module["time_assigned"] <= datetime.datetime.now(pytz.utc) and
            datetime.datetime.now(pytz.utc) <= module["time_due"]
        )
        # "hidden" controls the client-side CSS, and "hide" tells jinja2 to hide the module completely
        stats[module["id"]]["hidden"] = "time_visible" in module and module["time_visible"] >= datetime.datetime.now(pytz.utc)
        stats[module["id"]]["hide"] = not module_visible(dojo, module, user)

    return render_template(
        "dojo.html",
        dojo=dojo,
        stats=stats,
        infos=infos,
        render_markdown=render_markdown,
        asu_student=False if user is None else user.email.endswith("asu.edu"),
    )


@dojo.route("/<dojo>/<module>")
@dojo_route
@check_challenge_visibility
def view_module(dojo, module):
    user = get_current_user()
    module_report = module_grade_report(dojo, module, user)

    challenges = (
        dojo_challenges(dojo, module, get_current_user())
    ) if module_challenges_visible(dojo, module, get_current_user()) else [ ]
    current_challenge_id = get_current_challenge_id()

    return render_template(
        "module.html",
        dojo=dojo,
        module=module,
        module_report=module_report,
        utcnow=datetime.datetime.now(pytz.utc),
        render_markdown=render_markdown,
        challenges=challenges,
        asu_student=False if user is None else user.email.endswith("asu.edu"),
        current_challenge_id=current_challenge_id
    )

@dojo.route("/<dojo>/scoreboard")
def redirect_scoreboard(dojo):
    return redirect(f"/{dojo}/", code=301)

@dojo.route("/<dojo>/challenges")
def redirect_challenges(dojo):
    return redirect(f"/{dojo}/", code=301)

@dojo.route("/<dojo>/challenges/<module>")
def redirect_module(dojo, module):
    return redirect(f"/{dojo}/{module}", code=301)
