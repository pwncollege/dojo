import yaml
from flask import Blueprint, render_template, abort
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.utils.decorators.visibility import check_challenge_visibility

from .docker_challenge import get_current_challenge_id
from .utils import CHALLENGES_DIR


with open(CHALLENGES_DIR / "modules.yml") as f:
    modules = yaml.load(f.read(), Loader=yaml.BaseLoader)


challenges = Blueprint(
    "pwncollege_challenges", __name__, template_folder="assets/challenges/"
)


@check_challenge_visibility
def challenges_listing():
    challenges = (
        Challenges.query.filter(Challenges.state == "visible")
        .group_by(Challenges.category)
        .with_entities(
            Challenges.category,
            db.func.count(),
        )
    )
    challenges = {
        category: {"count": count, "solves": 0} for category, count in challenges
    }

    user = get_current_user()
    if user:
        solves = (
            Solves.query.filter(Solves.user_id == user.id)
            .join(Challenges, Challenges.id == Solves.challenge_id)
            .filter(Challenges.state == "visible")
            .group_by(Challenges.category)
            .with_entities(
                Challenges.category,
                db.func.count(),
            )
        )
        for category, solves in solves:
            challenges[category]["solves"] = solves

    return render_template(
        "modules.html",
        modules=modules,
        challenges=challenges,
    )


@challenges.route("/challenges/<permalink>")
@check_challenge_visibility
def view_challenges(permalink):
    for module in modules:
        if module.get("permalink") == permalink:
            break
    else:
        abort(404)

    challenges = []
    user_solves = set()
    current_challenge_id = None

    category = module.get("category")
    if category:
        labels = {
            "id": Challenges.id,
            "name": Challenges.name,
            "solves": db.func.count(Solves.id),
        }
        challenges = (
            Challenges.query.filter(
                Challenges.state == "visible",
                Challenges.category == category,
            )
            .outerjoin(Solves, Solves.challenge_id == Challenges.id)
            .group_by(Challenges.id)
            .with_entities(*labels.values())
        )
        challenges = [dict(zip(labels, challenge)) for challenge in challenges]

        user = get_current_user()
        if user:
            user_solves = (
                Solves.query.filter(Solves.user_id == user.id)
                .join(Challenges, Challenges.id == Solves.challenge_id)
                .filter(
                    Challenges.state == "visible",
                    Challenges.category == category,
                )
                .with_entities(Challenges.id)
            )
            user_solves = set(e[0] for e in user_solves)
            current_challenge_id = get_current_challenge_id()

    return render_template(
        "challenges.html",
        module=module,
        challenges=challenges,
        user_solves=user_solves,
        current_challenge_id=current_challenge_id
    )
