from sqlalchemy import and_, or_

from CTFd.models import db, Solves, Users

from ..models import DojoChallenges, UserVisibilityUpdates
from .background_stats import get_public_cached_stat


def dojo_scores_cache_key(dojo_id):
    return f"stats:scores:dojo:{dojo_id}"


def module_scores_cache_key(dojo_id, module_index):
    return f"stats:scores:module:{dojo_id}:{module_index}"


def get_dojo_scores(dojo_id):
    cached = get_public_cached_stat(dojo_scores_cache_key(dojo_id))
    if cached:
        return cached
    return {"ranks": [], "solves": {}}


def get_module_scores(dojo_id, module_index):
    cached = get_public_cached_stat(module_scores_cache_key(dojo_id, module_index))
    if cached:
        return cached
    return {"ranks": [], "solves": {}}


def score_groups_query(granularity, dojo_filter, target_user_id=None):
    query = DojoChallenges.solves(
        ignore_visibility=True,
        ignore_admins=False,
        required_only=False,
    )
    if target_user_id is None:
        eligible_user = and_(~Users.hidden, ~Users.banned)
    else:
        query = query.outerjoin(
            UserVisibilityUpdates,
            UserVisibilityUpdates.user_id == Users.id,
        )
        eligible_user = and_(
            ~Users.banned,
            or_(
                Users.id == target_user_id,
                and_(
                    ~Users.hidden,
                    UserVisibilityUpdates.user_id.is_(None),
                ),
            ),
        )
    solve_count = db.func.count(Solves.id).label("solve_count")
    last_solve_date = db.func.max(Solves.date).label("last_solve_date")
    fields = [*granularity, Solves.user_id, solve_count, last_solve_date]
    return (
        query
        .filter(dojo_filter, eligible_user)
        .with_entities(*fields)
        .group_by(*granularity, Solves.user_id)
    )


def scores_query(granularity, dojo_filter):
    query = score_groups_query(granularity, dojo_filter)
    return query.order_by(
        *granularity,
        db.desc("solve_count"),
        db.asc("last_solve_date"),
        Solves.user_id,
    )


def calculate_dojo_scores(dojo_id):
    query = scores_query(
        [DojoChallenges.dojo_id],
        DojoChallenges.dojo_id == dojo_id,
    )
    ranks = []
    solves = {}
    for _, user_id, solve_count, _ in query:
        ranks.append(user_id)
        solves[user_id] = solve_count
    return {"ranks": ranks, "solves": solves}


def calculate_module_scores(dojo_id, module_index):
    query = scores_query(
        [DojoChallenges.dojo_id, DojoChallenges.module_index],
        and_(
            DojoChallenges.dojo_id == dojo_id,
            DojoChallenges.module_index == module_index,
        ),
    )
    ranks = []
    solves = {}
    for _, _, user_id, solve_count, _ in query:
        ranks.append(user_id)
        solves[user_id] = solve_count
    return {"ranks": ranks, "solves": solves}


def ranked_score_groups(groups, partition_columns, name):
    ordering = (
        groups.c.solve_count.desc(),
        groups.c.last_solve_date,
        groups.c.user_id,
    )
    return db.session.query(
        *partition_columns,
        groups.c.user_id,
        groups.c.solve_count,
        db.func.row_number()
        .over(partition_by=partition_columns, order_by=ordering)
        .label("rank"),
        db.func.count()
        .over(partition_by=partition_columns)
        .label("population"),
    ).cte(name)


def calculate_profile_scores(user_id, dojo_ids):
    dojo_ids = set(dojo_ids)
    if not dojo_ids:
        return {}, {}

    module_groups = score_groups_query(
        [DojoChallenges.dojo_id, DojoChallenges.module_index],
        DojoChallenges.dojo_id.in_(dojo_ids),
        target_user_id=user_id,
    ).cte("profile_module_score_groups")
    module_ranked = ranked_score_groups(
        module_groups,
        [module_groups.c.dojo_id, module_groups.c.module_index],
        "profile_module_ranked_scores",
    )

    dojo_groups = db.session.query(
        module_groups.c.dojo_id,
        module_groups.c.user_id,
        db.func.sum(module_groups.c.solve_count).label("solve_count"),
        db.func.max(module_groups.c.last_solve_date).label("last_solve_date"),
    ).group_by(
        module_groups.c.dojo_id,
        module_groups.c.user_id,
    ).cte("profile_dojo_score_groups")
    dojo_ranked = ranked_score_groups(
        dojo_groups,
        [dojo_groups.c.dojo_id],
        "profile_dojo_ranked_scores",
    )

    module_rows = db.session.query(*module_ranked.c).filter(
        module_ranked.c.user_id == user_id
    ).all()
    dojo_rows = db.session.query(*dojo_ranked.c).filter(
        dojo_ranked.c.user_id == user_id
    ).all()

    dojo_scores = {
        row.dojo_id: {
            "rank": int(row.rank),
            "population": int(row.population),
            "solves": int(row.solve_count),
        }
        for row in dojo_rows
    }
    module_scores = {
        (row.dojo_id, row.module_index): {
            "rank": int(row.rank),
            "population": int(row.population),
            "solves": int(row.solve_count),
        }
        for row in module_rows
    }
    return dojo_scores, module_scores


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
