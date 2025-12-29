import logging
from sqlalchemy.sql import or_
from CTFd.models import Solves, db
from ...models import Dojos, DojoChallenges
from ...utils.background_stats import set_cached_stat
from . import register_handler

logger = logging.getLogger(__name__)

CACHE_KEY_DOJO_SCORES = "stats:scores:dojos"
CACHE_KEY_MODULE_SCORES = "stats:scores:modules"

def _scores_query(granularity, dojo_filter):
    solve_count = db.func.count(Solves.id).label("solve_count")
    last_solve_date = db.func.max(Solves.date).label("last_solve_date")
    fields = granularity + [Solves.user_id, solve_count, last_solve_date]
    grouping = granularity + [Solves.user_id]

    dsc_query = db.session.query(*fields).where(
        Dojos.dojo_id == DojoChallenges.dojo_id,
        DojoChallenges.challenge_id == Solves.challenge_id,
        dojo_filter
    ).group_by(*grouping).order_by(Dojos.id, solve_count.desc(), last_solve_date)

    return dsc_query

def calculate_dojo_scores():
    dsc_query = _scores_query([Dojos.id], or_(Dojos.data["type"].astext == "public", Dojos.official))

    user_ranks = {}
    user_solves = {}
    dojo_ranks = {}
    for dojo_id, user_id, solve_count, _ in dsc_query:
        dojo_ranks.setdefault(dojo_id, []).append(user_id)
        user_ranks.setdefault(user_id, {})[dojo_id] = len(dojo_ranks[dojo_id])
        user_solves.setdefault(user_id, {})[dojo_id] = solve_count

    return {
        "user_ranks": user_ranks,
        "user_solves": user_solves,
        "dojo_ranks": dojo_ranks
    }

def calculate_module_scores():
    dsc_query = _scores_query([Dojos.id, DojoChallenges.module_index], or_(Dojos.data["type"].astext == "public", Dojos.official))

    user_ranks = {}
    user_solves = {}
    module_ranks = {}
    for dojo_id, module_idx, user_id, solve_count, _ in dsc_query:
        module_ranks.setdefault(dojo_id, {}).setdefault(module_idx, []).append(user_id)
        user_ranks.setdefault(user_id, {}).setdefault(dojo_id, {})[module_idx] = len(module_ranks[dojo_id][module_idx])
        user_solves.setdefault(user_id, {}).setdefault(dojo_id, {})[module_idx] = solve_count

    return {
        "user_ranks": user_ranks,
        "user_solves": user_solves,
        "module_ranks": module_ranks
    }

@register_handler("scores_update")
def handle_scores_update(payload):
    db.session.expire_all()
    db.session.commit()

    try:
        logger.info("Calculating dojo scores...")
        dojo_data = calculate_dojo_scores()
        set_cached_stat(CACHE_KEY_DOJO_SCORES, dojo_data)
        logger.info(f"Successfully updated dojo scores cache ({len(dojo_data['dojo_ranks'])} dojos, {len(dojo_data['user_ranks'])} users)")
    except Exception as e:
        logger.error(f"Error calculating dojo scores: {e}", exc_info=True)

    try:
        logger.info("Calculating module scores...")
        module_data = calculate_module_scores()
        set_cached_stat(CACHE_KEY_MODULE_SCORES, module_data)
        dojo_count = len(module_data['module_ranks'])
        user_count = len(module_data['user_ranks'])
        logger.info(f"Successfully updated module scores cache ({dojo_count} dojos, {user_count} users)")
    except Exception as e:
        logger.error(f"Error calculating module scores: {e}", exc_info=True)

def initialize_all_scores():
    db.session.expire_all()
    db.session.commit()

    logger.info("Initializing dojo scores...")
    try:
        dojo_data = calculate_dojo_scores()
        set_cached_stat(CACHE_KEY_DOJO_SCORES, dojo_data)
        logger.info(f"Initialized dojo scores ({len(dojo_data['dojo_ranks'])} dojos, {len(dojo_data['user_ranks'])} users)")
    except Exception as e:
        logger.error(f"Error initializing dojo scores: {e}", exc_info=True)

    logger.info("Initializing module scores...")
    try:
        module_data = calculate_module_scores()
        set_cached_stat(CACHE_KEY_MODULE_SCORES, module_data)
        dojo_count = len(module_data['module_ranks'])
        user_count = len(module_data['user_ranks'])
        logger.info(f"Initialized module scores ({dojo_count} dojos, {user_count} users)")
    except Exception as e:
        logger.error(f"Error initializing module scores: {e}", exc_info=True)
