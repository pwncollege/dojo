import sqlalchemy
import datetime

from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import db, Users, Solves

from ...models import Dojos
from ...utils.dojo import BELT_REQUIREMENTS


belts_namespace = Namespace("belts", description="Endpoint to manage belts")


@cache.memoize(timeout=60)
def get_belts():
    result = {
        "dates": {},
        "users": {},
    }

    for n,(color,dojo_id) in enumerate(BELT_REQUIREMENTS.items()):
        result["dates"][color] = {}
        try:
            dojo = Dojos.query.filter_by(id=dojo_id).first()
        except sqlalchemy.exc.NoResultsFound:
            # We are likely missing the correct dojos in the DB (e.g., custom deployment)
            break

        for user,date in dojo.completions():
            if result["users"].get(user.id, {"rank_id":-1})["rank_id"] != n-1:
                continue
            result["dates"][color][user.id] = str(date)
            result["users"][user.id] = {
                "handle": user.name,
                "color": color,
                "rank_id": n,
            }

    return result


@belts_namespace.route("")
class Belts(Resource):
    def get(self):
        return get_belts()
