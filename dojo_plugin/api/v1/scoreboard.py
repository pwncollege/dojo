import contextlib
import math
import datetime

from flask import url_for
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model, generate_account_url

from ...utils import dojo_route, dojo_standings
from .belts import get_belts


def email_group_asset(email):
    if email.endswith("@asu.edu"):
        group = "fork.png"
    elif email.endswith(".edu"):
        group = "student.png"
    else:
        group = "hacker.png"
    return url_for("views.themes", path=f"img/dojo/{group}")


def belt_asset(color):
    if color == "blue":
        belt = "blue.svg"
    elif color == "yellow":
        belt = "yellow.svg"
    else:
        belt = "white.svg"
    return url_for("views.themes", path=f"img/dojo/{belt}")


@cache.memoize(timeout=60)
def get_standings(count=None, filters=None, *, dojo_id=None):
    if filters is None:
        filters = []

    Model = get_model()
    score = db.func.sum(Challenges.value).label("score")
    fields = [
        Solves.account_id,
        Model.name,
        Model.email,
        score
    ]
    standings_query = (
        dojo_standings(dojo_id, fields)
        .filter(*filters)
        .group_by(Solves.account_id)
        .order_by(score.desc(), db.func.max(Solves.id))
    )

    if count is None:
        standings = standings_query.all()
    else:
        standings = standings_query.limit(count).all()

    return standings


def standing_info(place, standing):
    belts = get_belts()["users"]
    return {
        "place": place,
        "name": standing.name,
        "score": int(standing.score),
        "url": generate_account_url(standing.account_id),
        "symbol": email_group_asset(standing.email),
        "belt": belt_asset(belts.get(standing.account_id, {}).get("color")),
    }


def get_scoreboard_data(page, filters, *, dojo=None):
    user = get_current_user()

    standings = get_standings(filters=filters, dojo_id=dojo.id if dojo else None)

    page_size = 20
    start = page_size * page
    end = page_size * (page + 1)
    page_standings = list((start + i + 1, standing) for i, standing in enumerate(standings[start:end]))

    result = {
        "page_standings": [standing_info(place, standing) for place, standing in page_standings],
        "num_pages": math.ceil(len(standings) / page_size),
    }

    if user:
        with contextlib.suppress(StopIteration):
            place, standing = next((i + 1, standing) for i, standing in enumerate(standings)
                                   if standing.account_id == user.id)
            result["me"] = standing_info(place, standing)

    return result


scoreboard_namespace = Namespace("scoreboard")


@scoreboard_namespace.route("/<dojo>/overall/<int:page>")
class ScoreboardOverall(Resource):
    @dojo_route
    def get(self, dojo, page):
        return get_scoreboard_data(page=page, filters=None, dojo=dojo)

@scoreboard_namespace.route("/<dojo>/week/<int:page>")
class ScoreboarWeek(Resource):
    @dojo_route
    def get(self, dojo, page):
        week_filter = Solves.date > (datetime.datetime.utcnow() - datetime.timedelta(days=7))
        return get_scoreboard_data(page=page, filters=[week_filter], dojo=dojo)

@scoreboard_namespace.route("/<dojo>/month/<int:page>")
class ScoreboardMonth(Resource):
    @dojo_route
    def get(self, dojo, page):
        month_filter = Solves.date > (datetime.datetime.utcnow() - datetime.timedelta(days=31))
        return get_scoreboard_data(page=page, filters=[month_filter], dojo=dojo)

@scoreboard_namespace.route("/<dojo>/semester/<int:page>")
class ScoreboardSemester(Resource):
    @dojo_route
    def get(self, dojo, page):
        semester_filter = Solves.date > datetime.date(year=2022, month=8, day=10)
        return get_scoreboard_data(page=page, filters=[semester_filter], dojo=dojo)
