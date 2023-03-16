import functools
from flask import Blueprint, render_template, abort
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only
from CTFd.models import db, Users, Challenges, Solves
from CTFd.cache import cache

from ..models import Dojos
from ..utils.dojo import dojo_scoreboard_data


users = Blueprint("pwncollege_users", __name__)


def hacker_rank(user, dojo, module=None):
    return (
        dojo_scoreboard_data(dojo, module, fields=[])
        .filter(Users.id == user.id)
        .first()
    )


def view_hacker(user):
    current_user_dojos = set(Dojos.viewable(user=get_current_user()))
    dojos = [dojo for dojo in Dojos.viewable(user=user) if dojo in current_user_dojos]

    def competitors(dojo, module=None, user=None):
        query = dojo_scoreboard_data(dojo, module)
        if user:
            return db.session.query(query.subquery()).filter_by(user_id=user.id).first()
        return query

    return render_template("hacker.html", dojos=dojos, user=user, competitors=competitors)

@users.route("/hacker/<int:user_id>")
def view_other(user_id):
    user = Users.query.filter_by(id=user_id).first()
    if user is None:
        abort(404)
    return view_hacker(user)

@users.route("/hacker/")
@authed_only
def view_self():
    return view_hacker(get_current_user())
