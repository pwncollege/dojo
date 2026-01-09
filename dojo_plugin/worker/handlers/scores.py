import logging
from sqlalchemy.sql import or_
from CTFd.models import Solves, db
from ...models import Dojos, DojoChallenges
from ...utils.background_stats import get_cached_stat, set_cached_stat
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
    ).group_by(*grouping).order_by(Dojos.dojo_id, solve_count.desc(), last_solve_date)

    return dsc_query

def calculate_dojo_scores():
    dsc_query = _scores_query([Dojos.dojo_id], or_(Dojos.data["type"].astext == "public", Dojos.official))

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
    dsc_query = _scores_query([Dojos.dojo_id, DojoChallenges.module_index], or_(Dojos.data["type"].astext == "public", Dojos.official))

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

def update_dojo_scores(scores, user_id, dojo_id):
    user_ranks = {int(k): v for k, v in scores.get("user_ranks", {}).items()}
    user_solves = {int(k): v for k, v in scores.get("user_solves", {}).items()}
    dojo_ranks = {int(k): list(v) for k, v in scores.get("dojo_ranks", {}).items()}

    if dojo_id not in dojo_ranks:
        dojo_ranks[dojo_id] = []

    user_solves.setdefault(user_id, {})
    user_ranks.setdefault(user_id, {})

    old_solve_count = user_solves[user_id].get(dojo_id, 0)
    new_solve_count = old_solve_count + 1
    user_solves[user_id][dojo_id] = new_solve_count

    ranking = dojo_ranks[dojo_id]
    if user_id in ranking:
        ranking.remove(user_id)

    insert_pos = 0
    for i, other_user_id in enumerate(ranking):
        other_solves = user_solves.get(other_user_id, {}).get(dojo_id, 0)
        if other_solves >= new_solve_count:
            insert_pos = i + 1
        else:
            break

    ranking.insert(insert_pos, user_id)

    for i, uid in enumerate(ranking):
        user_ranks.setdefault(uid, {})[dojo_id] = i + 1

    return {
        "user_ranks": user_ranks,
        "user_solves": user_solves,
        "dojo_ranks": dojo_ranks
    }


def update_module_scores(scores, user_id, dojo_id, module_index):
    user_ranks = {int(k): v for k, v in scores.get("user_ranks", {}).items()}
    user_solves = {int(k): v for k, v in scores.get("user_solves", {}).items()}
    module_ranks = {int(k): v for k, v in scores.get("module_ranks", {}).items()}

    if dojo_id not in module_ranks:
        module_ranks[dojo_id] = {}
    if module_index not in module_ranks[dojo_id]:
        module_ranks[dojo_id][module_index] = []

    user_solves.setdefault(user_id, {}).setdefault(dojo_id, {})
    user_ranks.setdefault(user_id, {}).setdefault(dojo_id, {})

    old_solve_count = user_solves[user_id][dojo_id].get(module_index, 0)
    new_solve_count = old_solve_count + 1
    user_solves[user_id][dojo_id][module_index] = new_solve_count

    ranking = module_ranks[dojo_id][module_index]
    if user_id in ranking:
        ranking.remove(user_id)

    insert_pos = 0
    for i, other_user_id in enumerate(ranking):
        other_solves = user_solves.get(other_user_id, {}).get(dojo_id, {}).get(module_index, 0)
        if other_solves >= new_solve_count:
            insert_pos = i + 1
        else:
            break

    ranking.insert(insert_pos, user_id)

    for i, uid in enumerate(ranking):
        user_ranks.setdefault(uid, {}).setdefault(dojo_id, {})[module_index] = i + 1

    return {
        "user_ranks": user_ranks,
        "user_solves": user_solves,
        "module_ranks": module_ranks
    }


@register_handler("scores_update_solve")
def handle_scores_update_solve(payload):
    user_id = payload.get("user_id")
    dojo_id = payload.get("dojo_id")
    module_index = payload.get("module_index")

    if user_id is None or dojo_id is None or module_index is None:
        logger.warning(f"scores_update_solve event missing required fields: {payload}")
        return

    logger.info(f"Handling scores_update_solve for user_id={user_id}, dojo_id={dojo_id}, module_index={module_index}")

    try:
        dojo_scores = get_cached_stat(CACHE_KEY_DOJO_SCORES) or {"user_ranks": {}, "user_solves": {}, "dojo_ranks": {}}
        updated_dojo_scores = update_dojo_scores(dojo_scores, user_id, dojo_id)
        set_cached_stat(CACHE_KEY_DOJO_SCORES, updated_dojo_scores)
        logger.info(f"Updated dojo scores for user {user_id} in dojo {dojo_id}")
    except Exception as e:
        logger.error(f"Error updating dojo scores: {e}", exc_info=True)

    try:
        module_scores = get_cached_stat(CACHE_KEY_MODULE_SCORES) or {"user_ranks": {}, "user_solves": {}, "module_ranks": {}}
        updated_module_scores = update_module_scores(module_scores, user_id, dojo_id, module_index)
        set_cached_stat(CACHE_KEY_MODULE_SCORES, updated_module_scores)
        logger.info(f"Updated module scores for user {user_id} in dojo {dojo_id} module {module_index}")
    except Exception as e:
        logger.error(f"Error updating module scores: {e}", exc_info=True)


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
