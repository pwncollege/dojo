import datetime

from flask import Blueprint, render_template, abort
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators.visibility import check_challenge_visibility

from ..utils import get_current_challenge_id, dojo_route


challenges = Blueprint("pwncollege_challenges", __name__)


def solved_challenges(dojo, module_id=None):
    user = get_current_user()
    user_id = user.id if user else None
    solves = db.func.count(Solves.id).label("solves")
    solved = db.func.max(Solves.user_id == user_id).label("solved")
    challenges = (
        db.session.query(Challenges.id, Challenges.name, Challenges.category, solves, solved)
        .filter(Challenges.state == "visible", dojo.challenges_query(module_id))
        .outerjoin(Solves, Solves.challenge_id == Challenges.id)
        .group_by(Challenges.id)
    ).all()
    return challenges


@challenges.route("/<dojo>/challenges")
@dojo_route
@check_challenge_visibility
def listing(dojo):
    stats = {}
    for module in dojo.modules:
        challenges = solved_challenges(dojo, module["id"])
        stats[module["id"]] = {
            "count": len(challenges),
            "solved": sum(1 for challenge in challenges if challenge.solved),
        }
    return render_template("challenges.html", dojo=dojo, stats=stats)


@challenges.route("/<dojo>/challenges/<module>")
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

    challenges = solved_challenges(dojo, module_id)
    current_challenge_id = get_current_challenge_id()

    return render_template(
        "module.html",
        dojo=dojo,
        module=module,
        ec_part=ec_part, ec_full=ec_full,
        challenges=challenges,
        current_challenge_id=current_challenge_id
    )
