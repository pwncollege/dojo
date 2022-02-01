#!/usr/bin/env python3

import sys
import os
import time

import docker


def error(msg):
    print(msg, file=sys.stderr)
    exit(1)


def main():
    if len(sys.argv) != 2:
        error(f"{sys.argv[0]} <container_name>")
    container_name = sys.argv[1]

    client = docker.from_env()

    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        error("No active challenge session; start a challenge!")

    original_command = os.getenv("SSH_ORIGINAL_COMMAND", "/bin/bash")
    ssh_tty = os.getenv("SSH_TTY") is not None

    if not ssh_tty:
        global print
        print = lambda *args, **kwargs: None

    attempts = 0
    while attempts < 30:
        try:
            container = client.containers.get(container_name)
            status = container.status
        except docker.errors.NotFound:
            status = "uninitialized"

        if status == "running":
            attempts = 0
            print("\r", " " * 80, "\rConnected!")
        else:
            attempts += 1
            print("\r", " " * 80, f"\rConnecting -- instance status: {status}", end="")
            time.sleep(1)
            continue

        if not os.fork():
            os.execve(
                "/usr/bin/docker",
                [
                    "docker",
                    "exec",
                    "-it" if ssh_tty else "-i",
                    "--user=hacker",
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
            if status == 0:
                break
            print()
            print("\r", " " * 80, "\rConnecting", end="")
            time.sleep(0.5)
    else:
        print("\r", " " * 80, "\rError: failed to connect!")


if __name__ == "__main__":
    main()
