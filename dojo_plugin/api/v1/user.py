import datetime

from flask_restx import Namespace, Resource
from flask import current_app, request, session
from itsdangerous.url_safe import URLSafeTimedSerializer
from ...models import Tokens, Users, db, get_config, verify_password
from ...utils.countries import lookup_country_code
from ...utils.decorators import authed_only, require_verified_emails
from ...utils.email import check_email_is_whitelisted
from ...utils.user import get_current_user, is_admin, update_user
from ...utils.validators import validate_email, validate_url
from ...config import DOJO_SSH_SERVICE_KEY
from ...utils import generate_user_token, get_current_container, iso_utc

user_namespace = Namespace("user", description="User management endpoints")
CLI_AUTH_PREFIX = "sk-workspace-local-"
SSH_AUTH_PREFIX = "sk-ssh-service-"
SELF_FIELDS = ("name", "email", "password", "website", "affiliation", "country", "hidden")
TRUTHY = {"t", "T", "true", "True", "TRUE", "1", 1, True}
FALSY = {"f", "F", "false", "False", "FALSE", "0", 0, False}

def authed_only_ssh(func):
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return func(*args, **kwargs)
        if not auth_header.startswith("Bearer "):
            return func(*args, **kwargs)
        token = auth_header[len("Bearer "):].strip()
        if not token.startswith(SSH_AUTH_PREFIX):
            return func(*args, **kwargs)
        token = token[len(SSH_AUTH_PREFIX):].strip()
        try:
            user_id, token_tag = URLSafeTimedSerializer(DOJO_SSH_SERVICE_KEY).loads(token, max_age=300)
            assert token_tag == "ssh-tui"
        except Exception:
            return {"success": False, "error": "Failed to authenticate ssh service token."}, 401
        user = Users.query.filter_by(id=user_id).first()
        if not user:
            return {"success": False, "error": "User not found."}, 404
        try:
            session.update({
                "id": user.id,
                "name": user.name,
                "type": user.type,
                "verified": user.verified,
            })
            return func(*args, **kwargs)
        finally:
            for k in ("id", "name", "type", "verified"):
                session.pop(k, None)
        return func(*args, **kwargs)
    return wrapper


def authed_only_cli(func):
    """Allows an endpoint to be used by the dojo cli application."""
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return func(*args, **kwargs)
        if not auth_header.startswith("Bearer "):
            return func(*args, **kwargs)
        token = auth_header[len("Bearer "):].strip()
        if not token.startswith(CLI_AUTH_PREFIX):
            return func(*args, **kwargs)
        token = token[len(CLI_AUTH_PREFIX):].strip()
        try:
            user_id, challenge_id, token_tag = URLSafeTimedSerializer(
                current_app.config["SECRET_KEY"]
            ).loads(token, max_age=21600)
            assert token_tag == "cli-auth-token"
        except Exception:
            return {"success": False, "error": "Failed to authenticate container token."}, 401
        user = Users.query.filter_by(id=user_id).one()
        container = get_current_container(user)
        if container is None:
            return {"success": False, "error": "No active challenge container."}, 403
        if container.labels["dojo.challenge_id"] != challenge_id:
            return {"success": False, "error": "Token failed to authenticate active challenge container."}, 403
        try:
            session.update({
                "id": user.id,
                "name": user.name,
                "type": user.type,
                "verified": user.verified,
            })
            return func(*args, **kwargs)
        finally:
            for key in ("id", "name", "type", "verified"):
                session.pop(key, None)
    return wrapper


def validate_self_patch(user, data):
    confirm = data.get("confirm")
    email = data.get("email")
    if email is not None and not (user.email and email.strip().lower() == user.email.lower()):
        if is_admin():
            pass
        elif not confirm:
            return {"confirm": ["Please confirm your current password"]}
        elif not verify_password(confirm, user.password):
            return {"confirm": ["Your previous password is incorrect"]}
        if Users.query.filter_by(email=email.strip()).first():
            return {"email": ["Email address has already been used"]}
        if not is_admin() and not check_email_is_whitelisted(email.strip()):
            return {"email": ["Email address is not from an allowed domain"]}
        if get_config("verify_emails"):
            user.verified = False
    name = data.get("name")
    if name is not None and name.strip() != user.name:
        if not is_admin() and get_config("name_changes", default=True) is False:
            return {"name": ["Name changes are disabled"]}
        if Users.query.filter_by(name=name.strip()).first():
            return {"name": ["User name has already been taken"]}
    if data.get("password") and not is_admin():
        if not confirm:
            return {"confirm": ["Please confirm your current password"]}
        if not verify_password(confirm, user.password):
            return {"confirm": ["Your previous password is incorrect"]}
    errors = {}
    for key, value in data.items():
        if key not in SELF_FIELDS or value is None:
            continue
        if key == "hidden":
            if not isinstance(value, (bool, int, str)) or (value not in TRUTHY and value not in FALSY):
                errors[key] = ["Not a valid boolean."]
        elif not isinstance(value, str):
            errors[key] = ["Not a valid string."]
        elif key == "name" and not 1 <= len(value) <= 128:
            errors[key] = ["User names must not be empty"]
        elif key == "email" and not (validate_email(value) and len(value) <= 128):
            errors[key] = ["Emails must be a properly formatted email address"]
        elif key == "website" and value and not validate_url(value):
            errors[key] = ["Websites must be a proper URL starting with http or https"]
        elif key == "country" and value.strip() and lookup_country_code(value) is None:
            errors[key] = ["Invalid Country"]
        elif key in ("affiliation", "password") and len(value) > 128:
            errors[key] = ["Longer than maximum length 128."]
    return errors


@user_namespace.route("/me")
class CurrentUser(Resource):
    @authed_only_cli
    @authed_only
    def get(self):
        """Get current user information"""
        user = get_current_user()
        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "website": user.website,
            "affiliation": user.affiliation,
            "country": user.country,
            "bracket": user.bracket,
            "hidden": user.hidden,
            "banned": user.banned,
            "verified": user.verified,
            "admin": user.type == "admin"
        }

    @authed_only
    def patch(self):
        user = get_current_user()
        data = request.get_json()
        if not isinstance(data, dict):
            return {"success": False, "errors": {"_schema": ["Invalid input type."]}}, 400
        errors = validate_self_patch(user, data)
        if errors:
            return {"success": False, "errors": errors}, 400
        for key in SELF_FIELDS:
            value = data.get(key)
            if value is None or (key == "password" and not value):
                continue
            setattr(user, key, value in TRUTHY if key == "hidden" else value)
        db.session.commit()
        update_user(user)
        response = {key: getattr(user, key) for key in
                    ("id", "name", "email", "website", "affiliation", "country", "bracket", "oauth_id", "hidden")}
        db.session.close()
        return {"success": True, "data": response}


@user_namespace.route("/me/awards")
class CurrentUserAwards(Resource):
    @authed_only
    def get(self):
        data = [{"id": award.id, "user_id": award.user_id, "name": award.name, "description": award.description,
                 "value": award.value, "category": award.category, "icon": award.icon, "date": iso_utc(award.date)}
                for award in get_current_user().awards]
        return {"success": True, "data": data}


@user_namespace.route("/me/tokens")
class CurrentUserTokens(Resource):
    @require_verified_emails
    @authed_only
    def post(self):
        expiration = (request.get_json(silent=True) or {}).get("expiration") or None
        if expiration:
            expiration = datetime.datetime.strptime(expiration, "%Y-%m-%d")
        token = generate_user_token(get_current_user(), expiration=expiration)
        return {"success": True, "data": {"id": token.id, "created": iso_utc(token.created),
                                          "expiration": iso_utc(token.expiration), "value": token.value}}


@user_namespace.route("/me/tokens/<int:token_id>")
class CurrentUserToken(Resource):
    @require_verified_emails
    @authed_only
    def delete(self, token_id):
        token = Tokens.query.filter_by(id=token_id, user_id=get_current_user().id).first_or_404()
        db.session.delete(token)
        db.session.commit()
        return {"success": True}
