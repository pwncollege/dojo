from flask import request
from flask_restx import Namespace, Resource

import re

from ...config import REGISTRY_API_SECRET
from ...models import Dojos, DojoAdmins
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


        is_global_admin = Admins.query.filter_by(id=user.id).first() is not None

        if not repository:
            return {"success": True}


        m = re.match(r"^(?P<dojo_id>[a-z0-9][a-z0-9-]*)-(?P<dojo_hex>[0-9a-f]{8})(?:/.*)?$", repository)
        if not m:
            return {
                "success": False,
                "error": "Invalid repository format. Reference ID looks like '<dojo_name>~<dojoid>' Check the admin page; use this format '<dojo_name>-<dojoid>/yourimage' as the repo name"
            }, 403

        dojo_name = m.group("dojo_id")
        dojo_hex = m.group("dojo_hex")

        dojo = Dojos.from_id(f"{dojo_name}~{dojo_hex}").first()
        if not dojo:
            return {"success": False, "error": "Dojo not found for provided reference id"}, 403

        requested = set(a.strip() for a in actions if a)
        allowed = set()

        if "pull" in requested:
            allowed.add("pull")

        if "push" in requested:
            if is_global_admin or DojoAdmins.query.filter_by(dojo=dojo, user_id=user.id).first() is not None:
                allowed.add("push")

        if not allowed and requested:
            return {"success": False, "error": "Not authorized for requested actions"}, 403

        return {"success": True, "allowed": sorted(allowed)}
