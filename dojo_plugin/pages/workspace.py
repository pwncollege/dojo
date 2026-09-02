import base64
import datetime
import functools
import hashlib
import hmac
import os

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from flask import request, Blueprint, Response, render_template, abort
from CTFd.models import Users
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.plugins import bypass_csrf_protection
from urllib.parse import urlencode

from ..config import WORKSPACE_SECRET
from ..models import Dojos
from ..utils import user_ipv4, get_current_container, container_password, parse_positive_int
from ..utils.dojo import get_current_dojo_challenge


workspace = Blueprint("pwncollege_workspace", __name__)
port_names = {
    "challenge": 80,
    "terminal": 7681,
    "code": 8080,
    "desktop": 6080,
    "desktop-view": 6081,
    "desktop-windows": 6082,
}


@workspace.route("/workspace", methods=["GET"])
@authed_only
def view_workspace():
    return render_workspace()


@workspace.route("/workspace/<int:port>", strict_slashes=False)
@authed_only
def view_workspace_port(port):
    return render_workspace(port=port)


@workspace.route("/workspace/<string:service>", strict_slashes=False)
@authed_only
def view_workspace_service(service):
    return render_workspace(service=service)


def render_workspace(*, service=None, port=None):
    launch_ids = {
        key: request.args.get(key)
        for key in ("dojo", "module", "challenge")
    }
    if any(value is not None for value in launch_ids.values()):
        if not all(launch_ids.values()):
            return render_template(
                "error.html",
                error="dojo, module, and challenge are all required to start a workspace",
            ), 400

        launch_options = {}
        for key, default in (("practice", False), ("home", True)):
            value = request.args.get(key)
            if value is None:
                launch_options[key] = default
            elif value.lower() == "true":
                launch_options[key] = True
            elif value.lower() == "false":
                launch_options[key] = False
            else:
                return render_template(
                    "error.html",
                    error=f"{key} must be true or false",
                ), 400

        return render_template(
            "workspace_launch.html",
            launch={**launch_ids, **launch_options},
            workspace_url=request.path,
        )

    current_challenge = get_current_dojo_challenge()
    if not current_challenge:
        return render_template("error.html", error="No active challenge session; start a challenge!")

    practice = get_current_container().labels.get("dojo.mode") == "privileged"
    initial_service = None
    if service is not None or port is not None:
        for interface in current_challenge.interfaces:
            interface_name = interface["name"].lower()
            interface_port = interface.get("port")
            if service is not None and interface_name != service.lower():
                continue
            if port is not None and interface_port != port:
                continue
            initial_service = f"{interface_name}: {interface_port or ''}"
            break

        if initial_service is None:
            return render_template(
                "error.html",
                error="Workspace service is not available for the active challenge",
            ), 404

    return render_template(
        "workspace.html",
        practice=practice,
        challenge=current_challenge,
        initial_service=initial_service,
    )

def forward_workspace(
    service, message, service_path="", include_host=True, transport=None, **kwargs
):
    if service.count("~") == 0:
        service_name = service
        try:
            user = get_current_user()
            port = int(port_names.get(service_name, service_name))
        except ValueError:
            abort(404)

    elif service.count("~") == 1:
        service_name, user_id = service.split("~", 1)
        user_id = parse_positive_int(user_id)
        port = parse_positive_int(port_names.get(service_name, service_name), maximum=65535)
        if user_id is None or port is None:
            abort(404)
        user = Users.query.filter_by(id=user_id).first_or_404()

        container = get_current_container(user)
        if not container:
            abort(404)
        dojo = Dojos.from_id(container.labels["dojo.dojo_id"]).first()
        if not dojo.is_admin():
            abort(403)

    elif service.count("~") == 2:
        service_name, user_id, access_code = service.split("~", 2)
        user_id = parse_positive_int(user_id)
        port = parse_positive_int(port_names.get(service_name, service_name), maximum=65535)
        if user_id is None or port is None:
            abort(404)
        user = Users.query.filter_by(id=user_id).first_or_404()

        container = get_current_container(user)
        if not container:
            abort(404)
        correct_access_code = container_password(container, service_name)
        if not hmac.compare_digest(access_code, correct_access_code):
            abort(403)

    else:
        abort(404)

    return forward_port(
        port,
        message,
        user,
        service_path=service_path,
        include_host=include_host,
        transport=transport,
        **(kwargs or {})
    )

def workspace_signature(message, port, transport=None):
    signature_message = f"{message}:{port}"
    if transport:
        signature_message = f"{message}:{transport}:{port}"
    digest = hmac.new(
        WORKSPACE_SECRET.encode(),
        signature_message.encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode()


@functools.lru_cache(maxsize=4096)
def workspace_xpra_tls_credentials(container_id):
    secret = WORKSPACE_SECRET.encode()
    ca_key = Ed25519PrivateKey.from_private_bytes(
        hmac.digest(secret, b"xpra-ca", hashlib.sha256)
    )
    leaf_key = Ed25519PrivateKey.from_private_bytes(
        hmac.digest(secret, f"xpra-leaf:{container_id}".encode(), hashlib.sha256)
    )
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dojo-xpra-ca")])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, container_id)])
    serial = int.from_bytes(
        hmac.digest(secret, f"xpra-cert:{container_id}".encode(), hashlib.sha256)[:20],
        "big",
    ) >> 1
    certificate = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(serial or 1)
        .not_valid_before(datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc))
        .not_valid_after(datetime.datetime(2124, 1, 1, tzinfo=datetime.timezone.utc))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(container_id)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, algorithm=None)
    )
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    private_key_pem = leaf_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return certificate_pem, private_key_pem


def forward_port(
    port, message, user, service_path="", include_host=True, transport=None, **kwargs
):
    port = parse_positive_int(port, maximum=65535)
    if port is None or transport not in (None, "xpra"):
        abort(404)
    current_user = get_current_user()
    if user != current_user:
        print(f"User {current_user.id} is accessing User {user.id}'s workspace (port {port})", flush=True)

    workspace_host = os.environ.get("WORKSPACE_HOST")

    if not workspace_host:
        abort(500)
        return

    signature = workspace_signature(message, port, transport)
    route = f"{transport}/{port}" if transport else str(port)
    url = f"/workspace/{message}/{signature}/{route}/{service_path}"

    scheme = request.scheme if request else "http"

    if include_host:
        url = f"{scheme}://{workspace_host}{url}"

    params = dict(kwargs or {})

    if params:
        args = urlencode(params)
        url = f"{url}?{args}"

    return url
