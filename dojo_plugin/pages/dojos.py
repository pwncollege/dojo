import datetime
import sys
import traceback

import docker
from flask import Blueprint, Response, stream_with_context, render_template, redirect, url_for, abort
from sqlalchemy.sql import and_
from sqlalchemy.exc import IntegrityError
from CTFd.models import db, Solves, Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.plugins import bypass_csrf_protection

from ..models import DojoAdmins, DojoChallenges, DojoMembers, DojoModules, DojoUsers, Dojos
from ..utils import user_dojos
from ..utils.dojo import dojo_route, generate_ssh_keypair, dojo_update, dojo_admins_only


dojos = Blueprint("pwncollege_dojos", __name__)

def dojo_stats(dojo):
    challenges = dojo.challenges(user=get_current_user())
    return {
        "count": len(challenges),
        "solved": sum(1 for challenge in challenges if challenge.solved),
    }


@dojos.route("/dojos")
def listing():
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

    return render_template("dojos.html", user=user, categorized_dojos=categorized_dojos)


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


@dojos.route("/dojo/<dojo>")
@dojo_route
def view_dojo(dojo):
    return redirect(url_for("pwncollege_dojo.listing", dojo=dojo.reference_id))


@dojos.route("/dojo/<dojo>/join")
@dojos.route("/dojo/<dojo>/join/")
@dojos.route("/dojo/<dojo>/join/<password>")
@authed_only
def join_dojo(dojo, password=None):
    dojo = Dojos.from_id(dojo).first()
    if not dojo:
        abort(404)

    if dojo.password and dojo.password != password:
        abort(403)

    try:
        member = DojoMembers(dojo=dojo, user=get_current_user())
        db.session.add(member)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()

    return redirect(url_for("pwncollege_dojo.listing", dojo=dojo.reference_id))


@dojos.route("/dojo/<dojo>/update/", methods=["GET", "POST"])
@dojos.route("/dojo/<dojo>/update/<update_code>", methods=["GET", "POST"])
@bypass_csrf_protection
def update_dojo(dojo, update_code=None):
    dojo = Dojos.from_id(dojo).first()
    if not dojo:
        return {"success": False, "error": "Not Found"}, 404

    if dojo.update_code != update_code:
        return {"success": False, "error": "Forbidden"}, 403

    try:
        dojo_update(dojo)
        db.session.commit()
    except Exception as e:
        print(f"ERROR: Dojo failed for {dojo}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return {"success": False, "error": str(e)}, 400
    return {"success": True}

@dojos.route("/dojo/<dojo>/delete/", methods=["POST"])
@authed_only
def delete_dojo(dojo):
    dojo = Dojos.from_id(dojo).first()
    if not dojo:
        return {"success": False, "error": "Not Found"}, 404

    # Check if the current user is an admin of the dojo
    if not is_admin():
        abort(403)

    try:
        DojoUsers.query.filter(DojoUsers.dojo_id == dojo.dojo_id).delete()
        Dojos.query.filter(Dojos.dojo_id == dojo.dojo_id).delete()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"ERROR: Dojo failed for {dojo}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return {"success": False, "error": str(e)}, 400
    return {"success": True}

@dojos.route("/dojo/<dojo>/admin/")
@dojo_route
@dojo_admins_only
def view_dojo_admin(dojo):
    return render_template("dojo_admin.html", dojo=dojo, is_admin=is_admin)


@dojos.route("/dojo/<dojo>/admin/activity")
@dojo_route
@dojo_admins_only
def view_dojo_activity(dojo):
    docker_client = docker.from_env()
    filters = {
        "name": "user_",
        "label": f"dojo.dojo_id={dojo.reference_id}"
    }
    containers = docker_client.containers.list(filters=filters, ignore_removed=True)

    actives = []
    now = datetime.datetime.now()
    for container in containers:
        user_id = container.labels["dojo.user_id"]
        dojo_id = container.labels["dojo.dojo_id"]
        module_id = container.labels["dojo.module_id"]
        challenge_id = container.labels["dojo.challenge_id"]

        user = Users.query.filter_by(id=user_id).first()
        challenge = DojoChallenges.from_id(dojo_id, module_id, challenge_id).first()

        created = datetime.datetime.fromisoformat(container.attrs["Created"].split(".")[0])
        uptime = now - created

        actives.append(dict(user=user, challenge=challenge, uptime=uptime))
    actives.sort(key=lambda active: active["uptime"])

    solves = dojo.solves().order_by(Solves.date).all()

    return render_template("dojo_activity.html", dojo=dojo, actives=actives, solves=solves)


@dojos.route("/dojo/<dojo>/admin/solves.csv")
@dojo_route
@dojo_admins_only
def view_dojo_solves(dojo):
    def stream():
        yield "user,module,challenge,time\n"
        solves = (
            dojo
            .solves(ignore_visibility=True)
            .join(DojoModules, and_(
                DojoModules.dojo_id == DojoChallenges.dojo_id,
                DojoModules.module_index == DojoChallenges.module_index))
            .filter(DojoUsers.user_id != None)
            .order_by(DojoChallenges.module_index, DojoChallenges.challenge_index, Solves.date)
            .with_entities(Solves.user_id, DojoModules.id, DojoChallenges.id, Solves.date)
        )
        for user, module, challenge, time in solves:
            time = time.replace(tzinfo=datetime.timezone.utc)
            yield f"{user},{module},{challenge},{time}\n"
    headers = {"Content-Disposition": "attachment; filename=data.csv"}
    return Response(stream_with_context(stream()), headers=headers, mimetype="text/csv")


@dojos.route("/admin/dojos")
@admins_only
def view_all_dojos():
    return render_template("admin_dojos.html", dojos=Dojos.query.order_by(*Dojos.ordering()).all())


def dojos_override():
    return redirect(url_for("pwncollege_dojos.listing"), code=301)
