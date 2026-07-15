import base64
from functools import wraps

from flask import request
from flask_restx import Namespace, Resource
from itsdangerous.url_safe import URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from CTFd.models import Users, db
from CTFd.utils import email, get_config, validators
from CTFd.utils.config import can_send_mail
from CTFd.utils.config.visibility import registration_visible
from sshpubkeys import SSHKey, InvalidKeyError

from ...config import DOJO_SSH_SERVICE_KEY
from ...models import SSHKeys


ssh_onboarding_namespace = Namespace("ssh_onboarding", description="SSH onboarding endpoints")
SSH_AUTH_PREFIX = "sk-ssh-service-"


def ssh_service_only(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return {"success": False, "error": "Missing SSH service token."}, 401
        token = auth_header[len("Bearer "):].strip()
        if not token.startswith(SSH_AUTH_PREFIX):
            return {"success": False, "error": "Invalid SSH service token."}, 401
        token = token[len(SSH_AUTH_PREFIX):].strip()
        try:
            token_tag = URLSafeTimedSerializer(DOJO_SSH_SERVICE_KEY).loads(token, max_age=300)
            assert token_tag == "ssh-onboarding"
        except Exception:
            return {"success": False, "error": "Failed to authenticate SSH service token."}, 401
        return func(*args, **kwargs)
    return wrapper


def offered_key_from_request(data):
    try:
        key = SSHKey(f"{data.get('key_type', '')} {data.get('key_base64', '')}", strict=True)
        key.parse()
        return f"{key.key_type.decode()} {base64.b64encode(key._decoded_key).decode()}", None
    except (InvalidKeyError, NotImplementedError) as error:
        return None, f"Invalid SSH key: {error}"


def validate_registration_request(data):
    errors = []
    name = data.get("name", "").strip()
    email_address = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    num_users_limit = int(get_config("num_users", default=0))
    num_users = Users.query.filter_by(banned=False, hidden=False).count()
    if num_users_limit and num_users >= num_users_limit:
        errors.append(f"Reached maximum users ({num_users_limit})")

    if not name:
        errors.append("Please provide a username")
    if Users.query.filter_by(name=name).first():
        errors.append("That username is already taken")
    if validators.validate_email(name):
        errors.append("Username cannot be an email address")

    if not validators.validate_email(email_address):
        errors.append("Please enter a valid email address")
    if Users.query.filter_by(email=email_address).first():
        errors.append("That email is already registered")
    if not email.check_email_is_whitelisted(email_address):
        errors.append("Email address is not from an allowed domain")

    if not password:
        errors.append("Please provide a password")
    if len(password) > 128:
        errors.append("Password is too long")

    if get_config("registration_code"):
        errors.append("SSH registration is not available while a registration code is required")

    return errors, name, email_address, password


@ssh_onboarding_namespace.route("/register")
class SSHRegister(Resource):
    @ssh_service_only
    def post(self):
        if not registration_visible():
            return {"success": False, "errors": ["Registration is currently disabled"]}, 403

        data = request.get_json() or {}
        key_value, key_error = offered_key_from_request(data)
        if key_error:
            return {"success": False, "errors": [key_error]}, 400

        errors, name, email_address, password = validate_registration_request(data)
        if errors:
            return {"success": False, "errors": errors}, 400

        user = Users(name=name, email=email_address, password=password)

        try:
            db.session.add(user)
            db.session.flush()
            db.session.add(SSHKeys(user_id=user.id, value=key_value))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return {"success": False, "errors": ["SSH key, username, or email is already in use"]}, 400

        if get_config("verify_emails") and can_send_mail():
            email.verify_email_address(user.email)
            verified = False
        else:
            user.verified = True
            db.session.commit()
            verified = True
            if can_send_mail():
                email.successful_registration_notification(user.email)

        return {
            "success": True,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "verified": verified,
            },
        }
