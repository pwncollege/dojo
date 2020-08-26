#!/usr/bin/env python3

import sys
import pathlib

import docker


# /etc/ssh/sshd_config
#
# Match User ctf
#       AuthorizedKeysCommand /opt/ctf.pwn.college/auth.py ctfpwncollege_db_1 ctf
#       AuthorizedKeysCommandUser root
#       X11Forwarding no
#       AllowTcpForwarding no
#
# AuthorizedKeysCommandUser must be root, because we need docker access
# and sshd does not respect groups for the AuthorizedKeysCommand


def error(msg):
    print(msg, file=sys.stderr)
    exit(1)


def main():
    if len(sys.argv) != 3:
        error(f"{sys.argv[0]} <db_container_name> <user_container_prefix>")
    db_container_name = sys.argv[1]
    user_container_prefix = sys.argv[2]

    enter_path = pathlib.Path(__file__).parent.resolve() / "enter.py"

    client = docker.from_env()

    try:
        container = client.containers.get(db_container_name)
    except docker.errors.NotFound:
        error(f"Error: db container '{db_container_name}' not found")

    result = container.exec_run(
        "mysql -pctfd -Dctfd -sNe 'select value, user_id from ssh_keys;'"
    )
    if result.exit_code != 0:
        error(f"Error: db query exited with code '{result.exit_code}'")

    for row in result.output.strip().split(b"\n"):
        key, user_id = row.decode().split("\t")

        print(f'command="{enter_path} {user_container_prefix}_user_{user_id}" {key}')


if __name__ == "__main__":
    main()
