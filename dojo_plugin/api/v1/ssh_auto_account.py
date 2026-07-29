import hmac
import os
import secrets
import logging

from flask import request
from flask_restx import Namespace, Resource
from CTFd.models import Users, db
from sshpubkeys import SSHKey, InvalidKeyError
import base64

from ...models import Dojos, DojoChallenges, DojoModules, SSHKeys, SSHPiperKeys
from .docker import start_challenge, remove_container
from ...utils import get_current_container

logger = logging.getLogger(__name__)

ssh_auto_account_namespace = Namespace(
    "ssh_auto_account", description="Internal endpoint for SSH Piper auto provisioning"
)


def normalize_ssh_key(value):
    key = SSHKey(value, strict=True)
    key.parse()
    return f"{key.key_type.decode()} {base64.b64encode(key._decoded_key).decode()}"


def generate_username(prefix):
    base = f"{prefix}{secrets.token_hex(6)}"
    candidate = base
    index = 0
    while Users.query.filter_by(name=candidate).first() is not None:
        index += 1
        candidate = f"{base}{index}"
    return candidate


def resolve_bootstrap_challenge():
    dojo_ref = os.environ.get("SSH_PIPER_BOOTSTRAP_DOJO", "welcome")
    dojo_name = os.environ.get("SSH_PIPER_BOOTSTRAP_DOJO_NAME", "Welcome")

    challenge = DojoChallenges.from_id(dojo_ref, "welcome", "practice").first()
    if challenge is not None:
        return challenge

    dojo = Dojos.from_id(dojo_ref).first()
    if dojo is None:
        dojo = (
            Dojos.query
            .filter_by(name=dojo_name)
            .order_by(Dojos.official.desc(), Dojos.dojo_id.asc())
            .first()
        )

    if dojo is None:
        return None

    module = (
        DojoModules.query
        .filter_by(dojo_id=dojo.dojo_id)
        .order_by(DojoModules.module_index.asc())
        .first()
    )
    if module is None:
        return None

    challenge = (
        DojoChallenges.query
        .filter_by(dojo_id=dojo.dojo_id, module_index=module.module_index)
        .order_by(DojoChallenges.challenge_index.asc())
        .first()
    )
    return challenge


def resolve_explicit_bootstrap_challenge(dojo_id, module_id, challenge_id):
    dojo = Dojos.from_id(dojo_id).first()
    if dojo is None:
        return None
    return (
        DojoChallenges.query
        .filter_by(id=challenge_id)
        .join(DojoModules.query.filter_by(dojo_id=dojo.dojo_id, id=module_id).subquery())
        .first()
    )


def ensure_piper_key(user):
    piper_key = SSHPiperKeys.query.filter_by(user_id=user.id).first()
    if piper_key is not None:
        return piper_key

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    private_key = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_key = private.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode()

    piper_key = SSHPiperKeys(user_id=user.id, public_key=public_key, private_key=private_key)
    db.session.add(piper_key)
    db.session.commit()
    return piper_key


def authorized():
    token = os.environ.get("SSH_PIPER_API_TOKEN", "ssh-piper-development-token")
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    supplied = auth_header[len("Bearer "):].strip()
    return hmac.compare_digest(supplied, token)


@ssh_auto_account_namespace.route("")
class SSHAutoAccount(Resource):
    def post(self):
        if not authorized():
            return {"success": False, "error": "Unauthorized"}, 401

        data = request.get_json() or {}
        public_key = data.get("public_key", "")

        try:
            normalized_key = normalize_ssh_key(public_key)
        except (InvalidKeyError, NotImplementedError):
            return {"success": False, "error": "Invalid SSH key"}, 400

        key = SSHKeys.query.filter_by(value=normalized_key).first()
        created_user = False

        if key is None:
            username = generate_username("ssh_")
            email = f"{username}@ssh.pwn.college"
            password = secrets.token_urlsafe(24)

            user = Users(name=username, email=email, password=password, verified=True)
            db.session.add(user)
            db.session.flush()

            db.session.add(SSHKeys(user_id=user.id, value=normalized_key))
            db.session.commit()
            created_user = True
        else:
            user = key.user

        banner = ""
        challenge = None
        workspace_started = False
        workspace_error = ""
        needs_workspace = get_current_container(user) is None
        if created_user or needs_workspace:
            dojo_id = data.get("bootstrap_dojo")
            module_id = data.get("bootstrap_module")
            challenge_id = data.get("bootstrap_challenge")
            explicit_bootstrap = bool(created_user and dojo_id and module_id and challenge_id)
            if explicit_bootstrap:
                challenge = resolve_explicit_bootstrap_challenge(dojo_id, module_id, challenge_id)
            else:
                challenge = resolve_bootstrap_challenge()
            if challenge is None:
                if created_user:
                    db.session.delete(user)
                    db.session.commit()
                return {"success": False, "error": "Bootstrap challenge not found"}, 500
            try:
                start_challenge(user, challenge, not explicit_bootstrap)
                workspace_started = True
            except Exception as exc:
                remove_container(user)
                workspace_error = str(exc)
                logger.warning("failed to start bootstrap workspace for user_id=%s: %s", user.id, workspace_error)
                if created_user:
                    db.session.delete(user)
                    db.session.commit()
                return {"success": False, "error": workspace_error}, 500
            module_id = challenge.module.id if challenge.module else ""
            banner = f"{challenge.dojo.name}: {module_id}/{challenge.id}\n\n{challenge.description or ''}\n"

        piper_key = ensure_piper_key(user)

        return {
            "success": True,
            "user_id": user.id,
            "username": user.name,
            "created_user": created_user,
            "banner": banner,
            "challenge": None if challenge is None else {
                "dojo": challenge.dojo.reference_id,
                "module": challenge.module.id,
                "challenge": challenge.id,
                "description": challenge.description,
            },
            "upstream": {
                "host": os.environ.get("SSH_PIPER_UPSTREAM_HOST", "127.0.0.1"),
                "port": int(os.environ.get("SSH_PIPER_UPSTREAM_PORT", "2222")),
                "user": os.environ.get("SSH_PIPER_UPSTREAM_USER", "hacker"),
                "private_key": piper_key.private_key,
            },
            "workspace": {
                "started": workspace_started,
                "error": workspace_error,
            },
        }
