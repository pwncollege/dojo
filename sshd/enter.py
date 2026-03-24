#!/usr/bin/env python3

import json
import os
import pathlib
import shlex
import sys
import time
import signal
import threading
import docker
import redis
import requests

from mac_docker import MacDockerClient


WORKSPACE_NODES = {
    int(node_id): node_key
    for node_id, node_key in
    json.load(pathlib.Path("/var/workspace_nodes.json").open()).items()
}

redis_client = redis.from_url(os.environ.get("REDIS_URL"))

def get_docker_client(user_id):
    image_name = redis_client.get(f"flask_cache_user_{user_id}-running-image")
    node_id = list(WORKSPACE_NODES.keys())[user_id % len(WORKSPACE_NODES)] if WORKSPACE_NODES else None
    docker_host = f"tcp://192.168.42.{node_id + 1}:2375" if node_id is not None else "unix:///var/run/docker.sock"

    is_mac = False
    if image_name and b"mac:" in image_name:
        docker_client = MacDockerClient(hostname=os.getenv("MAC_HOSTNAME"),
                                        username=os.getenv("MAC_USERNAME"),
                                        key_path="/home/hacker/.ssh/key")
        is_mac = True
    else:
        docker_client = docker.DockerClient(base_url=docker_host, tls=False)
    return docker_host, docker_client, is_mac

def kill_exec_on_container_death(container, exec_pid):
    container.wait(condition="not-running")
    try:
        os.kill(exec_pid, signal.SIGTERM)
        time.sleep(0.5)
    except ProcessLookupError:
        pass


def resolve_ctfd_api_base():
    url = os.environ.get("DOJO_CTFD_URL")
    if url:
        return url.rstrip("/")
    return "http://ctfd:8000/pwncollege_api/v1"


def run_challenge_tui(user_id, print_fn):
    api_base = resolve_ctfd_api_base()
    ssh_key = os.environ.get("DOJO_SSH_SERVICE_KEY")
    if not ssh_key:
        return False
    headers = {
        "X-SSH-Service-Key": ssh_key,
        "X-Dojo-User-Id": str(user_id),
        "Content-Type": "application/json",
    }

    def get(path, key):
        r = requests.get(f"{api_base}{path}", headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Request failed"))
        return data.get(key, [])

    def post(path, json_body):
        r = requests.post(f"{api_base}{path}", headers=headers, json=json_body, timeout=60)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Request failed"))
        return data

    try:
        dojos = get("/dojos", "dojos")
    except Exception as e:
        print_fn(f"Failed to list dojos: {e}")
        return False
    if not dojos:
        print_fn("No dojos available.")
        return False

    print_fn("Select a dojo:")
    for i, d in enumerate(dojos, 1):
        print_fn(f"  {i}. {d['name']} ({d['id']})")
    try:
        idx = int(input("Dojo number: ").strip())
        dojo = dojos[idx - 1]
    except (ValueError, IndexError, EOFError):
        return False

    try:
        modules = get(f"/dojos/{dojo['id']}/modules", "modules")
    except Exception as e:
        print_fn(f"Failed to list modules: {e}")
        return False
    if not modules:
        print_fn("No modules in this dojo.")
        return False

    print_fn("Select a module:")
    for i, m in enumerate(modules, 1):
        print_fn(f"  {i}. {m['name']} ({m['id']})")
    try:
        idx = int(input("Module number: ").strip())
        module = modules[idx - 1]
    except (ValueError, IndexError, EOFError):
        return False

    challenges = module.get("challenges", [])
    if not challenges:
        print_fn("No challenges in this module.")
        return False

    print_fn("Select a challenge:")
    for i, c in enumerate(challenges, 1):
        print_fn(f"  {i}. {c['name']} ({c['id']})")
    try:
        idx = int(input("Challenge number: ").strip())
        challenge = challenges[idx - 1]
    except (ValueError, IndexError, EOFError):
        return False

    print_fn("Starting challenge...")
    try:
        post("/docker", {
            "dojo": dojo["id"],
            "module": module["id"],
            "challenge": challenge["id"],
            "practice": False,
        })
    except Exception as e:
        print_fn(f"Failed to start challenge: {e}")
        return False
    print_fn("Challenge started. Connecting...")
    return True


def main():
    original_command = os.getenv("SSH_ORIGINAL_COMMAND")
    tty = os.getenv("SSH_TTY") is not None
    simple = bool(not tty or original_command)

    def print(*args, **kwargs):
        if simple:
            return
        kwargs.update(file=sys.stderr)
        return __builtins__.print(*args, **kwargs)

    if len(sys.argv) != 2:
        print(f"{sys.argv[0]} <container_name>")
        exit(1)
    container_name = sys.argv[1]
    user_id = int(container_name.split("_")[1])

    docker_host, docker_client, is_mac = get_docker_client(user_id)

    try:
        container = docker_client.containers.get(container_name)
    except docker.errors.NotFound:
        if not simple and os.environ.get("DOJO_SSH_SERVICE_KEY"):
            if run_challenge_tui(user_id, print):
                time.sleep(2)
                os.execv(sys.executable, [sys.executable, __file__, container_name])
        print("No active challenge session; start a challenge!")
        exit(1)

    attempts = 0
    while attempts < 30:
        if attempts != 0:
            docker_host, docker_client, is_mac = get_docker_client(user_id)
        try:
            container = docker_client.containers.get(container_name)
            status = container.status
        except docker.errors.NotFound:
            status = "uninitialized"

        if status == "running":
            try:
                container.get_archive("/run/dojo/var/ready")
            except docker.errors.NotFound:
                status = "initializing"

        if status != "running":
            attempts += 1
            print("\r", " " * 80, f"\rConnecting -- instance status: {status}", end="")
            time.sleep(1)
            continue

        attempts = 0
        print("\r", " " * 80, "\rConnected!")
        child_pid = os.fork();
        if not child_pid:
            ssh_entrypoint = "/run/dojo/bin/ssh-entrypoint"
            if is_mac:
                cmd = f"/bin/bash -c {shlex.quote(original_command)}" if original_command  else "zsh -i"
                container.execve_shell(cmd, user="1000", use_tty=tty)
            else:
                command = [ssh_entrypoint, "-c", original_command] if original_command else [ssh_entrypoint]
                environ = [] if "TERM" not in os.environ else [f"--env=TERM={os.environ['TERM']}"]
                os.execve(
                    "/usr/bin/docker",
                    [
                        "docker",
                        "exec",
                        "-it" if tty else "-i",
                        "--user=1000",
                        "--workdir=/home/hacker",
                        "--detach-keys=ctrl-q,ctrl-q",
                        *environ,
                        container_name,
                        *command,
                    ],
                    {
                        "HOME": os.environ["HOME"],
                        "DOCKER_HOST": docker_host,
                    },
                )

        else:
            runtime = (container.attrs or {}).get("HostConfig",{}).get("Runtime")
            is_kata = runtime == "io.containerd.run.kata.v2"
            if is_kata:
                # `docker exec` can hang due to a bug in kata, see https://github.com/pwncollege/dojo/issues/810
                monitor_thread = threading.Thread(target=kill_exec_on_container_death,
                                                  args=(container,child_pid),
                                                  daemon=True)
                monitor_thread.start()
            _, status = os.wait()
            if simple or status == 0:
                break
            print()
            print("\r", " " * 80, "\rConnecting", end="")
            time.sleep(0.5)
    else:
        print("\r", " " * 80, "\rError: failed to connect!")


if __name__ == "__main__":
    main()
