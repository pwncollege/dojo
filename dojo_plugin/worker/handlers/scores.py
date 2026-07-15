import logging
from sqlalchemy.sql import or_
from CTFd.models import Solves, db
from ...models import Dojos
from ...utils.background_stats import calculate_authoritative_stat, set_cached_stat, is_event_stale
from ...utils.module_cache import drain_module_cache_invalidations, lock_dojo_cache_target, lock_module_cache_target, module_cache_target, module_scores_cache_key
from . import register_handler

logger = logging.getLogger(__name__)


def dojo_scores_cache_key(dojo_id):
    return f"stats:scores:dojo:{dojo_id}"


def calculate_dojo_scores(dojo_id):
    dojo = Dojos.query.get(dojo_id)
    if dojo is None:
        return {"ranks": [], "solves": {}}
    solve_count = db.func.count(Solves.id).label("solve_count")
    last_solve_date = db.func.max(Solves.date).label("last_solve_date")
    query = (
        dojo.solves(required_only=False)
        .with_entities(Solves.user_id, solve_count, last_solve_date)
        .group_by(Solves.user_id)
        .order_by(solve_count.desc(), last_solve_date)
    )

    ranks = []
    solves = {}
    for user_id, solve_count, _ in query:
        ranks.append(user_id)
        solves[user_id] = solve_count

    return {"ranks": ranks, "solves": solves}


def calculate_module_scores(module):
    solve_count = db.func.count(Solves.id).label("solve_count")
    last_solve_date = db.func.max(Solves.date).label("last_solve_date")
    query = (
        module.cache_solves(required_only=False)
        .with_entities(Solves.user_id, solve_count, last_solve_date)
        .group_by(Solves.user_id)
        .order_by(solve_count.desc(), last_solve_date)
    )

    ranks = []
    solves = {}
    for user_id, solve_count, _ in query:
        ranks.append(user_id)
        solves[user_id] = solve_count

    return {"ranks": ranks, "solves": solves}


def update_dojo_scores(scores, user_id, solve_delta=1):
    ranks = list(scores.get("ranks", []))
    solves = {int(k): v for k, v in scores.get("solves", {}).items()}

    old_solve_count = solves.get(user_id, 0)
    new_solve_count = old_solve_count + solve_delta
    solves[user_id] = new_solve_count

    if user_id in ranks:
        ranks.remove(user_id)

    insert_pos = 0
    for i, other_user_id in enumerate(ranks):
        other_solves = solves.get(other_user_id, 0)
        if other_solves >= new_solve_count:
            insert_pos = i + 1
        else:
            break

    ranks.insert(insert_pos, user_id)

    return {"ranks": ranks, "solves": solves}


def update_module_scores(scores, user_id, solve_delta=1):
    return update_dojo_scores(scores, user_id, solve_delta)


@register_handler("scores_update")
def handle_scores_update(payload, event_timestamp=None):
    db.session.expire_all()
    db.session.commit()
    if not drain_module_cache_invalidations():
        return False

    dojo_id = payload.get("dojo_id")

    if dojo_id is not None:
        dojo_ids = [dojo_id]
        logger.info(f"Calculating scores for single dojo: {dojo_id}")
    else:
        dojo_ids = [
            selected_dojo_id
            for (selected_dojo_id,) in db.session.query(Dojos.dojo_id).filter(
                or_(Dojos.data["type"].astext == "public", Dojos.official)
            ).all()
        ]
        db.session.rollback()
        logger.info(f"Calculating scores for {len(dojo_ids)} public/official dojos...")

    for dojo_id in dojo_ids:
        dojo = lock_dojo_cache_target(dojo_id)
        if not dojo:
            logger.info(f"Dojo {dojo_id} not found, skipping scores update")
            db.session.rollback()
            continue
        try:
            cache_key = dojo_scores_cache_key(dojo_id)
            if not (event_timestamp and is_event_stale(cache_key, event_timestamp)):
                dojo_data, version, calculated_at = (
                    calculate_authoritative_stat(
                        lambda: calculate_dojo_scores(dojo_id)
                    )
                )
                set_cached_stat(
                    cache_key,
                    dojo_data,
                    updated_at=(
                        event_timestamp
                        if event_timestamp is not None
                        else calculated_at
                    ),
                    version=version,
                )
        except Exception as e:
            logger.error(f"Error calculating dojo scores for dojo_id {dojo_id}: {e}", exc_info=True)

        module_targets = [module_cache_target(module) for module in dojo.modules]
        for target in module_targets:
            module = lock_module_cache_target(target)
            if not module:
                continue
            module_index = module.module_index
            try:
                cache_key = module_scores_cache_key(module)
                if not (event_timestamp and is_event_stale(cache_key, event_timestamp)):
                    module_data, version, calculated_at = (
                        calculate_authoritative_stat(
                            lambda: calculate_module_scores(module)
                        )
                    )
                    set_cached_stat(
                        cache_key,
                        module_data,
                        updated_at=(
                            event_timestamp
                            if event_timestamp is not None
                            else calculated_at
                        ),
                        version=version,
                    )
            except Exception as e:
                logger.error(f"Error calculating module scores for dojo_id {dojo_id} module {module_index}: {e}", exc_info=True)
        db.session.commit()

    logger.info(f"Successfully updated scores cache for {len(dojo_ids)} dojos")
    return True


def initialize_all_scores():
    logger.info("Initializing all scores...")
    handle_scores_update({})
