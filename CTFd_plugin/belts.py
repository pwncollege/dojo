from flask_restx import Namespace, Resource
from CTFd.models import db, Users, Challenges, Solves

belts_namespace = Namespace("belts", description="Endpoint to manage belts")


yellow_categories = [
    "babysuid",
    "babyshell",
    "babyjail",
    "babyrev",
    "babymem",
    "toddler1",
]

blue_categories = [
    *yellow_categories,
    "babyrop",
    "babykernel",
    "babyheap",
    "babyrace",
    "toddler2",
    "babyauto",
]


def belts(categories):
    required_challenges = db.session.query(Challenges.id).filter(
        Challenges.state == "visible",
        Challenges.value > 0,
        Challenges.category.in_(categories),
    )

    belted_users = (
        db.session.query(Users.id, Users.name, db.func.max(Solves.date))
        .join(Solves, Users.id == Solves.user_id)
        .filter(Solves.challenge_id.in_(required_challenges.subquery()))
        .group_by(Users.id)
        .having(db.func.count() == required_challenges.count())
        .order_by(db.func.max(Solves.date))
    )

    belts = {
        user_id: {"handle": handle, "date": date.isoformat()}
        for user_id, handle, date in belted_users
    }

    return belts


@belts_namespace.route("/yellow")
class YellowBelts(Resource):
    def get(self):
        return belts(yellow_categories)


@belts_namespace.route("/blue")
class BlueBelts(Resource):
    def get(self):
        return belts(blue_categories)
