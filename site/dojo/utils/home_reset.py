import logging

import docker
import redis
import requests


logger = logging.getLogger(__name__)
HOME_RESET_TIMEOUT = 180
HOME_RESET_LOCK_TIMEOUT = 600


class HomeResetError(Exception):
    def __init__(self, message, status=500, *, uncertain=False, retry_after=None):
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain
        self.retry_after = retry_after


def check_home_rate_limit(redis_client, user_id):
    try:
        key = f"user.{user_id}.home.requests"
        with redis_client.pipeline() as counter:
            counter.incr(key)
            counter.expire(key, 3600, nx=True)
            counter.ttl(key)
            count, _, retry_after = counter.execute()
    except redis.exceptions.RedisError as error:
        raise HomeResetError("Home management is temporarily unavailable. Please try again.", 503) from error
    if count > 5:
        raise HomeResetError("Home management is limited to five operations per hour. Please try again later.",
                             429, retry_after=max(1, retry_after))


def request_home_operation(homefs_url, user_id, action):
    try:
        with requests.post(f"{homefs_url}/volume/{user_id}/{action}", stream=True, timeout=(5, HOME_RESET_TIMEOUT)) as response:
            if response.status_code != 200:
                raise HomeResetError(response.json().get("error", "Could not complete the home operation. Please try again."), response.status_code)
            if action == "backup":
                yield from response.iter_content(chunk_size=65536)
            elif not response.json().get("success"):
                raise ValueError("Home reset was not confirmed")
    except (requests.RequestException, ValueError) as error:
        logger.exception("Unable to confirm home operation user_id=%s action=%s", user_id, action)
        raise HomeResetError("Could not confirm completion. Wait 10 minutes before trying again.",
                             503, uncertain=True, retry_after=HOME_RESET_LOCK_TIMEOUT) from error


def manage_home_directory(docker_client, user_id, lock, *, homefs_url, action):
    try:
        acquired = lock.acquire(blocking=False)
    except redis.exceptions.RedisError as error:
        raise HomeResetError("Workspace locking is unavailable. Please try again.", 503) from error
    if not acquired:
        raise HomeResetError("Another workspace operation is in progress. Please try again.", 409)
    uncertain = False
    try:
        try:
            try:
                container = docker_client.containers.get(f"user_{user_id}")
            except docker.errors.NotFound:
                container = None
            if container is not None:
                if action == "reset":
                    raise HomeResetError("A workspace is active. Download a new backup before resetting.", 409)
                try:
                    container.stop(timeout=10)
                    # Workspaces use auto_remove; wait until their mounts have been released.
                    container.wait(condition="removed", timeout=30)
                except docker.errors.NotFound:
                    pass
        except (docker.errors.DockerException, requests.RequestException) as error:
            raise HomeResetError("Could not prepare the workspace. Please try again.", 503) from error
        uncertain = True
        yield from request_home_operation(homefs_url, user_id, action)
        uncertain = False
    except HomeResetError as error:
        uncertain = error.uncertain
        raise
    finally:
        # A disconnected request can still hold the homefs lock until its timeout.
        if not uncertain:
            try:
                lock.release()
            except redis.exceptions.RedisError:
                logger.exception("Failed to release home operation lock user_id=%s", user_id)
