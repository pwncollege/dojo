import logging
from datetime import datetime, timedelta
from collections import defaultdict

from flask_restx import Namespace, Resource
from CTFd.models import db, Solves, Users

from ...utils.background_stats import get_cached_stat
from ...worker.handlers.activity import calculate_activity, initialize_activity_for_user

logger = logging.getLogger(__name__)

activity_namespace = Namespace("activity", description="User activity endpoints")

def get_activity_for_user(user_id):
    cache_key = f"stats:activity:{user_id}"
    cached = get_cached_stat(cache_key)

    if cached:
        logger.info(f"Returning cached activity for user {user_id}")
        return cached

    logger.info(f"Cache miss for activity user {user_id}, computing on-demand")
    activity = calculate_activity(user_id)
    initialize_activity_for_user(user_id)
    return activity

@activity_namespace.route("/<int:user_id>")
class UserActivity(Resource):
    def get(self, user_id):
        user = Users.query.get(user_id)
        if not user:
            return {"success": False, "error": "User not found"}, 404

        activity = get_activity_for_user(user_id)

        return {
            "success": True,
            "data": activity
        }
