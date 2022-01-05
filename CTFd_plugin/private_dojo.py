import os
import re
import datetime

import yaml
from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from CTFd.models import db
from CTFd.utils import get_config
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user


class PrivateDojos(db.Model):
    __tablename__ = "private_dojos"
    id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    name = db.Column(db.Text)
    code = db.Column(db.Text, unique=True)
    data = db.Column(db.Text)


class PrivateDojoMembers(db.Model):
    __tablename__ = "private_dojo_members"
    dojo_id = db.Column(db.Integer, db.ForeignKey("private_dojos.id", ondelete="CASCADE"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class PrivateDojoActives(db.Model):
    __tablename__ = "private_dojo_actives"
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    dojo_id = db.Column(db.Integer, db.ForeignKey("private_dojos.id", ondelete="CASCADE"))


private_dojo_namespace = Namespace(
    "private_dojo", description="Endpoint to manage private dojos"
)


def user_dojos(user_id):
    active = PrivateDojoActives.dojo_id.isnot(None).label("active")
    return (
        db.session.query(PrivateDojos.id, PrivateDojos.name, active)
        .join(PrivateDojoMembers, PrivateDojos.id == PrivateDojoMembers.dojo_id)
        .filter(PrivateDojoMembers.user_id == user_id)
        .outerjoin(PrivateDojoActives, PrivateDojos.id == PrivateDojoActives.dojo_id)
        .all()
    )


def active_dojo_id(user_id):
    active = PrivateDojoActives.query.filter_by(user_id=user_id).first()
    if not active:
        return None
    return active.dojo_id


def dojo_modules(dojo_id=None):
    if dojo_id is not None:
        dojo = PrivateDojos.query.filter(PrivateDojos.id == dojo_id).first()
        if dojo and dojo.data:
            return yaml.safe_load(dojo.data)
    return yaml.safe_load(get_config("modules"))


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


def validate_dojo_data(data):
    try:
        data = yaml.safe_load(data)
    except yaml.error.YAMLError as e:
        assert False, f"YAML Error:\n{e}"

    if data is None:
        return None

    def type_assert(object_, type_, name):
        assert isinstance(object_, type_), f"YAML Type Error: {name} expected type `{type_.__name__}`, got `{type(object_).__name__}`"

    type_assert(data, list, "outer most")

    for module in data:
        type_assert(module, dict, "module")

        def type_check(name, type_, required=True, container=module):
            if required and name not in container:
                assert False, f"YAML Required Error: missing field `{name}`"
            if name not in container:
                return
            value = container.get(name)
            if isinstance(type_, str):
                match = isinstance(value, str) and re.fullmatch(type_, value)
                assert match, f"YAML Type Error: field `{name}` must be of type `{type_}`"
            else:
                type_assert(value, type_, f"field `{name}`")

        type_check("name", "[\w ]+", required=True)
        type_check("permalink", "\w+", required=True)
        type_check("category", "\w+", required=False)
        type_check("deadline", datetime.datetime, required=False)
        type_check("late", float, required=False)

        type_check("lectures", list, required=False)
        for lecture in module.get("lectures", []):
            type_assert(lecture, dict, "lecture")
            type_check("name", "[\w :]+", required=True, container=lecture)
            type_check("video", "[\w-]+", required=True, container=lecture)
            type_check("playlist", "[\w-]+", required=True, container=lecture)
            type_check("slides", "[\w-]+", required=True, container=lecture)

    return yaml.safe_dump(data, sort_keys=False)


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
                dojo_data = validate_dojo_data(dojo_data)
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
