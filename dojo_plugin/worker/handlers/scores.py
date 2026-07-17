import logging
from sqlalchemy.sql import or_
from CTFd.models import db
from ...models import Dojos
from ...utils.background_stats import (
    get_public_cached_stat as get_cached_stat,
    set_public_cached_stat as set_cached_stat,
    is_event_stale,
)
from ...utils.public_stats import capture_public_cache_revisions
from ...utils.scores import (
    calculate_dojo_scores,
    calculate_module_scores,
    dojo_scores_cache_key,
    module_scores_cache_key,
)
from . import register_handler

logger = logging.getLogger(__name__)

def update_dojo_scores(scores, user_id):
    ranks = list(scores.get("ranks", []))
    solves = {int(k): v for k, v in scores.get("solves", {}).items()}

    old_solve_count = solves.get(user_id, 0)
    new_solve_count = old_solve_count + 1
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


def update_module_scores(scores, user_id):
    return update_dojo_scores(scores, user_id)


@register_handler("scores_update")
def handle_scores_update(payload, event_timestamp=None):
    db.session.expire_all()
    db.session.commit()

    dojo_id = payload.get("dojo_id")

    if dojo_id is not None:
        dojo = Dojos.query.filter_by(dojo_id=dojo_id).first()
        if not dojo:
            logger.info(f"Dojo {dojo_id} not found, skipping scores update")
            return
        dojos = [dojo]
        logger.info(f"Calculating scores for single dojo: {dojo_id}")
    else:
        dojos = Dojos.query.filter(
            or_(Dojos.data["type"].astext == "public", Dojos.official)
        ).all()
        logger.info(f"Calculating scores for {len(dojos)} public/official dojos...")

    cache_keys = [
        cache_key
        for dojo in dojos
        for cache_key in (
            dojo_scores_cache_key(dojo.dojo_id),
            *(
                module_scores_cache_key(dojo.dojo_id, module.module_index)
                for module in dojo.modules
            ),
        )
    ]
    revisions = capture_public_cache_revisions(cache_keys)

    for dojo in dojos:
        dojo_id = dojo.dojo_id
        try:
            cache_key = dojo_scores_cache_key(dojo_id)
            if not (event_timestamp and is_event_stale(cache_key, event_timestamp)):
                dojo_data = calculate_dojo_scores(dojo_id)
                set_cached_stat(cache_key, dojo_data, revision=revisions[cache_key])
        except Exception as e:
            logger.error(f"Error calculating dojo scores for dojo_id {dojo_id}: {e}", exc_info=True)

        for module in dojo.modules:
            module_index = module.module_index
            try:
                cache_key = module_scores_cache_key(dojo_id, module_index)
                if not (event_timestamp and is_event_stale(cache_key, event_timestamp)):
                    module_data = calculate_module_scores(dojo_id, module_index)
                    set_cached_stat(
                        cache_key,
                        module_data,
                        revision=revisions[cache_key],
                    )
            except Exception as e:
                logger.error(f"Error calculating module scores for dojo_id {dojo_id} module {module_index}: {e}", exc_info=True)

    logger.info(f"Successfully updated scores cache for {len(dojos)} dojos")


def initialize_all_scores():
    logger.info("Initializing all scores...")
    handle_scores_update({})
