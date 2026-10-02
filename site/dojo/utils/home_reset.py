import json
import logging
import uuid
from contextlib import closing
from itertools import chain

import docker
import redis
import requests
from flask import Response


logger = logging.getLogger(__name__)
HOME_RESET_TIMEOUT = 180
HOME_RESET_LOCK_TIMEOUT = 600
MAX_ARCHIVE_SIZE = 1024 * 1024 * 1024
HOME_RATE_LIMIT_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 3600)
if redis.call('ZCARD', KEYS[1]) >= 3 then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return math.max(1, math.ceil(tonumber(oldest[2]) + 3600 - now))
end
redis.call('ZADD', KEYS[1], now, ARGV[1])
redis.call('EXPIRE', KEYS[1], 3600)
return 0
"""


class HomeResetError(Exception):
    def __init__(self, message, status=500, *, uncertain=False, retry_after=None):
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain
        self.retry_after = retry_after


def check_home_rate_limit(redis_client, user_id, action):
    try:
        retry_after = redis_client.eval(HOME_RATE_LIMIT_SCRIPT, 1, f"user.{user_id}.home.{action}.requests", uuid.uuid4().hex)
    except redis.exceptions.RedisError as error:
        raise HomeResetError("Home management is temporarily unavailable. Please try again.", 503) from error
    if retry_after:
        raise HomeResetError("You can back up or reset your home three times per hour. Please try again later.",
                             429, retry_after=retry_after)


def run_home_command(homefs, user_id, action):
    stderr, size = b"", 0
    try:
        _, chunks = homefs.exec_run(
            ["/usr/bin/timeout", "-k", "10", str(HOME_RESET_TIMEOUT),
             "/usr/local/bin/python", "/opt/homefs/reset_home.py", str(user_id), action],
            user="0", stream=True, demux=True,
        )
        with closing(chunks):
            for data, diagnostic in chunks:
                stderr = (stderr + (diagnostic or b""))[-4096:]
                if data:
                    size += len(data)
                    if size > MAX_ARCHIVE_SIZE:
                        raise ValueError("Home backup exceeds archive limit")
                    yield data
        detail = json.loads(stderr.splitlines()[-1])
        if not isinstance(detail, dict) or detail.get("event") not in ("complete", "failed"):
            raise ValueError("Invalid home operation result")
        if detail["event"] == "failed":
            logger.error("Home operation failed user_id=%s action=%s detail=%s", user_id, action, detail)
            status = detail.get("status", 500)
            message = {409: "Home storage is busy. Please try again.",
                       404: "No home directory found. Start a challenge and try again.",
                       413: "The backup exceeds 1 GiB. Remove some files and try again."}
            raise HomeResetError(message.get(status, "Could not complete the home operation. Please try again."), status)
        if action == "backup" and not 0 < size == detail.get("size"):
            raise ValueError("Incomplete home backup")
    except (docker.errors.DockerException, requests.RequestException, OSError, ValueError, IndexError) as error:
        logger.exception("Unable to confirm home operation user_id=%s action=%s", user_id, action)
        raise HomeResetError("Could not confirm completion. Wait 10 minutes before trying again.",
                             503, uncertain=True, retry_after=HOME_RESET_LOCK_TIMEOUT) from error


def manage_home_directory(docker_client, user_id, lock, *, action):
    def operation():
        try:
            acquired = lock.acquire(blocking=False)
        except redis.exceptions.RedisError as error:
            raise HomeResetError("Workspace locking is unavailable. Please try again.", 503) from error
        if not acquired:
            raise HomeResetError("Another workspace operation is in progress. Please try again.", 409)
        uncertain = False
        previous_timeout = docker_client.api.timeout
        try:
            try:
                homefs = docker_client.containers.get("homefs")
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
            docker_client.api.timeout = HOME_RESET_TIMEOUT + 30
            uncertain = True
            yield from run_home_command(homefs, user_id, action)
            uncertain = False
        except HomeResetError as error:
            uncertain = error.uncertain
            raise
        finally:
            docker_client.api.timeout = previous_timeout
            # A disconnected exec can still hold the homefs lock until its timeout.
            if not uncertain:
                try:
                    lock.release()
                except redis.exceptions.RedisError:
                    logger.exception("Failed to release home operation lock user_id=%s", user_id)

    stream = operation()
    if action == "reset":
        with closing(stream):
            for _ in stream:
                pass
        return {"success": True, "message": "Home reset. Start a new challenge to continue."}
    first = next(stream)
    response = Response(chain((first,), stream), mimetype="application/gzip", headers={
        "Content-Disposition": "attachment; filename=home-backup.tar.gz",
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
    })
    response.call_on_close(stream.close)
    return response
