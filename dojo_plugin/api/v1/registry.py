from flask import request
from flask_restx import Namespace, Resource

from ...config import REGISTRY_API_SECRET
from CTFd.models import Users, Admins
from CTFd.utils.crypto import verify_password


registry_namespace = Namespace(
    "registry", description="Endpoint to support registry auth checks"
)


def auth_check(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        return {"success": False, "error": "Unauthorized"}, 401

    token = authorization.split(" ")[1]
    if not (REGISTRY_API_SECRET and token == REGISTRY_API_SECRET):
        return {"success": False, "error": "Unauthorized"}, 401

    return None, None


@registry_namespace.route("/verify")
class RegistryVerify(Resource):
    def post(self):
        authorization = request.headers.get("Authorization")
        res, code = auth_check(authorization)
        if res:
            return res, code

        data = request.get_json() or {}
        username = data.get("username")
        password = data.get("password")
        repository = data.get("repository")
        actions = data.get("actions") or []

        if not username or not password:
            return {"success": False, "error": "Missing credentials"}, 400

        user = Users.query.filter((Users.name == username) | (Users.email == username)).first()
        if not user or not verify_password(password, user.password):
            return {"success": False, "error": "Invalid credentials"}, 401

        if not repository:
            return {"success": True}


        repo_namespace = repository.split("/", 1)[0]

        requested = set(a.strip() for a in actions if a)
        allowed = set()

        if "push" in requested:
            if repo_namespace == user.name:
                allowed.add("push")
            else:
                return {
                    "success": False,
                    "error": (
                        f"Push denied: repository namespace '{repo_namespace}' does not match your username '{user.name}'. "
                        f"Tag the image as '{user.name}/<repo>' to push."
                    ),
                }, 403

        # Pull allowed for any authenticated user
        if "pull" in requested:
            allowed.add("pull")

        if not allowed and requested:
            return {"success": False, "error": "Not authorized for requested actions"}, 403

        return {"success": True, "allowed": sorted(allowed)}
