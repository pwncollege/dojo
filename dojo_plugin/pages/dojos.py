import sys
import traceback

from flask import Blueprint, render_template, redirect, url_for, abort
from sqlalchemy.exc import IntegrityError
from CTFd.models import db
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.plugins import bypass_csrf_protection

from ..models import DojoAdmins, DojoMembers, Dojos
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
    dojos = Dojos.viewable(user=user)
    return render_template("dojos.html", user=user, dojos=dojos)


@dojos.route("/dojo/<dojo>")
@dojo_route
def view_dojo(dojo):
    return redirect(url_for("pwncollege_dojo.listing", dojo=dojo.reference_id))


@dojos.route("/dojo/<dojo>/join/")
@dojos.route("/dojo/<dojo>/join/<password>")
@authed_only
def join_dojo(dojo, password=None):
    # TODO SECURITY: Yes I know this is CSRF-able; no don't do it

    dojo = Dojos.from_id(dojo).first()
    if not dojo:
        return {"success": False, "error": "Not Found"}, 404

    if (dojo.password and dojo.password != password) or dojo.official:
        return {"success": False, "error": "Forbidden"}, 403

    try:
        member = DojoMembers(dojo=dojo, user=get_current_user())
        db.session.add(member)
        db.session.commit()
    except IntegrityError:
        pass

    return {"success": True}


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


@dojos.route("/dojos/settings")
@authed_only
def dojo_settings():
    user = get_current_user()
    dojos = Dojos.viewable(user=user).join(DojoAdmins.query.filter_by(user=user).subquery()).all()
    public_key, private_key = generate_ssh_keypair()
    return render_template(
        "dojos_settings.html",
        user=user,
        dojos=dojos,
        public_key=public_key,
        private_key=private_key,
    )


def dojos_override():
    return redirect(url_for("pwncollege_dojos.listing"), code=301)
