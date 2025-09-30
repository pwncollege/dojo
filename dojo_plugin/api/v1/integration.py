import logging
import docker
from flask import request, session
from flask_restx import Namespace, Resource
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import Users, Solves
from ...utils import validate_user_container

logger = logging.getLogger(__name__)

integrations_namespace = Namespace(
    "integrations", description="Endpoints for external integrations",
    decorators=[bypass_csrf_protection]
)

# Authentication of external applications.
def authenticate_application(token):
    return None, ({
        "success": False,
        "error": "Not Implemented",
        }, 405)

# Authentication of the internal dojo cli application.
def authenticate_container(token):
    try:
        user_id = validate_user_container(token)
        user = Users.query.filter_by(id=user_id).one()
        return user, None
    except:
        return None, ({
            "success": False,
            "error": "Invalid container authentication token",
            }, 401)

def authenticate(token, type):
    if not token:
        return None, ({
            "success": False,
            "error": "Authentication token is required",
            }, 400)

    match type:
        case "container":
            return authenticate_container(token)
        
        case "application":
            return authenticate_application(token)

        case _:
            return None, ({
                "success": False,
                "error": f"Unrecognized authentication type \"{type}\"",
                }, 400)

@integrations_namespace.route("/check_auth")
class check_authentication(Resource):
    def post(self):
        data = request.get_json()
        token = data.get("token")
        auth_type = data.get("type")
        user, message = authenticate(token, auth_type)
        if message:
            return message

        if not user:
            return ({
                "success": False,
                "error": "Authentication process failed"
                }, 500)

        return ({
            "success": True,
            "user_id": user.id,
            }, 200)

@integrations_namespace.route("/submit")
class submit(Resource):
    def post(self):
        return ({
            "success": False,
            "error": "Not Implemented",
            }, 405)

@integrations_namespace.route("/start")
class start(Resource):
    def post(self):
        return ({
            "success": False,
            "error": "Not Implemented",
            }, 405)

@integrations_namespace.route("/restart")
class restart(Resource):
    def post(self):
        return ({
            "success": False,
            "error": "Not Implemented",
            }, 405)

@integrations_namespace.route("/list")
@integrations_namespace.route("/list/<dojo>")
@integrations_namespace.route("/list/<dojo>/<module>")
class submit(Resource):
    def get(self, dojo=None, module=None):
        return ({
            "success": False,
            "error": "Not Implemented",
            }, 405)

@integrations_namespace.route("/info")
class info(Resource):
    def get(self):
        return ({
            "success": False,
            "error": "Not Implemented",
            }, 405)
