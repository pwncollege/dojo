from flask_restx import Namespace, Resource
from CTFd.cache import cache
from CTFd.models import db, Users, Solves

from ...utils import belt_challenges


belts_namespace = Namespace("belts", description="Endpoint to manage belts")


@cache.memoize(timeout=60)
def get_belts():
    result = {
        "dates": {},
        "users": {},
    }

    for color, challenges in belt_challenges().items():
        result["dates"][color] = {}

        belted_users = (
            db.session.query(Users.id, Users.name, db.func.max(Solves.date))
            .join(Solves, Users.id == Solves.user_id)
            .filter(Solves.challenge_id.in_(challenges.subquery()))
            .group_by(Users.id)
            .having(db.func.count() == challenges.count())
            .order_by(db.func.max(Solves.date))
        )

        for user_id, handle, date in belted_users:
            result["dates"][color][user_id] = str(date)
            result["users"][user_id] = {
                "handle": handle,
                "color": color,
            }

    return result


@belts_namespace.route("")
class Belts(Resource):
    def get(self):
        return get_belts()
