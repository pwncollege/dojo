import re

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from CTFd.models import db
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user
import markupsafe

from ...models import SSHKeys
from ...utils.ssh_key import InvalidKeyError, normalize_ssh_key


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
