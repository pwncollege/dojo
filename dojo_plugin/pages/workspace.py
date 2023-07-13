from flask import request, Blueprint, render_template
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from ..utils import random_home_path, redirect_user_socket
from ..utils.dojo import dojo_route, get_current_dojo_challenge


workspace = Blueprint("pwncollege_workspace", __name__)


@workspace.route("/workspace")
@authed_only
def view_workspace():
    active = bool(get_current_dojo_challenge())
    return render_template("iframe.html", iframe_src="/workspace/", active=active)


@workspace.route("/workspace/")
@workspace.route("/workspace/<path:path>")
@authed_only
def forward_workspace(path=""):
    prefix = "/workspace/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix):]
    return redirect_user_socket(get_current_user(), ".local/share/code-server/workspace.socket", f"/{path}")
