#!/usr/bin/env python3

import os
import pathlib
import re
import sys
from urllib.parse import urlparse

import psycopg2


# Each row is printed as one authorized_keys line, following this script's forced
# command. A value containing a space would shift the key fields along that line,
# and one containing a newline would begin a second, unrestricted entry, so only a
# bare "<type> <base64>" pair is ever emitted.
AUTHORIZED_KEY_RE = re.compile(r"[\x21-\x2b\x2d-\x7e]{1,64} [A-Za-z0-9+/]+={0,2}\Z")


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

    connection = create_db_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ssh_keys.user_id, ssh_keys.value FROM ssh_keys "
            "JOIN users ON users.id = ssh_keys.user_id "
            "WHERE NOT users.banned AND ssh_keys.value <> ''"
        )
        for user_id, key in cursor.fetchall():
            if not AUTHORIZED_KEY_RE.match(key):
                print(f"skipping malformed key for user {user_id}", file=sys.stderr)
                continue
            print(f'command="{enter_path} user_{user_id}" {key}')

if __name__ == "__main__":
    main()
