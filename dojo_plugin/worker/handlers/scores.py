import logging
from sqlalchemy.sql import or_
from CTFd.models import Solves, db
from ...models import Dojos, DojoChallenges
from ...utils.background_stats import get_cached_stat, set_cached_stat, is_event_stale
from . import register_handler

logger = logging.getLogger(__name__)


def dojo_scores_cache_key(dojo_id):
    return f"stats:scores:dojo:{dojo_id}"


def module_scores_cache_key(dojo_id, module_index):
    return f"stats:scores:module:{dojo_id}:{module_index}"


def _scores_query(granularity, dojo_filter):
    solve_count = db.func.count(Solves.id).label("solve_count")
    last_solve_date = db.func.max(Solves.date).label("last_solve_date")
    fields = granularity + [Solves.user_id, solve_count, last_solve_date]
    grouping = granularity + [Solves.user_id]

    dsc_query = db.session.query(*fields).where(
        Dojos.dojo_id == DojoChallenges.dojo_id,
        DojoChallenges.challenge_id == Solves.challenge_id,
        dojo_filter
    ).group_by(*grouping).order_by(Dojos.dojo_id, solve_count.desc(), last_solve_date)

    return dsc_query


def calculate_dojo_scores(dojo_id):
    dsc_query = _scores_query(
        [Dojos.dojo_id],
        Dojos.dojo_id == dojo_id
    )

    ranks = []
    solves = {}
    for _, user_id, solve_count, _ in dsc_query:
        ranks.append(user_id)
        solves[user_id] = solve_count

    return {"ranks": ranks, "solves": solves}


def calculate_module_scores(dojo_id, module_index):
    dsc_query = _scores_query(
        [Dojos.dojo_id, DojoChallenges.module_index],
        db.and_(Dojos.dojo_id == dojo_id, DojoChallenges.module_index == module_index)
    )

    ranks = []
    solves = {}
    for _, _, user_id, solve_count, _ in dsc_query:
        ranks.append(user_id)
        solves[user_id] = solve_count

    return {"ranks": ranks, "solves": solves}


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

    for dojo in dojos:
        dojo_id = dojo.dojo_id
        try:
            cache_key = dojo_scores_cache_key(dojo_id)
            if not (event_timestamp and is_event_stale(cache_key, event_timestamp)):
                dojo_data = calculate_dojo_scores(dojo_id)
                set_cached_stat(cache_key, dojo_data)
        except Exception as e:
            logger.error(f"Error calculating dojo scores for dojo_id {dojo_id}: {e}", exc_info=True)

        for module in dojo.modules:
            module_index = module.module_index
            try:
                cache_key = module_scores_cache_key(dojo_id, module_index)
                if not (event_timestamp and is_event_stale(cache_key, event_timestamp)):
                    module_data = calculate_module_scores(dojo_id, module_index)
                    set_cached_stat(cache_key, module_data)
            except Exception as e:
                logger.error(f"Error calculating module scores for dojo_id {dojo_id} module {module_index}: {e}", exc_info=True)

    logger.info(f"Successfully updated scores cache for {len(dojos)} dojos")


def initialize_all_scores():
    logger.info("Initializing all scores...")
    handle_scores_update({})
