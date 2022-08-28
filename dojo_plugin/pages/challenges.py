import datetime
import docker
import pytz

from flask import Blueprint, render_template, abort, redirect
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators.visibility import check_challenge_visibility
from CTFd.utils.helpers import get_infos
from CTFd.cache import cache

from sqlalchemy import String, DateTime
from sqlalchemy.sql import and_, or_

from ..utils import get_current_challenge_id, dojo_route, dojo_by_id, render_markdown, module_visible, module_challenges_visible

challenges = Blueprint("pwncollege_challenges", __name__)


def solved_challenges(dojo, module):
    user = get_current_user()
    user_id = user.id if user else None
    solves = db.func.count(Solves.id).label("solves")
    solved = db.func.max(Solves.user_id == user_id).label("solved")
    solve_date = db.func.substr(
        db.func.max((Solves.user_id == user_id).cast(String)+Solves.date.cast(String)),
        2, 1000
    ).cast(DateTime).label("solve_date")
    solve_filter = (Solves.challenge_id == Challenges.id) if "time_assigned" not in module else and_(
        Solves.challenge_id == Challenges.id, or_(Solves.date >= module["time_assigned"], Solves.user_id == user_id)
    )
    challenges = (
        db.session.query(Challenges.id, Challenges.name, Challenges.category, solves, solve_date, solved)
        .filter(Challenges.state == "visible", dojo.challenges_query(module["id"]))
        .outerjoin(Solves, solve_filter)
        .group_by(Challenges.id)
    ).all()
    return challenges

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

    dojo = dojo_by_id(dojo_id)
    challenge_query = dojo.challenges_query()
    time_query = Solves.date > dojo.config["time_created"] if "time_created" in dojo.config else True

    return {
        "active": int(active),
        "users": int(Users.query.count()),
        "challenges": int(Challenges.query.filter(challenge_query, Challenges.state == "visible").count()),
        "solves": int(Solves.query.join(Challenges, Solves.challenge_id == Challenges.id).filter(challenge_query, time_query).count()),
    }

@challenges.route("/<dojo>/challenges")
@dojo_route
@check_challenge_visibility
def listing(dojo):
    infos = get_infos()
    stats = get_stats(dojo.id)
    for module in dojo.modules:
        challenges = solved_challenges(dojo, module)
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
        stats[module["id"]]["hide"] = not module_visible(dojo, module)

    return render_template(
        "challenges.html",
        dojo=dojo,
        stats=stats,
        infos=infos,
    )


@challenges.route("/<dojo>/challenges/<module>")
@dojo_route
@check_challenge_visibility
def view_module(dojo, module):
    assigned = module.get("time_assigned", None)
    due = module.get("time_due", None)
    ec_full = module.get("time_ec_full", None)
    ec_part = module.get("time_ec_part", None)

    if assigned and due and not ec_full:
        ec_full = (assigned + (due-assigned)/2)
    if assigned and due and not ec_part:
        ec_part = (assigned + (due-assigned)/4)

    challenges = solved_challenges(dojo, module) if module_challenges_visible(dojo, module) else [ ]
    current_challenge_id = get_current_challenge_id()

    if get_current_user():
        num_timely_solves = len([ c for c in challenges if c.solved and pytz.UTC.localize(c.solve_date) < due ]) if due else 0
        num_late_solves = len([ c for c in challenges if c.solved and pytz.UTC.localize(c.solve_date) >= due ]) if due else 0
        num_full_ec_solves = len([ c for c in challenges if c.solved and pytz.UTC.localize(c.solve_date) < ec_full ]) if ec_full else 0
        num_part_ec_solves = len([ c for c in challenges if c.solved and pytz.UTC.localize(c.solve_date) < ec_part ]) if ec_part else 0
    else:
        num_timely_solves = 0
        num_late_solves = 0
        num_full_ec_solves = 0
        num_part_ec_solves = 0

    return render_template(
        "module.html",
        dojo=dojo,
        module=module,
        utcnow=datetime.datetime.now(pytz.utc),
        render_markdown=render_markdown,
        ec_part=ec_part, ec_full=ec_full,
        challenges=challenges,
        num_timely_solves=num_timely_solves,
        num_late_solves=num_late_solves,
        num_full_ec_solves=num_full_ec_solves,
        num_part_ec_solves=num_part_ec_solves,
        current_challenge_id=current_challenge_id
    )

@challenges.route("/<dojo>/scoreboard")
def redirect_scoreboard(dojo):
    return redirect(f"/{dojo}/challenges", code=302)

