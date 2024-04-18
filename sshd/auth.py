#!/usr/bin/env python3

import pathlib
import sys

from MySQLdb import connect, Error

def error(msg):
    print(msg, file=sys.stderr)
    exit(1)

def main():
    enter_path = pathlib.Path(__file__).parent.resolve() / "enter.py"
    config = dict(user="ctfd", passwd="ctfd", host="db", db="ctfd")

    try:
        db = connect(**config)
        cursor = db.cursor()
    except Error as e:
        error(f"Error: Failed to connect to database: {e}")

    try:
        cursor.execute("SELECT value, user_id FROM ssh_keys;")
        rows = cursor.fetchall()
    except Error as e:
        error(f"Error: DB query failed: {e}")

    if not rows:
        error("Error: No data returned from query")

    for key, user_id in rows:
        print(f'command="{enter_path} user_{user_id}" {key}')

    cursor.close()
    db.close()

if __name__ == "__main__":
    main()
