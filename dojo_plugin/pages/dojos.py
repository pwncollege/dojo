import collections

from flask import Blueprint, render_template, redirect, url_for
from CTFd.models import db
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only, admins_only

from ..models import DojoChallenges, Dojos, DojoAdmins, DojoMembers
from ..utils.dojo import generate_ssh_keypair
from ..utils.stats import get_container_stats


dojos = Blueprint("pwncollege_dojos", __name__)


@dojos.route("/dojos")
def listing(template="dojos.html"):
    categorized_dojos = {
        "welcome": [],
        "topic": [],
        "public": [],
        "course": [],
        "member": [],
        "admin": [],
        "next": [],
    }

    user = get_current_user()
    user_dojo_admins = []
    user_dojo_members = []
    dojo_solves = (
        Dojos.viewable(user=user)
        .options(db.undefer(Dojos.modules_count), db.undefer(Dojos.challenges_count))
    )
    if user:
        solves_subquery = (
            DojoChallenges.solves(user=user, ignore_visibility=True, ignore_admins=False)
            .group_by(DojoChallenges.dojo_id)
            .with_entities(DojoChallenges.dojo_id, db.func.count().label("solve_count"))
            .subquery()
        )
        dojo_solves = (
            dojo_solves
            .outerjoin(solves_subquery, Dojos.dojo_id == solves_subquery.c.dojo_id)
            .add_columns(db.func.coalesce(solves_subquery.c.solve_count, 0).label("solve_count"))
        )
        user_dojo_admins = DojoAdmins.query.where(DojoAdmins.user_id == user.id).all()
        user_dojo_members = DojoMembers.query.where(DojoMembers.user_id == user.id).all()
    else:
        dojo_solves = dojo_solves.add_columns(0)

    for dojo, solves in dojo_solves:
        if not (dojo.type == "hidden" or (dojo.type == "example" and dojo.official)):
            categorized_dojos.setdefault(dojo.type, []).append((dojo, solves))
            categorized_dojos["member"].extend((dojo_member.dojo, 0) for dojo_member in user_dojo_members
                                               if dojo_member.dojo == dojo and dojo.type not in ["welcome", "topic", "public"])
        categorized_dojos["admin"].extend((dojo_admin.dojo, 0) for dojo_admin in user_dojo_admins if dojo_admin.dojo == dojo)

    curriculum = categorized_dojos["welcome"] + categorized_dojos["topic"]

    getting_started = next((
        (dojo, solves) for dojo, solves in categorized_dojos["welcome"]
        if dojo.reference_id == "welcome"
    ), None)

    if not user:
        categorized_dojos["next"] = [getting_started] if getting_started else []
    else:
        categorized_dojos["next"] = []

        for i, (dojo, solves) in enumerate(curriculum):
            if 0 < solves < len(dojo.challenges):
                categorized_dojos["next"].append((dojo, solves))
            elif solves < len(dojo.challenges) and i and curriculum[i-1][1] > 0:
                categorized_dojos["next"].append((dojo, solves))

        if not categorized_dojos["next"]:
            if getting_started and getting_started[1] == 0:
                categorized_dojos["next"].append(getting_started)
            elif all(solves >= len(dojo.challenges) for dojo, solves in curriculum):
                categorized_dojos["next"] = categorized_dojos["public"][:]

    dojo_container_counts = collections.Counter(stats["dojo"] for stats in get_container_stats())

    return render_template(template, user=user, categorized_dojos=categorized_dojos, dojo_container_counts=dojo_container_counts)


@dojos.route("/dojos/create")
@authed_only
def dojo_create():
    public_key, private_key = generate_ssh_keypair()
    return render_template(
        "dojo_create.html",
        public_key=public_key,
        private_key=private_key,
        example_dojos=Dojos.viewable().where(Dojos.data["type"].astext == "example").all(),
    )




@dojos.route("/admin/dojos")
@admins_only
def view_all_dojos():
    return render_template("admin_dojos.html", dojos=Dojos.query.order_by(*Dojos.ordering()).all())


def dojos_override():
    return redirect(url_for("pwncollege_dojos.listing"), code=301)
