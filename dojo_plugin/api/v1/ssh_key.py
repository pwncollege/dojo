import datetime
import secrets

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from CTFd.models import db
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user
import markupsafe

from ...config import DOJO_HOST
from ...models import SSHKeyLinkRequests, SSHKeys
from ...utils.ssh_key import InvalidKeyError, normalize_offered_ssh_key, normalize_ssh_key
from ...utils.ssh_onboarding import ssh_link_token_digest
from .user import ssh_service_only


ssh_key_namespace = Namespace(
    "keys", description="Endpoint to manage users' public SSH keys"
)
LINK_TTL = datetime.timedelta(minutes=15)


def link_url(token):
    host = DOJO_HOST or request.host
    scheme = "http" if host.startswith("localhost") or host.startswith("127.") else "https"
    return f"{scheme}://{host}/ssh/link/{token}"


@ssh_key_namespace.route("")
class UpdateKey(Resource):
    @authed_only
    def post(self):
        data = request.get_json() or {}
        key_value = data.get("ssh_key", "").strip()
        if not key_value:
            return {"success": False, "error": "Please provide an SSH key"}, 400

        try:
            key_value = normalize_ssh_key(key_value)
        except (InvalidKeyError, NotImplementedError) as e:
            return (
                {
                    "success": False,
                    "error": f"Invalid SSH Key, error: <code>{markupsafe.escape(e)}</code> <br>Refer below for how to generate a valid ssh key"
                },
                400,
            )

        user = get_current_user()

        try:
            key = SSHKeys(user_id=user.id, value=key_value)
            db.session.add(key)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return (
                {"success": False, "error": "SSH Key already in use"},
                400,
            )

        return {"success": True}

    @authed_only
    def delete(self):
        data = request.get_json() or {}
        key_value = data.get("ssh_key", "").strip()
        if not key_value:
            return {"success": False, "error": "Please provide an SSH key"}, 400

        try:
            key_value = normalize_ssh_key(key_value)
        except (InvalidKeyError, NotImplementedError):
            return {"success": False, "error": "SSH Key does not exist"}, 400

        user = get_current_user()

        key = SSHKeys.query.filter_by(user_id=user.id, value=key_value).first()
        if not key:
            return (
                {"success": False, "error": "SSH Key does not exist"},
                400,
            )

        db.session.delete(key)
        db.session.commit()

        return {"success": True}


@ssh_key_namespace.route("/link")
class CreateLink(Resource):
    @ssh_service_only
    def post(self):
        data = request.get_json() or {}
        try:
            key_value = normalize_offered_ssh_key(data.get("key_type", ""), data.get("key_base64", ""))
        except (InvalidKeyError, NotImplementedError) as error:
            return {"success": False, "error": f"Invalid SSH key: {error}"}, 400

        if SSHKeys.query.filter_by(value=key_value).first():
            return {"success": False, "error": "SSH key is already linked to an account"}, 400

        token = secrets.token_urlsafe(32)
        link_request = SSHKeyLinkRequests(
            token_digest=ssh_link_token_digest(token),
            key_value=key_value,
            fingerprint=data.get("fingerprint", ""),
            expiration=datetime.datetime.utcnow() + LINK_TTL,
        )
        db.session.add(link_request)
        db.session.commit()
        return {
            "success": True,
            "token": token,
            "link_url": link_url(token),
            "expires_at": link_request.expiration.isoformat(),
        }


@ssh_key_namespace.route("/link/<token>")
class LinkStatus(Resource):
    @ssh_service_only
    def get(self, token):
        link_request = SSHKeyLinkRequests.query.filter_by(token_digest=ssh_link_token_digest(token)).first()
        if not link_request:
            return {"success": False, "status": "not_found"}, 404
        if link_request.consumed:
            return {
                "success": True,
                "status": "linked",
                "user": {
                    "id": link_request.user.id if link_request.user else None,
                    "name": link_request.user.name if link_request.user else None,
                },
            }
        if link_request.expiration < datetime.datetime.utcnow():
            return {"success": True, "status": "expired"}
        return {"success": True, "status": "pending"}
