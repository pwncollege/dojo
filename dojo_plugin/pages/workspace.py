import hmac

from flask import request, Blueprint, Response, render_template, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.plugins import bypass_csrf_protection

from ..models import Dojos
from ..utils import user_ipv4, get_current_container, container_password
from ..utils.dojo import get_current_dojo_challenge


workspace = Blueprint("pwncollege_workspace", __name__)
port_names = {
    "challenge": 80,
    "terminal": 7681,
    "code": 8080,
    "desktop": 6080,
    "desktop-windows": 6082,
}


@workspace.route("/workspace", methods=["GET"])
@authed_only
def view_workspace():

    current_challenge = get_current_dojo_challenge()
    if not current_challenge:
        return render_template("error.html", error="No active challenge session; start a challenge!")

    practice = get_current_container().labels.get("dojo.mode") == "privileged"

    return render_template(
        "workspace.html",
        practice=practice,
        challenge=current_challenge,
    )


@workspace.route("/workspace/<service>")
@authed_only
def view_workspace_service(service):
    return render_template("workspace_service.html", iframe_name="workspace", service=service)

@workspace.route("/workspace/<service>/", websocket=True)
@workspace.route("/workspace/<service>/<path:service_path>", websocket=True)
@workspace.route("/workspace/<service>/", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"])
@workspace.route("/workspace/<service>/<path:service_path>", methods=["GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"])
@authed_only
@bypass_csrf_protection
def forward_workspace(service, service_path=""):
    prefix = f"/workspace/{service}/"
    assert request.full_path.startswith(prefix)
    service_path = request.full_path[len(prefix):]

    if service.count("~") == 0:
        service_name = service
        try:
            user = get_current_user()
            port = int(port_names.get(service_name, service_name))
        except ValueError:
            abort(404)

    elif service.count("~") == 1:
        service_name, user_id = service.split("~", 1)
        try:
            user = Users.query.filter_by(id=int(user_id)).first_or_404()
            port = int(port_names.get(service_name, service_name))
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
        try:
            user = Users.query.filter_by(id=int(user_id)).first_or_404()
            port = int(port_names.get(service_name, service_name))
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

    return Response(headers={
        "X-Accel-Redirect": "@workspace",
        "redirect_uri": f"http://{user_ipv4(user)}:{port}/{service_path}",
    })
