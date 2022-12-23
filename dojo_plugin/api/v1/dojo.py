import sqlalchemy
import subprocess
import tempfile
import logging
import pathlib
import shutil
import docker
import os
import re

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import and_
from CTFd.models import db, Solves, Challenges
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user, is_admin
from CTFd.utils.modes import get_model
from CTFd.utils.security.sanitize import sanitize_html

from ...models import Dojos, DojoMembers, DojoAdmins
from ...utils import dojo_standings, DOJOS_DIR, HTMLHandler, id_regex, sandboxed_git_clone, ctfd_to_host_path, is_dojo_admin, load_dojo
from ...utils.dojo import dojo_clone, load_dojo_dir


dojo_namespace = Namespace(
    "dojo", description="Endpoint to manage dojos"
)


def random_dojo_join_code():
    return os.urandom(8).hex()


@dojo_namespace.route("/change-join-code")
class UpdateJoinCode(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        user = get_current_user()

        dojo_id = data.get("dojo_id")
        dojo = Dojos.query.filter_by(id=dojo_id).first()
        if not is_dojo_admin(user, dojo):
            return {"success": False, "error": f"Invalid dojo specified: {data.get('dojo_id')}"}

        dojo.join_code = random_dojo_join_code()
        db.session.add(dojo)
        db.session.commit()
        return {"success": True, "dojo_id": dojo.id, "join_code": dojo.join_code}


@dojo_namespace.route("/leave")
class Leave(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        user = get_current_user()

        dojo_id = data.get("dojo_id")
        dojo = Dojos.query.filter_by(id=dojo_id).first()
        if not dojo:
            return {"success": False, "error": f"Invalid dojo specified: {data.get('dojo_id')}"}

        deleter = sqlalchemy.delete(DojoMembers).where(and_(DojoMembers.dojo == dojo, DojoMembers.user == user)).execution_options(synchronize_session="fetch")
        db.session.execute(deleter)
        db.session.commit()
        return {"success": True, "dojo_id": dojo.id}


@dojo_namespace.route("/make-public")
class MakePublic(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        user = get_current_user()

        dojo_id = data.get("dojo_id")
        dojo = Dojos.query.filter_by(id=dojo_id).first()
        if not is_dojo_admin(user, dojo):
            return {"success": False, "error": f"Invalid dojo specified: {data.get('dojo_id')}"}

        if not (is_admin() or any(award.name == "PUBLIC_DOJO" for award in user.awards)):
            return {
                "success": False,
                "error":
                """<p><b>You do not have authorization to make public dojos.</b></p>"""
                """<p>For authorization to make public dojos, please email """
                """<a href="mailto:pwn-college@asu.edu">pwn-college@asu.edu</a>.</p>"""
            }

        dojo.join_code = None
        db.session.add(dojo)
        db.session.commit()
        return {"success": True, "dojo_id": dojo.id}


@dojo_namespace.route("/delete")
class DeleteDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        user = get_current_user()

        dojo_id = data.get("dojo_id")
        dojo = Dojos.query.filter_by(id=dojo_id).first()
        if not is_dojo_admin(user, dojo):
            return {"success": False, "error": f"Invalid dojo specified: {data.get('dojo_id')}"}

        dojo_dir = DOJOS_DIR/str(user.id)/dojo.id
        if not dojo_dir.exists():
            return {"success": False, "error": "Dojo directory does not exist."}

        db.session.delete(dojo)
        db.session.commit()

        shutil.rmtree(str(dojo_dir))

        return {"success": True, "dojo_id": dojo.id}

@dojo_namespace.route("/create")
class CreateDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        user = get_current_user()

        try:
            GIT_REPO_RE = r"^(https://github.com/|git@github.com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
            dojo_repo = data.get("dojo_repo", "")
            assert re.match(GIT_REPO_RE, dojo_repo), (
                f"Repository violates regular expression. Must match <code>{GIT_RE}</code>."
            )

            dojo_dir = dojo_clone(dojo_repo)
            dojo_path = Pathlib.path(dojo_dir.name)

            dojo = load_dojo_dir(dojo_path)
            dojo.repository = dojo_repo
            dojo.admins = [DojoAdmins(user_id=user.id)]

            db.session.add(dojo)
            db.session.commit()

            dojo_path.rename(DOJOS_DIR / dojo.type / dojo.id)


        except AssertionError as e:
            return {"success": False, "error": str(e)}, 400

        except subprocess.CalledProcessError as e:
            return {"success": False, "error": str(e.stderr)}, 400

        return {"success": True, "dojo_id": dojo.dojo_id}


@dojo_namespace.route("/join")
class JoinDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        join_code = data.get("join_code", "")
        grade_token = data.get("grade_token", "")

        if not id_regex(grade_token):
            return {"success": False, "error": "Invalid grade token."}

        user = get_current_user()

        dojo = Dojos.query.filter_by(join_code=join_code).first()
        if not dojo:
            return (
                {"success": False, "error": "Private dojo not found"},
                404
            )

        membership = DojoMembers.query.filter_by(dojo=dojo, user=user).first()
        if membership:
            membership.grade_token = grade_token
        else:
            membership = DojoMembers(dojo=dojo, user=user, grade_token=grade_token)

        try:
            db.session.add(membership)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

        return {"success": True}


@dojo_namespace.route("/solves")
class DojoSolves(Resource):
    @authed_only
    def get(self):
        user = get_current_user()
        dojo_id = f"private-{user.id}"

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
