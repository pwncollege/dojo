import os

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from CTFd.models import db, Solves, Challenges
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model

from ...models import Dojos, DojoMembers
from ...utils import dojo_standings


private_dojo_namespace = Namespace(
    "private_dojo", description="Endpoint to manage private dojos"
)


def random_dojo_join_code():
    return os.urandom(8).hex()


@private_dojo_namespace.route("/initialize")
class InitializeDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()

        dojo_data = data.get("data")
        if dojo_data and len(dojo_data) > 2 ** 20:
            return (
                {"success": False, "error": "YAML Size Error: maximum size allowed is 1 MiB"},
                400
            )

        user = get_current_user()

        while True:
            try:
                dojo = Dojos.query.filter_by(owner_id=user.id).first()
                if not dojo:
                    dojo = Dojos(id=str(user.id), owner_id=user.id)
                    db.session.add(dojo)
                dojo.join_code = random_dojo_join_code()
                dojo.data = dojo_data
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
            except AssertionError as e:
                return (
                    {"success": False, "error": str(e)},
                    400
                )
            else:
                break

        return {"success": True, "join_code": dojo.join_code, "id": dojo.id}


@private_dojo_namespace.route("/join")
class JoinDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        join_code = data.get("join_code", "")

        user = get_current_user()

        dojo = Dojos.query.filter_by(join_code=join_code).first()
        if not dojo:
            return (
                {"success": False, "error": "Private dojo not found"},
                404
            )

        member = DojoMembers(dojo_id=dojo.id, user_id=user.id)
        try:
            db.session.add(member)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

        return {"success": True}


@private_dojo_namespace.route("/solves")
class DojoSolves(Resource):
    @authed_only
    def get(self):
        user = get_current_user()
        dojo_id = user.id

        Model = get_model()
        fields = {
            "account_id": Solves.account_id,
            "account_name": Model.name,
            "account_email": Model.email,
            "challenge_id": Challenges.id,
            "challenge_category": Challenges.category,
            "challenge_name": Challenges.name,
            "solve_time": Solves.date,
        }
        standings = (
            dojo_standings(dojo_id, fields.values())
            .order_by(Solves.id)
            .all()
        )
        return [dict(zip(fields, standing)) for standing in standings]
