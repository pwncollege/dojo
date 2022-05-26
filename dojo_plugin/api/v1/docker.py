import os
import sys
import subprocess
import pathlib

import docker
from flask import request
from flask_restx import Namespace, Resource
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.decorators import authed_only

from ...config import HOST_DATA_PATH, INTERNET_ACCESS
from ...models import DojoChallenges
from ...utils import get_current_challenge_id, serialize_user_flag, challenge_paths, simple_tar, random_home_path, SECCOMP


docker_namespace = Namespace(
    "docker", description="Endpoint to manage docker containers"
)


def start_challenge(user, challenge, practice):
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

        # internet
        internet_award = any(a.name == "INTERNET" for a in get_current_user().awards)
        kwargs = { }
        if not (internet_award or is_admin() or INTERNET_ACCESS):
            kwargs['network'] = "none"

        return docker_client.containers.run(
            challenge.docker_image_name,
            entrypoint=["/bin/sleep", "6h"],
            name=container_name,
            hostname=hostname,
            user="hacker",
            working_dir="/home/hacker",
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
            **kwargs
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

    def insert_challenge(user, challenge):
        for path in challenge_paths(user, challenge):
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

            find /challenge -name '*.ko' -exec false {} + || vm start
            """,
            shell=True
        )
        exec_run(
            """
            mkdir /tmp/code-server
            start-stop-daemon --start \
                              --pidfile /tmp/code-server/code-server.pid \
                              --make-pidfile \
                              --background \
                              --no-close \
                              --startas /usr/bin/code-server \
                              -- \
                              --auth=none \
                              --socket=/home/hacker/.local/share/code-server/workspace.socket \
                              --extensions-dir=/opt/code-server/extensions \
                              --disable-telemetry \
                              </dev/null \
                              >>/tmp/code-server/code-server.log \
                              2>&1
            """,
            shell=True,
            user="hacker"
        )

    setup_home(user)

    container = start_container(user, challenge, practice)

    verify_nosuid_home()

    if practice:
        grant_sudo()

    insert_challenge(user, challenge)

    flag = "practice" if practice else serialize_user_flag(user.id, challenge.id)
    insert_flag(flag)

    initialize_container()


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

        try:
            start_challenge(user, challenge, practice)
        except RuntimeError as e:
            print(f"ERROR: Docker failed for {user.id}: {e}", file=sys.stderr, flush=True)
            return {"success": False, "error": str(e)}
        except Exception as e:
            print(f"ERROR: Docker failed for {user.id}: {e}", file=sys.stderr, flush=True)
            return {"success": False, "error": "Docker failed"}
        return {"success": True}


    @authed_only
    def get(self):
        return {"success": True, "challenge_id": get_current_challenge_id()}
