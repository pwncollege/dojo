import datetime
import hashlib
import itertools
import re

from flask import Blueprint, Response, render_template, abort, url_for
from sqlalchemy.sql import and_, or_
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.models import db, Users, Challenges, Solves
from CTFd.cache import cache

from ..models import Dojos, DojoModules, DojoChallenges
from ..utils.scores import get_dojo_scores, get_module_scores
from ..utils.awards import get_belts, get_viewable_emojis


users = Blueprint("pwncollege_users", __name__)


def build_user_scores(user, dojos):
    user_id = user.id

    dojo_scores = {
        "user_ranks": {user_id: {}},
        "user_solves": {user_id: {}},
        "dojo_ranks": {}
    }
    module_scores = {
        "user_ranks": {user_id: {}},
        "user_solves": {user_id: {}},
        "module_ranks": {}
    }

    for dojo in dojos:
        dojo_id = dojo.id
        scores = get_dojo_scores(dojo.dojo_id)
        ranks = scores.get("ranks", [])
        solves = scores.get("solves", {})

        dojo_scores["dojo_ranks"][dojo_id] = ranks

        try:
            rank = ranks.index(user_id) + 1
            dojo_scores["user_ranks"][user_id][dojo_id] = rank
            user_solve_count = solves.get(str(user_id)) or solves.get(user_id) or 0
            dojo_scores["user_solves"][user_id][dojo_id] = user_solve_count
        except ValueError:
            pass

        module_scores["module_ranks"][dojo_id] = {}
        module_scores["user_ranks"][user_id][dojo_id] = {}
        module_scores["user_solves"][user_id][dojo_id] = {}

        for module in dojo.modules:
            module_index = module.module_index
            m_scores = get_module_scores(dojo.dojo_id, module_index)
            m_ranks = m_scores.get("ranks", [])
            m_solves = m_scores.get("solves", {})

            module_scores["module_ranks"][dojo_id][module_index] = m_ranks

            try:
                rank = m_ranks.index(user_id) + 1
                module_scores["user_ranks"][user_id][dojo_id][module_index] = rank
                user_solve_count = m_solves.get(str(user_id)) or m_solves.get(user_id) or 0
                module_scores["user_solves"][user_id][dojo_id][module_index] = user_solve_count
            except ValueError:
                pass

    return dojo_scores, module_scores


def view_hacker(user, bypass_hidden=False):
    if user.hidden and not bypass_hidden:
        abort(404)

    dojos = (Dojos
             .viewable(user=get_current_user())
             .filter(Dojos.data["type"].astext != "hidden", Dojos.data["type"].astext != "course")
             .all())
    user_solves = {}
    for dojo in dojos:
        dojo_id = dojo.id
        user_solves[dojo_id] = {}

        for module in dojo.modules:
            module_id = module.id
            solves = module.solves(user=user, ignore_visibility=True, ignore_admins=False) if user else []

            if solves:
                user_solves[dojo_id][module_id] = {
                    solve.challenge_id: solve.date.strftime("%Y-%m-%d %H:%M:%S") for solve in solves
                }

    dojo_scores, module_scores = build_user_scores(user, dojos)

    return render_template(
        "hacker.html",
        dojos=dojos, user=user,
        dojo_scores=dojo_scores, module_scores=module_scores,
        belts=get_belts(), badges=get_viewable_emojis(get_current_user()),
        user_solves=user_solves
    )

@users.route("/hacker/<int:user_id>")
def view_other(user_id):
    user = Users.query.filter_by(id=user_id).first()
    if user is None or user.hidden:
        abort(404)
    return view_hacker(user)

@users.route("/hacker/<user_name>")
def view_other_name(user_name):
    user = Users.query.filter_by(name=user_name).first()
    if user is None or user.hidden:
        abort(404)
    return view_hacker(user)

@users.route("/hacker/")
@authed_only
def view_self():
    return view_hacker(get_current_user(), bypass_hidden=True)
