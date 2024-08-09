import docker
import hmac

from flask import request, Blueprint, render_template, url_for, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only
from CTFd.plugins import bypass_csrf_protection

from ..models import Dojos
from ..utils import redirect_user_socket, get_current_container, container_password
from ..utils.dojo import get_current_dojo_challenge
from ..utils.workspace import exec_run, start_on_demand_service


workspace = Blueprint("pwncollege_workspace", __name__)
port_names = {
    "challenge": 80,
    "code": 8080,
    "desktop": 6080,
    "desktop-windows": 6082,
}


@workspace.route("/workspace/<service>")
@authed_only
def view_workspace(service):
    return render_template("workspace.html", iframe_name="workspace", service=service)

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

    return redirect_user_socket(user, port, service_path)
