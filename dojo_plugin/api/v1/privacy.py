from flask import request
from flask_restx import Namespace, Resource
from CTFd.models import db
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

from ...models import UserPrivacySettings


privacy_namespace = Namespace(
    "privacy", description="Endpoint to manage users' privacy settings"
)


@privacy_namespace.route("")
class PrivacySettings(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        user = get_current_user()
        
        privacy_settings = UserPrivacySettings.get_or_create(user.id)
        
        privacy_settings.show_discord = data.get("show_discord", False)
        privacy_settings.show_activity = data.get("show_activity", False)
        privacy_settings.show_solve_data = data.get("show_solve_data", False)
        privacy_settings.show_username_in_activity = data.get("show_username_in_activity", False)
        
        db.session.commit()
        
        return {"success": True}