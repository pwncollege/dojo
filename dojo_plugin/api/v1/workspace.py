import hmac
import os
import hashlib
import base64

from flask_restx import Namespace, Resource
from flask import request, url_for, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ...utils import get_current_container, container_password, user_node
from ...utils.workspace import start_on_demand_service, reset_home
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

        user = get_current_user() if not user_id else Users.query.filter_by(id=int(user_id)).first_or_404()
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

        digest = hmac.new(
            WORKSPACE_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()

        signature = base64.urlsafe_b64encode(digest).decode()

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
                    "path": forward_workspace(service=service_param, service_path="websockify", signature=signature, message=message, include_host=False),
                    "view_only": int(view_only),
                    "password": password,
                }
                iframe_src = forward_workspace(service=service_param, service_path="vnc.html", signature=signature, message=message, **vnc_params)

            elif service == "desktop-windows":
                service_param = "~".join(("desktop-windows", str(user.id), container_password(container, "desktop-windows")))
                vnc_params = {
                    "autoconnect": 1,
                    "reconnect": 1,
                    "reconnect_delay": 200,
                    "resize": "local",
                    "path": forward_workspace(service=service_param, service_path="websockify", signature=signature, message=message, include_host=False),
                    "password": "password",
                }
                iframe_src = forward_workspace(service=service_param, service_path="vnc.html", signature=signature, message=message, **vnc_params)
            else:
                iframe_src = forward_workspace(service=service, service_path="", signature=signature, message=message)

            if start_on_demand_service(user, service) is False:
                return {"success": False, "active": True, "error": f"Failed to start service {service}"}
        elif port:
            iframe_src = forward_port(port=port, service_path="", user=user, signature=signature, message=message)

        return {"success": True, "active": True, "iframe_src": iframe_src, "service": service, "port": port, "setPort": os.getenv("DOJO_ENV") == "development", "current_challenge": challenge_info}


@workspace_namespace.route("/reset_home")
class ResetHome(Resource):
    @authed_only
    def post(self):
        user = get_current_user()

        if not get_current_container(user):
            return {"success": False, "error": "No running container found. Please start a container and try again."}

        try:
            reset_home(user.id)
        except AssertionError as e:
            return {"success": False, "error": f"Reset failed with error: {e}"}

        return {"success": True, "message": "Home directory reset successfully"}
