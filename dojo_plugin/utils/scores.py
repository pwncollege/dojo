from .background_stats import get_cached_stat


def dojo_scores_cache_key(dojo_id):
    return f"stats:scores:dojo:{dojo_id}"


def module_scores_cache_key(dojo_id, module_index):
    return f"stats:scores:module:{dojo_id}:{module_index}"


def get_dojo_scores(dojo_id):
    cached = get_cached_stat(dojo_scores_cache_key(dojo_id))
    if cached:
        return cached
    return {"ranks": [], "solves": {}}


def get_module_scores(dojo_id, module_index):
    cached = get_cached_stat(module_scores_cache_key(dojo_id, module_index))
    if cached:
        return cached
    return {"ranks": [], "solves": {}}


def get_user_dojo_rank(dojo_id, user_id):
    scores = get_dojo_scores(dojo_id)
    ranks = scores.get("ranks", [])
    try:
        return ranks.index(user_id) + 1
    except ValueError:
        return None


def get_user_module_rank(dojo_id, module_index, user_id):
    scores = get_module_scores(dojo_id, module_index)
    ranks = scores.get("ranks", [])
    try:
        return ranks.index(user_id) + 1
    except ValueError:
        return None


def get_user_dojo_solves(dojo_id, user_id):
    scores = get_dojo_scores(dojo_id)
    solves = scores.get("solves", {})
    return solves.get(str(user_id)) or solves.get(user_id) or 0


def get_user_module_solves(dojo_id, module_index, user_id):
    scores = get_module_scores(dojo_id, module_index)
    solves = scores.get("solves", {})
    return solves.get(str(user_id)) or solves.get(user_id) or 0
