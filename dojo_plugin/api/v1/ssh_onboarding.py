import datetime
import secrets
from functools import wraps

from flask import request, session, url_for
from flask_restx import Namespace, Resource
from itsdangerous.url_safe import URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from CTFd.models import Users, UserFieldEntries, UserFields, db
from CTFd.utils import email, get_config, validators
from CTFd.utils.config import can_send_mail
from CTFd.utils.config.visibility import registration_visible
from CTFd.utils.validators import ValidationError

from ...config import DOJO_HOST, DOJO_SSH_SERVICE_KEY
from ...models import SSHKeyLinkRequests, SSHKeys
from ...utils.ssh_key import InvalidKeyError, normalize_offered_ssh_key
from ...utils.ssh_onboarding import ssh_link_token_digest


ssh_onboarding_namespace = Namespace("ssh_onboarding", description="SSH onboarding endpoints")
SSH_AUTH_PREFIX = "sk-ssh-service-"
LINK_TTL = datetime.timedelta(minutes=15)


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
        return normalize_offered_ssh_key(data.get("key_type", ""), data.get("key_base64", "")), None
    except (InvalidKeyError, NotImplementedError) as error:
        return None, f"Invalid SSH key: {error}"


def validate_registration_request(data):
    errors = []
    name = data.get("name", "").strip()
    email_address = data.get("email", "").strip().lower()

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

    if get_config("registration_code"):
        errors.append("SSH registration is not available while a registration code is required")

    fields = {}
    for field in UserFields.query.all():
        field_value = data.get(f"fields[{field.id}]", "").strip()
        if field.required and not field_value:
            errors.append(f"Field '{field.name}' is required")
        fields[field.id] = field_value

    affiliation = data.get("affiliation")
    if affiliation and len(affiliation) > 128:
        errors.append("Affiliation is too long")

    website = data.get("website")
    if website and not validators.validate_url(website):
        errors.append("Website must be a valid URL")

    country = data.get("country")
    if country:
        try:
            validators.validate_country_code(country)
        except ValidationError:
            errors.append("Invalid country")

    return errors, name, email_address, fields


def link_url(token):
    host = DOJO_HOST or request.host
    scheme = "http" if host.startswith("localhost") or host.startswith("127.") else "https"
    return f"{scheme}://{host}{url_for('pwncollege_ssh_key.link_ssh_key', token=token)}"


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

        errors, name, email_address, fields = validate_registration_request(data)
        if errors:
            return {"success": False, "errors": errors}, 400

        user = Users(name=name, email=email_address, password=secrets.token_urlsafe(48))
        for attribute in ("website", "affiliation", "country"):
            if data.get(attribute):
                setattr(user, attribute, data[attribute])

        try:
            db.session.add(user)
            db.session.flush()
            db.session.add(SSHKeys(user_id=user.id, value=key_value))
            for field_id, value in fields.items():
                db.session.add(UserFieldEntries(field_id=field_id, value=value, user_id=user.id))
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

        session.clear()
        return {
            "success": True,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "verified": verified,
            },
        }


@ssh_onboarding_namespace.route("/link_requests")
class SSHLinkRequests(Resource):
    @ssh_service_only
    def post(self):
        data = request.get_json() or {}
        key_value, key_error = offered_key_from_request(data)
        if key_error:
            return {"success": False, "error": key_error}, 400
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


@ssh_onboarding_namespace.route("/link_requests/<token>/status")
class SSHLinkRequestStatus(Resource):
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
