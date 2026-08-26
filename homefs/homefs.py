import logging
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import requests
from flask import Flask
from werkzeug.routing import BaseConverter

from models import db
from btrfs_volume import check_volume_storage, BTRFSVolume
from volume_server import claim_volume, volume_server, workspace_node_ids
from volume_driver import volume_driver
from utils import file_lock, CONTROL_REQUEST_TIMEOUT


STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/data"))
STORAGE_HOST = os.environ.get("STORAGE_HOST", "localhost")
LOCAL_STORAGE_HOST = os.environ.get("LOCAL_STORAGE_HOST", "127.0.0.1")
HOME_VOLUME_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)")
WORKSPACE_NODE_PATTERN = re.compile(r"(?:0|[1-9]|1[0-5])")
RECONCILIATION_LOCK_PATH = "/run/homefs-reconciliation.lock"
RECONCILIATION_STATE_PATH = Path("/run/homefs-reconciliation.state")


def local_active_volume_names():
    active_volume_names = []
    for active_path in STORAGE_ROOT.glob("*/active"):
        volume_name = active_path.parent.name
        if not HOME_VOLUME_PATTERN.fullmatch(volume_name):
            continue
        result = subprocess.run(
            ["btrfs", "subvolume", "show", active_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            active_volume_names.append(volume_name)
    return sorted(active_volume_names, key=int)


@file_lock(RECONCILIATION_LOCK_PATH)
def reconcile_active_volumes():
    reconciliation_id = os.environ.get("INVOCATION_ID") or f"parent-{os.getppid()}"
    try:
        if RECONCILIATION_STATE_PATH.read_text() == reconciliation_id:
            return
    except OSError:
        pass

    workspace_node_value = os.environ.get("WORKSPACE_NODE", "0")
    if not WORKSPACE_NODE_PATTERN.fullmatch(workspace_node_value):
        raise RuntimeError(f"Invalid WORKSPACE_NODE: {workspace_node_value!r}")
    workspace_node = int(workspace_node_value)
    if workspace_node == 0:
        node_ids = workspace_node_ids()
        if node_ids is None:
            raise RuntimeError("Invalid workspace node topology")
        if node_ids:
            RECONCILIATION_STATE_PATH.write_text(reconciliation_id)
            return

        for volume_name in local_active_volume_names():
            _, status = claim_volume(volume_name, LOCAL_STORAGE_HOST)
            if status != 201:
                raise RuntimeError(
                    f"Failed to reconcile active volume {volume_name}: {status}"
                )
        RECONCILIATION_STATE_PATH.write_text(reconciliation_id)
        return

    for volume_name in local_active_volume_names():
        try:
            response = requests.post(
                f"http://{STORAGE_HOST}:4201/volume/{volume_name}/activate",
                allow_redirects=False,
                stream=True,
                timeout=CONTROL_REQUEST_TIMEOUT,
            )
        except requests.RequestException as error:
            raise RuntimeError(f"Failed to reconcile active volume {volume_name}") from error
        with response:
            if response.status_code != 201:
                raise RuntimeError(
                    f"Failed to reconcile active volume {volume_name}: {response.status_code}"
                )

    RECONCILIATION_STATE_PATH.write_text(reconciliation_id)


class VolumeConverter(BaseConverter):
    def to_python(self, value):
        return BTRFSVolume(value)

    def to_url(self, value):
        return value.name


@file_lock("/run/homefs.lock")
def create_app():
    check_volume_storage()

    app = Flask(__name__)

    homefs_db_path = STORAGE_ROOT / "homefs.db"
    with closing(sqlite3.connect(homefs_db_path, timeout=30)) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if journal_mode != "wal":
            raise RuntimeError(f"Failed to enable WAL for {homefs_db_path}: {journal_mode}")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{homefs_db_path}"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"timeout": 30}}

    db.init_app(app)

    with app.app_context():
        db.create_all()

    app.url_map.converters["volume"] = VolumeConverter

    app.register_blueprint(volume_driver, url_prefix="/")
    app.register_blueprint(volume_server, url_prefix="/volume")

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    with app.app_context():
        reconcile_active_volumes()

    return app
