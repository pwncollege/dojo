from typing import Any
from flask import request, session
from flask_restx import Namespace, Resource
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import Users
from ...utils import validate_user_container, get_current_container

integration_namespace = Namespace(
    "integration",
    description="Endpoints for internal container integration",
    decorators=[bypass_csrf_protection]
)

def authenticate_container(token : str) -> tuple[Any, str | None, int | None]:
    """
    Takes in a container token and returns the user if authentication succeeds.
    Otherwise it will return `None`, an error message, and an error code.
    """

    try:
        userID, challengeID = validate_user_container(token)
    except:
        # validate user container (probably) raised BadSignature.
        return None, "Failed to authenticate container token.", 401
    
    # Validate user.
    user = Users.query.filter_by(id=userID).one()
    if user is None:
        return None, "Failed to authenticate container token", 401
    
    # Validate challenge matches.
    container = get_current_container(user)
    if container is None:
        return None, "No active challenge container.", 403
    if container.labels["dojo.challenge_id"] != challengeID:
        return None, "Token failed to authenticate active challenge container.", 403
    
    return user, None, None

# Idealy we would want to use before_request and teardown_request,
# however this is only supported at the application level. It is
# currently not possible to define this at the route or namespace
# level.
def authenticated(func):
    """
    Function decorator.

    Performs authentication of the request. Excepts
    authentication information to be provided as part
    of the request Headers. Temporarily creates an
    authenticated session, then destroys it before
    returning.
    """
    def wrapper(*args, **kwargs):
        # Authenticate.
        token = request.headers.get("AuthToken", None)
        if token is None:
            return ({"success": False, "error": "Authentication token not provided."}, 400)
        user, error, code = authenticate_container(token)
        if user is None:
            return ({"success": False, "error": error}, code)

        try:
            # Configure session and perform operation.
            session["id"] = user.id
            session["name"] = user.name
            session["type"] = user.type
            session["verified"] = user.verified
            session["cli"] = True
            return func(*args, **kwargs)

        except:
            # FUBAR
            return ({"success": False, "error": "An internal exception occured."}, 500)

        finally:
            # Make sure we destroy the session, no matter what.
            session["id"] = None
            session["name"] = None
            session["type"] = None
            session["verified"] = None
    return wrapper

@integration_namespace.route("/whoami")
class whoami(Resource):
    @authenticated
    def get(self):
        return ({
            "success": True,
            "message": f"You are the epic hacker {session["name"]} ({session["id"]}).",
            "user_id": session["id"]
            }, 200)
