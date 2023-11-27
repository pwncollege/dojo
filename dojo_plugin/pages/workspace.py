import hmac

from flask import request, Blueprint, render_template, redirect, url_for, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ..models import Dojos
from ..utils import random_home_path, redirect_user_socket, get_current_container
from ..utils.dojo import dojo_route, get_current_dojo_challenge


workspace = Blueprint("pwncollege_workspace", __name__)
port_names = {
    "challenge": 80,
    "vscode": 6080,
    "desktop": 6081,
    "desktop-windows": 6082,
}


def container_password(container, *args):
    key = container.id.encode()
    message = "-".join(args).encode()
    return hmac.HMAC(key, message, "sha256").hexdigest()


@workspace.route("/workspace/desktop")
@authed_only
def view_desktop():
    user_id = request.args.get("user")
    password = request.args.get("password")

    if user_id and password:
        user = Users.query.filter_by(id=int(user_id)).first_or_404()
        container = get_current_container(user)
        interact_password = container_password(container, "desktop", "interact")
        view_password = container_password(container, "desktop", "view")
        if not hmac.compare_digest(password, interact_password) and not hmac.compare_digest(password, view_password):
            abort(403)
        password = password[:8]
        view_only = True
        access_code = container_password(container, "desktop")
        service = f"desktop~{user.id}~{access_code}"

    elif user_id and not password:
        if not is_admin():
            abort(403)
        user = Users.query.filter_by(id=int(user_id)).first_or_404()
        container = get_current_container(user)
        password = container_password(container, "desktop", "interact")[:8]
        view_only = True
        service = f"desktop~{user.id}"

    else:
        user = get_current_user()
        container = get_current_container(user)
        password = container_password(container, "desktop", "interact")[:8]
        view_only = False
        service = "desktop"

    vnc_params = {
        "autoconnect": 1,
        "reconnect": 1,
        "reconnect_delay": 10,
        "resize": "remote",
        "view_only": int(view_only),
        "password": password,
    }
    iframe_src = url_for("pwncollege_workspace.forward_workspace", service=service, path="vnc.html", **vnc_params)
    active = bool(get_current_dojo_challenge(user))
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

    if service.count("~") == 0:
        port = service
        try:
            user = get_current_user()
            port = int(port_names.get(port, port))
        except ValueError:
            abort(404)

    elif service.count("~") == 1:
        port, user_id = service.split("~", 1)
        try:
            user = Users.query.filter_by(id=int(user_id)).first_or_404()
            port = int(port_names.get(port, port))
        except ValueError:
            abort(404)

        container = get_current_container(user)
        dojo = Dojos.from_id(container.labels["dojo.dojo_id"]).first()
        if not dojo.is_admin():
            abort(403)

    elif service.count("~") == 2:
        port, user_id, access_code = service.split("~", 2)
        try:
            user = Users.query.filter_by(id=int(user_id)).first_or_404()
            port = int(port_names.get(port, port))
        except ValueError:
            abort(404)

        container = get_current_container(user)
        correct_access_code = container_password(container, service)
        if not hmac.compare_digest(access_code, correct_access_code):
            abort(403)

    else:
        abort(404)

    return redirect_user_socket(user, port, path)
