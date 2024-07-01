import hashlib
import os
import pathlib
import re
import subprocess
import logging

import docker
import docker.errors
import docker.types
from flask import abort, request, current_app
from flask_restx import Namespace, Resource
from CTFd.exceptions import UserNotFoundException, UserTokenExpiredException
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from ...config import HOST_DATA_PATH, INTERNET_FOR_ALL, SECCOMP, USER_FIREWALL_ALLOWED
from ...models import Dojos, DojoModules, DojoChallenges
from ...utils import (
    gen_container_name,
    lookup_workspace_token,
    serialize_user_flag,
    resolved_tar,
    user_ipv4,
)
from ...utils.dojo import dojo_accessible, get_current_dojo_challenge
from ...utils.workspace import exec_run

logger = logging.getLogger(__name__)

docker_namespace = Namespace(
    "docker", description="Endpoint to manage docker containers"
)


def setup_home(user):
    homes = pathlib.Path("/var/homes")
    homefs = homes / "homefs"
    user_data = homes / "data" / str(user.id)
    user_nosuid = homes / "nosuid" / str(user.id)

    assert homefs.exists()
    user_data.parent.mkdir(exist_ok=True)
    user_nosuid.parent.mkdir(exist_ok=True)

    if not user_data.exists():
        # Shell out to `cp` in order to sparsely copy
        subprocess.run(["cp", homefs, user_data], check=True)

    process = subprocess.run(
        ["findmnt", "--output", "OPTIONS", user_nosuid], capture_output=True
    )
    if b"nosuid" not in process.stdout:
        subprocess.run(
            ["mount", user_data, "-o", "nosuid,X-mount.mkdir", user_nosuid],
            check=True,
        )


def remove_container(docker_client, user):
    try:
        container = docker_client.containers.get(gen_container_name(user))
        container.remove(force=True)
        container.wait(condition="removed")
    except docker.errors.NotFound:
        pass


def start_container(docker_client, user, as_user, dojo_challenge, practice):
    container_name = gen_container_name(user)
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

    devices = []
    if os.path.exists("/dev/kvm"):
        devices.append("/dev/kvm:/dev/kvm:rwm")
    if os.path.exists("/dev/net/tun"):
        devices.append("/dev/net/tun:/dev/net/tun:rwm")

    container = docker_client.containers.create(
        dojo_challenge.image,
        entrypoint=["/bin/sleep", "6h"],
        name=container_name,
        hostname=hostname,
        user="hacker",
        working_dir="/home/hacker",
        labels={
            "dojo.dojo_id": dojo_challenge.dojo.reference_id,
            "dojo.module_id": dojo_challenge.module.id,
            "dojo.challenge_id": dojo_challenge.id,
            "dojo.challenge_description": dojo_challenge.description,
            "dojo.user_id": str(user.id),
            "dojo.as_user_id": str(as_user.id),
            "dojo.mode": "privileged" if practice else "standard",
            "dojo.auth_token": os.urandom(32).hex(),
        },
        mounts=[
            docker.types.Mount(
                "/home/hacker",
                f"{HOST_DATA_PATH}/homes/nosuid/{as_user.id}",
                "bind",
                propagation="shared",
            )
        ]
        + (
            [
                docker.types.Mount(
                    "/home/me",
                    f"{HOST_DATA_PATH}/homes/nosuid/{user.id}",
                    "bind",
                    propagation="shared",
                    read_only=True,
                )
            ]
            if as_user != user
            else []
        ),
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
        cpu_period=100000,
        cpu_quota=400000,
        pids_limit=1024,
        mem_limit="4G",
        detach=True,
        auto_remove=True,
    )

    user_network = docker_client.networks.get("user_network")
    user_network.connect(
        container, ipv4_address=user_ipv4(user), aliases=[container_name]
    )

    default_network = docker_client.networks.get("bridge")
    internet_access = INTERNET_FOR_ALL or any(
        award.name == "INTERNET" for award in user.awards
    )
    if not internet_access:
        default_network.disconnect(container)

    container.start()
    return container


def expect_homedir_mount_info(container, path):
    exit_code, output = exec_run(
        f"findmnt --output OPTIONS {path}", container=container, assert_success=False
    )
    if exit_code != 0:
        container.kill()
        container.wait(condition="removed")
        raise RuntimeError("Home directory failed to mount")
    return output


def assert_nosuid(container, mount_info):
    if b"nosuid" not in mount_info:
        container.kill()
        container.wait(condition="removed")
        raise RuntimeError("Home directory failed to mount as nosuid")


def assert_readonly(container, mount_info):
    if b"ro" not in mount_info:
        container.kill()
        container.wait(condition="removed")
        raise RuntimeError("Home directory failed to mount as read-only")


def insert_challenge(container, as_user, dojo_challenge):
    def is_option_path(path):
        path = pathlib.Path(*path.parts[: len(dojo_challenge.path.parts) + 1])
        return path.name.startswith("_") and path.is_dir()

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

    exec_run("chown -R root:root /challenge", container=container)
    exec_run("chmod -R 4755 /challenge", container=container)


def grant_sudo(container):
    exec_run(
        """
        chmod 4755 /usr/bin/sudo
        usermod -aG sudo hacker
        echo 'hacker ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
        passwd -d root
        """,
        container=container,
        shell=True,
    )


def insert_flag(container, flag):
    exec_run(f"echo 'pwn.college{{{flag}}}' > /flag", container=container, shell=True)


def insert_auth_token(container, auth_token):
    exec_run(f"echo '{auth_token}' > /.authtoken", container=container, shell=True)


def run_initialization_scripts(container, practice):
    exec_run(
        f"""
        export DOJO_PRIVILEGED={"1" if practice else "0"}
        /opt/pwn.college/docker-initialize.sh
        touch /opt/pwn.college/.initialized
        """,
        container=container,
        shell=True,
    )
    exec_run(
        """
        /opt/pwn.college/docker-entrypoint.sh &
        """,
        shell=True,
        container=container,
        workspace_user="hacker",
    )


def start_challenge(user, dojo_challenge, practice, *, as_user=None):
    """
    owner: the user that started the container
    challenged_user: the user whose challenge will be loaded. will be the same, except
        during partnering.
    partner: a user whose home directory will be mounted in read-only in /home/partner
    """
    as_user = as_user or user
    docker_client = docker.from_env()
    remove_container(docker_client, user)

    setup_home(user)
    if as_user != user:
        setup_home(as_user)

    container = start_container(
        docker_client=docker_client, 
        user=user, 
        as_user=as_user, 
        dojo_challenge=dojo_challenge, 
        practice=practice
    )

    hacker_mount_info = expect_homedir_mount_info(container, "/home/hacker")
    assert_nosuid(container, hacker_mount_info)
    if as_user != user:
        me_home_info = expect_homedir_mount_info(container, "/home/me")
        assert_nosuid(container, me_home_info)
        assert_readonly(container, me_home_info)

    if practice:
        grant_sudo(container)

    insert_challenge(container, as_user, dojo_challenge)

    if practice:
        flag = "practice"
    elif as_user != user:
        flag = "support_flag"
    else:
        # owner vs. challenged_user distinction shouldn't matter here, because they
        #  *should* be the same in this branch
        flag = serialize_user_flag(as_user.id, dojo_challenge.challenge_id)
    insert_flag(container, flag)

    auth_token = container.labels["dojo.auth_token"]
    insert_auth_token(container, auth_token)

    run_initialization_scripts(container, practice)


@docker_namespace.route("")
class RunDocker(Resource):
    @authed_only
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
                if user == token_user:
                    abort(400, description="you cannot use your own support token")
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

        try:
            start_challenge(
                user, dojo_challenge, practice, as_user=as_user
            )
        except RuntimeError as e:
            logger.exception(f"ERROR: Docker failed for {user.id}:")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.exception(f"ERROR: Docker failed for {user.id}:")
            return {"success": False, "error": "Docker failed"}
        return {"success": True}

    @authed_only
    def get(self):
        dojo_challenge = get_current_dojo_challenge()
        if not dojo_challenge:
            return {"success": False, "error": "No active challenge"}
        return {
            "success": True,
            "dojo": dojo_challenge.dojo.reference_id,
            "module": dojo_challenge.module.id,
            "challenge": dojo_challenge.id,
        }
