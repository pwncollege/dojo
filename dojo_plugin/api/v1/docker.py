import os
import sys
import subprocess
import pathlib

import docker
from flask import request
from flask_restx import Namespace, Resource
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ...config import HOST_DATA_PATH
from ...models import DojoChallenges
from ...utils import get_current_dojo_challenge_id, serialize_user_flag, simple_tar, random_home_path, SECCOMP, USER_FIREWALL_ALLOWED, dojo_by_id, module_challenges_visible


docker_namespace = Namespace(
    "docker", description="Endpoint to manage docker containers"
)


def start_challenge(user, dojo, dojo_challenge, practice):
    def exec_run(cmd, *, shell=False, assert_success=True, user="root", **kwargs):
        if shell:
            cmd = f"""/bin/sh -c \"
            {cmd}
            \""""
        exit_code, output = container.exec_run(cmd, user=user, **kwargs)
        if assert_success:
            assert exit_code in (0, None), output
        return exit_code, output

    def setup_home(user):
        homes = pathlib.Path("/var/homes")
        homefs = homes / "homefs"
        user_data = homes / "data" / str(user.id)
        user_nosuid = homes / "nosuid" / random_home_path(user)

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

    def start_container(user, dojo, dojo_challenge, practice):
        docker_client = docker.from_env()
        try:
            container_name = f"user_{user.id}"
            container = docker_client.containers.get(container_name)
            container.remove(force=True)
            container.wait(condition="removed")
        except docker.errors.NotFound:
            pass
        challenge_name = f"{dojo_challenge.category}_{dojo_challenge.name}"
        hostname = challenge_name
        if practice:
            hostname = f"practice_{hostname}"
        devices = []
        if os.path.exists("/dev/kvm"):
            devices.append("/dev/kvm:/dev/kvm:rwm")
        internet = any(award.name == "INTERNET" for award in user.awards)

        return docker_client.containers.run(
            dojo_challenge.docker_image_name,
            entrypoint=["/bin/sleep", "6h"],
            name=container_name,
            hostname=hostname,
            user="hacker",
            working_dir="/home/hacker",
            environment={
                "DOJO_ID": str(dojo.id),
                "CHALLENGE_ID": str(dojo_challenge.challenge_id),
                "DOJO_CHALLENGE_ID": dojo_challenge.dojo_challenge_id,
                "CHALLENGE_NAME": challenge_name,
                "PRACTICE": str(bool(practice)),
            },
            mounts=[
                docker.types.Mount(
                    "/home/hacker",
                    f"{HOST_DATA_PATH}/homes/nosuid/{random_home_path(user)}",
                    "bind",
                    propagation="shared",
                ),
            ],
            devices=devices,
            network=None if internet else "user_firewall",
            extra_hosts={
                hostname: "127.0.0.1",
                "vm": "127.0.0.1",
                f"vm_{hostname}": "127.0.0.1",
                "challenge.localhost": "127.0.0.1",
                "hacker.localhost": "127.0.0.1",
                **USER_FIREWALL_ALLOWED,
            },
            init=True,
            cap_add=["SYS_PTRACE"],
            security_opt=[f"seccomp={SECCOMP}"],
            cpu_period=100000,
            cpu_quota=400000,
            pids_limit=1024,
            mem_limit="4000m",
            detach=True,
            remove=True,
        )

    def verify_nosuid_home():
        exit_code, output = exec_run("findmnt --output OPTIONS /home/hacker",
                                     assert_success=False)
        if exit_code != 0:
            container.kill()
            container.wait(condition="removed")
            raise RuntimeError("Home directory failed to mount")
        elif b"nosuid" not in output:
            container.kill()
            container.wait(condition="removed")
            raise RuntimeError("Home directory failed to mount as nosuid")

    def grant_sudo():
        exec_run(
            """
            chmod 4755 /usr/bin/sudo
            usermod -aG sudo hacker
            echo 'hacker ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
            passwd -d root
            """,
            shell=True
        )

    def insert_challenge(user, dojo_challenge):
        for path in dojo_challenge.challenge_paths(user=user):
            with simple_tar(path, f"/challenge/{path.name}") as tar:
                container.put_archive("/", tar)
        exec_run("chown -R root:root /challenge")
        exec_run("chmod -R 4755 /challenge")

    def insert_flag(flag):
        exec_run(f"echo 'pwn.college{{{flag}}}' > /flag", shell=True)

    def initialize_container():
        exec_run(
            """
            /opt/pwn.college/docker-initialize.sh

            if [ -x "/challenge/.init" ]; then
                /challenge/.init
            fi

            touch /opt/pwn.college/.initialized
            """,
            shell=True
        )
        exec_run(
            """
            /opt/pwn.college/docker-entrypoint.sh &
            """,
            shell=True,
            user="hacker"
        )

    setup_home(user)

    container = start_container(user, dojo, dojo_challenge, practice)

    verify_nosuid_home()

    if practice:
        grant_sudo()

    insert_challenge(user, dojo_challenge)

    flag = "practice" if practice else serialize_user_flag(user.id, dojo_challenge.challenge_id)
    insert_flag(flag)

    initialize_container()


@docker_namespace.route("")
class RunDocker(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        dojo_challenge_id = data.get("dojo_challenge_id")
        dojo_id = data.get("dojo_id")
        practice = data.get("practice")

        dojo = dojo_by_id(dojo_id)
        if not dojo:
            return {"success": False, "error": "Invalid dojo"}

        dojo_challenge = DojoChallenges.query.filter_by(id=dojo_challenge_id).first()
        if not dojo_challenge:
            return {"success": False, "error": "Invalid challenge"}

        user = get_current_user()
        if not module_challenges_visible(dojo, dojo.modules[dojo_challenge.module_idx], get_current_user()):
            return {"success": False, "error": "Invalid challenge"}

        try:
            start_challenge(user, dojo, dojo_challenge, practice)
        except RuntimeError as e:
            print(f"ERROR: Docker failed for {user.id}: {e}", file=sys.stderr, flush=True)
            return {"success": False, "error": str(e)}
        except Exception as e: #pylint:disable=broad-except
            print(f"ERROR: Docker failed for {user.id}: {e}", file=sys.stderr, flush=True)
            return {"success": False, "error": "Docker failed"}
        return {"success": True}


    @authed_only
    def get(self):
        return {"success": True, "dojo_challenge_id": get_current_dojo_challenge_id()}
