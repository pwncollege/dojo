import os

from flask import request, Blueprint, render_template, abort
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.models import Users

from ..utils import random_home_path, get_active_users, redirect_user_socket
from ..utils.dojo import dojo_route, get_current_dojo_challenge
from ..utils.workspace import exec_run


desktop = Blueprint("pwncollege_desktop", __name__)


def can_connect_to(desktop_user):
    return any((
        is_admin(),
        desktop_user.id == get_current_user().id,
        os.path.exists(f"/var/homes/nosuid/{random_home_path(desktop_user)}/LIVE")
    ))


def can_control(desktop_user):
    return any((
        is_admin(),
        desktop_user.id == get_current_user().id
    ))


def view_desktop_res(route, user_id=None, password=None):
    current_user = get_current_user()
    if user_id is None:
        user_id = current_user.id

    user = Users.query.filter_by(id=user_id).first()
    if not can_connect_to(user):
        abort(403)

    if password is None:
        try:
            password_type = "interact" if can_control(user) else "view"
            password_path = f"/var/homes/nosuid/{random_home_path(user)}/.vnc/pass-{password_type}"
            password = open(password_path).read()
        except FileNotFoundError:
            password = None

    active = bool(password) if get_current_dojo_challenge(user) is not None else None
    view_only = int(user_id != current_user.id)

    iframe_src = f"/{route}/{user_id}/vnc.html?autoconnect=1&reconnect=1&path={route}/{user_id}/websockify&resize=remote&reconnect_delay=10&view_only={view_only}&password={password}"
    return render_template("iframe.html", iframe_name="workspace", iframe_src=iframe_src, active=active)

@desktop.route("/desktop")
@desktop.route("/desktop/<int:user_id>")
@authed_only
def view_desktop(user_id=None):
    return view_desktop_res("desktop", user_id)


@desktop.route("/desktop-win")
@desktop.route("/desktop-win/<int:user_id>")
@authed_only
def view_desktop_win(user_id=None):
    exec_run(
        "/opt/pwn.college/services.d/desktop-windows",
        workspace_user="hacker", user_id=user_id or get_current_user().id, shell=True,
        assert_success=True
    )
    return view_desktop_res("desktop-win", user_id, "abcd")


def forward_desktop_res(route, socket_path, user_id, path=""):
    prefix = f"/{route}/{user_id}/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix):]

    user = Users.query.filter_by(id=user_id).first()
    if not can_connect_to(user):
        abort(403)

    return redirect_user_socket(user, socket_path, path)


@desktop.route("/desktop/<int:user_id>/")
@desktop.route("/desktop/<int:user_id>/<path:path>")
@desktop.route("/desktop/<int:user_id>/", websocket=True)
@desktop.route("/desktop/<int:user_id>/<path:path>", websocket=True)
@authed_only
def forward_desktop(user_id, path=""):
    return forward_desktop_res("desktop", 6081, user_id, path)


@desktop.route("/desktop-win/<int:user_id>/")
@desktop.route("/desktop-win/<int:user_id>/<path:path>")
@desktop.route("/desktop-win/<int:user_id>/", websocket=True)
@desktop.route("/desktop-win/<int:user_id>/<path:path>", websocket=True)
@authed_only
def forward_desktop_win(user_id, path=""):
    return forward_desktop_res("desktop-win", 6082, user_id, path)


@desktop.route("/admin/desktops", methods=["GET"])
@admins_only
def view_all_desktops():
    # active_desktops=True here would filter out only desktops that have been connected to, but that is too slow in
    # the current implementation...
    return render_template("admin_desktops.html", users=get_active_users())
