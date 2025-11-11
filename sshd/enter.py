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
