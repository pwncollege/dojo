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

    all_welcome_and_topic_dojos = categorized_dojos["welcome"] + categorized_dojos["topic"]
    
    getting_started_dojo = None
    for dojo, solves in categorized_dojos["welcome"]:
        if "getting" in dojo.name.lower() and "started" in dojo.name.lower():
            getting_started_dojo = (dojo, solves)
            break
    
    if not user:
        if getting_started_dojo:
            categorized_dojos["next"].append(getting_started_dojo)
    else:
        dojos_with_progress = set()
        
        for dojo, solves in all_welcome_and_topic_dojos:
            if solves > 0:
                dojos_with_progress.add(dojo.dojo_id)
                if solves < len(dojo.challenges) and (dojo, solves) not in categorized_dojos["next"]:
                    categorized_dojos["next"].append((dojo, solves))
        
        for i, (dojo, solves) in enumerate(all_welcome_and_topic_dojos):
            if dojo.dojo_id in dojos_with_progress:
                if i + 1 < len(all_welcome_and_topic_dojos):
                    next_dojo, next_solves = all_welcome_and_topic_dojos[i + 1]
                    if next_dojo.dojo_id not in dojos_with_progress and (next_dojo, next_solves) not in categorized_dojos["next"]:
                        categorized_dojos["next"].append((next_dojo, next_solves))
        
        all_completed = True
        for dojo, solves in all_welcome_and_topic_dojos:
            if solves < len(dojo.challenges):
                all_completed = False
                break
        
        if all_completed:
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
