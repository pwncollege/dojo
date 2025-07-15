import hashlib
import os
import pathlib
import re
import logging
import time
import datetime

import docker
import docker.errors
import docker.types
import redis
from flask import abort, request, current_app
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import Users, Solves
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only
from CTFd.exceptions import UserNotFoundException, UserTokenExpiredException

from ...config import HOST_DATA_PATH, INTERNET_FOR_ALL, SECCOMP, USER_FIREWALL_ALLOWED
from ...models import DojoModules, DojoChallenges
from ...utils import (
    container_name,
    lookup_workspace_token,
    resolved_tar,
    serialize_user_flag,
    user_docker_client,
    user_ipv4,
    get_current_container,
    is_challenge_locked,
)
from ...utils.dojo import dojo_accessible, get_current_dojo_challenge
from ...utils.workspace import exec_run

logger = logging.getLogger(__name__)

docker_namespace = Namespace(
    "docker", description="Endpoint to manage docker containers"
)

HOST_HOMES = pathlib.Path(HOST_DATA_PATH) / "workspace" / "homes"
HOST_HOMES_MOUNTS = HOST_HOMES / "mounts"
HOST_HOMES_OVERLAYS = HOST_HOMES / "overlays"


def remove_container(user):
    # Just in case our container is still running on the other docker container, let's make sure we try to kill both
    known_image_name = cache.get(f"user_{user.id}-running-image")
    images = [None, known_image_name]
    for image_name in images:
        docker_client = user_docker_client(user, image_name)
        try:
            container = docker_client.containers.get(container_name(user))
            container.remove(force=True)
            container.wait(condition="removed")
        except (docker.errors.NotFound, docker.errors.APIError):
            pass
        for volume in [f"{user.id}", f"{user.id}-overlay"]:
            try:
                docker_client.volumes.get(volume).remove()
            except (docker.errors.NotFound, docker.errors.APIError):
                pass

def get_available_devices(docker_client):
    key = f"devices-{docker_client.api.base_url}"
    if (cached := cache.get(key)) is not None:
        return cached
    find_command = ["/bin/find", "/dev", "-type", "c"]
    devices = docker_client.containers.run("busybox:uclibc", find_command, privileged=True, remove=True).decode().splitlines()
    timeout = int(datetime.timedelta(days=1).total_seconds())
    cache.set(key, devices, timeout=timeout)
    return devices

def start_container(docker_client, user, as_user, user_mounts, dojo_challenge, practice):
    hostname = "~".join(
        (["practice"] if practice else [])
        + [
            dojo_challenge.module.id,
            re.sub(
                r"[\s.-]+",
                "-",
                re.sub(r"[^a-z0-9\s.-]", "", dojo_challenge.name.lower()),
            ),
        ]
    )[:64]

    auth_token = os.urandom(32).hex()

    challenge_bin_path = "/run/challenge/bin"
    workspace_bin_path = "/run/workspace/bin"
    dojo_bin_path = "/run/dojo/bin"
    image = docker_client.images.get(dojo_challenge.image)
    image_env = image.attrs["Config"].get("Env") or []
    image_path = next((env_var[len("PATH="):].split(":") for env_var in image_env if env_var.startswith("PATH=")), [])
    env_path = ":".join([challenge_bin_path, workspace_bin_path, *image_path])

    mounts = [
        docker.types.Mount(
            "/nix",
            f"{HOST_DATA_PATH}/workspace/nix",
            "bind",
            read_only=True,
        ),
        docker.types.Mount(
            "/run/workspace",
            f"{HOST_DATA_PATH}/workspacefs",
            "bind",
            read_only=True,
            propagation="shared",
        ),
        docker.types.Mount(
            "/run/dojo/sys",
            "/run/dojofs",
            "bind",
            read_only=True,
            propagation="slave",
        ),
        *user_mounts,
    ]

    allowed_devices = ["/dev/kvm", "/dev/net/tun"]
    available_devices = set(get_available_devices(docker_client))
    devices = [f"{device}:{device}:rwm" for device in allowed_devices if device in available_devices]

    container = docker_client.containers.create(
        dojo_challenge.image,
        entrypoint=[
            "/nix/var/nix/profiles/dojo-workspace/bin/dojo-init",
            f"{dojo_bin_path}/sleep",
            "6h",
        ],
        name=container_name(user),
        hostname=hostname,
        user="0",
        working_dir="/home/hacker",
        environment={
            "HOME": "/home/hacker",
            "PATH": env_path,
            "SHELL": f"{dojo_bin_path}/bash",
            "DOJO_AUTH_TOKEN": auth_token,
        },
        labels={
            "dojo.dojo_id": dojo_challenge.dojo.reference_id,
            "dojo.module_id": dojo_challenge.module.id,
            "dojo.challenge_id": dojo_challenge.id,
            "dojo.challenge_description": dojo_challenge.description,
            "dojo.user_id": str(user.id),
            "dojo.as_user_id": str(as_user.id),
            "dojo.auth_token": auth_token,
            "dojo.mode": "privileged" if practice else "standard",
        },
        mounts=mounts,
        devices=devices,
        network=None,
        extra_hosts={
            hostname: "127.0.0.1",
            "vm": "127.0.0.1",
            f"vm_{hostname}"[:64]: "127.0.0.1",
            "challenge.localhost": "127.0.0.1",
            "hacker.localhost": "127.0.0.1",
            "dojo-user": user_ipv4(user),
            **USER_FIREWALL_ALLOWED,
        },
        init=True,
        cap_add=["SYS_PTRACE"],
        security_opt=[f"seccomp={SECCOMP}"],
        sysctls={"net.ipv4.ip_unprivileged_port_start": 1024},
        cpu_period=100000,
        cpu_quota=400000,
        pids_limit=1024,
        mem_limit="4G",
        detach=True,
        stdin_open=True,
        auto_remove=True,
    )

    workspace_net = docker_client.networks.get("workspace_net")
    workspace_net.connect(
        container, ipv4_address=user_ipv4(user), aliases=[container_name(user)]
    )

    default_network = docker_client.networks.get("bridge")
    internet_access = INTERNET_FOR_ALL or any(
        award.name == "INTERNET" for award in user.awards
    )
    if not internet_access:
        default_network.disconnect(container)

    container.start()
    for message in container.attach(stream=True):
        if message == b"Initialized.\n":
            break

    cache.set(f"user_{user.id}-running-image", dojo_challenge.image, timeout=0)
    return container


def insert_challenge(container, as_user, dojo_challenge):
    def is_option_path(path):
        path = pathlib.Path(*path.parts[: len(dojo_challenge.path.parts) + 1])
        return path.name.startswith("_") and path.is_dir()

    exec_run("/run/dojo/bin/mkdir -p /challenge", container=container)

    root_dir = dojo_challenge.path.parent.parent
    challenge_tar = resolved_tar(
        dojo_challenge.path,
        root_dir=root_dir,
        filter=lambda path: not is_option_path(path),
    )
    container.put_archive("/challenge", challenge_tar)

    option_paths = sorted(
        path for path in dojo_challenge.path.iterdir() if is_option_path(path)
    )
    if option_paths:
        secret = current_app.config["SECRET_KEY"]
        option_hash = hashlib.sha256(
            f"{secret}_{as_user.id}_{dojo_challenge.challenge_id}".encode()
        ).digest()
        option = option_paths[
            int.from_bytes(option_hash[:8], "little") % len(option_paths)
        ]
        container.put_archive("/challenge", resolved_tar(option, root_dir=root_dir))

    exec_run(
        "/run/dojo/bin/find /challenge/ -mindepth 1 -exec /run/dojo/bin/chown root:root {} \;", container=container
    )
    exec_run("/run/dojo/bin/find /challenge/ -mindepth 1 -exec /run/dojo/bin/chmod 4755 {} \;", container=container)


def insert_flag(container, flag):
    flag = f"pwn.college{{{flag}}}"
    if "localhost" in container.client.api.base_url:
        socket = container.attach_socket(params=dict(stdin=1, stream=1))
        socket._sock.sendall(flag.encode() + b"\n")
        socket.close()
    else:
        ws = container.attach_socket(params=dict(stdin=1, stream=1), ws=True)
        ws.send_text(f"{flag}\n")
        ws.close()


def start_challenge(user, dojo_challenge, practice, *, as_user=None):
    docker_client = user_docker_client(user, image_name=dojo_challenge.image)
    remove_container(user)

    user_mounts = []
    if as_user is None:
        user_mounts.append(
            docker.types.Mount(
                "/home/hacker",
                str(user.id),
                "volume",
                no_copy=True,
                driver_config=docker.types.DriverConfig("homefs"),
            )
        )
    else:
        user_mounts.extend([
            docker.types.Mount(
                "/home/hacker",
                f"{user.id}-overlay",
                "volume",
                no_copy=True,
                driver_config=docker.types.DriverConfig("homefs", options=dict(overlay=str(as_user.id))),
            ),
            docker.types.Mount(
                "/home/me",
                str(user.id),
                "volume",
                no_copy=True,
                driver_config=docker.types.DriverConfig("homefs"),
            ),
        ])

    as_user = as_user or user

    container = start_container(
        docker_client=docker_client,
        user=user,
        as_user=as_user,
        user_mounts=user_mounts,
        dojo_challenge=dojo_challenge,
        practice=practice,
    )

    insert_challenge(container, as_user, dojo_challenge)

    if practice:
        flag = "practice"
    elif as_user != user:
        flag = "support_flag"
    else:
        flag = serialize_user_flag(as_user.id, dojo_challenge.challenge_id)
    insert_flag(container, flag)


def docker_locked(func):
    def wrapper(*args, **kwargs):
        user = get_current_user()
        redis_client = redis.from_url(current_app.config["REDIS_URL"])
        try:
            with redis_client.lock(f"user.{user.id}.docker.lock", blocking_timeout=0, timeout=60):
                return func(*args, **kwargs)
        except redis.exceptions.LockError:
            return {"success": False, "error": "Already starting a challenge"}
    return wrapper


@docker_namespace.route("")
class RunDocker(Resource):
    @authed_only
    @docker_locked
    def post(self):
        data = request.get_json()
        dojo_id = data.get("dojo")
        module_id = data.get("module")
        challenge_id = data.get("challenge")
        practice = data.get("practice")

        user = get_current_user()
        as_user = None

        # https://github.com/CTFd/CTFd/blob/3.6.0/CTFd/utils/initialization/__init__.py#L286-L296
        workspace_token = request.headers.get("X-Workspace-Token")
        if workspace_token:
            try:
                token_user = lookup_workspace_token(workspace_token)
            except UserNotFoundException:
                abort(401, description="Invalid workspace token")
            except UserTokenExpiredException:
                abort(401, description="This workspace token has expired")
            except Exception:
                logger.exception(f"error resolving workspace token for {user.id}:")
                abort(401, description="Internal error while resolving workspace token")
            else:
                as_user = token_user

        dojo = dojo_accessible(dojo_id)
        if not dojo:
            return {"success": False, "error": "Invalid dojo"}

        dojo_challenge = (
            DojoChallenges.query.filter_by(id=challenge_id)
            .join(DojoModules.query.filter_by(dojo=dojo, id=module_id).subquery())
            .first()
        )
        if not dojo_challenge:
            return {"success": False, "error": "Invalid challenge"}

        if not dojo_challenge.visible() and not dojo.is_admin():
            return {"success": False, "error": "Invalid challenge"}

        if practice and not dojo_challenge.allow_privileged:
            return {
                "success": False,
                "error": "This challenge does not support practice mode.",
            }
        
        if is_challenge_locked(dojo_challenge, user):
            return {
                "success": False,
                "error": "This challenge is locked"
            }

        if dojo.is_admin(user) and "as_user" in data:
            try:
                as_user_id = int(data["as_user"])
            except ValueError:
                return {"success": False, "error": f"Invalid user ID ({data['as_user']})"}
            if is_admin():
                as_user = Users.query.get(as_user_id)
            else:
                student = next((student for student in dojo.students if student.user_id == as_user_id), None)
                if student is None:
                    return {"success": False, "error": f"Not a student in this dojo ({as_user_id})"}
                if not student.official:
                    return {"success": False, "error": f"Not an official student in this dojo ({as_user_id})"}
                as_user = student.user

        max_attempts = 3
        for attempt in range(1, max_attempts+1):
            try:
                logger.info(f"Starting challenge for user {user.id} (attempt {attempt}/{max_attempts})...")
                start_challenge(user, dojo_challenge, practice, as_user=as_user)
                break
            except Exception as e:
                logger.exception(f"Attempt {attempt} failed for user {user.id} with error: {e}")
                if attempt < max_attempts:
                    logger.info(f"Retrying... ({attempt}/{max_attempts})")
                    time.sleep(2)
        else:
            logger.error(f"ERROR: Docker failed for {user.id} after {max_attempts} attempts.")
            return {"success": False, "error": "Docker failed"}

        return {"success": True}

    @authed_only
    def get(self):
        dojo_challenge = get_current_dojo_challenge()
        if not dojo_challenge:
            return {"success": False, "error": "No active challenge"}

        user = get_current_user()
        container = get_current_container(user)
        if not container:
            return {"success": False, "error": "No challenge container"}

        practice = container.labels.get("dojo.mode") == "privileged"

        return {
            "success": True,
            "dojo": dojo_challenge.dojo.reference_id,
            "module": dojo_challenge.module.id,
            "challenge": dojo_challenge.id,
            "practice" : practice
        }
