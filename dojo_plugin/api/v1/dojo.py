import sqlalchemy
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

from ...models import Dojos, DojoMembers
from ...utils import dojo_standings, DOJOS_DIR, HTMLHandler, id_regex, sandboxed_git_clone, ctfd_to_host_path, is_dojo_admin, load_dojo


dojo_namespace = Namespace(
    "dojo", description="Endpoint to manage private dojos"
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

        with tempfile.TemporaryDirectory(dir=DOJOS_DIR, prefix=str(user.id), suffix=".git-clone") as tmp_dir:
            try:
                dojo_repo = data.get("dojo_repo")
                GIT_SSH_REGEX = "^git@github.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
                GIT_HTTPS_REGEX = "^https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
                assert re.match(GIT_SSH_REGEX, dojo_repo) or re.match(GIT_HTTPS_REGEX, dojo_repo), (
                    f"Repository violates regular expression. Must match <code>{GIT_SSH_REGEX}</code> or <code>{GIT_HTTPS_REGEX}</code>."
                )

                # clone it!
                clone_dir = pathlib.Path(tmp_dir)/"clone"
                clone_dir.mkdir()
                returncode, output = sandboxed_git_clone(dojo_repo, str(ctfd_to_host_path(clone_dir)))

                N=b"\n"
                assert returncode == 0, (
                    f"Dojo clone failed with error code {returncode}:<br>"
                    f"<code>{output.replace(N,b'<br>').decode('latin1')}</code><br>"
                    "Please make sure that you properly added the deploy key to the repository settings, "
                    "and properly entered the repository URL."
                )

                # figure out the dojo ID
                dojo_specs = list(clone_dir.glob("*.yml"))
                assert len(dojo_specs) == 1, (
                    f"Dojo repository must have exactly one top-level dojo spec yml named {{YOUR_DOJO_ID}}.yml. Yours has: {dojo_specs}"
                )
                dojo_id = dojo_specs[0].stem
                assert id_regex(dojo_id), (
                    f"Your dojo ID (the extensionless name of your .yml file) must be a valid URL component."
                )

                # make sure there aren't any symlink shenanigans
                assert dojo_specs[0].is_file() and not dojo_specs[0].is_symlink(), (
                    f"{dojo_specs[0].name} is not a regular file!"
                )

                # make sure we're not overwriting unintentionally
                dojo_permanent_dir = pathlib.Path(DOJOS_DIR)/str(user.id)/dojo_id
                if data.get("dojo_replace", False) not in ("true", True, 1):
                    assert not dojo_permanent_dir.exists(), (
                        f"You already have a cloned dojo repository containing a dojo with ID {dojo_id}."
                    )

                # make sure we're not overwriting someone else's dojo
                existing_dojo = Dojos.query.filter_by(id=dojo_id).first()
                if existing_dojo is not None:
                    assert existing_dojo.owner_id == user.id, (
                        f"A dojo with the ID {dojo_id} was already created by a different user. Please choose a different ID."
                    )
                    join_code = existing_dojo.join_code
                else:
                    join_code = random_dojo_join_code()

                # do a test load
                log_handler = HTMLHandler()
                logger = logging.getLogger(f"dojo-load-{user.id}-{dojo_id}")
                logger.setLevel('DEBUG')
                logger.addHandler(log_handler)
                load_dojo(
                    dojo_id, dojo_specs[0].read_text(),
                    user=user, commit=False, dojo_dir=clone_dir, log=logger
                )
                assert ("WARNING" not in log_handler.html) and ("ERROR" not in log_handler.html), (
                    "A test load of your dojo resulted in the following log messages. Please fix all warnings and try again.<br>" +
                    log_handler.html
                )

                # move the pulled dojo in
                if dojo_permanent_dir.exists():
                    shutil.rmtree(dojo_permanent_dir)
                dojo_permanent_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(clone_dir, dojo_permanent_dir)

                # load it for real!
                log_handler.reset()
                load_dojo(
                    dojo_id, (dojo_permanent_dir/(dojo_id+".yml")).read_text(),
                    user=user, commit=True, dojo_dir=dojo_permanent_dir, log=logger, initial_join_code=join_code
                )
                html_logs = log_handler.html
            except AssertionError as e:
                return (
                    {"success": False, "error": e.args[0]},
                    400
                )

        return {"success": True, "dojo_id": dojo_id, "load_logs": html_logs}


@dojo_namespace.route("/join")
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
