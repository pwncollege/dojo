import logging
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy import func

from CTFd.models import db, Solves, Users
from ...utils.background_stats import get_cached_stat, set_cached_stat, is_event_stale
from . import register_handler

logger = logging.getLogger(__name__)

def calculate_activity(user_id):
    now = datetime.utcnow()
    one_year_ago = now - timedelta(days=365)

    solves = (
        Solves.query
        .filter(Solves.user_id == user_id)
        .filter(Solves.date >= one_year_ago)
        .with_entities(Solves.date)
        .all()
    )

    timestamps = [solve.date.isoformat() + 'Z' for solve in solves if solve.date]

    return {
        'solve_timestamps': timestamps,
        'total_solves': len(timestamps),
    }

@register_handler("activity_update")
def handle_activity_update(payload, event_timestamp=None):
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("activity_update event missing user_id")
        return

    logger.info(f"Handling activity_update for user_id {user_id}")

    cache_key = f"stats:activity:{user_id}"
    if event_timestamp and is_event_stale(cache_key, event_timestamp):
        return

    db.session.expire_all()
    db.session.commit()

    user = Users.query.get(user_id)
    if not user:
        logger.info(f"User not found for user_id {user_id} (may have been deleted)")
        return

    try:
        logger.info(f"Calculating activity for user {user_id}...")
        activity = calculate_activity(user_id)
        set_cached_stat(cache_key, activity)
        logger.info(f"Successfully updated and cached activity for user {user_id} (total_solves: {activity['total_solves']})")
    except Exception as e:
        logger.error(f"Error calculating activity for user_id {user_id}: {e}", exc_info=True)


def update_activity(activity, solve_date=None):
    timestamps = list(activity.get('solve_timestamps', []))
    timestamp = (solve_date or datetime.utcnow()).isoformat() + 'Z'
    timestamps.append(timestamp)
    return {
        'solve_timestamps': timestamps,
        'total_solves': len(timestamps),
    }


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
    one_year_ago = datetime.utcnow() - timedelta(days=365)

    all_solves = (
        Solves.query
        .filter(Solves.date >= one_year_ago)
        .with_entities(Solves.user_id, Solves.date)
        .all()
    )

    user_timestamps = defaultdict(list)
    for user_id, date in all_solves:
        if date:
            user_timestamps[user_id].append(date.isoformat() + 'Z')

    logger.info(f"Initializing activity for {len(user_timestamps)} active users (batch mode)...")

    for user_id, timestamps in user_timestamps.items():
        activity = {
            'solve_timestamps': timestamps,
            'total_solves': len(timestamps),
        }
        cache_key = f"stats:activity:{user_id}"
        set_cached_stat(cache_key, activity)

    logger.info(f"Activity initialization complete for {len(user_timestamps)} users")
