import contextlib
import math
import datetime

from flask import url_for
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model, generate_account_url

from ...utils import active_dojo_id, dojo_standings
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


scoreboard_namespace = Namespace("scoreboard")


@scoreboard_namespace.route("/overall/<int:page>")
class ScoreboardOverall(Resource):
    def get(self, page):
        user = get_current_user()
        dojo_id = active_dojo_id(user.id) if user else None

        standings = get_standings(dojo_id=dojo_id)

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


@scoreboard_namespace.route("/weekly")
class ScoreboardWeekly(Resource):
    def get(self):
        user = get_current_user()
        dojo_id = active_dojo_id(user.id) if user else None

        week_filter = Solves.date > (datetime.datetime.utcnow() - datetime.timedelta(days=7))
        standings = get_standings(count=10, filters=[week_filter], dojo_id=dojo_id)

        page_standings = list((i + 1, standing) for i, standing in enumerate(standings))

        result = {
            "page_standings": [standing_info(place, standing) for place, standing in page_standings],
        }
        return result
