#!/usr/bin/env python3

import os
import sys
from urllib.parse import urlparse

import psycopg2


def error(msg):
    print(msg, file=sys.stderr)
    exit(1)

def create_db_connection():
    if not (db_url := os.environ.get("DATABASE_URL")):
        db_user = os.environ.get("DB_USER", "ctfd")
        db_pass = os.environ.get("DB_PASS", "ctfd")
        db_name = os.environ.get("DB_NAME", "ctfd")
        db_url = f"postgresql://{db_user}:{db_pass}@127.0.0.1:5432/{db_name}"
    parsed = urlparse(db_url)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
        user=parsed.username,
        password=parsed.password,
    )

def main():
    enter_path = os.environ.get("DOJO_SSH_ENTER", "/run/current-system/sw/bin/dojo-ssh-enter")

    connection = create_db_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT ssh_keys.user_id, ssh_keys.value FROM ssh_keys "
            "JOIN users ON users.id = ssh_keys.user_id "
            "WHERE NOT users.banned AND ssh_keys.value <> ''"
        )
        for user_id, key in cursor.fetchall():
            print(f'command="{enter_path} user_{user_id}" {key}')

if __name__ == "__main__":
    main()
