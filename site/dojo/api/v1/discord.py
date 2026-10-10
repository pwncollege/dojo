from flask_restx import Namespace, Resource

from ...utils.decorators import authed_only
from ...utils.user import get_current_user
from ...models import DiscordUsers, db


discord_namespace = Namespace("discord", description="Endpoint to manage Discord account links")


@discord_namespace.route("")
class Discord(Resource):
    @authed_only
    def delete(self):
        user = get_current_user()
        discord_user = DiscordUsers.query.filter_by(user=user).first()
        if discord_user:
            db.session.delete(discord_user)
            db.session.commit()
        return {"success": True}
