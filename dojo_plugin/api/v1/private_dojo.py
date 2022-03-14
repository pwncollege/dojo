import os

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from CTFd.models import db, Solves, Challenges
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model

from ...models import PrivateDojos, PrivateDojoMembers, PrivateDojoActives
from ...utils import validate_dojo_data, dojo_standings


private_dojo_namespace = Namespace(
    "private_dojo", description="Endpoint to manage private dojos"
)


def activate_dojo(user_id, dojo_id):
    if dojo_id is not None:
        dojo = PrivateDojos.query.filter_by(id=dojo_id).first()
        if not dojo:
            return False

        member = PrivateDojoMembers.query.filter_by(dojo_id=dojo_id, user_id=user_id).first()
        if not member:
            return False

    active = PrivateDojoActives.query.filter_by(user_id=user_id).first()
    if not active:
        active = PrivateDojoActives(user_id=user_id)
        db.session.add(active)
    active.dojo_id = dojo_id
    db.session.commit()

    return True


def random_dojo_code():
    return os.urandom(8).hex()


@private_dojo_namespace.route("/initialize")
class InitializeDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()

        name = data.get("name", "")
        if not 0 < len(name) < 64:
            return (
                {"success": False, "error": "Invalid dojo name"},
                400
            )

        dojo_data = data.get("data")
        if dojo_data:
            if len(dojo_data) > 2 ** 20:
                return (
                    {"success": False, "error": "YAML Size Error: maximum size allowed is 1 MiB"},
                    400
                )
            try:
                validate_dojo_data(dojo_data)
            except AssertionError as e:
                return (
                    {"success": False, "error": str(e)},
                    400
                )

        user = get_current_user()

        while True:
            try:
                dojo = PrivateDojos.query.filter_by(id=user.id).first()
                if not dojo:
                    dojo = PrivateDojos(id=user.id)
                    db.session.add(dojo)
                dojo.name = name
                dojo.code = random_dojo_code()
                dojo.data = dojo_data if dojo_data else None
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
            else:
                break

        return {"success": True, "code": dojo.code, "id": dojo.id}


@private_dojo_namespace.route("/join")
class JoinDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        code = data.get("code", "")

        user = get_current_user()

        dojo = PrivateDojos.query.filter_by(code=code).first()
        if not dojo:
            return (
                {"success": False, "error": "Private dojo not found"},
                404
            )

        member = PrivateDojoMembers(dojo_id=dojo.id, user_id=user.id)
        try:
            db.session.add(member)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

        activate_dojo(user.id, dojo.id)

        return {"success": True}


@private_dojo_namespace.route("/activate")
class ActivateDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        dojo_id = data.get("id")

        try:
            dojo_id = int(dojo_id)
        except (ValueError, TypeError):
            dojo_id = None

        user = get_current_user()

        if not activate_dojo(user.id, dojo_id):
            return (
                {"success": False, "error": "Private dojo not found"},
                404
            )

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
