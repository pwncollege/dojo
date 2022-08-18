from flask import request, Blueprint, render_template
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from ..utils import get_current_challenge_id, random_home_path, redirect_user_socket


workspace = Blueprint("workspace", __name__)


@workspace.route("/workspace")
@authed_only
def view_workspace():
    active = get_current_challenge_id() is not None
    return render_template("workspace.html", active=active)


@workspace.route("/workspace/", defaults={"path": ""})
@workspace.route("/workspace/<path:path>")
@authed_only
def forward_workspace(path):
    prefix = "/workspace/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix) :]
    return redirect_user_socket(get_current_user(), ".local/share/code-server/workspace.socket", f"/{path}")
