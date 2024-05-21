from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import db
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

from ...models import DiscordUsers
from ...utils.discord import get_discord_user


discord_namespace = Namespace("discord", description="Endpoint to manage discord")


@discord_namespace.route("")
class Discord(Resource):
    @authed_only
    def delete(self):
        user = get_current_user()
        DiscordUsers.query.filter_by(user=user).delete()
        db.session.commit()
        cache.delete_memoized(get_discord_user, user.id)
        return {"success": True}
