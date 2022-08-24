from flask import Blueprint, render_template, redirect, url_for
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user

from ..utils import dojo_route, user_dojos


dojos = Blueprint("pwncollege_dojos", __name__)


def dojo_stats(dojo):
    user = get_current_user()
    user_id = user.id if user else None
    solves = db.func.count(Solves.id).label("solves")
    solved = db.func.max(Solves.user_id == user_id).label("solved")
    challenges = (
        db.session.query(Challenges.id, Challenges.name, Challenges.category, solves, solved)
        .filter(Challenges.state == "visible", dojo.challenges_query())
        .outerjoin(Solves, Solves.challenge_id == Challenges.id)
        .group_by(Challenges.id)
    ).all()
    return {
        "count": len(challenges),
        "solved": sum(1 for challenge in challenges if challenge.solved),
    }


@dojos.route("/dojos")
def listing():
    user = get_current_user()
    dojos = user_dojos(user)

    private_dojos = [ d for d in dojos if not d.public and not d.archived ]
    public_dojos = [ d for d in dojos if d.public and not d.archived ]
    archived_dojos = [ d for d in dojos if d.archived ]

    stats = {
        dojo.id: dojo_stats(dojo)
        for dojo in dojos
    }

    return render_template("dojos.html", public_dojos=public_dojos, private_dojos=private_dojos, archived_dojos=archived_dojos, stats=stats)


@dojos.route("/dojo/<dojo>")
@dojo_route
def view_dojo(dojo):
    return redirect(url_for("pwncollege_challenges.listing", dojo=dojo.id))


def dojos_override():
    return redirect(url_for("pwncollege_dojos.listing"))
