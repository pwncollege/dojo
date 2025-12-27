import time
import logging
from typing import Any
from flask import request, session
from flask_restx import Namespace, Resource
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import Users, Solves
from CTFd.utils.user import get_current_user
from CTFd.plugins.challenges import get_chal_class
from dojo_plugin.api.v1.docker import start_challenge
from dojo_plugin.models import DojoChallenges, DojoModules
from dojo_plugin.utils.feed import publish_container_start
from ...utils import is_challenge_locked, validate_user_container, get_current_container
from ...utils.dojo import dojo_accessible, get_current_dojo_challenge

logger = logging.getLogger(__name__)

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

@integration_namespace.route("/solve")
class solve(Resource):
    @authenticated
    def post(self):
        user = get_current_user()
        dojo_challenge = get_current_dojo_challenge(user)

        if not dojo_challenge:
            return {"success": False, "error": "Challenge not found"}, 404

        solve = Solves.query.filter_by(user=user, challenge=dojo_challenge.challenge).first()
        if solve:
            return {"success": True, "status": "already_solved"}

        chal_class = get_chal_class(dojo_challenge.challenge.type)
        status, _ = chal_class.attempt(dojo_challenge.challenge, request)
        if status:
            chal_class.solve(user, None, dojo_challenge.challenge, request)
            return {"success": True, "status": "solved"}
        else:
            chal_class.fail(user, None, dojo_challenge.challenge, request)
            return {"success": False, "status": "incorrect"}, 400

@integration_namespace.route("/start")
class start(Resource):
    @authenticated
    def post(self):
        data = request.get_json()
        user = get_current_user()

        # Determine what challenge we are trying to start.
        if data.get("use_current_challenge", False):
            dojo_challenge = get_current_dojo_challenge(user)
            dojo_id = dojo_challenge.dojo.reference_id
            module_id = dojo_challenge.module.id
            challenge_id = dojo_challenge.id
        elif data.get("use_current_module", False):
            dojo_challenge = get_current_dojo_challenge(user)
            dojo_id = dojo_challenge.dojo.reference_id
            module_id = dojo_challenge.module.id
            challenge_id = data["challenge"]
        else:
            dojo_id = data.get("dojo")
            module_id = data.get("module")
            challenge_id = data.get("challenge")

        if None in [dojo_id, module_id, challenge_id]:
            return 400, {"success": False, "error": "Must supply dojo, module, and challenge (or supply a challenge and use_current_module as True)."}

        # Determine what mode we are trying to start in.
        mode = data.get("mode")
        if mode not in ["normal", "privileged", "current"]:
            return 400, {"success": False, "error": "Must specify mode as one of [normal, privileged, current]"}

        if mode == "normal":
            privileged = False
        elif mode == "privileged":
            privileged = True
        else:
            container = get_current_container(user)
            privileged = container.labels.get("dojo.mode") == "privileged"

        # Start the docker container! (modified from docker.py, with as_user removed)
        dojo = dojo_accessible(dojo_id)
        if not dojo:
            return 404, {"success": False, "error": "Invalid dojo"}

        dojo_challenge = (
            DojoChallenges.query.filter_by(id=challenge_id)
            .join(DojoModules.query.filter_by(dojo=dojo, id=module_id).subquery())
            .first()
        )
        if not dojo_challenge:
            return 404, {"success": False, "error": "Invalid challenge"}

        if not dojo_challenge.visible() and not dojo.is_admin():
            return 404, {"success": False, "error": "Invalid challenge"}

        if privileged and not dojo_challenge.allow_privileged:
            return 400, {
                "success": False,
                "error": "This challenge does not support practice mode.",
            }

        if is_challenge_locked(dojo_challenge, user):
            return 400, {
                "success": False,
                "error": "This challenge is locked"
            }

        max_attempts = 3
        for attempt in range(1, max_attempts+1):
            try:
                logger.info(f"Starting challenge for user {user.id} (attempt {attempt}/{max_attempts})...")
                start_challenge(user, dojo_challenge, privileged)

                if dojo.official or dojo.data.get("type") == "public":
                    challenge_data = {
                        "challenge_id": dojo_challenge.challenge_id,
                        "challenge_name": dojo_challenge.name,
                        "module_id": dojo_challenge.module.id if dojo_challenge.module else None,
                        "module_name": dojo_challenge.module.name if dojo_challenge.module else None,
                        "dojo_id": dojo.reference_id,
                        "dojo_name": dojo.name
                    }
                    mode = "practice" if privileged else "assessment"
                    publish_container_start(user, mode, challenge_data)

                break
            except Exception as e:
                logger.warning(f"Attempt {attempt} failed for user {user.id} with error: {e}")
                if attempt < max_attempts:
                    logger.info(f"Retrying... ({attempt}/{max_attempts})")
                    time.sleep(2)
        else:
            logger.error(f"ERROR: Docker failed for {user.id} after {max_attempts} attempts.")
            return 508, {"success": False, "error": "Docker failed"}

        return {"success": True}
