from urllib.parse import quote

from flask import request, Blueprint, render_template
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only, admins_only

from ..utils import redirect_internal
from ..utils.dojo import get_current_dojo_challenge


sensai = Blueprint("pwncollege_sensai", __name__)


@sensai.route("/sensai")
@admins_only
@authed_only
def view_sensai():
    active = bool(get_current_dojo_challenge())
    return render_template("iframe.html", iframe_src="/sensai/", active=active)


@sensai.route("/sensai/", methods=["GET", "POST"])
@sensai.route("/sensai/<path:path>", methods=["GET", "POST"])
@admins_only
@authed_only
def forward_sensai(path=""):
    user = get_current_user()
    path = quote(request.full_path.lstrip("/"), safe="/?=&")
    return redirect_internal(f"http://sensai/{path}", {"Authorization": f"User {user.id}"})
