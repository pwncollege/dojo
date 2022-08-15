from flask import request, Blueprint, Response, render_template
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from ..utils import get_current_challenge_id, random_home_path


desktop = Blueprint("desktop", __name__)


@desktop.route("/desktop")
@authed_only
def view_desktop():
    active = get_current_challenge_id() is not None
    return render_template("desktop.html", active=active)


@desktop.route("/desktop/", defaults={"path": ""})
@desktop.route("/desktop/<path:path>")
@authed_only
def forward_desktop(path):
    prefix = "/desktop/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix) :]

    response = Response()

    user = get_current_user()
    redirect_uri = f"http://unix:/var/homes/nosuid/{random_home_path(user)}/.vnc/novnc.socket:/{path}"

    response.headers["X-Accel-Redirect"] = "/internal/"
    response.headers["redirect_uri"] = redirect_uri

    return response
