import os
import sys
import json
import subprocess
import pathlib

import docker
import requests
from flask import request, Blueprint
from flask_restx import Namespace, Resource
from CTFd.models import (
    db,
    Solves,
    Fails,
    Flags,
    Challenges,
    ChallengeFiles,
    Tags,
    Hints,
)
from CTFd.utils.user import get_ip, get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.utils.uploads import delete_file
from CTFd.plugins.challenges import BaseChallenge
from CTFd.plugins.flags import get_flag_class

from .config import VIRTUAL_HOST, HOST_DATA_PATH
from .utils import serialize_user_flag, challenge_paths, simple_tar, random_home_path


dir_path = os.path.dirname(os.path.realpath(__file__))
with open(f"{dir_path}/seccomp.json") as f:
    SECCOMP = json.dumps(json.load(f))


def get_current_challenge_id():
    user = get_current_user()
    docker_client = docker.from_env()
    container_name = f"user_{user.id}"

    try:
        container = docker_client.containers.get(container_name)
    except docker.errors.NotFound:
        return

    for env in container.attrs["Config"]["Env"]:
        if env.startswith("CHALLENGE_ID"):
            try:
                challenge_id = int(env[len("CHALLENGE_ID=") :])
                return challenge_id
            except ValueError:
                pass


class DockerChallenges(Challenges):
    __mapper_args__ = {"polymorphic_identity": "docker"}
    id = db.Column(None, db.ForeignKey("challenges.id"), primary_key=True)
    docker_image_name = db.Column(db.String(256))


class DockerChallenge(BaseChallenge):
    id = "docker"  # Unique identifier used to register challenges
    name = "docker"  # Name of a challenge type
    templates = {  # Templates used for each aspect of challenge editing & viewing
        "create": "/plugins/pwncollege_plugin/assets/docker_challenge/create.html",
        "update": "/plugins/pwncollege_plugin/assets/docker_challenge/update.html",
        "view": "/plugins/pwncollege_plugin/assets/docker_challenge/view.html",
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        "create": "/plugins/pwncollege_plugin/assets/docker_challenge/create.js",
        "update": "/plugins/pwncollege_plugin/assets/docker_challenge/update.js",
        "view": "/plugins/pwncollege_plugin/assets/docker_challenge/view.js",
    }
    # Route at which files are accessible. This must be registered using register_plugin_assets_directory()
    route = "/plugins/pwncollege_plugin/assets/docker_challenge/"
    # Blueprint used to access the static_folder directory.
    blueprint = Blueprint(
        "docker", __name__, template_folder="templates", static_folder="assets"
    )
    challenge_model = DockerChallenges


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

        challenge = DockerChallenges.query.filter_by(id=challenge_id).first()
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
        hostname = container.attrs["Config"]["Hostname"]
        container.exec_run(
            f"""/bin/sh -c \"
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
