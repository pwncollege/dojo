import requests
import logging
import docker
import time
from typing import Any
from CTFd.models import Users
from flask import request, session
from .request_logging import log_generator_output
from ..utils import validate_user_container, get_current_container

from . import user_docker_client

logger = logging.getLogger(__name__)

on_demand_services = { "terminal", "code", "desktop"}

def start_on_demand_service(user, service_name):
    if service_name not in on_demand_services:
        return None
    try:
        exec_run(
            f"/run/current-system/sw/bin/timeout -k 10 30 /run/current-system/sw/bin/dojo-{service_name}",
            workspace_user="hacker",
            user_id=user.id,
            assert_success=True,
            log=True,
        )
    except (docker.errors.NotFound, AssertionError, requests.HTTPError) as exception:
        logger.warning(f"start_on_demand_service failure: {service_name=} {exception=}")
        return False
    return True


def exec_run(cmd, *, shell=False, assert_success=True, workspace_user="root", user_id=None, container=None, log=False, **kwargs):
    # TODO: Cleanup this interface
    if workspace_user == "root":
        workspace_user = "0"
    if workspace_user == "hacker":
        workspace_user = "1000"

    if shell:
        cmd = f"""/bin/sh -c \"
        {cmd}
        \""""

    if not container:
        docker_client = user_docker_client(Users.query.get(user_id))
        container = docker_client.containers.get(f"user_{user_id}")

    start_time = time.time()
    if log:
        exec_id = docker_client.api.exec_create(container.id, cmd, privileged=False, user=workspace_user)["Id"]
        out_stream = docker_client.api.exec_start(exec_id, stream=True, demux=False)
        output = b"".join(log_generator_output(f"exec_run {cmd=} ", out_stream, start_time=start_time))
        exit_code = docker_client.api.exec_inspect(exec_id)['ExitCode']
    else:
        exit_code, output = container.exec_run(cmd, user=workspace_user, **kwargs)

    logger.info(f"exec_run finished {cmd=} {workspace_user=} elapsed={time.time()-start_time:.1f}s {exit_code=} output={output[:13337]}")

    if assert_success:
        assert exit_code in (0, None), output
    return exit_code, output

def reset_home(user_id):
    exec_run("/bin/tar cvzf /tmp/home-backup.tar.gz /home/hacker", user_id=user_id, shell=True, workspace_user="hacker")
    exec_run("find /home/hacker -mindepth 1 -delete", user_id=user_id, shell=True, workspace_user="root")
    exec_run("chown hacker:hacker /home/hacker", user_id=user_id, shell=True, workspace_user="root")
    exec_run("cp /tmp/home-backup.tar.gz /home/hacker/", user_id=user_id, shell=True, workspace_user="hacker")

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

def authed_only_cli(func):
    """
    Function decorator, should be placed before
    authed_only. This opens the API to also be used
    by challenge containers.

    This checks if the request has a container API
    token, and authenticates using this token if it
    is present. In this case, sessions are destroyed
    after the request.

    Otherwise, normal authentication will happen.
    """
    def wrapper(*args, **kwargs):
        # Check for a container token.
        token = request.headers.get("AuthToken", None)

        # No token, do normal auth.
        if token is None:
            return func(*args, **kwargs)

        # Auth using token.
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
