from flask import request, Blueprint, Response, render_template, abort
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.models import Users
import docker

from ..utils import get_current_challenge_id, random_home_path


docker_client = docker.from_env()
desktop = Blueprint("desktop", __name__)


@desktop.route("/desktop")
@authed_only
def view_desktop():
    active = get_current_challenge_id() is not None
    return render_template("desktop.html", active=active, user_id=get_current_user().id, view_only=0)

@desktop.route("/desktop/<int:user_id>")
@admins_only
def view_specific_desktop(user_id):
    view_only = bool(request.args.get("view_only"))
    return render_template("desktop.html", active=True, user_id=user_id, view_only=int(view_only))

@desktop.route("/desktop/", defaults={"path": ""})
@desktop.route("/desktop/<int:user_id>/<path:path>")
@authed_only
def forward_desktop(user_id, path):
    prefix = f"/desktop/{user_id}/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix) :]

    if not is_admin() and user_id != get_current_user().id:
        abort(403)

    response = Response()

    user = Users.query.filter_by(id=user_id).first()
    assert user is not None
    redirect_uri = f"http://unix:/var/homes/nosuid/{random_home_path(user)}/.vnc/novnc.socket:/{path}"

    response.headers["X-Accel-Redirect"] = "/internal/"
    response.headers["redirect_uri"] = redirect_uri

    return response

@desktop.route("/admin/desktops", methods=["GET"])
@admins_only
def view_all_desktops():
    containers = docker_client.containers.list(filters=dict(name="user_"), ignore_removed=True)
    uids = [ c.name.split("_")[-1] for c in containers ]
    users = [ Users.query.filter_by(id=uid).first() for uid in uids ]
    return render_template("admin_desktops.html", users=users)
