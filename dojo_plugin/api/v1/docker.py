import os
import sys
import subprocess
import pathlib

import docker
from flask import request
from flask_restx import Namespace, Resource
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from ...config import HOST_DATA_PATH
from ...models import DojoChallenges
from ...utils import get_current_challenge_id, serialize_user_flag, challenge_paths, simple_tar, random_home_path, SECCOMP


docker_namespace = Namespace(
    "docker", description="Endpoint to manage docker containers"
)


@docker_namespace.route("")
class RunDocker(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        challenge_id = data.get("challenge_id")
        practice = data.get("practice")

        try:
            challenge_id = int(challenge_id)
        except (ValueError, TypeError):
            return {"success": False, "error": "Invalid challenge id"}

        challenge = DojoChallenges.query.filter_by(id=challenge_id).first()
        if not challenge:
            return {"success": False, "error": "Invalid challenge"}

        user = get_current_user()

        self.setup_home(user)

        try:
            container = self.start_container(user, challenge, practice)
        except Exception as e:
            print(f"ERROR: Docker failed: {e}", file=sys.stderr, flush=True)
            return {"success": False, "error": "Docker failed"}

        error = self.verify_nosuid_home(container)
        if error:
            print(
                f"ERROR: {error} for {user.id}",
                file=sys.stderr,
                flush=True,
            )
            return error

        if practice:
            self.grant_sudo(container)

        self.insert_challenge(container, user, challenge)

        flag = "practice" if practice else serialize_user_flag(user.id, challenge.id)
        self.insert_flag(container, flag)

        return {"success": True}

    @authed_only
    def get(self):
        return {"success": True, "challenge_id": get_current_challenge_id()}

    @staticmethod
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

    @staticmethod
    def start_container(user, challenge, practice):
        docker_client = docker.from_env()
        try:
            container_name = f"user_{user.id}"
            container = docker_client.containers.get(container_name)
            container.kill()
            container.wait(condition="removed")
        except docker.errors.NotFound:
            pass
        challenge_name = f"{challenge.category}_{challenge.name}"
        hostname = challenge_name
        if practice:
            hostname = f"practice_{hostname}"
        devices = []
        if os.path.exists("/dev/kvm"):
            devices.append("/dev/kvm:/dev/kvm:rwm")
        return docker_client.containers.run(
            challenge.docker_image_name,
            ["/bin/su", "hacker", "/opt/pwn.college/docker-entrypoint.sh"],
            name=container_name,
            hostname=hostname,
            environment={
                "CHALLENGE_ID": str(challenge.id),
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
            network="none",
            extra_hosts={
                hostname: "127.0.0.1",
                "vm": "127.0.0.1",
                f"vm_{hostname}": "127.0.0.1",
            },
            init=True,
            cap_add=["SYS_PTRACE"],
            security_opt=[f"seccomp={SECCOMP}"],
            cpu_period=100000,
            cpu_quota=400000,
            pids_limit=1024,
            mem_limit="4000m",
            detach=True,
            tty=True,
            stdin_open=True,
            remove=True,
        )

    @staticmethod
    def verify_nosuid_home(container):
        exit_code, output = container.exec_run("findmnt --output OPTIONS /home/hacker")
        if exit_code != 0:
            container.kill()
            container.wait(condition="removed")
            return {"success": False, "error": "Home directory failed to mount"}
        elif b"nosuid" not in output:
            container.kill()
            container.wait(condition="removed")
            return {
                "success": False,
                "error": "Home directory failed to mount as nosuid",
            }

    @staticmethod
    def grant_sudo(container):
        container.exec_run(
            """/bin/sh -c \"
            chmod 4755 /usr/bin/sudo;
            usermod -aG sudo hacker;
            echo 'hacker ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers;
            passwd -d root;
            \""""
        )

    @staticmethod
    def insert_challenge(container, user, challenge):
        for path in challenge_paths(user, challenge):
            with simple_tar(path, f"/challenge/{path.name}") as tar:
                container.put_archive("/", tar)
        container.exec_run("chown -R root:root /challenge")
        container.exec_run("chmod -R 4755 /challenge")

    @staticmethod
    def insert_flag(container, flag):
        container.exec_run(f"/bin/sh -c \"echo 'pwn.college{{{flag}}}' > /flag\"")
