import logging
import docker
from flask import request, session
from flask_restx import Namespace, Resource
from CTFd.plugins import bypass_csrf_protection
from CTFd.models import Users, Solves

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
    docker_client = docker.DockerClient(base_url="unix://var/run/docker.sock")

    container = None
    try:
        for c in docker_client.containers.list():
            if c.labels.get("dojo.auth_token") == token:
                continer = c
                break
    except Exception as e:
        logger.error(f"Exception while listing containers: {e}")
        return None, ({
            "success": False,
            "error": "Authentication processed failed"
            }, 500)

    if not container:
        return None, ({
            "success": False,
            "error": "Invalid container authentication token",
            }, 401)
    
    user_id = int(container.labels.get("dojo.as_user_id"))
    session["id"] = user_id
    user = Users.query.filter_by(id=user_id).one()

    return user, None

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


