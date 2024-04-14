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
    def patch(self):

        data = request.get_json()
        key_value = data.get("ssh_key", "")


        if key_value:
            key_re = "ssh-(rsa|ed25519|dss) AAAA[0-9A-Za-z+/]+[=]{0,2}"
            key_match = re.match(key_re, key_value)
            if not key_match:
                return (
                    {
                        "success": False,
                        "error": f"Invalid public key, expected format:<br><code>{key_re}</code>"
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
                {"success": False, "errors": {"key": "Public key already in use"}},
                400,
            )

        return {"success": True}
    
    
@ssh_key_namespace.route("/delete")
class UpdateKey(Resource):
    @authed_only
    def patch(self):
        data = request.get_json()
        key_value = data.get("ssh_key", "")

        data = request.get_json()
        key_value = data.get("ssh_key", "")
        if not key_value:
            return (
                    {
                        "success": False,
                        "error": "No key in request"
                    },
                    400,
                )
        
        user = get_current_user()

        try:
            current_key = SSHKeys.query.filter_by(value=key_value)
            if not current_key.first(): 
                return (
                    {"success": False, "error": "Key does not exist"},
                    400,
                )
            if not current_key.first().user_id != user: 
                return (
                    {"success": False, "error": "This is not your public key"},
                    400,
                )
            current_key.delete()
            db.session.commit()
        except IntegrityError:
            return (
                {"success": False, "errors": "Public key not currently in use"},
                400,
            )
        return {"success": True}
