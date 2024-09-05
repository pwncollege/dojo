import hmac

from flask import request
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import db
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

from ...config import DISCORD_CLIENT_SECRET
from ...models import DiscordUsers
from ...utils.discord import get_discord_member
from ...utils.dojo import get_current_dojo_challenge


discord_namespace = Namespace("discord", description="Endpoint to manage discord")


@discord_namespace.route("")
class Discord(Resource):
    @authed_only
    def delete(self):
        user = get_current_user()
        DiscordUsers.query.filter_by(user=user).delete()
        db.session.commit()
        cache.delete_memoized(get_discord_member, user.id)
        return {"success": True}


@discord_namespace.route("/activity/<discord_id>")
class DiscordActivity(Resource):
    def get(self, discord_id):
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            return {"success": False, "error": "Unauthorized"}, 401

        token = authorization.split(" ")[1]
        if not hmac.compare_digest(token, DISCORD_CLIENT_SECRET):
            return {"success": False, "error": "Unauthorized"}, 401

        discord_user = DiscordUsers.query.filter_by(discord_id=discord_id).first()
        if not discord_user:
            return {"success": False, "error": "Discord user not found"}, 404

        dojo_challenge = get_current_dojo_challenge(discord_user.user)
        if not dojo_challenge:
            return {"success": True, "activity": None}

        dojo_challenge = dojo_challenge.resolve()
        activity = {
            "challenge": {
                "dojo": dojo_challenge.dojo.name,
                "module": dojo_challenge.module.name,
                "challenge": dojo_challenge.name,
                "description": dojo_challenge.description,
                "reference_id": dojo_challenge.reference_id,
            }
        }

        return {"success": True, "activity": activity}
