import hmac
import os

from flask_restx import Namespace, Resource
from flask import request, url_for, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ...utils import get_current_container, container_password, parse_positive_int, user_node
from ...utils.workspace import start_on_demand_service, reset_home
from ...pages.workspace import (
    forward_workspace,
    forward_port,
    workspace_signature,
    workspace_xpra_tls_credentials,
)
from ...config import WORKSPACE_SECRET


workspace_namespace = Namespace(
    "workspace", description="Endpoint to manage workspace iframe urls"
)

@workspace_namespace.route("")
class view_desktop(Resource):
    @authed_only
    def get(self):
        user_id = request.args.get("user")
        if "password" in request.args:
            abort(400)
        password = request.headers.get("X-Workspace-Password")
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
        on_demand_service = service
        service_environment = None
        if not service == "desktop":
            if user_id and not is_admin():
                abort(403)

        if service:
            if service in ("desktop", "desktop-view"):
                on_demand_service = service
                if service == "desktop":
                    interact_password = container_password(
                        container, "desktop", "interact"
                    )
                    view_password = container_password(container, "desktop", "view")

                    if user_id and password:
                        interact_authorized = hmac.compare_digest(
                            password, interact_password
                        )
                        view_authorized = hmac.compare_digest(password, view_password)
                        if not interact_authorized and not view_authorized:
                            abort(403)
                        if view_authorized:
                            on_demand_service = "desktop-view"
                    elif user_id is not None:
                        on_demand_service = "desktop-view"

                service_param = "~".join((on_demand_service, str(user.id), container_password(container, on_demand_service)))

                xpra_params = {
                    "reconnect": 1,
                    "clipboard": 1,
                    "sharing": 1,
                    "steal": 1,
                    "toolbar_position": "novnc",
                    "autohide": 1,
                    "sound": 0,
                    "printing": 0,
                    "file_transfer": 0,
                    "remote_logging": 0,
                }
                iframe_src = forward_workspace(
                    service=service_param,
                    service_path="",
                    message=message,
                    transport="xpra",
                    **xpra_params,
                )
                tls_certificate, tls_private_key = workspace_xpra_tls_credentials(container_id)
                service_environment = {
                    "DOJO_XPRA_DESKTOP_ROUTE_PASSWORD": workspace_signature(
                        message, 6080, "xpra"
                    ),
                    "DOJO_XPRA_TLS_CERTIFICATE": tls_certificate,
                    "DOJO_XPRA_TLS_PRIVATE_KEY": tls_private_key,
                }
                if on_demand_service == "desktop-view":
                    service_environment["DOJO_XPRA_VIEW_ROUTE_PASSWORD"] = (
                        workspace_signature(message, 6081, "xpra")
                    )

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

            if start_on_demand_service(user, on_demand_service, environment=service_environment) is False:
                return {"success": False, "active": True, "error": f"Failed to start service {service}"}
        elif port:
            iframe_src = forward_port(port=port, service_path="", user=user, message=message)

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
