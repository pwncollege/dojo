import re

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from ...utils.decorators import authed_only
from ...utils.user import get_current_user
from sshpubkeys import SSHKey, InvalidKeyError
import base64
import markupsafe

from ...models import SSHKeys, db


# The stored value becomes one line of sshd's authorized_keys stream, so a key type
# carrying a separator would add fields to that line. RFC 4250 s4.6.1 limits an
# algorithm name to 1-64 printable US-ASCII characters with no whitespace, comma,
# control character or DEL. Matched against bytes so that a type which is not even
# ASCII is rejected rather than raising on decode, and anchored with \Z because $
# would admit a trailing newline.
KEY_TYPE_RE = re.compile(rb"[\x21-\x2b\x2d-\x7e]{1,64}\Z")


ssh_key_namespace = Namespace(
    "keys", description="Endpoint to manage users' public SSH keys"
)


@ssh_key_namespace.route("")
class UpdateKey(Resource):
    @authed_only
    def post(self):
        data = request.get_json(silent=True)
        key_value = data.get("ssh_key", "") if isinstance(data, dict) else ""
        if not isinstance(key_value, str):
            return {"success": False, "error": "ssh_key must be a string"}, 400

        key_value = key_value.strip()
        if not key_value:
            return {"success": False, "error": "Please provide an SSH key"}, 400

        try:
            key = SSHKey(key_value, strict=True)
            key.parse()
            if not KEY_TYPE_RE.match(key.key_type):
                raise InvalidKeyError(f"unsupported key type: {key.key_type[:64]!r}")
            key_value = f"{key.key_type.decode()} {base64.b64encode(key._decoded_key).decode()}"
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
        data = request.get_json(silent=True)
        key_value = data.get("ssh_key", "") if isinstance(data, dict) else ""
        if not isinstance(key_value, str):
            return {"success": False, "error": "ssh_key must be a string"}, 400

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
