from flask import Blueprint, render_template, abort
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.models import db, Users, Challenges, Solves
from CTFd.cache import cache

import pytz

from ..utils import user_dojos, dojo_challenges, module_visible, dojo_standings
from ..api.v1.scoreboard import belt_asset, belt_asset_for

users = Blueprint("pwncollege_users", __name__)

@cache.memoize(timeout=120)
def standings(dojo_id=None):
    score = db.func.sum(Challenges.value).label("score")
    global_standings = (
        dojo_standings(dojo_id=dojo_id, fields=[Solves.account_id, Users.name, score])
        .group_by(Solves.account_id)
        .order_by(score.desc(), db.func.max(Solves.id))
    ).all()
    return global_standings

def user_standings(user, dojo_id=None):
    global_standings = standings(dojo_id=dojo_id)
    total_solvers = len(global_standings)
    try:
        gpi = next(i for i,u in enumerate(global_standings, start=1) if u.account_id == user.id)
        ending = { "1": "st", "2": "nd", "3": "rd" }
        global_position = str(gpi)+ending.get(str(gpi)[-1], "th")
    except StopIteration:
        global_position = "last"

    return global_position, total_solvers

def dojo_full_stats(dojo, user):
    challenges = dojo_challenges(dojo, user=user)
    visible_modules = [ m for m in dojo.modules if module_visible(dojo, m, None) ]
    module_challenges = { m["id"]: [ c for c in challenges if c.module == m["id"] ] for m in visible_modules }

    dojo_position, dojo_solvers = user_standings(user, dojo_id=dojo.id)

    return {
        "count": len(challenges),
        "solved": len([c for c in challenges if c.solved]),
        "visible_modules": visible_modules,
        "total_solvers": dojo_solvers,
        "position": dojo_position,
        "module_stats": {
            m["id"]: {
                "solved_chals": [
                    { "name": c.name, "solve_date": c.solve_date.astimezone(pytz.timezone("America/Phoenix")), "solves": c.solves }
                    for c in module_challenges[m["id"]] if c.solved
                ],
                "unsolved_chals": [
                    { "name": c.name, "solves": c.solves }
                    for c in module_challenges[m["id"]] if not c.solved
                ],
                "count": len(module_challenges[m["id"]]),
                "solved": len([c for c in module_challenges[m["id"]] if c.solved])
            } for m in visible_modules
        }
    }


def view_profile(user):
    current_user = get_current_user()
    dojos = user_dojos(user)
    if user is not current_user:
        other_dojos = user_dojos(current_user)
        dojos = [ d for d in dojos if d in other_dojos ]

    public_dojos = [ d for d in dojos if d.public and not d.archived ]
    private_dojos = [ d for d in dojos if not d.public and not d.archived ]
    archived_dojos = [ d for d in dojos if d.archived ]
    stats = { d.id: dojo_full_stats(d, user) for d in dojos }

    global_position, total_solvers = user_standings(user)

    return render_template(
        "hacker.html",
        public_dojos=public_dojos, private_dojos=private_dojos, archived_dojos=archived_dojos, stats=stats,
        user=user, current_user=current_user, belt=belt_asset("black") if user.type == "admin" else belt_asset_for(user.id),
        global_position=global_position, total_solvers=total_solvers
    )

@users.route("/hackers/<int:user_id>")
def view_other(user_id):
    user = Users.query.filter_by(id=user_id).first()
    if user is None:
        abort(404)
    return view_profile(user)

@users.route("/hackers/<user_name>")
def view_named(user_name):
    user = Users.query.filter_by(name=user_name).first()
    if user is None:
        abort(404)
    return view_profile(user)

@users.route("/hacker")
@authed_only
def view_self():
    return view_profile(get_current_user())
