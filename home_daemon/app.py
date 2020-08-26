#!/usr/bin/env python3

import os
import sys
import pathlib
import shutil
import subprocess

from flask import Flask

app = Flask(__name__)

"""
TODO: This is a total nightmare.
For some reason linux and docker will not comply.
The bind mount will propagete, but the nosuid option will not!
"""


@app.route("/init/<int:user_id>", methods=["POST"])
def init(user_id):
    try:
        homes = pathlib.Path("/homes")
        homes_data = homes / "data"
        homes_nosuid = homes / "nosuid"
        assert homes.exists(), "'/homes' does not exist"

        homes_data.mkdir(exist_ok=True)
        homes_nosuid.mkdir(exist_ok=True)

        user_home_data = homes_data / str(user_id)
        user_home_nosuid = homes_nosuid / str(user_id)

        if not user_home_data.exists():
            shutil.copytree("/etc/skel", user_home_data)
            os.chown(user_home_data, 1000, 1000)
            for path in user_home_data.rglob("*"):
                os.chown(path, 1000, 1000)

        if not user_home_nosuid.exists():
            user_home_nosuid.mkdir()

        try:
            output = subprocess.check_output(
                ["findmnt", "--output", "OPTIONS", user_home_nosuid]
            )
            assert b"nosuid" in output, "Mount found, but not nosuid"
        except subprocess.CalledProcessError:
            result = subprocess.run(
                ["mount", "--bind", user_home_data, user_home_nosuid],
                stderr=subprocess.PIPE,
            )
            assert not result.stderr, result.stderr
            result = subprocess.run(
                ["mount", "-o", "remount,nosuid", user_home_nosuid],
                stderr=subprocess.PIPE,
            )
            assert not result.stderr, result.stderr

    except Exception as e:
        print(f"Error for user {user_id}: {e}", file=sys.stderr, flush=True)
        return {"success": False, "error": str(e)}

    return {"success": True}
