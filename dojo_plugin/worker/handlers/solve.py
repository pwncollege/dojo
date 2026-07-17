import logging
from datetime import datetime

from CTFd.models import db, Users
from ...models import DojoChallenges, UserVisibilityUpdates
from ...utils.background_stats import (
    get_cached_stat,
    get_public_cached_stat,
    set_cached_stat,
    set_public_cached_stat,
    is_event_stale,
)
from ...utils.public_stats import capture_public_cache_revisions
from . import register_handler
from .scoreboard import (
    COMMON_DURATIONS,
    challenge_solves_cache_key,
    handle_scoreboard_update,
    update_challenge_solves,
    update_scoreboard_cache,
)
from .dojo_stats import handle_dojo_stats_update, update_dojo_stats
from .scores import (
    dojo_scores_cache_key,
    handle_scores_update,
    module_scores_cache_key,
    update_dojo_scores,
    update_module_scores,
)
from .activity import update_activity

logger = logging.getLogger(__name__)


def challenge_solve_public_cache_keys(dojo_challenges):
    keys = set()
    for dojo_challenge in dojo_challenges:
        dojo = dojo_challenge.dojo
        dojo_id = dojo.dojo_id
        module_index = dojo_challenge.module.module_index
        if dojo_challenge.required:
            keys.add(f"stats:dojo:{dojo.reference_id}")
            keys.add(challenge_solves_cache_key(dojo_id, module_index))
            for duration in COMMON_DURATIONS:
                dojo_key = f"stats:scoreboard:dojo:{dojo_id}:{duration}"
                module_key = (
                    f"stats:scoreboard:module:{dojo_id}:{module_index}:{duration}"
                )
                keys.update(
                    {
                        dojo_key,
                        dojo_key.replace("stats:scoreboard:", "stats:crews:", 1),
                        module_key,
                        module_key.replace("stats:scoreboard:", "stats:crews:", 1),
                    }
                )
        if dojo.is_public_or_official:
            keys.add(dojo_scores_cache_key(dojo_id))
            keys.add(module_scores_cache_key(dojo_id, module_index))
    return keys


def rebuild_challenge_public_stats(dojo_challenges):
    modules_by_dojo = {}
    for dojo_challenge in dojo_challenges:
        modules_by_dojo.setdefault(dojo_challenge.dojo_id, set()).add(
            dojo_challenge.module_index
        )

    for dojo_id, module_indices in modules_by_dojo.items():
        dojo = next(
            dojo_challenge.dojo
            for dojo_challenge in dojo_challenges
            if dojo_challenge.dojo_id == dojo_id
        )
        handle_dojo_stats_update({"dojo_id": dojo_id})
        handle_scoreboard_update({"model_type": "dojo", "model_id": dojo_id})
        for module_index in module_indices:
            handle_scoreboard_update(
                {
                    "model_type": "module",
                    "model_id": {
                        "dojo_id": dojo_id,
                        "module_index": module_index,
                    },
                }
            )
        if dojo.is_public_or_official:
            handle_scores_update({"dojo_id": dojo_id})


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
    user = Users.query.populate_existing().filter_by(id=user_id).first()
    pending_transition = UserVisibilityUpdates.query.filter_by(
        user_id=user_id
    ).first()
    publish_public_stats = (
        user is not None
        and not user.hidden
        and not user.banned
        and pending_transition is None
    )

    if payload.get("visibility_transition") is not None:
        if publish_public_stats:
            rebuild_challenge_public_stats(dojo_challenges)
        _update_user_activity(user_id, solve_date, event_timestamp)
        return

    if not publish_public_stats:
        _update_user_activity(user_id, solve_date, event_timestamp)
        return

    cache_keys = challenge_solve_public_cache_keys(dojo_challenges)
    revisions = capture_public_cache_revisions(cache_keys)
    if any(get_public_cached_stat(cache_key) is None for cache_key in cache_keys):
        logger.info(
            "Public challenge caches are incomplete; rebuilding exact stats "
            f"for challenge_id={challenge_id}"
        )
        rebuild_challenge_public_stats(dojo_challenges)
        _update_user_activity(user_id, solve_date, event_timestamp)
        return

    for dojo_challenge in dojo_challenges:
        dojo = dojo_challenge.dojo
        dojo_id = dojo.dojo_id
        dojo_ref_id = dojo.reference_id
        module_index = dojo_challenge.module.module_index
        challenge_name = dojo_challenge.name

        is_member = dojo.is_member(user_id)
        is_public_or_official = dojo.is_public_or_official

        if publish_public_stats and is_member and dojo_challenge.required:
            logger.info(f"Updating dojo scoreboard for dojo {dojo_ref_id}")
            _update_dojo_scoreboard(
                dojo,
                user_id,
                challenge_id,
                event_timestamp,
                revisions,
            )
            logger.info(f"Updating module scoreboard for dojo {dojo_ref_id} module {module_index}")
            _update_module_scoreboard(
                dojo_challenge.module,
                user_id,
                challenge_id,
                event_timestamp,
                revisions,
            )
            logger.info(f"Updating dojo stats for dojo {dojo_ref_id}")
            _update_dojo_stats(
                dojo_ref_id,
                challenge_name,
                event_timestamp,
                revisions,
            )
            logger.info(f"Updating challenge solves for dojo {dojo_ref_id} module {module_index}")
            _update_challenge_solves(
                dojo_id,
                module_index,
                challenge_id,
                event_timestamp,
                revisions,
            )
        else:
            logger.info(f"User {user_id} is not public or not a member of dojo {dojo_ref_id}, skipping scoreboard/stats updates")

        if publish_public_stats and is_public_or_official:
            logger.info(f"Updating scores for dojo {dojo_ref_id}")
            _update_scores(
                dojo_id,
                module_index,
                user_id,
                event_timestamp,
                revisions,
            )
        else:
            logger.info(f"Dojo {dojo_ref_id} is not public or official, skipping scores update")

    logger.info(f"Updating activity for user {user_id}")
    _update_user_activity(user_id, solve_date, event_timestamp)
    logger.info(f"Completed challenge_solve for user_id={user_id}, challenge_id={challenge_id}")


def _update_dojo_scoreboard(
    dojo,
    user_id,
    challenge_id,
    event_timestamp,
    revisions,
):
    cache_prefix = f"stats:scoreboard:dojo:{dojo.dojo_id}"
    for duration in COMMON_DURATIONS:
        try:
            cache_key = f"{cache_prefix}:{duration}"
            if is_event_stale(cache_key, event_timestamp):
                continue
            crews_key = cache_key.replace("stats:scoreboard:", "stats:crews:", 1)
            update_scoreboard_cache(
                dojo,
                cache_key,
                user_id,
                challenge_id,
                revisions={
                    cache_key: revisions[cache_key],
                    crews_key: revisions[crews_key],
                },
            )
        except Exception as e:
            logger.error(f"Error updating dojo scoreboard for dojo {dojo.dojo_id}, duration={duration}: {e}", exc_info=True)


def _update_module_scoreboard(
    module,
    user_id,
    challenge_id,
    event_timestamp,
    revisions,
):
    cache_prefix = f"stats:scoreboard:module:{module.dojo_id}:{module.module_index}"
    for duration in COMMON_DURATIONS:
        try:
            cache_key = f"{cache_prefix}:{duration}"
            if is_event_stale(cache_key, event_timestamp):
                continue
            crews_key = cache_key.replace("stats:scoreboard:", "stats:crews:", 1)
            update_scoreboard_cache(
                module,
                cache_key,
                user_id,
                challenge_id,
                revisions={
                    cache_key: revisions[cache_key],
                    crews_key: revisions[crews_key],
                },
            )
        except Exception as e:
            logger.error(f"Error updating module scoreboard for dojo {module.dojo_id} module {module.module_index}, duration={duration}: {e}", exc_info=True)


def _update_dojo_stats(
    dojo_ref_id,
    challenge_name,
    event_timestamp,
    revisions,
):
    cache_key = f"stats:dojo:{dojo_ref_id}"
    if is_event_stale(cache_key, event_timestamp):
        return
    current_stats = get_public_cached_stat(cache_key)
    if not current_stats:
        logger.info(f"No cached stats for dojo {dojo_ref_id}, skipping incremental update")
        return
    try:
        updated_stats = update_dojo_stats(current_stats, challenge_name)
        set_public_cached_stat(
            cache_key,
            updated_stats,
            revision=revisions[cache_key],
        )
    except Exception as e:
        logger.error(f"Error updating dojo stats for {dojo_ref_id}: {e}", exc_info=True)


def _update_challenge_solves(
    dojo_id,
    module_index,
    challenge_id,
    event_timestamp,
    revisions,
):
    cache_key = challenge_solves_cache_key(dojo_id, module_index)
    if is_event_stale(cache_key, event_timestamp):
        return
    current = get_public_cached_stat(cache_key)
    if current is None:
        logger.info(f"No cached challenge_solves for dojo {dojo_id} module {module_index}, skipping incremental update")
        return
    try:
        updated = update_challenge_solves(current, challenge_id)
        set_public_cached_stat(
            cache_key,
            updated,
            revision=revisions[cache_key],
        )
    except Exception as e:
        logger.error(f"Error updating challenge_solves for dojo {dojo_id} module {module_index}: {e}", exc_info=True)


def _update_scores(
    dojo_id,
    module_index,
    user_id,
    event_timestamp,
    revisions,
):
    logger.info(f"Updating dojo scores for dojo_id={dojo_id}, user_id={user_id}")
    try:
        cache_key = dojo_scores_cache_key(dojo_id)
        if not is_event_stale(cache_key, event_timestamp):
            current_scores = get_public_cached_stat(cache_key)
            if current_scores is None:
                logger.info(f"No current public scores cache for dojo_id={dojo_id}, skipping incremental update")
                return
            updated_scores = update_dojo_scores(current_scores, user_id)
            set_public_cached_stat(
                cache_key,
                updated_scores,
                revision=revisions[cache_key],
            )
    except Exception as e:
        logger.error(f"Error updating dojo scores: {e}", exc_info=True)

    logger.info(f"Updating module scores for dojo_id={dojo_id}, module_index={module_index}, user_id={user_id}")
    try:
        cache_key = module_scores_cache_key(dojo_id, module_index)
        if not is_event_stale(cache_key, event_timestamp):
            current_scores = get_public_cached_stat(cache_key)
            if current_scores is None:
                logger.info(f"No current public module scores cache for dojo_id={dojo_id}, module_index={module_index}, skipping incremental update")
                return
            updated_scores = update_module_scores(current_scores, user_id)
            set_public_cached_stat(
                cache_key,
                updated_scores,
                revision=revisions[cache_key],
            )
    except Exception as e:
        logger.error(f"Error updating module scores: {e}", exc_info=True)


def _update_user_activity(user_id, solve_date, event_timestamp):
    cache_key = f"stats:activity:{user_id}"
    if is_event_stale(cache_key, event_timestamp):
        return
    current_activity = get_cached_stat(cache_key) or {'solve_timestamps': [], 'total_solves': 0}
    try:
        updated_activity = update_activity(current_activity, solve_date)
        set_cached_stat(cache_key, updated_activity)
    except Exception as e:
        logger.error(f"Error updating activity for user_id {user_id}: {e}", exc_info=True)
