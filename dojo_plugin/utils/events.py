import logging
from datetime import datetime, timedelta

from flask import g
from CTFd.models import db
from sqlalchemy import or_

from .background_stats import publish_stat_event

logger = logging.getLogger(__name__)


def publish_dojo_stats_event(dojo_id_int):
    publish_stat_event("dojo_stats_update", {"dojo_id": dojo_id_int})


def publish_scoreboard_event(model_type, model_id):
    publish_stat_event("scoreboard_update", {"model_type": model_type, "model_id": model_id})


def publish_scores_event(dojo_id=None):
    payload = {"dojo_id": dojo_id} if dojo_id is not None else {}
    publish_stat_event("scores_update", payload)


def publish_belts_event():
    publish_stat_event("belts_update", {})


def publish_emojis_event():
    publish_stat_event("emojis_update", {})


def publish_activity_event(user_id):
    publish_stat_event("activity_update", {"user_id": user_id})


def publish_challenge_solve_event(user_id, challenge_id, solve_date=None):
    from ..models import UserVisibilityUpdates

    payload = {"user_id": user_id, "challenge_id": challenge_id}
    if solve_date:
        payload["solve_date"] = solve_date.isoformat() + 'Z'
    transition = UserVisibilityUpdates.query.filter_by(user_id=user_id).first()
    if transition is not None:
        payload["visibility_transition"] = transition.token
    publish_stat_event("challenge_solve", payload)


def publish_user_visibility_event(user_id, token):
    return publish_stat_event(
        "user_visibility_update",
        {"user_id": user_id, "token": token},
    )


def queue_stat_event(event_func):
    if not hasattr(g, '_pending_stat_events'):
        g._pending_stat_events = []
    g._pending_stat_events.append(event_func)


def publish_queued_events():
    if hasattr(g, '_pending_stat_events'):
        count = len(g._pending_stat_events)
        if count > 0:
            logger.info(f"Publishing {count} queued stat events after request")
        for event_func in g._pending_stat_events:
            event_func()
        g._pending_stat_events = []


def publish_pending_user_visibility_events():
    from ..models import UserVisibilityUpdates
    from .background_stats import invalidate_public_cached_stats
    from .feed import remove_user_events
    from .public_stats import affected_public_cache_keys

    table = UserVisibilityUpdates.__table__
    try:
        with db.engine.begin() as connection:
            transitions = connection.execute(
                db.select([table.c.user_id, table.c.token])
                .where(
                    or_(
                        table.c.published_at.is_(None),
                        table.c.published_at < datetime.utcnow() - timedelta(minutes=1),
                    )
                )
                .with_for_update(skip_locked=True)
            ).all()
            for user_id, token in transitions:
                invalidated = invalidate_public_cached_stats(
                    affected_public_cache_keys(connection, user_id)
                )
                purged = remove_user_events(user_id)
                if (
                    invalidated
                    and purged
                    and publish_user_visibility_event(user_id, token) is not None
                ):
                    connection.execute(
                        table.update()
                        .where(
                            table.c.user_id == user_id,
                            table.c.token == token,
                        )
                        .values(published_at=datetime.utcnow())
                    )
    except Exception as error:
        logger.error(
            f"Failed to publish pending user visibility events: {error}",
            exc_info=True,
        )
