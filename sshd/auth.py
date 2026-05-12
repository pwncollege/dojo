#!/usr/bin/env python3

import os
import pathlib
import shlex
import sys
from urllib.parse import urlparse

import psycopg2


def error(msg):
    print(msg, file=sys.stderr)
    exit(1)

def create_db_connection():
    os.environ.update(dict(entry.split("=", maxsplit=1) for entry in open("/etc/environment", "r").read().splitlines()))
    if not (db_url := os.environ.get("DATABASE_URL")):
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
    enter_path = pathlib.Path(__file__).parent.resolve() / "enter.py"
    onboard_path = pathlib.Path(__file__).parent.resolve() / "onboard.py"
    username = sys.argv[1] if len(sys.argv) > 1 else None
    key_type = sys.argv[2] if len(sys.argv) > 2 else None
    key_base64 = sys.argv[3] if len(sys.argv) > 3 else None
    fingerprint = sys.argv[4] if len(sys.argv) > 4 else None

    connection = create_db_connection()
    with connection.cursor() as cursor:
        if username and username != "hacker":
            return
        if key_type and key_base64:
            key = f"{key_type} {key_base64}"
            cursor.execute("SELECT user_id FROM ssh_keys WHERE value = %s", (key,))
            if user_id := cursor.fetchone():
                print(f'command="{enter_path} user_{user_id[0]}" {key}')
                return
            command = shlex.join([
                str(onboard_path),
                "--key-type", key_type,
                "--key-base64", key_base64,
                "--fingerprint", fingerprint or "",
            ]).replace("\\", "\\\\").replace('"', '\\"')
            print(f'command="{command}" {key}')
            return

        cursor.execute("SELECT user_id, value FROM ssh_keys")
        for user_id, key in cursor.fetchall():
            print(f'command="{enter_path} user_{user_id}" {key}')

if __name__ == "__main__":
    main()
