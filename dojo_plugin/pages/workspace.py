import hmac
import os

from flask import request, Blueprint, Response, render_template, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.plugins import bypass_csrf_protection
from urllib.parse import urlencode

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

@workspace.route("/workspace/<int:port>", strict_slashes=False)
@authed_only
def view_workspace_port(port):
    return render_template("workspace_port.html", iframe_name="workspace", port=port)

@workspace.route("/workspace/<string:service>", strict_slashes=False)
@authed_only
def view_workspace_service(service):
    return render_template("workspace_service.html", iframe_name="workspace", service=service)

def forward_workspace(service, signature, message, service_path="", include_host=True, **kwargs):
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

    return forward_port(
        port,
        signature,
        message,
        user,
        service_path=service_path,
        include_host=include_host,
        **(kwargs or {})
    )

def forward_port(port, signature, message, user, service_path="", include_host=True, **kwargs):
    current_user = get_current_user()
    if user != current_user:
        print(f"User {current_user.id} is accessing User {user.id}'s workspace (port {port})", flush=True)

    workspace_host = os.environ.get("WORKSPACE_HOST")

    if not workspace_host:
        abort(500)
        return

    url = f"/workspace/{message}/{signature}/{port}/{service_path}"

    scheme = request.scheme if request else "http"

    if include_host:
        url = f"{scheme}://{workspace_host}{url}"

    params = dict(kwargs or {})

    if params:
        args = urlencode(params)
        url = f"{url}?{args}"

    return url
