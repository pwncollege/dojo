from flask import request, Blueprint, render_template, abort
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.models import Users

from ..utils import get_current_challenge_id, random_home_path, get_active_users, redirect_user_socket


desktop = Blueprint("desktop", __name__)

@desktop.route("/desktop", defaults={"user_id": None})
@desktop.route("/desktop/<int:user_id>")
@admins_only
def view_desktop(user_id):
    current_user = get_current_user()
    if user_id is None:
        user_id = current_user.id
        active = get_current_challenge_id() is not None
    else:
        if not is_admin() and user_id != current_user.id:
            abort(403)
        active = True

    user = Users.query.filter_by(id=user_id).first()
    view_only = bool(request.args.get("view_only"))
    pwtype = "view" if view_only else "interact"
    with open(f"/var/homes/nosuid/{random_home_path(user)}/.vnc/pass-{pwtype}") as pwfile:
        password = pwfile.read()

    return render_template("desktop.html", password=password, active=active, user_id=user_id, view_only=int(view_only))

@desktop.route("/desktop/", defaults={"path": ""})
@desktop.route("/desktop/<int:user_id>/<path:path>")
@authed_only
def forward_desktop(user_id, path):
    prefix = f"/desktop/{user_id}/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix) :]

    if not is_admin() and user_id != get_current_user().id:
        abort(403)

    user = Users.query.filter_by(id=user_id).first()
    return redirect_user_socket(user, ".vnc/novnc.socket", f"/{path}")

@desktop.route("/admin/desktops", methods=["GET"])
@admins_only
def view_all_desktops():
    return render_template("admin_desktops.html", users=get_active_users())
