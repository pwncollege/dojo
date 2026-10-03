import hmac
import os
from itertools import chain

import redis
from flask_restx import Namespace, Resource
from flask import request, url_for, abort, current_app, Response
from ...models import Users
from ...utils.user import get_current_user, is_admin
from ...utils.decorators import authed_only

from ...utils import get_current_container, container_password, parse_positive_int, user_node, user_docker_client
from ...utils.workspace import start_on_demand_service
from ...utils.home_management import WORKSPACE_LOCK_TIMEOUT, HomeManagementError, check_home_rate_limit, backup_home_directory, reset_home_directory
from ...pages.workspace import forward_workspace, forward_port
from ...config import WORKSPACE_SECRET


workspace_namespace = Namespace(
    "workspace", description="Endpoint to manage workspace iframe urls"
)

@workspace_namespace.route("")
class view_desktop(Resource):
    @authed_only
    def get(self):
        user_id = request.args.get("user")
        password = request.args.get("password")
        service = request.args.get("service", None)
        port = request.args.get("port", None)

        if user_id and not password and not is_admin():
            abort(403)

        if user_id is not None:
            user_id = parse_positive_int(user_id)
            if user_id is None:
                abort(404)

        if port is not None:
            port = parse_positive_int(port, maximum=65535)
            if port is None:
                abort(404)

        user = get_current_user() if user_id is None else Users.query.filter_by(id=user_id).first_or_404()
        container = get_current_container(user)
        if not container:
            return {"success": False, "active": False}

        # Get current challenge information from container labels
        challenge_info = None
        if container.labels.get("dojo.challenge_id"):
            challenge_info = {
                "dojo_id": container.labels.get("dojo.dojo_id"),
                "module_id": container.labels.get("dojo.module_id"),
                "challenge_id": container.labels.get("dojo.challenge_id")
            }


        elif not service or not port:
            return {"success": False, "active": True, "current_challenge": challenge_info}

        if not WORKSPACE_SECRET:
            abort(500)
            return

        container_id = container.id[:12]
        message = container_id

        node = user_node(user)
        if not node == None and not node == 0:
            message = f"{container_id}:192.168.42.{node + 1}"

        iframe_src = None
        if not service == "desktop":
            if user_id and not is_admin():
                abort(403)

        if service:
            if service == "desktop":
                interact_password = container_password(container, "desktop", "interact")
                view_password = container_password(container, "desktop", "view")

                if user_id and password:
                    if not hmac.compare_digest(password, interact_password) and not hmac.compare_digest(password, view_password):
                        abort(403)
                    password = password[:8]
                else:
                    password = interact_password[:8]

                view_only = user_id is not None
                service_param = "~".join(("desktop", str(user.id), container_password(container, "desktop")))

                vnc_params = {
                    "autoconnect": 1,
                    "reconnect": 1,
                    "reconnect_delay": 200,
                    "resize": "remote",
                    "path": forward_workspace(service=service_param, service_path="websockify", message=message, include_host=False),
                    "view_only": int(view_only),
                    "password": password,
                }
                iframe_src = forward_workspace(service=service_param, service_path="vnc.html", message=message, **vnc_params)

            elif service == "desktop-windows":
                service_param = "~".join(("desktop-windows", str(user.id), container_password(container, "desktop-windows")))
                vnc_params = {
                    "autoconnect": 1,
                    "reconnect": 1,
                    "reconnect_delay": 200,
                    "resize": "local",
                    "path": forward_workspace(service=service_param, service_path="websockify", message=message, include_host=False),
                    "password": "password",
                }
                iframe_src = forward_workspace(service=service_param, service_path="vnc.html", message=message, **vnc_params)
            else:
                iframe_src = forward_workspace(service=service, service_path="", message=message)

            if start_on_demand_service(user, service) is False:
                return {"success": False, "active": True, "error": f"Failed to start service {service}"}
        elif port:
            iframe_src = forward_port(port=port, service_path="", user=user, message=message)

        return {"success": True, "active": True, "iframe_src": iframe_src, "service": service, "port": port, "setPort": os.getenv("DOJO_ENV") == "development", "current_challenge": challenge_info}


@workspace_namespace.route("/reset_home")
class ResetHome(Resource):
    @authed_only
    def post(self):
        try:
            user, lock, homefs_url = prepare_home_request()
            reset_home_directory(user_docker_client(user), user.id, lock, homefs_url=homefs_url)
            return {"success": True, "message": "Home reset. Start a new challenge to continue."}
        except HomeManagementError as error:
            return home_error_response(error)


@workspace_namespace.route("/backup_home")
class BackupHome(Resource):
    @authed_only
    def post(self):
        try:
            user, lock, homefs_url = prepare_home_request()
            stream = backup_home_directory(user_docker_client(user), user.id, lock, homefs_url=homefs_url)
            first = next(stream)
            response = Response(chain((first,), stream), mimetype="application/gzip", headers={
                "Content-Disposition": "attachment; filename=home-backup.tar.gz",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            })
            response.call_on_close(stream.close)
            return response
        except HomeManagementError as error:
            return home_error_response(error)


def prepare_home_request():
    user = get_current_user()
    redis_client = redis.from_url(current_app.config["REDIS_URL"])
    check_home_rate_limit(redis_client, user.id)
    lock = redis_client.lock(f"user.{user.id}.docker.lock", timeout=WORKSPACE_LOCK_TIMEOUT,
                             blocking_timeout=0, raise_on_release_error=False)
    node = user_node(user)
    homefs_url = f"http://192.168.42.{node + 1}:4201" if node is not None else "http://homefs:4201"
    return user, lock, homefs_url


def home_error_response(error):
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else {}
    return {"success": False, "error": str(error)}, error.status, headers
