import gzip
import io
import json
import logging
import tarfile
import tempfile
import time
import uuid

import docker
import redis
import requests
from flask import send_file


logger = logging.getLogger(__name__)
HOME_RESET_TIMEOUT = 180
HOME_TRANSFER_TIMEOUT = 60
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


class HomeArchive:
    def __init__(self, file, size, skipped=0):
        self.file = file
        self.size = size
        self.skipped = skipped
        self.status = "success"
        self.message = "Home backup downloaded."


class DockerArchiveReader(io.RawIOBase):
    def __init__(self, chunks, deadline):
        self.chunks = iter(chunks)
        self.pending = memoryview(b"")
        self.deadline = deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        if time.monotonic() > self.deadline:
            raise TimeoutError("Home backup transfer timed out")
        while not self.pending:
            try:
                self.pending = memoryview(next(self.chunks))
            except StopIteration:
                return 0
        if time.monotonic() > self.deadline:
            raise TimeoutError("Home backup transfer timed out")
        count = min(len(buffer), len(self.pending))
        buffer[:count] = self.pending[:count]
        self.pending = self.pending[count:]
        return count

    def close(self):
        try:
            close = getattr(self.chunks, "close", None)
            if close:
                close()
        finally:
            super().close()


def check_home_rate_limit(redis_client, user_id, *, downloads_only=False):
    bucket = "downloads" if downloads_only else "requests"
    try:
        retry_after = redis_client.eval(HOME_RATE_LIMIT_SCRIPT, 1, f"user.{user_id}.home.{bucket}", uuid.uuid4().hex)
    except redis.exceptions.RedisError as error:
        raise HomeResetError("Home management is temporarily unavailable. Please try again.", 503) from error
    if retry_after:
        operation = "download your latest backup" if downloads_only else "back up or reset your home"
        raise HomeResetError(f"You can {operation} three times per hour. Please try again later.",
                             429, retry_after=retry_after)


def run_home_command(homefs, user_id, action):
    try:
        exit_code, output = homefs.exec_run(
            ["/usr/bin/timeout", "-k", "10", str(HOME_RESET_TIMEOUT),
             "/usr/local/bin/python", "/opt/homefs/reset_home.py", str(user_id), action],
            user="0", demux=True,
        )
    except (docker.errors.DockerException, requests.RequestException) as error:
        logger.exception("Unable to confirm home operation user_id=%s action=%s", user_id, action)
        raise HomeResetError("Could not confirm completion. Wait 10 minutes before trying again.",
                             503, uncertain=True) from error
    stdout, stderr = output or (b"", b"")
    stdout, stderr = stdout or b"", stderr or b""
    if exit_code is None:
        raise HomeResetError("Could not confirm completion. Wait 10 minutes before trying again.",
                             503, uncertain=True)
    if exit_code != 0:
        logger.error("Home operation failed user_id=%s action=%s exit_code=%s stdout_tail=%r stderr_tail=%r",
                     user_id, action, exit_code, stdout[-4096:], stderr[-4096:])
        try:
            detail = json.loads(stderr.splitlines()[-1])
        except (IndexError, ValueError):
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        if detail.get("phase") == "lock":
            raise HomeResetError("Home storage is busy. Please try again.", 409)
        if detail.get("phase") == "missing":
            raise HomeResetError("No home backup is available yet.", 404)
        if "archive limit" in detail.get("error", ""):
            raise HomeResetError("The backup exceeds 1 GiB. Remove some files and try again.", 413)
        if exit_code in (124, 137):
            raise HomeResetError("The home operation timed out. Please try again.")
        raise HomeResetError("Could not complete the home operation. Please try again.")
    try:
        detail = json.loads(stdout.splitlines()[-1])
        if not isinstance(detail, dict) or detail.get("event") != "complete":
            raise ValueError("Invalid home operation result")
    except (IndexError, ValueError) as error:
        raise HomeResetError("Could not confirm completion. Wait 10 minutes before trying again.",
                             503, uncertain=True) from error
    return detail


def copy_home_archive(homefs, user_id, detail):
    size = detail.get("size")
    path = detail.get("backup", "")
    if not isinstance(size, int) or not 0 < size <= MAX_ARCHIVE_SIZE or not path.endswith(f"/{user_id}/home-backups/backup.tar.gz"):
        raise HomeResetError("Could not prepare the backup download. Please try again.")
    file = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        deadline = time.monotonic() + HOME_TRANSFER_TIMEOUT
        chunks, _ = homefs.get_archive(path, chunk_size=1024 * 1024)
        with io.BufferedReader(DockerArchiveReader(chunks, deadline)) as stream:
            with tarfile.open(fileobj=stream, mode="r|") as archive:
                member = archive.next()
                if member is None or not member.isfile() or member.size != size:
                    raise ValueError("Invalid backup transfer")
                source = archive.extractfile(member)
                while chunk := source.read(1024 * 1024):
                    file.write(chunk)
        if file.tell() != size:
            raise ValueError("Incomplete backup transfer")
        file.seek(0)
        with gzip.GzipFile(fileobj=file, mode="rb") as compressed:
            total = 0
            while chunk := compressed.read(1024 * 1024):
                if time.monotonic() > deadline:
                    raise TimeoutError("Home backup transfer timed out")
                total += len(chunk)
                if total > MAX_ARCHIVE_SIZE:
                    raise ValueError("Backup exceeds archive limit")
        file.seek(0)
        return HomeArchive(file, size, detail.get("skipped", 0))
    except Exception as error:
        file.close()
        logger.exception("Failed to transfer home backup user_id=%s", user_id)
        raise HomeResetError("Could not download the backup. Use the latest backup link to retry.", 503) from error


def manage_home_directory(docker_client, user_id, lock, *, action="reset"):
    try:
        acquired = lock.acquire(blocking=False)
    except redis.exceptions.RedisError as error:
        raise HomeResetError("Workspace locking is unavailable. Please try again.", 503) from error
    if not acquired:
        raise HomeResetError("Another workspace operation is in progress. Please try again.", 409)
    uncertain = False
    archive = None
    returned = False
    previous_timeout = docker_client.api.timeout
    try:
        try:
            homefs = docker_client.containers.get("homefs")
        except (docker.errors.DockerException, requests.RequestException) as error:
            raise HomeResetError("Home storage is unavailable. Please try again.", 503) from error
        if action != "latest":
            try:
                container = docker_client.containers.get(f"user_{user_id}")
                if container.status != "running":
                    raise docker.errors.NotFound("Workspace is not running")
            except docker.errors.NotFound as error:
                raise HomeResetError("No running container found. Please start a container and try again.", 409) from error
            except (docker.errors.DockerException, requests.RequestException) as error:
                raise HomeResetError("Workspace is unavailable. Please try again.", 503) from error
        if action == "reset":
            try:
                container.stop(timeout=10)
                # Workspaces use auto_remove; wait until their mounts have been released.
                container.wait(condition="removed", timeout=30)
            except docker.errors.NotFound:
                pass
            except (docker.errors.DockerException, requests.RequestException) as error:
                raise HomeResetError("Could not stop the workspace. Please try again.", 503) from error
        docker_client.api.timeout = HOME_RESET_TIMEOUT + 30
        detail = run_home_command(homefs, user_id, "latest" if action == "latest" else "backup")
        docker_client.api.timeout = HOME_TRANSFER_TIMEOUT
        archive = copy_home_archive(homefs, user_id, detail)
        if action == "reset":
            docker_client.api.timeout = HOME_RESET_TIMEOUT + 30
            try:
                run_home_command(homefs, user_id, "reset")
                archive.message = "Home reset and backup downloaded. Start a new challenge to continue."
            except HomeResetError as error:
                uncertain = error.uncertain
                archive.status = "unknown" if uncertain else "failed"
                archive.message = str(error)
        returned = True
        return archive
    except HomeResetError as error:
        uncertain = error.uncertain
        raise
    finally:
        docker_client.api.timeout = previous_timeout
        if archive is not None and not returned:
            archive.file.close()
        # A lost connection can leave the homefs exec modifying files after the request ends.
        if not uncertain:
            try:
                lock.release()
            except redis.exceptions.RedisError:
                logger.exception("Failed to release home operation lock user_id=%s", user_id)


def home_download_response(archive):
    try:
        response = send_file(archive.file, mimetype="application/gzip", as_attachment=True,
                             download_name="home-backup.tar.gz", conditional=False, etag=False)
        response.content_length = archive.size
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Home-Operation-Status"] = archive.status
        response.headers["X-Home-Operation-Message"] = archive.message
        response.headers["X-Home-Backup-Skipped-Files"] = str(archive.skipped)
        if archive.status == "failed":
            response.status_code = 500
        elif archive.status == "unknown":
            response.status_code = 503
            response.headers["Retry-After"] = str(HOME_RESET_LOCK_TIMEOUT)
        return response
    except Exception:
        archive.file.close()
        raise
