from flask import Blueprint, request, Response


volume_server = Blueprint("volume", __name__)


@volume_server.route("/<volume:volume>", methods=["GET"])
def get_volume(volume):
    snapshot_path = volume.snapshot()
    if request.headers.get("If-None-Match") == snapshot_path.name:
        return "", 304
    parents = request.args.getlist("from")
    stream = volume.send(snapshot_path, parents)
    response = Response(stream, mimetype="application/octet-stream")
    response.headers["ETag"] = snapshot_path.name
    return response


@volume_server.route("/<volume:volume>", methods=["PUT"])
def put_volume(volume):
    try:
        volume.receive(request.stream)
    except RuntimeError as e:
        return str(e), 400
    return "Volume successfully received\n", 200
