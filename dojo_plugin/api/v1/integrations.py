import logging
import docker
from flask import request, session
from flask_restx import Namespace, Resource
from CTFd.plugins.challenges import get_chal_class
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import Users, Solves

from ...models import DojoChallenges

logger = logging.getLogger(__name__)

integrations_namespace = Namespace(
    "integrations", description="Endpoints for external integrations",
    decorators=[bypass_csrf_protection]
)


def authenticate_container(auth_token):
    if not auth_token:
        return None, ({"success": False, "error": "Missing auth_token"}, 400)
        
    docker_client = docker.DockerClient(base_url="unix://var/run/docker.sock")
    
    container = None
    try:
        for c in docker_client.containers.list():
            if c.labels.get("dojo.auth_token") == auth_token:
                container = c
                break
    except Exception as e:
        logger.error(f"Error listing containers: {e}")
        return None, ({"success": False, "error": "Failed to verify authentication"}, 500)
        
    if not container:
        return None, ({"success": False, "error": "Invalid authentication code"}, 401)
        
    user_id = int(container.labels.get("dojo.as_user_id"))
    dojo_id = container.labels.get("dojo.dojo_id")
    module_id = container.labels.get("dojo.module_id")
    challenge_id = container.labels.get("dojo.challenge_id")
    
    user = Users.query.filter_by(id=user_id).one()
    dojo_challenge = (DojoChallenges.from_id(dojo_id, module_id, challenge_id)
                      .filter(DojoChallenges.visible()).one())

    session["id"] = user_id
    return (user, dojo_challenge), None


@integrations_namespace.route("/solve")
class IntegrationSolve(Resource):
    def post(self):
        data = request.get_json()
        auth_token = data.get("auth_token") or data.get("auth_code")  # Support both for backward compatibility
        submission = data.get("submission")
        
        if not submission:
            return {"success": False, "error": "Missing submission"}, 400
            
        auth_result, error_response = authenticate_container(auth_token)
        if error_response:
            return error_response
            
        user, dojo_challenge = auth_result

        solve = Solves.query.filter_by(user=user, challenge=dojo_challenge.challenge).first()
        if solve:
            return {"success": True, "status": "already_solved"}

        chal_class = get_chal_class(dojo_challenge.challenge.type)
        request.form = {"submission": submission}
        status, _ = chal_class.attempt(dojo_challenge.challenge, request)
        if status:
            chal_class.solve(user, None, dojo_challenge.challenge, request)
            return {"success": True, "status": "solved"}
        else:
            chal_class.fail(user, None, dojo_challenge.challenge, request)
            return {"success": False, "status": "incorrect"}, 400
