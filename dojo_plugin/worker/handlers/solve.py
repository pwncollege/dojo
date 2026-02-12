import logging
from datetime import datetime

from CTFd.models import db
from ...models import DojoChallenges
from ...utils.background_stats import get_cached_stat, set_cached_stat, is_event_stale
from . import register_handler
from .scoreboard import update_scoreboard, update_challenge_solves, challenge_solves_cache_key, COMMON_DURATIONS
from .dojo_stats import update_dojo_stats
from .scores import update_dojo_scores, update_module_scores, dojo_scores_cache_key, module_scores_cache_key
from .activity import update_activity

logger = logging.getLogger(__name__)


@register_handler("challenge_solve")
def handle_challenge_solve(payload, event_timestamp):
    user_id = payload.get("user_id")
    challenge_id = payload.get("challenge_id")
    solve_date_str = payload.get("solve_date")

    if user_id is None or challenge_id is None:
        logger.warning(f"challenge_solve event missing required fields: {payload}")
        return

    solve_date = None
    if solve_date_str:
        solve_date = datetime.fromisoformat(solve_date_str.rstrip('Z'))

    logger.info(f"Handling challenge_solve for user_id={user_id}, challenge_id={challenge_id}")

    db.session.expire_all()
    db.session.commit()

    dojo_challenges = DojoChallenges.query.filter_by(challenge_id=challenge_id).all()
    logger.info(f"Found {len(dojo_challenges)} dojo(s) containing challenge_id={challenge_id}")

    for dojo_challenge in dojo_challenges:
        dojo = dojo_challenge.dojo
        dojo_id = dojo.dojo_id
        dojo_ref_id = dojo.reference_id
        module_index = dojo_challenge.module.module_index
        challenge_name = dojo_challenge.name

        is_member = dojo.is_member(user_id)
        is_public_or_official = dojo.is_public_or_official

        if is_member:
            logger.info(f"Updating dojo scoreboard for dojo {dojo_ref_id}")
            _update_dojo_scoreboard(dojo_id, user_id, event_timestamp)
            logger.info(f"Updating module scoreboard for dojo {dojo_ref_id} module {module_index}")
            _update_module_scoreboard(dojo_id, module_index, user_id, event_timestamp)
            logger.info(f"Updating dojo stats for dojo {dojo_ref_id}")
            _update_dojo_stats(dojo_ref_id, challenge_name, event_timestamp)
            logger.info(f"Updating challenge solves for dojo {dojo_ref_id} module {module_index}")
            _update_challenge_solves(dojo_id, module_index, challenge_id, event_timestamp)
        else:
            logger.info(f"User {user_id} is not a member of dojo {dojo_ref_id}, skipping scoreboard/stats updates")

        if is_public_or_official:
            logger.info(f"Updating scores for dojo {dojo_ref_id}")
            _update_scores(dojo_id, module_index, user_id, event_timestamp)
        else:
            logger.info(f"Dojo {dojo_ref_id} is not public or official, skipping scores update")

    logger.info(f"Updating activity for user {user_id}")
    _update_user_activity(user_id, solve_date, event_timestamp)
    logger.info(f"Completed challenge_solve for user_id={user_id}, challenge_id={challenge_id}")


def _update_dojo_scoreboard(dojo_id, user_id, event_timestamp):
    cache_prefix = f"stats:scoreboard:dojo:{dojo_id}"
    for duration in COMMON_DURATIONS:
        try:
            cache_key = f"{cache_prefix}:{duration}"
            if is_event_stale(cache_key, event_timestamp):
                continue
            current_scoreboard = get_cached_stat(cache_key) or []
            updated_scoreboard = update_scoreboard(current_scoreboard, user_id)
            set_cached_stat(cache_key, updated_scoreboard, updated_at=event_timestamp)
        except Exception as e:
            logger.error(f"Error updating dojo scoreboard for dojo {dojo_id}, duration={duration}: {e}", exc_info=True)


def _update_module_scoreboard(dojo_id, module_index, user_id, event_timestamp):
    cache_prefix = f"stats:scoreboard:module:{dojo_id}:{module_index}"
    for duration in COMMON_DURATIONS:
        try:
            cache_key = f"{cache_prefix}:{duration}"
            if is_event_stale(cache_key, event_timestamp):
                continue
            current_scoreboard = get_cached_stat(cache_key) or []
            updated_scoreboard = update_scoreboard(current_scoreboard, user_id)
            set_cached_stat(cache_key, updated_scoreboard, updated_at=event_timestamp)
        except Exception as e:
            logger.error(f"Error updating module scoreboard for dojo {dojo_id} module {module_index}, duration={duration}: {e}", exc_info=True)


def _update_dojo_stats(dojo_ref_id, challenge_name, event_timestamp):
    cache_key = f"stats:dojo:{dojo_ref_id}"
    if is_event_stale(cache_key, event_timestamp):
        return
    current_stats = get_cached_stat(cache_key)
    if not current_stats:
        logger.info(f"No cached stats for dojo {dojo_ref_id}, skipping incremental update")
        return
    try:
        updated_stats = update_dojo_stats(current_stats, challenge_name)
        set_cached_stat(cache_key, updated_stats, updated_at=event_timestamp)
    except Exception as e:
        logger.error(f"Error updating dojo stats for {dojo_ref_id}: {e}", exc_info=True)


def _update_challenge_solves(dojo_id, module_index, challenge_id, event_timestamp):
    cache_key = challenge_solves_cache_key(dojo_id, module_index)
    if is_event_stale(cache_key, event_timestamp):
        return
    current = get_cached_stat(cache_key)
    if not current:
        logger.info(f"No cached challenge_solves for dojo {dojo_id} module {module_index}, skipping incremental update")
        return
    try:
        updated = update_challenge_solves(current, challenge_id)
        set_cached_stat(cache_key, updated, updated_at=event_timestamp)
    except Exception as e:
        logger.error(f"Error updating challenge_solves for dojo {dojo_id} module {module_index}: {e}", exc_info=True)


def _update_scores(dojo_id, module_index, user_id, event_timestamp):
    logger.info(f"Updating dojo scores for dojo_id={dojo_id}, user_id={user_id}")
    try:
        cache_key = dojo_scores_cache_key(dojo_id)
        if not is_event_stale(cache_key, event_timestamp):
            current_scores = get_cached_stat(cache_key) or {"ranks": [], "solves": {}}
            updated_scores = update_dojo_scores(current_scores, user_id)
            set_cached_stat(cache_key, updated_scores, updated_at=event_timestamp)
    except Exception as e:
        logger.error(f"Error updating dojo scores: {e}", exc_info=True)

    logger.info(f"Updating module scores for dojo_id={dojo_id}, module_index={module_index}, user_id={user_id}")
    try:
        cache_key = module_scores_cache_key(dojo_id, module_index)
        if not is_event_stale(cache_key, event_timestamp):
            current_scores = get_cached_stat(cache_key) or {"ranks": [], "solves": {}}
            updated_scores = update_module_scores(current_scores, user_id)
            set_cached_stat(cache_key, updated_scores, updated_at=event_timestamp)
    except Exception as e:
        logger.error(f"Error updating module scores: {e}", exc_info=True)


def _update_user_activity(user_id, solve_date, event_timestamp):
    cache_key = f"stats:activity:{user_id}"
    if is_event_stale(cache_key, event_timestamp):
        return
    current_activity = get_cached_stat(cache_key) or {'solve_timestamps': [], 'total_solves': 0}
    try:
        updated_activity = update_activity(current_activity, solve_date)
        set_cached_stat(cache_key, updated_activity, updated_at=event_timestamp)
    except Exception as e:
        logger.error(f"Error updating activity for user_id {user_id}: {e}", exc_info=True)
