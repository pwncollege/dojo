from flask_restx import Namespace, Resource
from flask import request, render_template, url_for, abort
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from ...utils import get_current_container, container_password
from ...utils.workspace import exec_run, start_on_demand_service


workspace_namespace = Namespace(
    "workspace", description="Endpoint to manage workspace iframe urls"
)


@workspace_namespace.route("")
class view_desktop(Resource):
    @authed_only
    def get(self):
           user_id = request.args.get("user")
           password = request.args.get("password")
           service = request.args.get("service")

           if not service:
               return { "active": False }


           if user_id and not password and not is_admin():
               abort(403)

           user = get_current_user() if not user_id else Users.query.filter_by(id=int(user_id)).first_or_404()
           container = get_current_container(user)
           if not container:
               return { "active": False }


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
                   "path": url_for("pwncollege_workspace.forward_workspace", service=service_param, service_path="websockify"),
                   "view_only": int(view_only),
                   "password": password,
               }
               iframe_src = url_for("pwncollege_workspace.forward_workspace", service=service_param, service_path="vnc.html", **vnc_params)
           else:
               iframe_src = f"/workspace/{service}/"

           if start_on_demand_service(user, service) is False:
               return { "active": False }

           return {
           "iframe_src": iframe_src,
           "service": service,
           "active": True
           }
