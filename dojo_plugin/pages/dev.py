import os
import subprocess
import urllib.parse

import requests
from flask import request, Response, Blueprint
from CTFd.utils.decorators import admins_only
from CTFd.plugins import bypass_csrf_protection

from ..utils import redirect_internal


dev = Blueprint("pwncollege_dev", __name__)


def dev_initialize():
    try:
        os.mkdir("/run/dev-server")
    except FileExistsError:
        pass

    args = [
        "start-stop-daemon",
        "--start",
        "--pidfile", "/run/dev-server/dev-server.pid",
        "--make-pidfile",
        "--background",
        "--no-close",
        "--quiet",
        "--oknodo",
        "--startas", "/usr/local/bin/python",
        "--",
        "-m", "jupyterlab",
        "--ip=0.0.0.0",
        "--port=8888",
        "--allow-root",
        "--no-browser",
        "--NotebookApp.token=''",
        "--NotebookApp.base_url='/dev/'",
        "--NotebookApp.allow_origin='*'",
    ]
    subprocess.run(args,
                   stdin=subprocess.DEVNULL,
                   stdout=open("/run/dev-server/dev-server.log", "a"),
                   stderr=subprocess.STDOUT,
                   check=True)


@dev.route("/dev/", methods=["GET", "POST", "PUT"])
@dev.route("/dev/<path:path>", methods=["GET", "POST", "PUT"])
@bypass_csrf_protection
@admins_only
def dev_proxy(path=""):
    proxy_url = urllib.parse.urlparse(request.url)
    dev_url = proxy_url._replace(
        scheme="http",
        netloc="ctfd:8888",
    )
    return redirect_internal(dev_url.geturl())
