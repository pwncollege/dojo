import logging

from CTFd.models import db

from ...models import DojoCacheRefreshes, DojoModules
from ...utils.background_stats import calculate_authoritative_stat, set_cached_stat
from ...utils.module_cache import (
    ModuleCacheTarget,
    SCOREBOARD_DURATIONS,
    dojo_aggregate_cache_keys,
    dojo_scoreboard_cache_key,
    dojo_scores_cache_key,
    dojo_stats_cache_key,
    drain_module_cache_invalidations,
    lock_dojo_cache_target,
    lock_module_cache_target,
    module_cache_maintenance_lock,
    module_challenge_solves_cache_key,
    module_identity_cache_keys,
    module_scoreboard_cache_key,
    module_scores_cache_key,
)
from . import register_handler


logger = logging.getLogger(__name__)


def _lock_refresh(kind, dojo_id, module_id, cache_identity, generation):
    return (
        DojoCacheRefreshes.query
        .filter_by(
            kind=kind,
            dojo_id=dojo_id,
            module_id=module_id,
            cache_identity=cache_identity,
            generation=generation,
        )
        .with_for_update()
        .one_or_none()
    )


def _module_payload(payload):
    model_id = payload.get("model_id")
    if isinstance(model_id, dict):
        return {**model_id, **payload}
    return payload


def _module_target(payload):
    payload = _module_payload(payload)
    dojo_id = payload.get("dojo_id")
    module_id = payload.get("module_id")
    cache_identity = payload.get("cache_identity")
    if dojo_id is None:
        return None
    if module_id is not None and cache_identity is not None:
        return ModuleCacheTarget(dojo_id, module_id, cache_identity)

    module_index = payload.get("module_index")
    if module_index is None:
        return None
    module = DojoModules.query.get((dojo_id, module_index))
    if module is None:
        return None
    return ModuleCacheTarget(dojo_id, module.id, module.cache_identity)


def _write_module_caches(module, event_timestamp=None):
    from .scoreboard import (
        calculate_challenge_solves,
        calculate_member_challenges,
        calculate_scoreboard,
        set_scoreboard_cache,
    )
    from .scores import calculate_module_scores

    def calculate():
        scoreboards = []
        for duration in SCOREBOARD_DURATIONS:
            scoreboard = calculate_scoreboard(module, duration)
            member_challenges = calculate_member_challenges(
                module,
                duration,
                scoreboard,
            )
            scoreboards.append((duration, scoreboard, member_challenges))
        return (
            scoreboards,
            calculate_challenge_solves(module),
            calculate_module_scores(module),
        )

    (
        scoreboards,
        challenge_solves,
        scores,
    ), version, calculated_at = calculate_authoritative_stat(calculate)
    updated_at = (
        event_timestamp
        if event_timestamp is not None
        else calculated_at
    )

    succeeded = True
    for duration, scoreboard, member_challenges in scoreboards:
        succeeded = set_scoreboard_cache(
            module_scoreboard_cache_key(module, duration),
            scoreboard,
            member_challenges,
            updated_at=updated_at,
            version=version,
        ) and succeeded
    succeeded = set_cached_stat(
        module_challenge_solves_cache_key(module),
        challenge_solves,
        updated_at=updated_at,
        version=version,
    ) and succeeded
    succeeded = set_cached_stat(
        module_scores_cache_key(module),
        scores,
        updated_at=updated_at,
        version=version,
    ) and succeeded
    return succeeded


def _write_dojo_caches(dojo, event_timestamp=None):
    from .dojo_stats import calculate_dojo_stats
    from .scoreboard import (
        calculate_member_challenges,
        calculate_scoreboard,
        set_scoreboard_cache,
    )
    from .scores import calculate_dojo_scores

    def calculate():
        scoreboards = []
        for duration in SCOREBOARD_DURATIONS:
            scoreboard = calculate_scoreboard(dojo, duration)
            member_challenges = calculate_member_challenges(
                dojo,
                duration,
                scoreboard,
            )
            scoreboards.append((duration, scoreboard, member_challenges))
        return (
            scoreboards,
            calculate_dojo_stats(dojo),
            calculate_dojo_scores(dojo.dojo_id),
        )

    (scoreboards, stats, scores), version, calculated_at = (
        calculate_authoritative_stat(calculate)
    )
    updated_at = (
        event_timestamp
        if event_timestamp is not None
        else calculated_at
    )

    succeeded = True
    for duration, scoreboard, member_challenges in scoreboards:
        succeeded = set_scoreboard_cache(
            dojo_scoreboard_cache_key(dojo.dojo_id, duration),
            scoreboard,
            member_challenges,
            updated_at=updated_at,
            version=version,
        ) and succeeded
    succeeded = set_cached_stat(
        dojo_stats_cache_key(dojo),
        stats,
        updated_at=updated_at,
        version=version,
    ) and succeeded
    succeeded = set_cached_stat(
        dojo_scores_cache_key(dojo.dojo_id),
        scores,
        updated_at=updated_at,
        version=version,
    ) and succeeded
    return succeeded


@register_handler("module_cache_refresh")
def handle_module_cache_refresh(payload, event_timestamp=None):
    db.session.rollback()
    maintenance_lock = None
    maintenance_lock_entered = False
    try:
        maintenance_lock = module_cache_maintenance_lock(blocking=True)
        acquired = maintenance_lock.__enter__()
        maintenance_lock_entered = True
        if not acquired:
            return False
        payload = _module_payload(payload)
        dojo_id = payload.get("dojo_id")
        generation = payload.get("generation")
        dojo = lock_dojo_cache_target(dojo_id) if dojo_id is not None else None
        target = _module_target(payload) if dojo is not None else None
        module = lock_module_cache_target(target) if target is not None else None

        refresh = None
        if generation is not None and target is not None:
            refresh = _lock_refresh(
                "module",
                target.dojo_id,
                target.module_id,
                target.cache_identity,
                generation,
            )
            if refresh is None:
                db.session.rollback()
                return True
        elif generation is not None:
            module_id = payload.get("module_id", "")
            cache_identity = payload.get("cache_identity", "")
            if dojo_id is not None:
                refresh = _lock_refresh(
                    "module",
                    dojo_id,
                    module_id,
                    cache_identity,
                    generation,
                )
            if refresh is None:
                db.session.rollback()
                return True

        if module is None:
            if refresh is not None:
                db.session.delete(refresh)
                db.session.commit()
            else:
                db.session.rollback()
            return True
        if not drain_module_cache_invalidations(
            module_identity_cache_keys(
                module.dojo_id,
                module.cache_identity,
            )
        ):
            db.session.rollback()
            return False
        if not _write_module_caches(module, event_timestamp):
            db.session.rollback()
            return False
        if refresh is not None:
            db.session.delete(refresh)
        db.session.commit()
        return True
    except Exception as error:
        db.session.rollback()
        logger.error(
            "Failed to refresh module caches for payload %s: %s",
            payload,
            error,
            exc_info=True,
        )
        return False
    finally:
        if maintenance_lock_entered:
            maintenance_lock.__exit__(None, None, None)


@register_handler("dojo_cache_refresh")
def handle_dojo_cache_refresh(payload, event_timestamp=None):
    db.session.rollback()
    maintenance_lock = None
    maintenance_lock_entered = False
    try:
        maintenance_lock = module_cache_maintenance_lock(blocking=True)
        acquired = maintenance_lock.__enter__()
        maintenance_lock_entered = True
        if not acquired:
            return False
        dojo_id = payload.get("dojo_id")
        generation = payload.get("generation")
        dojo = lock_dojo_cache_target(dojo_id) if dojo_id is not None else None

        refresh = None
        if generation is not None and dojo_id is not None:
            refresh = _lock_refresh("dojo", dojo_id, "", "", generation)
            if refresh is None:
                db.session.rollback()
                return True

        if dojo is None:
            if refresh is not None:
                db.session.delete(refresh)
                db.session.commit()
            else:
                db.session.rollback()
            return True
        if not drain_module_cache_invalidations(
            dojo_aggregate_cache_keys(dojo)
        ):
            db.session.rollback()
            return False
        if not _write_dojo_caches(dojo, event_timestamp):
            db.session.rollback()
            return False
        if refresh is not None:
            db.session.delete(refresh)
        db.session.commit()
        return True
    except Exception as error:
        db.session.rollback()
        logger.error(
            "Failed to refresh dojo caches for payload %s: %s",
            payload,
            error,
            exc_info=True,
        )
        return False
    finally:
        if maintenance_lock_entered:
            maintenance_lock.__exit__(None, None, None)
