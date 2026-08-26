import ipaddress
import json
import os
import re
from pathlib import Path

from flask import Blueprint, Response, request
from sqlalchemy.exc import IntegrityError

from models import ActiveVolumes, db


volume_server = Blueprint("volume", __name__)
LOCAL_STORAGE_HOSTS = {"127.0.0.1", os.environ.get("LOCAL_STORAGE_HOST")}
LOCAL_STORAGE_HOSTS.discard(None)
WORKSPACE_NODES_PATH = Path("/data/workspace_nodes.json")
NUMERIC_VOLUME_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)")
LEGACY_DOCKER_NETWORK = ipaddress.ip_network("172.16.0.0/12")


def workspace_node_ids():
    try:
        workspace_nodes = json.loads(WORKSPACE_NODES_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(workspace_nodes, dict):
        return None

    node_ids = []
    for node_id in workspace_nodes:
        if not isinstance(node_id, str) or not NUMERIC_VOLUME_PATTERN.fullmatch(node_id):
            return None
        parsed_node_id = int(node_id)
        if parsed_node_id < 1 or parsed_node_id > 15 or parsed_node_id in node_ids:
            return None
        node_ids.append(parsed_node_id)
    return node_ids


def expected_volume_host(volume_name, node_ids=None):
    if not isinstance(volume_name, str) or not NUMERIC_VOLUME_PATTERN.fullmatch(volume_name):
        return None
    if node_ids is None:
        node_ids = workspace_node_ids()
    if not node_ids:
        return None
    node_id = node_ids[int(volume_name) % len(node_ids)]
    return f"192.168.42.{node_id + 1}"


def host_address(host):
    try:
        address = ipaddress.ip_address(host)
    except (TypeError, ValueError):
        return None
    if address.version == 6 and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def is_local_storage_host(host):
    if host in LOCAL_STORAGE_HOSTS or host == "localhost":
        return True
    address = host_address(host)
    return address is not None and address.is_loopback


def activation_claim_allowed(volume_name, claimant_host, node_ids):
    if not isinstance(volume_name, str) or not NUMERIC_VOLUME_PATTERN.fullmatch(volume_name):
        return True
    if node_ids is None:
        return False
    if node_ids:
        return expected_volume_host(volume_name, node_ids) == claimant_host
    return is_local_storage_host(claimant_host)


def migration_claim_allowed(volume_name, current_host, claimant_host, node_ids):
    if node_ids is None or not isinstance(current_host, str) or not current_host:
        return False
    current_address = host_address(current_host)
    legacy_owner = current_address is not None and current_address in LEGACY_DOCKER_NETWORK
    if node_ids:
        return legacy_owner and expected_volume_host(volume_name, node_ids) == claimant_host
    return is_local_storage_host(claimant_host) and (
        legacy_owner or is_local_storage_host(current_host)
    )


def activation_result(volume_name, claimant_host):
    active_volume = ActiveVolumes.query.filter_by(name=volume_name).first()
    if active_volume and active_volume.host == claimant_host:
        return "Volume activated\n", 201
    return "Volume already active\n", 409


@volume_server.route("/<volume:volume>", methods=["GET"])
def get_volume(volume):
    # If it active on this node, do not fetch it (infinite recursive loop)
    if not volume.active:
        active_volume = ActiveVolumes.query.filter_by(name=volume.name).first()
        if active_volume and active_volume.host not in LOCAL_STORAGE_HOSTS:
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


def claim_volume(volume_name, claimant_host):
    node_ids = workspace_node_ids()
    if not activation_claim_allowed(volume_name, claimant_host, node_ids):
        return "Volume already active\n", 409

    active_volume = ActiveVolumes.query.filter_by(name=volume_name).first()
    if active_volume:
        if active_volume.host == claimant_host:
            return "Volume activated\n", 201
        if not migration_claim_allowed(
            volume_name,
            active_volume.host,
            claimant_host,
            node_ids,
        ):
            return "Volume already active\n", 409

        updated = ActiveVolumes.query.filter_by(
            name=volume_name,
            host=active_volume.host,
        ).update({ActiveVolumes.host: claimant_host}, synchronize_session=False)
        if updated:
            db.session.commit()
            return "Volume activated\n", 201
        db.session.rollback()
        return activation_result(volume_name, claimant_host)

    active_volume = ActiveVolumes(name=volume_name, host=claimant_host)
    try:
        db.session.add(active_volume)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return activation_result(volume_name, claimant_host)

    return "Volume activated\n", 201


@volume_server.route("/<volume:volume>/activate", methods=["POST"])
def activate_volume(volume):
    return claim_volume(volume.name, request.remote_addr)
