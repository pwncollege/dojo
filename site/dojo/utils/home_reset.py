import json
import logging

import docker
import redis
import requests


logger = logging.getLogger(__name__)
HOME_RESET_TIMEOUT = 300
HOME_RESET_LOCK_TIMEOUT = HOME_RESET_TIMEOUT + 300


class HomeResetError(Exception):
    def __init__(self, message, status=500, *, uncertain=False):
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain


def reset_home_directory(docker_client, user_id, lock):
    try:
        acquired = lock.acquire(blocking=False)
    except redis.exceptions.RedisError as error:
        raise HomeResetError("Workspace locking is unavailable. Please try again.", 503) from error
    if not acquired:
        raise HomeResetError("Another workspace operation is in progress. Please try again.", 409)

    uncertain = False
    try:
        reset_locked_home(docker_client, user_id)
    except HomeResetError as error:
        uncertain = error.uncertain
        raise
    finally:
        # A lost connection can leave the homefs exec modifying files after the request ends.
        if not uncertain:
            try:
                lock.release()
            except redis.exceptions.RedisError:
                logger.exception("Failed to release home reset lock user_id=%s", user_id)


def reset_locked_home(docker_client, user_id):
    try:
        container = docker_client.containers.get(f"user_{user_id}")
    except docker.errors.NotFound as error:
        raise HomeResetError("No running container found. Please start a container and try again.", 409) from error
    except (docker.errors.DockerException, requests.RequestException) as error:
        raise HomeResetError("Workspace is unavailable. Please try again.", 503) from error

    if container.status != "running":
        raise HomeResetError("No running container found. Please start a container and try again.", 409)
    try:
        homefs = docker_client.containers.get("homefs")
    except (docker.errors.DockerException, requests.RequestException) as error:
        raise HomeResetError("Home storage is unavailable. Please try again.", 503) from error
    try:
        container.stop(timeout=10)
        # Workspaces use auto_remove; wait until their mounts have been released.
        container.wait(condition="removed", timeout=30)
    except docker.errors.NotFound:
        pass
    except (docker.errors.DockerException, requests.RequestException) as error:
        logger.exception("Could not confirm workspace stopped before home reset user_id=%s", user_id)
        raise HomeResetError("Could not stop the workspace. Please try again.", 503) from error

    previous_timeout = docker_client.api.timeout
    try:
        docker_client.api.timeout = HOME_RESET_TIMEOUT + 30
        try:
            exit_code, output = homefs.exec_run(
                ["/usr/bin/timeout", "-k", "10", str(HOME_RESET_TIMEOUT),
                 "/usr/local/bin/python", "/opt/homefs/reset_home.py", str(user_id)],
                user="0", demux=True,
            )
        except (docker.errors.DockerException, requests.RequestException) as error:
            logger.exception("Unable to confirm home reset completion user_id=%s; workspace has been stopped", user_id)
            raise HomeResetError(
                "Could not confirm the reset completed. Please contact an administrator before restarting your challenge.",
                503, uncertain=True,
            ) from error

        stdout, stderr = output or (b"", b"")
        stdout, stderr = stdout or b"", stderr or b""
        if exit_code is None:
            raise HomeResetError("Could not confirm the reset completed. Please contact an administrator.", 503, uncertain=True)
        if exit_code != 0:
            logger.error("Home reset failed user_id=%s exit_code=%s stdout_tail=%r stderr_tail=%r",
                         user_id, exit_code, stdout[-4096:], stderr[-4096:])
            detail = {}
            try:
                detail = json.loads(stderr.splitlines()[-1])
            except (IndexError, ValueError):
                pass
            if not isinstance(detail, dict):
                detail = {}
            if detail.get("phase") == "lock":
                raise HomeResetError("Home storage is busy. Please try again.", 409)
            if detail.get("backup"):
                raise HomeResetError("Home reset failed. Your backup was preserved; contact an administrator for recovery.")
            if exit_code in (124, 137):
                raise HomeResetError("Home reset timed out. Please contact an administrator for recovery.")
            raise HomeResetError("Could not reset your home directory. Please contact an administrator.")
        if stderr:
            logger.warning("Home reset cleanup warning user_id=%s stderr_tail=%r", user_id, stderr[-4096:])
        logger.info("Home reset complete user_id=%s", user_id)
    finally:
        docker_client.api.timeout = previous_timeout
