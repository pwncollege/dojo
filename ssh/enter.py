#!/usr/bin/env python3

import sys
import os
import time

import docker


def main():
    original_command = os.getenv("SSH_ORIGINAL_COMMAND", "/bin/bash")
    tty = os.getenv("SSH_TTY") is not None

    def print(*args, **kwargs):
        if not tty:
            return
        kwargs.update(file=sys.stderr)
        return __builtins__.print(*args, **kwargs)

    if len(sys.argv) != 2:
        print(f"{sys.argv[0]} <container_name>")
        exit(1)
    container_name = sys.argv[1]

    client = docker.from_env()

    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        print("No active challenge session; start a challenge!")
        exit(1)

    attempts = 0
    while attempts < 30:
        try:
            container = client.containers.get(container_name)
            status = container.status
        except docker.errors.NotFound:
            status = "uninitialized"

        if status == "running":
            try:
                container.get_archive("/opt/pwn.college/.initialized")
            except docker.errors.NotFound:
                status = "initializing"

        if status != "running":
            attempts += 1
            print("\r", " " * 80, f"\rConnecting -- instance status: {status}", end="")
            time.sleep(1)
            continue

        attempts = 0
        print("\r", " " * 80, "\rConnected!")

        if not os.fork():
            os.execve(
                "/usr/bin/docker",
                [
                    "docker",
                    "exec",
                    "-it" if tty else "-i",
                    container_name,
                    "/bin/bash",
                    "-c",
                    original_command,
                ],
                {
                    "HOME": os.environ["HOME"],
                },
            )

        else:
            _, status = os.wait()
            if status == 0 or not tty:
                break
            print()
            print("\r", " " * 80, "\rConnecting", end="")
            time.sleep(0.5)
    else:
        print("\r", " " * 80, "\rError: failed to connect!")


if __name__ == "__main__":
    main()
