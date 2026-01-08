import logging

from flask import g

from .background_stats import publish_stat_event

logger = logging.getLogger(__name__)


def publish_dojo_stats_event(dojo_id_int):
    publish_stat_event("dojo_stats_update", {"dojo_id": dojo_id_int})


def publish_scoreboard_event(model_type, model_id):
    publish_stat_event("scoreboard_update", {"model_type": model_type, "model_id": model_id})


def publish_scoreboard_solve_event(model_type, model_id, user_id):
    publish_stat_event("scoreboard_update_solve", {"model_type": model_type, "model_id": model_id, "user_id": user_id})


def publish_scores_event():
    publish_stat_event("scores_update", {})


def publish_belts_event():
    publish_stat_event("belts_update", {})


def publish_emojis_event():
    publish_stat_event("emojis_update", {})


def publish_activity_event(user_id):
    publish_stat_event("activity_update", {"user_id": user_id})


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
