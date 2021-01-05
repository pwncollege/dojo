import os
import sys
import json
import pathlib
import tempfile
import tarfile

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

from .settings import INSTANCE, HOST_DATA_PATH
from .utils import serialize_user_flag, challenge_path


dir_path = os.path.dirname(os.path.realpath(__file__))
with open(f"{dir_path}/seccomp.json") as f:
    SECCOMP = json.dumps(json.load(f))


class DockerChallenges(Challenges):
    __mapper_args__ = {"polymorphic_identity": "docker"}
    id = db.Column(None, db.ForeignKey("challenges.id"), primary_key=True)
    docker_image_name = db.Column(db.String(32))


class DockerChallenge(BaseChallenge):
    id = "docker"  # Unique identifier used to register challenges
    name = "docker"  # Name of a challenge type
    templates = {  # Templates used for each aspect of challenge editing & viewing
        "create": "/plugins/CTFd-pwn-college-plugin/assets/docker_challenge/create.html",
        "update": "/plugins/CTFd-pwn-college-plugin/assets/docker_challenge/update.html",
        "view": "/plugins/CTFd-pwn-college-plugin/assets/docker_challenge/view.html",
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        "create": "/plugins/CTFd-pwn-college-plugin/assets/docker_challenge/create.js",
        "update": "/plugins/CTFd-pwn-college-plugin/assets/docker_challenge/update.js",
        "view": "/plugins/CTFd-pwn-college-plugin/assets/docker_challenge/view.js",
    }
    # Route at which files are accessible. This must be registered using register_plugin_assets_directory()
    route = "/plugins/CTFd-pwn-college-plugin/assets/docker_challenge/"
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
        account_id = user.account_id

        image_name = challenge.docker_image_name
        category = challenge.category
        challenge = challenge.name

        if category == "babysuid":
            # TODO: make babysuid not so hacked in
            selected_path = data.get("selected_path")

        else:
            chall_path = challenge_path(account_id, category, challenge)
            if not chall_path:
                print(
                    f"Challenge data does not exist: {account_id}, {category}, {challenge}",
                    file=sys.stderr,
                    flush=True,
                )
                return {"success": False, "error": "Challenge data does not exist"}

        docker_client = docker.from_env()

        container_name = f"{INSTANCE}_user_{user.id}"

        try:
            container = docker_client.containers.get(container_name)
            container.kill()
            container.wait(condition="removed")
        except docker.errors.NotFound:
            pass

        # try:
        #     response = requests.post(f"http://home_daemon/init/{user.id}").json()
        #     if not response["success"]:
        #         error = response["error"]
        #         print(
        #             f"Home daemon failed to init home for user {user.id}: {error}",
        #             file=sys.stderr,
        #             flush=True,
        #         )
        #         return {"success": False, "error": "Home daemon failed to init home"}
        # except Exception as e:
        #     print(f"Failed to reach home daemon: {e}", file=sys.stderr, flush=True)
        #     return {"success": False, "error": "Failed to reach home daemon"}

        try:
            container = docker_client.containers.run(
                image_name,
                ["/bin/bash", "-c", "while true; do su ctf; done"],
                name=container_name,
                hostname=f"{category}_{challenge}",
                environment={"CHALLENGE_ID": str(challenge_id)},
                mounts=[
                    docker.types.Mount(
                        "/home/ctf",
                        f"{HOST_DATA_PATH}/homes/nosuid/{user.id}",
                        "bind",
                        propagation="shared",
                    ),
                    docker.types.Mount(
                        "/challenges",
                        f"{HOST_DATA_PATH}/challenges/{user.id}",
                        "bind",
                        read_only=True,
                    ),
                ],
                network="none",
                cap_add=["SYS_PTRACE"],
                security_opt=[f"seccomp={SECCOMP}"],
                pids_limit=100,
                mem_limit="1000m",
                detach=True,
                tty=True,
                stdin_open=True,
                remove=True,
            )
        except Exception as e:
            print(f"Docker failed: {e}", file=sys.stderr, flush=True)
            return {"success": False, "error": "Docker failed"}

        exit_code, output = container.exec_run("findmnt --output OPTIONS /home/ctf")
        if exit_code != 0:
            container.kill()
            container.wait(condition="removed")
            print(
                f"Home directory failed to mount for user {user.id}",
                file=sys.stderr,
                flush=True,
            )
            return {"success": False, "error": "Home directory failed to mount"}
        elif b"nosuid" not in output:
            container.kill()
            container.wait(condition="removed")
            print(
                f"Home directory failed to mount as nosuid for user {user.id}",
                file=sys.stderr,
                flush=True,
            )
            return {
                "success": False,
                "error": "Home directory failed to mount as nosuid",
            }

        extra_data = None

        if category == "babysuid":
            # TODO: make babysuid not so hacked in

            # No command injection please
            selected_path = selected_path.replace("'", "").replace('"', "")

            exit_code, output = container.exec_run(
                f"""/bin/sh -c \"
                test -f '{selected_path}' &&
                chmod u+s '{selected_path}' &&
                readlink -e '{selected_path}';
                \""""
            )

            if exit_code != 0:
                container.kill()
                container.wait(condition="removed")
                return {"success": False, "error": "Invalid path"}

            selected_path = output.decode("latin").strip()

            suid_path = selected_path
            extra_data = selected_path

        else:

            def simple_tar(path, name=None):
                f = tempfile.NamedTemporaryFile()
                t = tarfile.open(mode="w", fileobj=f)

                abs_path = os.path.abspath(path)
                t.add(abs_path, arcname=(name or os.path.basename(path)))

                t.close()
                f.seek(0)
                return f

            with simple_tar(chall_path, f"{category}_{challenge}") as tar:
                container.put_archive("/", tar)

            suid_path = f"/{category}_{challenge}"

        container.exec_run(
            f"""/bin/sh -c \"
            chmod -R 4755 {suid_path};
            touch /flag;
            chmod 400 /flag;
            \""""
        )

        if not practice:
            flag = serialize_user_flag(account_id, challenge_id, extra_data)

        else:
            flag = serialize_user_flag(0, 0, 0)
            container.exec_run(
                f"""/bin/sh -c \"
                chmod 4755 /usr/bin/sudo;
                adduser ctf sudo;
                echo 'ctf ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers;
                echo '127.0.0.1\t{category}_{challenge}' >> /etc/hosts;
                \""""
            )

        flag = f"pwn_college{{{flag}}}"
        container.exec_run(f"/bin/sh -c \"echo '{flag}' > /flag\"")

        return {"success": True, "ssh": f"ssh {INSTANCE}@{INSTANCE}.pwn.college"}

    @authed_only
    def get(self):
        user = get_current_user()

        docker_client = docker.from_env()

        container_name = f"{INSTANCE}_user_{user.id}"

        try:
            container = docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            return {"success": False, "error": "No container"}

        for env in container.attrs["Config"]["Env"]:
            if env.startswith("CHALLENGE_ID"):
                try:
                    challenge_id = int(env[len("CHALLENGE_ID=") :])
                    return {"success": True, "challenge_id": challenge_id}
                except ValueError:
                    return {"success": False, "error": "Invalid challenge id"}
        else:
            return {"success": False, "error": "No challenge id"}
