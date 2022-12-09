import os
import subprocess
import urllib.parse

import requests
from flask import request, Response, Blueprint
from CTFd.utils.decorators import admins_only
from CTFd.plugins import bypass_csrf_protection


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
        "--port=8888",
        "--allow-root",
        "--no-browser",
        "--NotebookApp.token=''",
        "--NotebookApp.base_url='/dev/'",
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
        netloc="localhost:8888",
    )

    ignored_headers = ["host", "origin"]

    import sys
    data = (request.method, dev_url.geturl(), {key: value for key, value in request.headers if key.lower() not in ignored_headers}, request.get_data(), request.cookies)
    print("1", str(data), flush=True)
    print("2", str(data), flush=True, file=sys.stderr)


    response = requests.request(
        method=request.method,
        url=dev_url.geturl(),
        headers={key: value for key, value in request.headers if key.lower() not in ignored_headers},
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False
    )

    excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
    headers = [
        (name, value) for name, value in response.raw.headers.items()
        if name.lower() not in excluded_headers
    ]

    return Response(response=response.iter_content(chunk_size=10*1024),
                    status=response.status_code,
                    headers=headers,
                    content_type=response.headers["Content-Type"])
