from flask import Blueprint, render_template, redirect, url_for
from CTFd.models import db
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only, admins_only

from ..models import DojoChallenges, Dojos
from ..utils.dojo import generate_ssh_keypair


dojos = Blueprint("pwncollege_dojos", __name__)

def dojo_stats(dojo):
    challenges = dojo.challenges(user=get_current_user())
    return {
        "count": len(challenges),
        "solved": sum(1 for challenge in challenges if challenge.solved),
    }


@dojos.route("/dojos")
def listing(template="dojos.html"):
    user = get_current_user()
    categorized_dojos = {
        "Start Here": [],
        "Topics": [],
        "Courses": [],
        "More Material": [],
    }
    type_to_category = {
        "topic": "Topics",
        "course": "Courses",
        "welcome": "Start Here"
    }
    options = db.undefer(Dojos.modules_count), db.undefer(Dojos.challenges_count)
    dojo_solves = Dojos.viewable(user=user).options(*options)
    if user:
        solves_subquery = (DojoChallenges.solves(user=user, ignore_visibility=True, ignore_admins=False)
            .group_by(DojoChallenges.dojo_id)
            .with_entities(DojoChallenges.dojo_id, db.func.count().label("solve_count"))
            .subquery())
        dojo_solves = (dojo_solves.outerjoin(solves_subquery, Dojos.dojo_id == solves_subquery.c.dojo_id)
            .add_columns(db.func.coalesce(solves_subquery.c.solve_count, 0).label("solve_count")))
    else:
        dojo_solves = dojo_solves.add_columns(0)
    for dojo, solves in dojo_solves:
        if dojo.type == "hidden" or (dojo.type == "example" and dojo.official):
            continue
        category = type_to_category.get(dojo.type, "More Material")
        categorized_dojos[category].append((dojo, solves))

    if "Start Here" in categorized_dojos:
        categorized_dojos["Start Here"].sort(key=lambda x: x[0].name)

    return render_template(template, user=user, categorized_dojos=categorized_dojos)


@dojos.route("/dojos/create")
@authed_only
def dojo_create():
    public_key, private_key = generate_ssh_keypair()
    return render_template(
        "dojo_create.html",
        public_key=public_key,
        private_key=private_key,
        example_dojos=Dojos.viewable().where(Dojos.data["type"] == "example").all()
    )




@dojos.route("/admin/dojos")
@admins_only
def view_all_dojos():
    return render_template("admin_dojos.html", dojos=Dojos.query.order_by(*Dojos.ordering()).all())


def dojos_override():
    return redirect(url_for("pwncollege_dojos.listing"), code=301)
