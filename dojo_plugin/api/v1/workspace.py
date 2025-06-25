import hmac
import os
import hashlib
import base64

from flask_restx import Namespace, Resource
from flask import request, url_for, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ...utils import get_current_container, container_password
from ...utils.workspace import start_on_demand_service, reset_home
from ...pages.workspace import forward_workspace


workspace_namespace = Namespace(
    "workspace", description="Endpoint to manage workspace iframe urls"
)

signing_key = os.environ.get("WORKSPACE_SECRET")

@workspace_namespace.route("")
class view_desktop(Resource):
    @authed_only
    def get(self):
        user_id = request.args.get("user")
        password = request.args.get("password")
        service = request.args.get("service")

        if not service:
            return {"active": False}

        if user_id and not password and not is_admin():
            abort(403)

        user = get_current_user() if not user_id else Users.query.filter_by(id=int(user_id)).first_or_404()
        container = get_current_container(user)
        if not container:
            return {"active": False}

        if not signing_key:
            abort(500)
            return

        container_id = container.id
        if not container_id:
            abort(400, "Invalid container")
            return

        container_id = container_id[:12]

        digest = hmac.new(
            signing_key.encode(),
            container_id.encode(),
            hashlib.sha256
        ).digest()

        sig = base64.urlsafe_b64encode(digest).decode()

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
                "path": forward_workspace(service=service_param, service_path="websockify", sig=sig, container_id=container_id, include_host=False),
                "view_only": int(view_only),
                "password": password,
            }
            iframe_src = forward_workspace(service=service_param, service_path="vnc.html", sig=sig, container_id=container_id, **vnc_params)

        elif service == "desktop-windows":
            service_param = "~".join(("desktop-windows", str(user.id), container_password(container, "desktop-windows")))
            vnc_params = {
                "autoconnect": 1,
                "reconnect": 1,
                "reconnect_delay": 200,
                "resize": "local",
                "path": forward_workspace(service=service_param, service_path="websockify", sig=sig, container_id=container_id, include_host=False),
                "password": "password",
            }
            iframe_src = forward_workspace(service=service_param, service_path="vnc.html", sig=sig, container_id=container_id, **vnc_params)
        else:
            iframe_src = forward_workspace(service=service, service_path="", sig=sig, container_id=container_id)

        if start_on_demand_service(user, service) is False:
            return {"active": False}

        return {"active": True, "iframe_src": iframe_src, "service": service, "setPort": os.getenv("DOJO_ENV") == "development"}


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
