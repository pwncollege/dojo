#!/usr/bin/env python3

import sys
import pathlib
import os
import subprocess

# adamd: insanity to reload the environment varaibles from the docker compose

global_env = "/etc/environment"
if os.path.exists(global_env):
    with open(global_env, "r") as f:
        for line in f.readlines():
            res = line.strip().split("=", maxsplit=1)
            if res and len(res) == 2:
                key = res[0]
                value = res[1]
                os.environ[key] = value


DB_HOST = os.environ.get('DB_HOST', "db")
DB_NAME = os.environ.get('DB_NAME', "ctfd")
DB_USER = os.environ.get('DB_USER', "ctfd")
DB_PASS = os.environ.get('DB_PASS', "ctfd")

def error(msg):
    print(msg, file=sys.stderr)
    exit(1)


def main():
    enter_path = pathlib.Path(__file__).parent.resolve() / "enter.py"

    connect_arg = f"-h{DB_HOST}" if DB_HOST else ""
    result = subprocess.run(["mysql", connect_arg, f"-p{DB_PASS}", f"-u{DB_USER}", f"-D{DB_NAME}", "-sNe", 'select value, user_id from ssh_keys;'], stdout=subprocess.PIPE)
    if result.returncode != 0:
        error(f"Error: db query exited with code '{result.returncode}'")

    for row in result.stdout.strip().split(b"\n"):
        key, user_id = row.decode().split("\t")
        print(f'command="{enter_path} user_{user_id}" {key}')


if __name__ == "__main__":
    main()
