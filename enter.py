#!/usr/bin/env python3

import sys
import os


def error(msg):
    print(msg, file=sys.stderr)
    exit(1)


def main():
    if len(sys.argv) != 2:
        error(f"{sys.argv[0]} <container_name>")
    container_name = sys.argv[1]

    original_command = os.getenv("SSH_ORIGINAL_COMMAND", "/bin/bash")

    ssh_tty = os.getenv("SSH_TTY") is not None

    os.execve(
        "/usr/bin/docker",
        [
            "docker",
            "exec",
            "-it" if ssh_tty else "-i",
            "--user=ctf",
            container_name,
            "/bin/bash",
            "-c",
            original_command,
        ],
        {
            "HOME": os.environ["HOME"],
        },
    )

    print(sys.argv)
    os.system("env")


if __name__ == "__main__":
    main()
