import os
import subprocess
import urllib.parse

import requests
from flask import request, Response, Blueprint
from CTFd.utils.decorators import admins_only

from ..utils import redirect_internal


dev = Blueprint("pwncollege_dev", __name__)


def dev_initialize():
    try:
        os.mkdir("/run/code-server")
    except FileExistsError:
        pass

    args = [
        "start-stop-daemon",
        "--start",
        "--pidfile", "/run/code-server/code-server.pid",
        "--make-pidfile",
        "--background",
        "--no-close",
        "--quiet",
        "--oknodo",
        "--startas", "/usr/bin/code-server",
        "--",
        "--auth=none",
        "--bind-addr=0.0.0.0:8080",
        "--extensions-dir=/opt/code-server/extensions",
        "--disable-telemetry",
    ]
    subprocess.run(args,
                   stdin=subprocess.DEVNULL,
                   stdout=open("/run/code-server/code-server.log", "a"),
                   stderr=subprocess.STDOUT,
                   check=True)


@dev.route("/dev/")
@dev.route("/dev/<path:path>")
@admins_only
def dev_proxy(path=""):
    prefix = "/dev/"
    assert request.full_path.startswith(prefix)
    path = request.full_path[len(prefix):]
    return redirect_internal(f"http://ctfd:8080/{path}")
