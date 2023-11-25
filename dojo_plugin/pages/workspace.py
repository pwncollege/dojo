from urllib.parse import urlparse

from flask import request, Blueprint, render_template, redirect, url_for, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ..utils import random_home_path, redirect_user_socket
from ..utils.dojo import dojo_route, get_current_dojo_challenge


workspace = Blueprint("pwncollege_workspace", __name__)
port_names = {
    "vscode": 6080,
}


@workspace.route("/workspace")
@authed_only
def view_workspace():
    active = bool(get_current_dojo_challenge())
    return render_template("iframe.html", iframe_src="/workspace/vscode/", active=active)


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


def redirect_workspace_referers():
    referer = request.headers.get("Referer", "")
    referer_path = urlparse(referer).path
    current_path = request.path

    if referer_path.startswith("/workspace/") and not current_path.startswith("/workspace/"):
        return redirect(url_for("pwncollege_workspace.forward_workspace", service="vscode", path=current_path.lstrip("/")))
