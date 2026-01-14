from ...utils.workspace import authed_only_cli
from flask import session
from flask_restx import Namespace, Resource
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

user_namespace = Namespace(
    "user", description="User management endpoints"
)

@user_namespace.route("/me")
class CurrentUser(Resource):
    @authed_only_cli
    @authed_only
    def get(self):
        """Get current user information"""
        user = get_current_user()

        # Don't expose as much info to containers.
        if session.get("cli", False):
            return {
                "id":   -1            if user.hidden else user.id,
                "name": "Hidden User" if user.hidden else user.name,
            }

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