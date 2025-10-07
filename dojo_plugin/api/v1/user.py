from flask_restx import Namespace, Resource
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

user_namespace = Namespace(
    "user", description="User management endpoints"
)

@user_namespace.route("/me")
class CurrentUser(Resource):
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