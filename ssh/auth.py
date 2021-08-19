#!/usr/bin/env python3

import sys
import pathlib

import docker


def error(msg):
    print(msg, file=sys.stderr)
    exit(1)


def main():
    enter_path = pathlib.Path(__file__).parent.resolve() / "enter.py"
    client = docker.from_env()

    try:
        container = client.containers.get("ctfd_db")
    except docker.errors.NotFound:
        error("Error: ctfd is not running!")

    result = container.exec_run(
        "mysql -pctfd -Dctfd -sNe 'select value, user_id from ssh_keys;'"
    )
    if result.exit_code != 0:
        error(f"Error: db query exited with code '{result.exit_code}'")

    for row in result.output.strip().split(b"\n"):
        key, user_id = row.decode().split("\t")
        print(f'command="{enter_path} user_{user_id}" {key}')


if __name__ == "__main__":
    main()
