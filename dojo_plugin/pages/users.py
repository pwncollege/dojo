from flask import Blueprint, render_template, abort
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.models import db, Users, Solves

from ..models import Dojos, DojoChallenges, UserVisibilityUpdates
from ..utils.scores import (
    calculate_profile_scores,
    get_dojo_scores,
    get_module_scores,
)
from ..utils.awards import get_belts, get_viewable_emojis
from ..utils.public_stats import lock_public_stats_visibility
from ..utils.users import can_view_user, refresh_user


users = Blueprint("pwncollege_users", __name__)


def profile_solves_query(dojo_ids):
    return DojoChallenges.solves(
        ignore_visibility=True,
        ignore_admins=False,
        required_only=False,
    ).filter(DojoChallenges.dojo_id.in_(dojo_ids))


def build_user_solves(user, dojos):
    user_solves = {dojo.dojo_id: {} for dojo in dojos}
    module_keys = {
        (dojo.dojo_id, module.module_index): (dojo.dojo_id, module.id)
        for dojo in dojos
        for module in dojo.modules
    }
    if not module_keys:
        return user_solves

    solves = (
        profile_solves_query({key[0] for key in module_keys})
        .with_entities(
            DojoChallenges.dojo_id,
            DojoChallenges.module_index,
            DojoChallenges.id,
            db.func.min(Solves.date),
        )
        .filter(
            Solves.user_id == user.id,
        )
        .group_by(
            DojoChallenges.dojo_id,
            DojoChallenges.module_index,
            DojoChallenges.id,
        )
        .all()
    )

    for dojo_id, module_index, challenge_id, solve_date in solves:
        module_key = module_keys.get((dojo_id, module_index))
        if module_key is None:
            continue
        mapped_dojo_id, module_id = module_key
        user_solves[mapped_dojo_id].setdefault(module_id, {})[challenge_id] = (
            solve_date.strftime("%Y-%m-%d %H:%M:%S")
        )

    return user_solves


def build_user_scores(user, dojos):
    user_id = user.id
    visibility_pending = UserVisibilityUpdates.query.filter_by(
        user_id=user_id
    ).first() is not None
    live_dojos = [
        dojo
        for dojo in dojos
        if user.hidden or visibility_pending or not dojo.is_public_or_official
    ]
    live_dojo_scores, live_module_scores = calculate_profile_scores(
        user_id,
        {dojo.dojo_id for dojo in live_dojos},
    )
    live_dojo_ids = {dojo.dojo_id for dojo in live_dojos}

    dojo_scores = {
        "user_ranks": {user_id: {}},
        "user_solves": {user_id: {}},
        "dojo_ranks": {},
        "dojo_populations": {},
    }
    module_scores = {
        "user_ranks": {user_id: {}},
        "user_solves": {user_id: {}},
        "module_ranks": {},
        "module_populations": {},
    }

    for dojo in dojos:
        dojo_id = dojo.dojo_id
        if dojo.dojo_id in live_dojo_ids:
            score = live_dojo_scores.get(dojo.dojo_id)
            ranks = []
            if score:
                rank = score["rank"]
                user_solve_count = score["solves"]
                population = score["population"]
            else:
                rank = None
                user_solve_count = 0
                population = 0
        else:
            scores = get_dojo_scores(dojo.dojo_id)
            ranks = scores.get("ranks", [])
            solves = scores.get("solves", {})
            try:
                rank = ranks.index(user_id) + 1
            except ValueError:
                rank = None
            user_solve_count = solves.get(str(user_id)) or solves.get(user_id) or 0
            population = len(ranks)

        dojo_scores["dojo_ranks"][dojo_id] = ranks
        dojo_scores["dojo_populations"][dojo_id] = population
        if rank is not None:
            dojo_scores["user_ranks"][user_id][dojo_id] = rank
            dojo_scores["user_solves"][user_id][dojo_id] = user_solve_count

        module_scores["module_ranks"][dojo_id] = {}
        module_scores["module_populations"][dojo_id] = {}
        module_scores["user_ranks"][user_id][dojo_id] = {}
        module_scores["user_solves"][user_id][dojo_id] = {}

        for module in dojo.modules:
            module_index = module.module_index
            if dojo.dojo_id in live_dojo_ids:
                module_score = live_module_scores.get(
                    (dojo.dojo_id, module_index)
                )
                m_ranks = []
                if module_score:
                    module_rank = module_score["rank"]
                    module_solve_count = module_score["solves"]
                    module_population = module_score["population"]
                else:
                    module_rank = None
                    module_solve_count = 0
                    module_population = 0
            else:
                m_scores = get_module_scores(dojo.dojo_id, module_index)
                m_ranks = m_scores.get("ranks", [])
                m_solves = m_scores.get("solves", {})
                try:
                    module_rank = m_ranks.index(user_id) + 1
                except ValueError:
                    module_rank = None
                module_solve_count = (
                    m_solves.get(str(user_id)) or m_solves.get(user_id) or 0
                )
                module_population = len(m_ranks)

            module_scores["module_ranks"][dojo_id][module_index] = m_ranks
            module_scores["module_populations"][dojo_id][module_index] = (
                module_population
            )
            if module_rank is not None:
                module_scores["user_ranks"][user_id][dojo_id][module_index] = (
                    module_rank
                )
                module_scores["user_solves"][user_id][dojo_id][module_index] = (
                    module_solve_count
                )

    return dojo_scores, module_scores


def view_hacker(user):
    lock_public_stats_visibility()
    user = refresh_user(user)
    if not can_view_user(user):
        abort(404)

    current_user = refresh_user(get_current_user())
    dojos = (Dojos
             .viewable(user=current_user)
             .filter(Dojos.data["type"].astext != "hidden", Dojos.data["type"].astext != "course")
             .all())
    user_solves = build_user_solves(user, dojos)

    dojo_scores, module_scores = build_user_scores(user, dojos)

    return render_template(
        "hacker.html",
        dojos=dojos, user=user,
        dojo_scores=dojo_scores, module_scores=module_scores,
        belts=get_belts(user), badges=get_viewable_emojis(current_user),
        user_solves=user_solves
    )

@users.route("/hacker/<int:user_id>")
def view_other(user_id):
    user = Users.query.populate_existing().filter_by(id=user_id).first()
    if user is None:
        abort(404)
    return view_hacker(user)

@users.route("/hacker/<user_name>")
def view_other_name(user_name):
    user = Users.query.populate_existing().filter_by(name=user_name).first()
    if user is None:
        abort(404)
    return view_hacker(user)

@users.route("/hacker/")
@authed_only
def view_self():
    return view_hacker(get_current_user())
