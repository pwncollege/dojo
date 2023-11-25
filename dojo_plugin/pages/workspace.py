import hashlib
from urllib.parse import urlparse

from flask import request, Blueprint, render_template, redirect, url_for, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ..utils import random_home_path, redirect_user_socket, get_current_container
from ..utils.dojo import dojo_route, get_current_dojo_challenge


workspace = Blueprint("pwncollege_workspace", __name__)
port_names = {
    "challenge": 80,
    "vscode": 6080,
    "desktop": 6081,
    "desktop-windows": 6082,
}


@workspace.route("/workspace/desktop")
@authed_only
def view_desktop():
    # vnc.html?autoconnect=1&reconnect=1&path={route}/{user_id}/websockify&resize=remote&reconnect_delay=10&view_only={view_only}&password={password}

    container = get_current_container()
    data = "-".join([container.id, "desktop", "view"])
    data = "-".join([container.id, "desktop", "interact"])
    hashlib.sha256(container.id).hexdigest()

    # current_user = get_current_user()
    # if user_id is None:
    #     user_id = current_user.id

    # user = Users.query.filter_by(id=user_id).first()
    # if not can_connect_to(user):
    #     abort(403)

    # if password is None:
    #     try:
    #         password_type = "interact" if can_control(user) else "view"
    #         password_path = f"/var/homes/nosuid/{random_home_path(user)}/.vnc/pass-{password_type}"
    #         password = open(password_path).read()
    #     except FileNotFoundError:
    #         password = None


    active = bool(get_current_dojo_challenge())
    iframe_src = f"/workspace/desktop/vnc.html?autoconnect=1&reconnect=1&resize=remote&reconnect_delay=10&view_only=0&password={data}"
    return render_template("iframe.html", iframe_src=iframe_src, active=active)


@workspace.route("/workspace/<service>")
@authed_only
def view_workspace(service):
    active = bool(get_current_dojo_challenge())
    return render_template("iframe.html", iframe_src=f"/workspace/{service}/", active=active)


@workspace.route("/workspace/<service>/")
@workspace.route("/workspace/<service>/<path:path>")
@workspace.route("/workspace/<service>/", websocket=True)
@workspace.route("/workspace/<service>/<path:path>", websocket=True)
@authed_only
def forward_workspace(service, path=""):
    prefix = f"/workspace/{service}/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix):]

    if "~" not in service:
        port = service
        try:
            user = get_current_user()
            port = int(port_names.get(port, port))
        except ValueError:
            abort(404)

    elif is_admin():
        port, user_id = service.split("~")
        try:
            user = Users.query.filter_by(id=int(user_id)).first_or_404()
            port = int(port_names.get(port, port))
        except ValueError:
            abort(404)

    else:
        abort(403)

    return redirect_user_socket(user, port, path)
