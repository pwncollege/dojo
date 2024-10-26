import functools
import inspect
import logging
import os

import requests
from flask import Blueprint, jsonify, request

from volume import Volume


STORAGE_HOST = os.environ.get("STORAGE_HOST", "http://localhost")

logger = logging.getLogger(__name__)
volume_driver = Blueprint("volume_driver", __name__)


@volume_driver.route("/Plugin.Activate", methods=["POST"])
def plugin_activate():
    return jsonify({"Implements": ["VolumeDriver"]})


def driver_route(method_name):
    def decorator(func):
        @volume_driver.route(f"/VolumeDriver.{method_name}", methods=["POST"])
        @functools.wraps(func)
        def wrapped():
            data = request.get_json(force=True)
            signature = inspect.signature(func)
            kwargs = {k.lower(): v for k, v in data.items() if k.lower() in signature.parameters}
            if "volume" in signature.parameters and "Name" in data:
                kwargs["volume"] = Volume(data["Name"])
            return func(**kwargs)
        return wrapped
    return decorator


@driver_route("Get")
def get(volume):
    return jsonify({
        "Volume": {
            "Name": volume.name,
            "Mountpoint": str(volume.active_path),
            "Status": {}
        },
        "Err": ""
    })


@driver_route("Create")
def create_volume(volume, opts=None):
    return jsonify({"Err": ""})


@driver_route("Mount")
def mount_volume(volume, id):
    logger.info("Mounting %s %s", volume.name, id)
    with volume.active_lock():
        if not volume.active:
            headers = {}
            if volume.latest_snapshot_path:
                headers["If-None-Match"] = volume.latest_snapshot_path.name
            response = requests.get(f"{STORAGE_HOST}/volume/{volume.name}", headers=headers, stream=True)
            if response.status_code == 304:
                snapshot_path = volume.latest_snapshot_path
            elif (volume.snapshots_path / response.headers["ETag"]).exists():
                snapshot_path = volume.snapshots_path / response.headers["ETag"]
            else:
                with response.raw as stream:
                    snapshot_path = volume.receive(stream)
            volume.activate(snapshot_path, locked=True)
        else:
            volume.snapshot(locked=True)
    return jsonify({"Mountpoint": str(volume.active_path), "Err": ""})


@driver_route("Unmount")
def unmount_volume(volume, id):
    logger.info("Unmounting %s %s", volume.name, id)
    with volume.active_lock():
        volume.snapshot(locked=True)
    return jsonify({"Err": ""})


@driver_route("Remove")
def remove_volume(volume):
    return jsonify({"Err": ""})


@driver_route("Path")
def volume_path(volume):
    return jsonify({"Mountpoint": str(volume.active_path), "Err": ""})


@driver_route("List")
def list_volumes():
    return jsonify({"Volumes": [], "Err": ""})
