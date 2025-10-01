import logging
import docker
from flask import request, session
from flask_restx import Namespace, Resource
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import Users, Solves
from ...utils import validate_user_container, get_current_container
from .docker import run_challenge_authed

logger = logging.getLogger(__name__)

integrations_namespace = Namespace(
    "integrations", description="Endpoints for external integrations",
    decorators=[bypass_csrf_protection]
)

def authenticate_container(token):
    """
    Authenticates the user by the containuer authentication token.
    """
    try:
        user_id = validate_user_container(token)
        user = Users.query.filter_by(id=user_id).one()
        return user, None
    except:
        return None, ({
            "success": False,
            "error": "Invalid container authentication token",
            }, 401)

def authenticated(func):
    """
    Performs integration authentication. Authentication information
    is passed in as part of the request headers. Authentication can
    be performed using a container token.
    """
    def wrapper(*args, **kwargs):
        method = request.headers.get("auth_method", None)
        token = request.headers.get("auth_token", None)
        if method is None or token is None:
            return ({
                "success": False,
                "error": "Authentication information not provided",
            }, 400)

        auth_methods = ["container"]
        match method:
            case "container":
                user, message = authenticate_container(token)
            case _:
                return ({
                    "success": False,
                    "error": f"Invalid authentication method \"{method}\", must be one of {str(auth_methods)}"
                }, 400)

        if message is not None:
            return message

        if user is None:
            return ({
                "success": False,
                "error": "Failed to authenticate"
            }, 401)

        kwargs["user"] = user

        return func(*args, **kwargs)
    return wrapper

@integrations_namespace.route("/check_auth")
class check_authentication(Resource):
    @authenticated
    def post(self, user=None):
        """
        Returns the authenticated user id if authentication succeeds.
        """
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
    @authenticated
    def post(self, user=None):
        """
        Starts a challenge in the given debug mode.

        Takes in 4 arguments as json data:
        - dojo
        - module
        - challenge
        - debug
        """
        data = request.json()
        dojo = data["dojo"]
        module = data["module"]
        challenge = data["module"]
        debug = data["practice"]

        if None in [dojo, module, challenge, debug]:
            return ({
                "success": False,
                "error": "Failed to supply proper arguments",
            }, 400)

        return run_challenge_authed(user, None, data, dojo, module, challenge, debug)

@integrations_namespace.route("/restart")
class restart(Resource):
    @authenticated
    def post(self, user=None):
        """
        Restarts the current challenge in the given mode.

        Takes 1 json argument:
        - practice
        """
        container = get_current_container(user)

        if container is None:
            return ({
                "success": False,
                "error": "No active challenge to restart",
            }, 200)

        dojo = container.labels["dojo.dojo_id"]
        module = container.labels["dojo.module_id"]
        challenge = container.labels["dojo.challenge_id"]
        debug = request.json()["practice"]

        run_challenge_authed(user, None, {}, dojo, module, challenge, debug)

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
