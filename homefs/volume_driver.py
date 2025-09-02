import functools
import inspect
import json
import logging
import os
import time
import uuid

from flask import Blueprint, jsonify, request, g
from sqlalchemy.exc import IntegrityError

from models import DockerVolumes, db


STORAGE_HOST = os.environ.get("STORAGE_HOST", "localhost")
volume_driver = Blueprint("volume_driver", __name__)
logger = logging.getLogger(__name__)


@volume_driver.route("/Plugin.Activate", methods=["POST"])
def plugin_activate():
    return jsonify({"Implements": ["VolumeDriver"]})


@volume_driver.before_request
def before_request():
    g.start_time = time.monotonic()
    g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    logger.info(json.dumps(dict(
        type="request",
        id=g.request_id,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        method=request.method,
        path=request.path,
        query=request.query_string.decode(),
        body=request.get_json(force=True, silent=True),
    )))


@volume_driver.after_request
def after_request(response):
    duration = time.monotonic() - g.start_time
    logger.info(json.dumps(dict(
        type="response",
        id=g.request_id,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        status=response.status_code,
        body=response.get_json(force=True, silent=True),
        duration=duration,
    )))
    response.headers["X-Request-ID"] = g.request_id
    return response


def driver_route(method_name):
    def decorator(func):
        @volume_driver.route(f"/VolumeDriver.{method_name}", methods=["POST"])
        @functools.wraps(func)
        def wrapped():
            data = request.get_json(force=True)
            signature = inspect.signature(func)
            kwargs = {k.lower(): v for k, v in data.items() if k.lower() in signature.parameters}
            return func(**kwargs)
        return wrapped
    return decorator


@driver_route("Get")
def get(name):
    docker_volume = DockerVolumes.query.filter_by(name=name).first()
    if not docker_volume:
        return jsonify({"Err": f"Volume {name} not found"}), 404
    return jsonify({
        "Volume": {
            "Name": docker_volume.name,
            "Mountpoint": str(docker_volume.mountpoint),
            "Status": {}
        },
        "Err": "",
    })


@driver_route("Create")
def create_volume(name, opts=None):
    if opts is None:
        opts = {}
    docker_volume = DockerVolumes(name=name, overlay=opts.get("overlay"))
    try:
        db.session.add(docker_volume)
        db.session.commit()
    except IntegrityError:
        return jsonify({"Err": f"Volume {name} already exists"}), 409
    return jsonify({"Err": ""}), 200


@driver_route("Mount")
def mount_volume(name, id):
    docker_volume = DockerVolumes.query.filter_by(name=name).first()
    if not docker_volume:
        return jsonify({"Err": f"Volume {name} not found"}), 404

    if not docker_volume.overlay:
        docker_volume.btrfs.activate(STORAGE_HOST)

    elif not docker_volume.mountpoint.exists():
        snapshot_path = docker_volume.btrfs.fetch(STORAGE_HOST)
        docker_volume.btrfs.overlay(docker_volume.name, snapshot_path)

    return jsonify({"Mountpoint": str(docker_volume.mountpoint), "Err": ""})


@driver_route("Unmount")
def unmount_volume(name, id):
    docker_volume = DockerVolumes.query.filter_by(name=name).first()
    if not docker_volume:
        return jsonify({"Err": f"Volume {name} not found"}), 404

    return jsonify({"Err": ""})


@driver_route("Remove")
def remove_volume(name):
    docker_volume = DockerVolumes.query.filter_by(name=name).first()
    if not docker_volume:
        return jsonify({"Err": f"Volume {name} not found"}), 404

    if docker_volume.overlay:
        docker_volume.btrfs.remove_overlay(docker_volume.name)
    # TODO: Restore snapshotting; it has been disabled for performance
    # else:
    #     docker_volume.btrfs.snapshot()

    db.session.delete(docker_volume)
    db.session.commit()
    return jsonify({"Err": ""})


@driver_route("Path")
def volume_path(name):
    docker_volume = DockerVolumes.query.filter_by(name=name).first()
    if not docker_volume:
        return jsonify({"Err": f"Volume {name} not found"}), 404
    return jsonify({"Mountpoint": str(docker_volume.mountpoint), "Err": ""})


@driver_route("List")
def list_volumes():
    return jsonify({
        "Volumes": [
            {"Name": docker_volume.name, "Mountpoint": str(docker_volume.mountpoint)}
            for docker_volume in DockerVolumes.query.all()
        ],
        "Err": ""
    })


@driver_route("Capabilities")
def volume_capabilities():
    return jsonify({"Capabilities": {"Scope": "local"}})
