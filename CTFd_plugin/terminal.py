from flask import Blueprint, Response, render_template
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from .settings import INSTANCE


terminal = Blueprint("terminal", __name__, template_folder="assets/terminal/")


@terminal.route("/terminal_ws")
@authed_only
def terminal_ws():
    response = Response()

    user = get_current_user()
    container_name = f"{INSTANCE}_user_{user.id}"

    redirect_uri = f"http://unix:/tmp/docker.sock:/containers/{container_name}/attach/ws?logs=0&stream=1&stdin=1&stdout=1&stderr=1"

    response.headers["X-Accel-Redirect"] = "/internal-ws/"
    response.headers["redirect_uri"] = redirect_uri

    return response


@terminal.route("/terminal")
@authed_only
def view_terminal():
    user = get_current_user()
    container_name = f"{INSTANCE}_user_{user.id}"
    return render_template("terminal.html")
