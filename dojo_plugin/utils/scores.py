from sqlalchemy.sql import or_
from CTFd.models import Solves, db
from CTFd.cache import cache
from ..models import Dojos, DojoChallenges

@cache.memoize(timeout=1200)
def dojo_scores():
    solve_count = db.func.count(Solves.id).label("solve_count")
    last_solve_id = db.func.max(Solves.id).label("last_solve_id")
    dsc_query = db.session.query(Dojos.id, Solves.user_id, solve_count, last_solve_id).where(
        Dojos.dojo_id == DojoChallenges.dojo_id, DojoChallenges.challenge_id == Solves.challenge_id,
        or_(Dojos.data["type"] == "public", Dojos.official)
    ).group_by(Dojos.id, Solves.user_id).order_by(Dojos.id, solve_count.desc(), last_solve_id)

    user_ranks = { }
    user_solves = { }
    dojo_ranks = { }
    for dojo_id, user_id, solve_count, last_solve_id in dsc_query:
        dojo_ranks.setdefault(dojo_id, [ ]).append(user_id)
        user_ranks.setdefault(user_id, {})[dojo_id] = len(dojo_ranks[dojo_id])
        user_solves.setdefault(user_id, {})[dojo_id] = solve_count

    return {
        "user_ranks": user_ranks,
        "user_solves": user_solves,
        "dojo_ranks": dojo_ranks
    }

@cache.memoize(timeout=1200)
def module_scores():
    solve_count = db.func.count(Solves.id).label("solve_count")
    last_solve_id = db.func.max(Solves.id).label("last_solve_id")
    dsc_query = db.session.query(Dojos.id, DojoChallenges.module_index, Solves.user_id, solve_count, last_solve_id).where(
        Dojos.dojo_id == DojoChallenges.dojo_id, DojoChallenges.challenge_id == Solves.challenge_id,
        or_(Dojos.data["type"] == "public", Dojos.official)
    ).group_by(Dojos.id, DojoChallenges.module_index, Solves.user_id).order_by(Dojos.id, DojoChallenges.module_index, solve_count.desc(), last_solve_id)

    user_ranks = { }
    user_solves = { }
    module_ranks = { }
    for dojo_id, module_idx, user_id, solve_count, last_solve_id in dsc_query:
        module_ranks.setdefault(dojo_id, {}).setdefault(module_idx, []).append(user_id)
        user_ranks.setdefault(user_id, {}).setdefault(dojo_id, {})[module_idx] = len(module_ranks[dojo_id][module_idx])
        user_solves.setdefault(user_id, {}).setdefault(dojo_id, {})[module_idx] = solve_count

    return {
        "user_ranks": user_ranks,
        "user_solves": user_solves,
        "module_ranks": module_ranks
    }
