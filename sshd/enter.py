#!/usr/bin/env python3

import sys
import os
import time

import docker


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
            print("\033c", end="") # Clear the terminal when the user opens a new chall.
            print("\r", " " * 80, f"\rConnecting -- instance status: {status}", end="")
            time.sleep(1)
            continue

        attempts = 0
        print("\r", " " * 80, "\rConnected!")

        if not os.fork():
            ssh_entrypoint = "/opt/pwn.college/ssh-entrypoint"
            command = [ssh_entrypoint, "-c", original_command] if original_command else [ssh_entrypoint]
            os.execve(
                "/usr/bin/docker",
                [
                    "docker",
                    "exec",
                    "-it" if tty else "-i",
                    container_name,
                    *command,
                ],
                {
                    "HOME": os.environ["HOME"],
                },
            )

        else:
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
