import datetime

from CTFd.cache import cache
from CTFd.models import Awards
from flask import url_for
from ..models import Dojos


CUMULATIVE_CUTOFF = datetime.datetime(2023, 10, 1)
BELT_REQUIREMENTS = {
    "orange": "intro-to-cybersecurity",
    "yellow": "program-security",
    "green": "system-security",
    "blue": "software-exploitation",
}

def belt_asset(color):
    belt = color + ".svg" if color in BELT_REQUIREMENTS else "white.svg"
    return url_for("views.themes", path=f"img/dojo/{belt}")

def get_user_belts(user):
    result = [ ]
    for belt, dojo_id in BELT_REQUIREMENTS.items():
        dojo = Dojos.query.filter(Dojos.official, Dojos.id == dojo_id).one()
        if not dojo.completed(user):
            break
        result.append(belt.title() + " Belt")
    return result

@cache.memoize(timeout=60)
def get_belts():
    result = {
        "dates": {},
        "users": {},
        "ranks": {},
    }

    for n,(color,dojo_id) in enumerate(BELT_REQUIREMENTS.items()):
        dojo = Dojos.query.filter_by(id=dojo_id).first()
        if not dojo:
            # We are likely missing the correct dojos in the DB (e.g., custom deployment)
            break

        result["dates"][color] = {}
        result["ranks"][color] = []

        belt_awards = [ (award.user, award.date) for award in Awards.query.filter_by(name="BELT_"+color.upper()) ]
        awarded_ids = set(u.id for u,_ in belt_awards)
        sorted_belts = sorted(belt_awards + dojo.completions(), key=lambda d: d[1])

        for user,date in sorted_belts:
            if (
                date > CUMULATIVE_CUTOFF and
                user.id not in awarded_ids and
                result["users"].get(user.id, {"rank_id":-1})["rank_id"] != n-1
            ):
                continue

            result["dates"][color][user.id] = str(date)
            result["users"][user.id] = {
                "handle": user.name,
                "site": user.website,
                "color": color,
                "date": str(date),
                "rank_id": n,
            }

    for user_id in result["users"]:
        result["ranks"][result["users"][user_id]["color"]].append(user_id)

    return result
