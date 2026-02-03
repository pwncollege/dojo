from flask_restx import Namespace, Resource
from flask import current_app, request, session
from itsdangerous.url_safe import URLSafeTimedSerializer
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user
from CTFd.models import Users
from ...utils import get_current_container

user_namespace = Namespace("user", description="User management endpoints")
CLI_AUTH_PREFIX = "sk-workspace-local-"


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
