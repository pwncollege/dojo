#!/usr/bin/env python3

import os
import pathlib
import subprocess
import sys
from urllib.parse import urlparse

import psycopg2


def error(msg):
    print(msg, file=sys.stderr)
    exit(1)

def create_db_connection():
    root_environ = dict(entry.split("=", maxsplit=1) for entry in open("/proc/1/environ", "r").read().split("\0"))
    if not (db_url := root_environ.get("DATABASE_URL")):
        error("DATABASE_URL environment variable is not set")
    parsed = urlparse(db_url)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
        user=parsed.username,
        password=parsed.password,
    )

def main():
    # dirty dirty hack
    target_key = pathlib.Path(__file__).parent.resolve() / "pwn-college-mac-key"
    subprocess.run(f"cp {os.environ.get('MAC_KEY_FILE', '/opt/pwn.college/data/mac-key')} {target_key} ; chown hacker:docker {target_key} ; chmod 600 {target_key}",
                   shell=True,
                   )

    enter_path = pathlib.Path(__file__).parent.resolve() / "enter.py"

    connection = create_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id, value FROM ssh_keys")
        for user_id, key in cursor.fetchall():
            print(f'command="{enter_path} user_{user_id}" {key}')

if __name__ == "__main__":
    main()
