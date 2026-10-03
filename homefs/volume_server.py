import errno
from itertools import chain

from flask import Blueprint, Response, current_app, request
from sqlalchemy.exc import IntegrityError

from models import ActiveVolumes, db
from btrfs_volume import STORAGE_ROOT
from reset_home import backup_home, reset_home


volume_server = Blueprint("volume", __name__)


@volume_server.route("/<int(min=1):user_id>/<any(backup,reset):action>", methods=["POST"])
def manage_home_volume(user_id, action):
    try:
        volume_path = STORAGE_ROOT / str(user_id)
        if action == "reset":
            reset_home(volume_path)
            return {"success": True}
        stream = backup_home(volume_path)
        first = next(stream)
    except OSError as error:
        current_app.logger.exception("Home operation failed")
        status = {errno.EAGAIN: 409, errno.ENOENT: 404, errno.EFBIG: 413}.get(error.errno, 500)
        message = {409: "Home storage is busy. Please try again.",
                   404: "No home directory found. Start a challenge and try again.",
                   413: "The backup exceeds 1 GiB. Remove some files and try again."}
        return {"success": False, "error": message.get(status, "Could not complete the home operation. Please try again.")}, status
    response = Response(chain((first,), stream), mimetype="application/gzip")
    response.call_on_close(stream.close)
    return response


@volume_server.route("/<volume:volume>", methods=["GET"])
def get_volume(volume):
    # If it active on this node, do not fetch it (infinite recursive loop)
    if not volume.active:
        active_volume = ActiveVolumes.query.filter_by(name=volume.name).first()
        # The requester is the recorded active host when a node re-activates its own
        # volume, and when this node asks itself after a home was removed behind its
        # back; fetching from the requester would recurse until every worker is stuck.
        if active_volume and active_volume.host != request.remote_addr:
            volume.fetch(active_volume.host)

    snapshot_path = volume.snapshot()
    if request.headers.get("If-None-Match") == snapshot_path.name:
        return Response(status=304, headers={"ETag": snapshot_path.name})

    stream = volume.send(snapshot_path)
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
            return "Volume activated\n", 201

    active_volume = ActiveVolumes(name=volume.name, host=request.remote_addr)
    try:
        db.session.add(active_volume)
        db.session.commit()
    except IntegrityError:
        # Someone else might have activated the volume in the meantime
        # Error even if the remote host is the same (this shouldn't happen)
        return "Volume already active\n", 409

    return "Volume activated\n", 201
