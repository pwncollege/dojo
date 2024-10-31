from flask import Blueprint, Response, jsonify, request
from sqlalchemy.exc import IntegrityError

from models import ActiveVolumes, db
from btrfs_volume import all_active_volumes


volume_server = Blueprint("volume", __name__)


@volume_server.route("/", methods=["GET"])
def list_volumes():
    return jsonify(dict(volumes=all_active_volumes())), 200


@volume_server.route("/<volume:volume>", methods=["GET"])
def get_volume(volume):
    with volume.active_lock():
        # If it active here, do not fetch it (infinite recursive loop)
        if not volume.active:
            active_volume = ActiveVolumes.query.filter_by(name=volume.name).first()
            if active_volume:
                volume.fetch(active_volume.host)

    snapshot_path = volume.snapshot()
    if request.headers.get("If-None-Match") == snapshot_path.name:
        return Response(status=304, headers={"ETag": snapshot_path.name})

    parents = request.args.getlist("from")
    stream = volume.send(snapshot_path, parents)
    return Response(stream, mimetype="application/octet-stream", headers={"ETag": snapshot_path.name})


@volume_server.route("/<volume:volume>", methods=["PUT"])
def put_volume(volume):
    try:
        volume.receive(request.stream)
    except RuntimeError as e:
        return str(e), 400
    return "Volume successfully received\n", 201


@volume_server.route("/<volume:volume>/activate", methods=["POST"])
def activate_volume(volume):
    active_volume = ActiveVolumes.query.filter_by(name=volume.name).first()
    if active_volume:
        if active_volume.host != request.remote_addr:
            return "Volume already active\n", 409
        else:
            active_volume.modified = db.func.now()
            db.session.commit()
            return "Volume activated\n", 201

    active_volume = ActiveVolumes(name=volume.name, host=request.remote_addr)
    try:
        # Someone else might have activated the volume in the meantime
        db.session.add(active_volume)
        db.session.commit()
    except IntegrityError:
        # Error even if the remote host is the same (this shouldn't happen)
        return "Volume already active\n", 409

    return "Volume activated\n", 201
