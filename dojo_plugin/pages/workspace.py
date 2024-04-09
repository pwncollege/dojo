import hmac

from flask import request, Blueprint, render_template, redirect, url_for, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ..models import Dojos
from ..utils import random_home_path, redirect_user_socket, get_current_container
from ..utils.dojo import dojo_route, get_current_dojo_challenge
from ..utils.workspace import exec_run


workspace = Blueprint("pwncollege_workspace", __name__)
port_names = {
    "challenge": 80,
    "vscode": 6080,
    "desktop": 6081,
    "desktop-windows": 6082,
}
ondemand_services = { "vscode", "desktop", "desktop-windows" }

def container_password(container, *args):
    key = container.labels["dojo.auth_token"].encode()
    message = "-".join(args).encode()
    return hmac.HMAC(key, message, "sha256").hexdigest()


@workspace.route("/workspace/desktop")
@authed_only
def view_desktop():
    user_id = request.args.get("user")
    password = request.args.get("password")

    if user_id and not password and not is_admin():
        abort(403)

    user = get_current_user() if not user_id else Users.query.filter_by(id=int(user_id)).first_or_404()
    container = get_current_container(user)
    if not container:
        return render_template("iframe.html", active=False)

    exec_run(
        "/opt/pwn.college/services.d/desktop",
        workspace_user="hacker", user_id=user.id, shell=True,
        assert_success=True
    )

    interact_password = container_password(container, "desktop", "interact")
    view_password = container_password(container, "desktop", "view")

    if user_id and password:
        if not hmac.compare_digest(password, interact_password) and not hmac.compare_digest(password, view_password):
            abort(403)
        password = password[:8]
    else:
        password = interact_password[:8]

    view_only = user_id is not None
    service = "~".join(("desktop", str(user.id), container_password(container, "desktop")))

    vnc_params = {
        "autoconnect": 1,
        "reconnect": 1,
        "reconnect_delay": 10,
        "resize": "remote",
        "path": url_for("pwncollege_workspace.forward_workspace", service=service, service_path="websockify"),
        "view_only": int(view_only),
        "password": password,
    }
    iframe_src = url_for("pwncollege_workspace.forward_workspace", service=service, service_path="vnc.html", **vnc_params)

    share_urls = {
        "Desktop (Interact)": url_for("pwncollege_workspace.view_desktop", user=user.id, password=interact_password, _external=True),
        "Desktop (View)": url_for("pwncollege_workspace.view_desktop", user=user.id, password=view_password, _external=True),
    }

    return render_template("iframe.html",
                           iframe_name="workspace",
                           iframe_src=iframe_src,
                           share_urls=share_urls,
                           active=True)


@workspace.route("/workspace/<service>")
@authed_only
def view_workspace(service):
    active = bool(get_current_dojo_challenge())
    return render_template("iframe.html", iframe_name="workspace", iframe_src=f"/workspace/{service}/", active=active)


@workspace.route("/workspace/<service>/", websocket=True)
@workspace.route("/workspace/<service>/<path:service_path>", websocket=True)
@workspace.route("/workspace/<service>/")
@workspace.route("/workspace/<service>/<path:service_path>")
@authed_only
def forward_workspace(service, service_path=""):
    prefix = f"/workspace/{service}/"
    assert request.full_path.startswith(prefix)
    service_path = request.full_path[len(prefix):]

    if service.count("~") == 0:
        port = service
        try:
            user = get_current_user()
            port = int(port_names.get(port, port))
        except ValueError:
            abort(404)

        if service in ondemand_services:
            exec_run(
                f"/opt/pwn.college/services.d/{service}",
                workspace_user="hacker", user_id=user.id, shell=True,
                assert_success=True
            )

    elif service.count("~") == 1:
        port, user_id = service.split("~", 1)
        try:
            user = Users.query.filter_by(id=int(user_id)).first_or_404()
            port = int(port_names.get(port, port))
        except ValueError:
            abort(404)

        container = get_current_container(user)
        if not container:
            abort(404)
        dojo = Dojos.from_id(container.labels["dojo.dojo_id"]).first()
        if not dojo.is_admin():
            abort(403)

    elif service.count("~") == 2:
        service_name, user_id, access_code = service.split("~", 2)
        port = service_name
        try:
            user = Users.query.filter_by(id=int(user_id)).first_or_404()
            port = int(port_names.get(port, port))
        except ValueError:
            abort(404)

        container = get_current_container(user)
        if not container:
            abort(404)
        correct_access_code = container_password(container, service_name)
        if not hmac.compare_digest(access_code, correct_access_code):
            abort(403)

    else:
        abort(404)

    current_user = get_current_user()
    if user != current_user:
        print(f"User {current_user.id} is accessing User {user.id}'s workspace (port {port})", flush=True)

    return redirect_user_socket(user, port, service_path)
