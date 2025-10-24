from flask import request
from flask_restx import Namespace, Resource

from ...utils.awards import grant_event_award

from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

event_namespace = Namespace(
    "event", description="Endpoint to manage events"
)

@event_namespace.route("/grant")
class GrantAward(Resource):
    @authed_only
    def post(self):
        user = get_current_user()
        data = request.get_json()
        event = data.get("event")
        place = data.get("place")
        result = grant_event_award(user, event, place)
        return ({"success": result}, 200)

