from flask import Blueprint, render_template, abort
from sqlalchemy.sql import or_, and_
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators.visibility import check_challenge_visibility

from ..utils import get_current_challenge_id, dojo_modules


challenges = Blueprint("pwncollege_challenges", __name__)


def module_challenges(module, user_id=None):
    solves = db.func.count(Solves.id).label("solves")
    solved = db.func.max(Solves.user_id == user_id).label("solved")
    challenges = (
        db.session.query(Challenges.id, Challenges.name, Challenges.category, solves, solved)
        .filter(Challenges.state == "visible",
                or_(*(
                    and_(Challenges.category == module_challenge["category"],
                         Challenges.name.in_(module_challenge["names"]))
                    if module_challenge.get("names") else
                    Challenges.category == module_challenge["category"]
                    for module_challenge in module.get("challenges", [])
                ), False))
        .outerjoin(Solves, Solves.challenge_id == Challenges.id)
        .group_by(Challenges.id)
    ).all()
    return challenges


@challenges.route("/<dojo>/challenges")
@check_challenge_visibility
def listing(dojo):
    user = get_current_user()
    modules = dojo_modules()

    for module in modules:
        challenges = module_challenges(module, user.id if user else None)
        module["challenges_count"] = len(challenges)
        module["challenges_solved"] = sum(1 for challenge in challenges if challenge.solved)

    return render_template(
        "challenges.html",
        dojo=dojo,
        modules=modules,
    )


@challenges.route("/<dojo>/challenges/<module>")
@check_challenge_visibility
def view_module(dojo, module):
    user = get_current_user()
    modules = dojo_modules()

    module_permalink = module
    for module in modules:
        if module.get("permalink") == module_permalink:
            break
    else:
        abort(404)

    challenges = module_challenges(module, user.id if user else None)
    current_challenge_id = get_current_challenge_id()

    return render_template(
        "module.html",
        dojo=dojo,
        module=module,
        challenges=challenges,
        current_challenge_id=current_challenge_id
    )
