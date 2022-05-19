from flask import request, Blueprint, render_template
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from ..utils import get_current_challenge_id, random_home_path, dojo_route, redirect_user_socket


workspace = Blueprint("pwncollege_workspace", __name__)


@workspace.route("/workspace")
@workspace.route("/<dojo>/workspace")
@dojo_route
@authed_only
def view_workspace(dojo=None):
    active = get_current_challenge_id() is not None
    return render_template("workspace.html", dojo=dojo, active=active)


@workspace.route("/workspace/")
@workspace.route("/workspace/<path:path>")
@authed_only
def forward_workspace(path=""):
    prefix = "/workspace/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix):]
    return redirect_user_socket(get_current_user(), ".local/share/code-server/workspace.socket", f"/{path}")
