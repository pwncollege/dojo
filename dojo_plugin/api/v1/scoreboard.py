import contextlib
import math
import datetime

from flask_restx import Namespace, Resource
from sqlalchemy.sql import or_, and_
from CTFd.cache import cache
from CTFd.models import db, Solves, Challenges
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model, generate_account_url

from ...models import PrivateDojoMembers
from ...utils import active_dojo_id, dojo_modules
from .belts import get_belts


def email_group_asset(email):
    if email.endswith("@asu.edu"):
        group = "fork.png"
    elif email.endswith(".edu"):
        group = "student.png"
    else:
        group = "hacker.png"
    return f"/plugins/dojo_plugin/assets/scoreboard/{group}"


def belt_asset(color):
    if color == "blue":
        belt = "blue.svg"
    elif color == "yellow":
        belt = "yellow.svg"
    else:
        belt = "white.svg"
    return f"/plugins/dojo_plugin/assets/scoreboard/{belt}"


@cache.memoize(timeout=60)
def get_standings(count=None, fields=None, filters=None, *, dojo_id=None):
    if fields is None:
        fields = []
    if filters is None:
        filters = []
    Model = get_model()

    private_dojo_filters = []
    if dojo_id is not None:
        modules = dojo_modules(dojo_id)
        challenges_filter = or_(*(
            and_(Challenges.category == module_challenge["category"],
                 Challenges.name.in_(module_challenge["names"]))
            if module_challenge.get("names") else
            Challenges.category == module_challenge["category"]
            for module in modules
            for module_challenge in module.get("challenges", [])
        ))
        private_dojo_filters.append(challenges_filter)

        members = db.session.query(PrivateDojoMembers.user_id).filter_by(dojo_id=dojo_id)
        private_dojo_filters.append(Solves.account_id.in_(members.subquery()))

    score = db.func.sum(Challenges.value).label("score")
    standings_query = (
        db.session.query(
            Solves.account_id,
            Model.name,
            score,
            *fields,
        )
        .join(Challenges)
        .join(Model, Model.id == Solves.account_id)
        .group_by(Solves.account_id)
        .filter(Challenges.value != 0, Model.banned == False, Model.hidden == False,
                *filters, *private_dojo_filters)
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

        Model = get_model()
        standings = get_standings(fields=[Model.email], dojo_id=dojo_id)

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

        Model = get_model()

        week_filter = Solves.date > (datetime.datetime.utcnow() - datetime.timedelta(days=7))
        standings = get_standings(count=10, fields=[Model.email], filters=[week_filter], dojo_id=dojo_id)

        page_standings = list((i + 1, standing) for i, standing in enumerate(standings))

        result = {
            "page_standings": [standing_info(place, standing) for place, standing in page_standings],
        }
        return result
