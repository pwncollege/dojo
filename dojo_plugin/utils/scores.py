from .module_cache import dojo_scores_cache_key, get_dojo_cached_stat, get_module_cached_stat, module_scores_cache_key


def get_dojo_scores(dojo_id):
    cached = get_dojo_cached_stat(dojo_id, dojo_scores_cache_key(dojo_id))
    if cached:
        return cached
    return {"ranks": [], "solves": {}}


def get_module_scores(module):
    cached = get_module_cached_stat(module, module_scores_cache_key(module))
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


def get_user_module_rank(module, user_id):
    scores = get_module_scores(module)
    ranks = scores.get("ranks", [])
    try:
        return ranks.index(user_id) + 1
    except ValueError:
        return None


def get_user_dojo_solves(dojo_id, user_id):
    scores = get_dojo_scores(dojo_id)
    solves = scores.get("solves", {})
    return solves.get(str(user_id)) or solves.get(user_id) or 0


def get_user_module_solves(module, user_id):
    scores = get_module_scores(module)
    solves = scores.get("solves", {})
    return solves.get(str(user_id)) or solves.get(user_id) or 0
