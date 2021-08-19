import docker
from flask import request, Blueprint, Response, render_template
from flask_restx import Namespace, Resource
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only


terminal = Blueprint("terminal", __name__, template_folder="assets/terminal/")
terminal_namespace = Namespace("terminal", description="Endpoint to manage terminal")


@terminal.route("/terminal")
@authed_only
def view_terminal():
    user = get_current_user()
    container_name = f"user_{user.id}"
    return render_template("terminal.html")


@terminal.route("/terminal_ws")
@authed_only
def terminal_ws():
    response = Response()

    user = get_current_user()
    container_name = f"user_{user.id}"

    redirect_uri = f"http://unix:/tmp/docker.sock:/containers/{container_name}/attach/ws?logs=0&stream=1&stdin=1&stdout=1&stderr=1"

    response.headers["X-Accel-Redirect"] = "/internal-ws/"
    response.headers["redirect_uri"] = redirect_uri

    return response


@terminal_namespace.route("/resize")
class TerminalResize(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        try:
            width = int(data.get("width"))
            height = int(data.get("height"))
        except (ValueError, TypeError):
            return {"success": False, "error": "ERROR: Invalid width or height"}

        docker_client = docker.from_env()

        user = get_current_user()
        container_name = f"user_{user.id}"

        try:
            container = docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            return {"success": False, "error": "ERROR: No active container"}

        try:
            container.resize(height, width)
        except Exception as e:
            print(f"ERROR: Docker failed: {e}", file=sys.stderr, flush=True)
            return {"success": False, "error": "Docker failed"}

        return {"success": True}
