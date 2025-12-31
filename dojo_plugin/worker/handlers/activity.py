import logging
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import func

from CTFd.models import db, Solves, Users
from ...utils.background_stats import set_cached_stat
from . import register_handler

logger = logging.getLogger(__name__)

def calculate_activity(user_id):
    now = datetime.now()
    one_year_ago = now - timedelta(days=365)

    solves = (
        Solves.query
        .filter(Solves.user_id == user_id)
        .filter(Solves.date >= one_year_ago)
        .with_entities(Solves.date)
        .all()
    )

    daily_counts = defaultdict(int)
    for solve in solves:
        if solve.date:
            date_str = solve.date.strftime('%Y-%m-%d')
            daily_counts[date_str] += 1

    return {
        'daily_solves': dict(daily_counts),
        'total_solves': len(solves),
    }

@register_handler("activity_update")
def handle_activity_update(payload):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("activity_update event missing user_id")
        return

    logger.info(f"Handling activity_update for user_id {user_id}")

    db.session.expire_all()
    db.session.commit()

    user = Users.query.get(user_id)
    if not user:
        logger.info(f"User not found for user_id {user_id} (may have been deleted)")
        return

    try:
        logger.info(f"Calculating activity for user {user_id}...")
        activity = calculate_activity(user_id)
        cache_key = f"stats:activity:{user_id}"
        set_cached_stat(cache_key, activity)
        logger.info(f"Successfully updated and cached activity for user {user_id} (total_solves: {activity['total_solves']})")
    except Exception as e:
        logger.error(f"Error calculating activity for user_id {user_id}: {e}", exc_info=True)

def initialize_activity_for_user(user_id):
    try:
        activity = calculate_activity(user_id)
        cache_key = f"stats:activity:{user_id}"
        set_cached_stat(cache_key, activity)
        return True
    except Exception as e:
        logger.error(f"Error initializing activity for user {user_id}: {e}", exc_info=True)
        return False

def initialize_all_activity():
    db.session.expire_all()
    db.session.commit()

    one_year_ago = datetime.now() - timedelta(days=365)
    active_user_ids = (
        Solves.query
        .filter(Solves.date >= one_year_ago)
        .with_entities(func.distinct(Solves.user_id))
        .all()
    )
    user_ids = [uid[0] for uid in active_user_ids]

    logger.info(f"Initializing activity for {len(user_ids)} active users...")

    for user_id in user_ids:
        initialize_activity_for_user(user_id)

    logger.info(f"Activity initialization complete for {len(user_ids)} users")
