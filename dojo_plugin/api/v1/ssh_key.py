import re

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from CTFd.models import db
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

from ...models import SSHKeys


ssh_key_namespace = Namespace(
    "keys", description="Endpoint to manage users' public SSH keys"
)


@ssh_key_namespace.route("")
class UpdateKey(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        key_value = data.get("ssh_key", "")

        if key_value:
            key_re = "ssh-(rsa|ed25519|dss) AAAA[0-9A-Za-z+/]{1,730}[=]{0,2}"
            key_match = re.match(key_re, key_value)
            if not key_match:
                return (
                    {
                        "success": False,
                        "error": f"Invalid SSH Key, expected format:<br><code>{key_re}</code>"
                    },
                    400,
                )
            key_value = key_match.group()

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
        data = request.get_json()
        key_value = data.get("ssh_key", "")

        user = get_current_user()

        key = SSHKeys.query.filter_by(user=user, value=key_value).first()
        if not key:
            return (
                {"success": False, "error": "SSH Key does not exist"},
                400,
            )

        db.session.delete(key)
        db.session.commit()

        return {"success": True}
