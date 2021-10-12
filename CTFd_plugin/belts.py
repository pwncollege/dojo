import collections

from flask_restx import Namespace, Resource
from CTFd.models import db, Users, Challenges, Solves

belts_namespace = Namespace("belts", description="Endpoint to manage belts")


yellow_categories = [
    "embryoio",
    "babysuid",
    "embryoasm",
    "babyshell",
    "babyjail",
    "embryogdb",
    "babyrev",
    "babymem",
    "toddlerone",
]

blue_categories = [
    *yellow_categories,
    "babyrop",
    "babykernel",
    "babyheap",
    "babyrace",
    "toddlertwo",
]


class BeltInfos(db.Model):
    __tablename__ = "belt_infos"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name = db.Column(db.Text)
    emoji = db.Column(db.Text)
    email = db.Column(db.Text)
    website = db.Column(db.Text)


def get_belts():
    color_categories = {
        "yellow": yellow_categories,
        # "blue": blue_categories,
    }

    result = {
        "colors": {
            color: {}
            for color in color_categories
        },
        "info": {},
    }

    for color, categories in color_categories.items():
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

        for user_id, handle, date in belted_users:
            result["colors"][color][user_id] = str(date)
            result["info"][user_id] = {
                "handle": Users.name
            }

    return result


@belts_namespace.route("")
class Belts(Resource):
    def get(self):
        return get_belts()
