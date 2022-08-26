import datetime
import pytz

from flask import Blueprint, render_template, abort
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators.visibility import check_challenge_visibility

from sqlalchemy import String, DateTime
from sqlalchemy.sql import and_, or_

from ..utils import get_current_challenge_id, dojo_route


modules = Blueprint("pwncollege_modules", __name__)


def solved_challenges(dojo, module=None):
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


@modules.route("/<dojo>/modules")
@dojo_route
@check_challenge_visibility
def listing(dojo):
    stats = {}
    for module in dojo.modules:
        challenges = solved_challenges(dojo, module)
        stats[module["id"]] = {
            "count": len(challenges),
            "solved": sum(1 for challenge in challenges if challenge.solved),
        }
        stats[module["id"]]["active"] = (
            "time_assigned" in module and "time_due" in module and
            module["time_assigned"] <= pytz.UTC.localize(datetime.datetime.now()) and
            pytz.UTC.localize(datetime.datetime.now()) <= module["time_due"]
        )
    return render_template("modules.html", dojo=dojo, stats=stats)


@modules.route("/<dojo>/modules/<module>")
@dojo_route
@check_challenge_visibility
def view_module(dojo, module):
    module_id = module
    for module in dojo.modules:
        if module.get("id") == module_id:
            break
    else:
        abort(404)

    assigned = module.get("time_assigned", None)
    due = module.get("time_due", None)
    ec_full = module.get("time_ec_full", None)
    ec_part = module.get("time_ec_part", None)

    if assigned and due and not ec_full:
        ec_full = (assigned + (due-assigned)/2)
    if assigned and due and not ec_part:
        ec_part = (assigned + (due-assigned)/4)

    challenges = solved_challenges(dojo, module)
    current_challenge_id = get_current_challenge_id()

    num_timely_solves = len([ c for c in challenges if c.solved and pytz.UTC.localize(c.solve_date) < due ]) if due else 0
    num_late_solves = len([ c for c in challenges if c.solved and pytz.UTC.localize(c.solve_date) >= due ]) if due else 0
    num_full_ec_solves = len([ c for c in challenges if c.solved and pytz.UTC.localize(c.solve_date) < ec_full ]) if ec_full else 0
    num_part_ec_solves = len([ c for c in challenges if c.solved and pytz.UTC.localize(c.solve_date) < ec_part ]) if ec_part else 0

    return render_template(
        "module.html",
        dojo=dojo,
        module=module,
        ec_part=ec_part, ec_full=ec_full,
        challenges=challenges,
        num_timely_solves=num_timely_solves,
        num_late_solves=num_late_solves,
        num_full_ec_solves=num_full_ec_solves,
        num_part_ec_solves=num_part_ec_solves,
        current_challenge_id=current_challenge_id
    )
