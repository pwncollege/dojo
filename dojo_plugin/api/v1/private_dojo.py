import subprocess
import pathlib
import shutil
import os
import re

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from CTFd.models import db, Solves, Challenges
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model

from ...models import Dojos, DojoMembers
from ...utils import dojo_standings, DOJOS_DIR, DOJOS_PRIV_KEY


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
                    dojo = Dojos(id=f"private-{user.id}", owner_id=user.id)
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

GIT_REGEX = "^git@github.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"

@private_dojo_namespace.route("/create")
class CreateDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()

        dojo_repo = data.get("dojo_repo")
        if not re.match(GIT_REGEX, dojo_repo):
            return (
                {"success": False, "error": f"Repository violates regular expression: <code>{GIT_REGEX}</code>."},
                400
            )

        user = get_current_user()
        user_pull_dir = (pathlib.Path(DOJOS_DIR)/str(user.id)).with_suffix(".tmp")
        dojo_pull_dir = user_pull_dir/dojo_repo.split("/")[-1]
        dojo_permanent_dir = pathlib.Path(DOJOS_DIR)/str(user.id)/dojo_repo.split("/")[-1]

        if user_pull_dir.exists():
            shutil.rmtree(user_pull_dir)
        dojo_pull_dir.mkdir(parents=True, exist_ok=True)
        try:
            clone_result = subprocess.run(
                [ "git", "clone", "--depth", "1", dojo_repo, str(dojo_pull_dir) ],
                env={
                    "GIT_SSH_COMMAND":
                    f"ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o LogLevel=ERROR -i {DOJOS_PRIV_KEY}"
                },
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='latin1',
                check=False
            )
            N="\n"
            assert "Permission denied (publickey)" not in clone_result.stdout, (
                f"Dojo clone failed with <code>'Permission denied (publickey)'</code>. Most likely, the deploy key has not been"
                f" added to the {dojo_repo} repository."
            )
            assert clone_result.returncode == 0, (
                f"Dojo clone failed with error code {clone_result.returncode}:<br><code>{clone_result.stdout.replace(N,'<br>')}</code>"
            )

            # move the pulled dojo in
            if dojo_permanent_dir.exists():
                shutil.rmtree(dojo_permanent_dir)
            dojo_permanent_dir.mkdir(parents=True, exist_ok=True)
            dojo_pull_dir.replace(dojo_permanent_dir)
        except AssertionError as e:
            return (
                {"success": False, "error": e.args[0]},
                400
            )
        finally:
            shutil.rmtree(user_pull_dir)

        return {"success": True}


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
