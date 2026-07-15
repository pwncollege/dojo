import logging

from CTFd.models import db
from ...models import DojoChallenges, DojoModules
from ...utils.background_stats import set_cached_stat
from ...utils.module_cache import drain_module_cache_invalidations, lock_dojo_cache_target, lock_module_cache_target, module_cache_target
from . import register_handler

logger = logging.getLogger(__name__)


@register_handler("challenge_solve")
def handle_challenge_solve(payload, event_timestamp):
    user_id = payload.get("user_id")
    challenge_id = payload.get("challenge_id")
    if user_id is None or challenge_id is None:
        logger.warning(f"challenge_solve event missing required fields: {payload}")
        return

    logger.info(f"Handling challenge_solve for user_id={user_id}, challenge_id={challenge_id}")

    db.session.expire_all()
    db.session.commit()
    if not drain_module_cache_invalidations():
        return False

    modules = (
        DojoModules.query
        .join(DojoChallenges, db.and_(
            DojoModules.dojo_id == DojoChallenges.dojo_id,
            DojoModules.module_index == DojoChallenges.module_index,
        ))
        .filter(DojoChallenges.challenge_id == challenge_id)
        .order_by(DojoModules.dojo_id, DojoModules.module_index)
        .all()
    )
    targets_by_dojo = {}
    for module in modules:
        target = module_cache_target(module)
        dojo_targets = targets_by_dojo.setdefault(target.dojo_id, {})
        dojo_targets[target.module_id] = target
    module_count = sum(
        len(targets) for targets in targets_by_dojo.values()
    )
    logger.info(
        f"Found {module_count} module(s) in {len(targets_by_dojo)} dojo(s) "
        f"containing challenge_id={challenge_id}"
    )

    for dojo_id, targets_by_id in targets_by_dojo.items():
        dojo = lock_dojo_cache_target(dojo_id)
        if not dojo:
            db.session.rollback()
            continue

        module_updates = []
        for target in targets_by_id.values():
            module = lock_module_cache_target(target)
            if not module:
                continue
            associations = (
                DojoChallenges.query
                .filter_by(
                    dojo_id=module.dojo_id,
                    module_index=module.module_index,
                    challenge_id=challenge_id,
                )
                .order_by(DojoChallenges.challenge_index)
                .all()
            )
            if associations:
                module_updates.append(module)

        if not module_updates:
            db.session.commit()
            continue

        from .cache_refresh import _write_dojo_caches, _write_module_caches

        for module in module_updates:
            if not _write_module_caches(module, event_timestamp):
                db.session.rollback()
                return False
        if not _write_dojo_caches(dojo, event_timestamp):
            db.session.rollback()
            return False
        db.session.commit()

    logger.info(f"Updating activity for user {user_id}")
    from ...utils.background_stats import calculate_authoritative_stat
    from .activity import calculate_activity

    activity, version, calculated_at = calculate_authoritative_stat(
        lambda: calculate_activity(user_id)
    )
    if not set_cached_stat(
        f"stats:activity:{user_id}",
        activity,
        updated_at=(
            event_timestamp
            if event_timestamp is not None
            else calculated_at
        ),
        version=version,
    ):
        return False
    logger.info(f"Completed challenge_solve for user_id={user_id}, challenge_id={challenge_id}")
    return True
