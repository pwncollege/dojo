#!/usr/bin/env python3

import grp
import os
import pathlib
import pwd
import shutil
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
    if (mac_key_file := os.environ.get("MAC_KEY_FILE")) and not os.path.exists("/tmp/mac-key"):
        shutil.copy(mac_key_file, "/tmp/mac-key")
        os.chown("/tmp/mac-key", pwd.getpwnam("hacker").pw_uid, grp.getgrnam("docker").gr_gid)
        os.chmod("/tmp/mac-key", 0o600)

    enter_path = pathlib.Path(__file__).parent.resolve() / "enter.py"

    connection = create_db_connection()
    with connection.cursor() as cursor:
        cursor.execute("SELECT user_id, value FROM ssh_keys")
        for user_id, key in cursor.fetchall():
            print(f'command="{enter_path} user_{user_id}" {key}')

if __name__ == "__main__":
    main()
