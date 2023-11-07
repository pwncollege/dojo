import datetime
import sys
import traceback

import docker
from flask import Blueprint, Response, stream_with_context, render_template, redirect, url_for, abort
from sqlalchemy.sql import and_
from sqlalchemy.exc import IntegrityError
from CTFd.models import db, Solves
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.plugins import bypass_csrf_protection

from ..models import DojoAdmins, DojoChallenges, DojoMembers, DojoModules, DojoUsers, Dojos
from ..utils import user_dojos
from ..utils.dojo import dojo_route, generate_ssh_keypair, dojo_update


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
    typed_dojos = {
        "Courses": [],
        "Topics": [],
        "More": [],
    }
    for dojo in Dojos.viewable(user=user):
        if dojo.type == "course":
            typed_dojos["Courses"].append(dojo)
        elif dojo.type == "topic":
            typed_dojos["Topics"].append(dojo)
        elif dojo.type == "hidden":
            continue
        else:
            typed_dojos["More"].append(dojo)

    return render_template("dojos.html", user=user, typed_dojos=typed_dojos)


@dojos.route("/dojos/create")
@authed_only
def dojo_create():
    public_key, private_key = generate_ssh_keypair()
    return render_template(
        "dojo_create.html",
        public_key=public_key,
        private_key=private_key,
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

    if dojo.official:
        return redirect(url_for("pwncollege_dojo.listing", dojo=dojo.reference_id))

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


@dojos.route("/dojo/<dojo>/admin/")
@dojo_route
def view_dojo_admin(dojo):
    if not dojo.is_admin():
        abort(403)
    return render_template("dojo_admin.html", dojo=dojo)


@dojos.route("/dojo/<dojo>/admin/activity")
@dojo_route
def view_dojo_activity(dojo):
    if not dojo.is_admin():
        abort(403)

    docker_client = docker.from_env()
    filters = {
        "name": "user_",
        "label": f"dojo.dojo_id={dojo.reference_id}"
    }
    containers = docker_client.containers.list(filters=filters, ignore_removed=True)

    actives = []
    now = datetime.datetime.now()
    for container in containers:
        dojo_id = container.labels["dojo.dojo_id"]
        module_id = container.labels["dojo.module_id"]
        challenge_id = container.labels["dojo.challenge_id"]
        challenge = DojoChallenges.from_id(dojo_id, module_id, challenge_id).first()
        created = datetime.datetime.fromisoformat(container.attrs["Created"].split(".")[0])
        uptime = now - created
        actives.append(dict(challenge=challenge, uptime=uptime))
    actives.sort(key=lambda active: active["uptime"])

    solves = dojo.solves().order_by(Solves.date).all()

    return render_template("dojo_activity.html", dojo=dojo, actives=actives, solves=solves)


@dojos.route("/dojo/<dojo>/admin/solves.csv")
@dojo_route
def view_dojo_solves(dojo):
    if not dojo.is_admin():
        abort(403)
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
