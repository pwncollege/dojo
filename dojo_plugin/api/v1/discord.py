from flask_restx import Namespace, Resource
from CTFd.models import db
from CTFd.utils.user import get_current_user

from ...models import DiscordUsers


discord_namespace = Namespace("discord", description="Endpoint to manage discord")


@discord_namespace.route("")
class Discord(Resource):
    def delete(self):
        DiscordUsers.query.filter_by(user=get_current_user()).delete()
        db.session.commit()
        return {"success": True}
