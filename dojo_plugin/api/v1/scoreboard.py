import collections
import contextlib
import datetime
import math
import pytz

from flask import url_for
from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import db, Solves, Challenges, Users
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model, generate_account_url

from ...models import Dojos
from ...utils import dojo_route, dojo_standings, dojo_by_id, dojo_completions, user_dojos, first_bloods, daily_solve_counts
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
    if color == "black":
        belt = "black.svg"
    elif color == "blue":
        belt = "blue.svg"
    elif color == "yellow":
        belt = "yellow.svg"
    else:
        belt = "white.svg"
    return url_for("views.themes", path=f"img/dojo/{belt}")

def belt_asset_for(user_id):
    belts = get_belts()["users"]
    return belt_asset(belts.get(user_id, {}).get("color"))

@cache.memoize(timeout=60)
def get_standings(count=None, span=None, *, dojo_id=None, module_id=None):
    dojo = dojo_by_id(dojo_id)
    if span in [ None, 'overall', 'dojo' ]:
        start = None
    elif span == 'week':
        start = datetime.datetime.now(pytz.utc) - datetime.timedelta(days=7)
    elif span == 'month':
        start = datetime.datetime.now(pytz.utc) - datetime.timedelta(days=31)
    elif span == 'module':
        if not module_id:
            abort(500)
        module = dojo.module_by_id(module_id)
        start = module["time_assigned"] if "time_assigned" in module else None

    if dojo and "time_created" in dojo.config and (start is None or dojo.config["time_created"] > start):
        start = dojo.config["time_created"]
    filters = [ Solves.date > start ] if start else [ ]

    Model = get_model()
    score = db.func.count(Challenges.id.distinct()).label("score")
    fields = [
        Solves.account_id,
        Model.name,
        Model.email,
        score
    ]
    standings_query = (
        dojo_standings(dojo_id, fields, module_id=module_id)
        .filter(*filters)
        .group_by(Solves.account_id)
        .order_by(score.desc(), db.func.max(Solves.id))
    )

    if count is None:
        standings = standings_query.all()
    else:
        standings = standings_query.limit(count).all()

    return standings


@cache.memoize(timeout=60)
def global_hacker_stats():
    MANY_SOLVE_THRESHOLD = 50

    all_users = Users.query.filter_by(banned=False, hidden=False).all()
    completions = dojo_completions()
    dojo_emojis = { d.id: d.config["completion_emoji"] for d in Dojos.query.all() if "completion_emoji" in d.config }

    _bloods = first_bloods()
    blood_counts = collections.Counter(b.user_id for b in _bloods)
    blood_timestamps = { }
    for b in _bloods:
        blood_timestamps.setdefault(b.user_id, []).append(b.timestamp)

    max_daily_solves = { }
    many_solve_days = { }
    for s in daily_solve_counts():
        max_daily_solves[s.user_id] = max(max_daily_solves.get(s.user_id, 0), s.solves)
        if s.solves >= MANY_SOLVE_THRESHOLD:
            many_solve_days.setdefault(s.user_id, []).append(
                datetime.datetime(year=s.year, month=s.month, day=s.day, hour=23, minute=59, second=59)
            )

    all_stats = { }
    for user in all_users:
        badges = [ ]

        # many solve badges
        #if len(many_solve_days.get(user.id, [])):
        #   badges.append({
        #       "emoji": "&#129302;", # robot emoji
        #       "count": len(many_solve_days[user.id]),
        #       "timestamp": many_solve_days[user.id][0],
        #       "text": f"This emoji is earned by solving more than 50 non-embryo challenges in a single day (UTC reckoning)."
        #   })

        # dojo completion badges
        for completion in completions.get(user.id, []):
            if completion["dojo"] in dojo_emojis:
                badges.append({
                    "emoji": dojo_emojis[completion["dojo"]],
                    "count": 1,
                    "url": url_for("pwncollege_dojo.listing", dojo=completion["dojo"]),
                    "dojo": completion["dojo"],
                    "timestamp": completion["last_solve"],
                    "text": f"""This emoji was earned by completing all challenges in the {completion["dojo"]} dojo."""
                })

        # first blood badges
        if blood_counts.get(user.id, 0):
            badges.append({
                "emoji": "&#128640;",
                "count": blood_counts[user.id],
                "timestamp": blood_timestamps[user.id][0],
                "text": "This emoji is awarded for being the first hacker to solve a challenge."
            })

        # sort badges by timestamp
        badges.sort(key=lambda i: i.get("timestamp"))

        stats = {
            "badges": badges,
            "dojos_completed": completions.get(user.id, []),
            "first_blood_count": blood_counts[user.id],
            "max_solves_per_day": max_daily_solves.get(user.id, []),
            "num_many_solve_days": many_solve_days.get(user.id, 0),
        }
        all_stats[user.id] = stats

    return all_stats


def get_scoreboard_data(page, span, *, dojo=None, module=None):
    user = get_current_user()
    visible_dojos = { d.id for d in user_dojos(user) }

    standings = get_standings(span=span, dojo_id=dojo.id if dojo else None, module_id=module["id"] if module else None)
    hacker_stats = global_hacker_stats()

    def standing_info(_place, _standing):
        _info = {
            "place": _place,
            "name": _standing.name,
            "account_id": _standing.account_id,
            "score": int(_standing.score),
            "url": generate_account_url(_standing.account_id).replace("users", "hackers"),
            "symbol": email_group_asset(_standing.email),
            "belt": belt_asset_for(_standing.account_id),
        }
        _info.update(hacker_stats.get(_standing.account_id, {}))
        _info["dojos_completed"] = [ (c if c["dojo"] in visible_dojos else "<redacted>") for c in _info["dojos_completed"] ]
        _info["badges"] = [ (b if ("dojo" not in b or b["dojo"] in visible_dojos) else dict(
            b, dojo="<redacted>", url="#",
            text="This emoji was earned by completing all challenges in a dojo you cannot view."
        )) for b in _info["badges"] ]
        return _info

    page_size = 20
    start = page_size * page
    end = page_size * (page + 1)
    page_standings = list((start + i + 1, standing) for i, standing in enumerate(standings[start:end]))

    result = {
        "page_standings": [ standing_info(place, standing) for place, standing in page_standings],
        "num_pages": math.ceil(len(standings) / page_size),
    }

    if user:
        with contextlib.suppress(StopIteration):
            place, standing = next((i + 1, standing) for i, standing in enumerate(standings)
                                   if standing.account_id == user.id)
            result["me"] = standing_info(place, standing)

    return result


scoreboard_namespace = Namespace("scoreboard")

@scoreboard_namespace.route("/<span>/<int:page>")
class ScoreboardGlobal(Resource):
    def get(self, span, page):
        return get_scoreboard_data(page=page, span=span)

@scoreboard_namespace.route("/<dojo>/<span>/<int:page>")
class ScoreboardDojo(Resource):
    @dojo_route
    def get(self, dojo, span, page):
        return get_scoreboard_data(page=page, span=span, dojo=dojo)

@scoreboard_namespace.route("/<dojo>/<module>/<span>/<int:page>")
class ScoreboardModule(Resource):
    @dojo_route
    def get(self, dojo, module, span, page):
        return get_scoreboard_data(page=page, module=module, span=span, dojo=dojo)
