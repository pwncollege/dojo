import datetime
import sys
import traceback
import sqlalchemy
import subprocess
import tempfile
import logging
import pathlib
import shutil
import docker
import pathlib
import yaml
import os
import re

from flask import request
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import and_
from CTFd.models import db, Solves, Challenges
from CTFd.cache import cache
from CTFd.utils.decorators import authed_only, admins_only
from CTFd.utils.user import get_current_user, is_admin, get_ip
from CTFd.utils.modes import get_model
from CTFd.utils.security.sanitize import sanitize_html

from ...models import Dojos, DojoMembers, DojoAdmins, DojoUsers, Emojis
from ...utils.dojo import dojo_accessible, dojo_clone, dojo_from_dir, dojo_yml_dir, dojo_route, dojo_admins_only


dojo_namespace = Namespace(
    "dojo", description="Endpoint to manage dojos"
)

def create_dojo(user, repository, public_key, private_key, spec):
    DOJO_EXISTS = "This repository already exists as a dojo"

    try:
        if repository:
            repository_re = r"[\w\-]+/[\w\-]+"
            repository = repository.replace("https://github.com/", "")
            assert re.match(repository_re, repository), f"Invalid repository, expected format: <code>{repository_re}</code>"

            assert not Dojos.query.filter_by(repository=repository).first(), DOJO_EXISTS

            dojo_dir = dojo_clone(repository, private_key)
        elif spec:
            assert is_admin(), "Must be an admin user to create dojos from spec rather than repositories"
            dojo_dir = dojo_yml_dir(spec)
            repository, public_key, private_key = None, None, None

        dojo_path = pathlib.Path(dojo_dir.name)

        dojo = dojo_from_dir(dojo_path)
        dojo.repository = repository
        dojo.public_key = public_key
        dojo.private_key = private_key
        dojo.admins = [DojoAdmins(user=user)]

        db.session.add(dojo)
        db.session.commit()

        dojo.path.parent.mkdir(exist_ok=True)
        dojo_path.rename(dojo.path)
        dojo_path.mkdir()  # TODO: ignore_cleanup_errors=True

    except subprocess.CalledProcessError as e:
        print(f"ERROR: Dojo failed to clone for {repository}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        print(str(e.stderr), file=sys.stderr, flush=True)
        deploy_url = f"https://github.com/{repository}/settings/keys"
        return {"success": False, "error": f'Failed to clone: <a href="{deploy_url}" target="_blank">add deploy key</a>'}, 400

    except IntegrityError as e:
        return {"success": False, "error": DOJO_EXISTS}, 400

    except AssertionError as e:
        return {"success": False, "error": str(e)}, 400

    except Exception as e:
        print(f"ERROR: Dojo failed for {repository}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return {"success": False, "error": str(e)}, 400

    return {"success": True, "dojo": dojo.reference_id}, 200

@dojo_namespace.route("/<dojo>/prune-awards")
class PruneAwards(Resource):
    @authed_only
    @dojo_route
    @dojo_admins_only
    def post(self, dojo):
        all_completions = set(user for user,_ in dojo.completions())
        num_pruned = 0
        for award in Emojis.query.where(Emojis.category==dojo.hex_dojo_id):
            if award.user not in all_completions:
                num_pruned += 1
                db.session.delete(award)
        db.session.commit()
        return {"success": True, "pruned_awards": num_pruned}

@dojo_namespace.route("/<dojo>/promote-dojo")
class PromoteDojo(Resource):
    @admins_only
    @dojo_route
    def post(self, dojo):
        dojo.official = True
        db.session.commit()
        return {"success": True}

@dojo_namespace.route("/<dojo>/promote-admin")
class PromoteAdmin(Resource):
    @authed_only
    @dojo_route
    @dojo_admins_only
    def post(self, dojo):
        data = request.get_json()
        if 'user_id' not in data:
            return {"success": False, "error": "User not specified."}, 400
        new_admin_id = data['user_id']
        u = DojoUsers.query.filter_by(dojo=dojo, user_id=new_admin_id).first()
        if u:
            u.type = 'admin'
        else:
            return {"success": False, "error": "User is not currently a dojo member."}, 400
        db.session.commit()
        return {"success": True}

@dojo_namespace.route("/create")
class CreateDojo(Resource):
    @authed_only
    def post(self):
        data = request.get_json()
        user = get_current_user()

        repository = data.get("repository", "")
        spec = data.get("spec", "")
        public_key = data.get("public_key", "")
        private_key = data.get("private_key", "").replace("\r\n", "\n")

        key = f"rl:{get_ip()}:{request.endpoint}"
        timeout = int(datetime.timedelta(days=1).total_seconds())

        if not is_admin() and cache.get(key) is not None:
            return {"success": False, "error": "You can only create 1 dojo per day."}, 429

        result = create_dojo(user, repository, public_key, private_key, spec)
        if result[0]["success"]:
            cache.set(key, 1, timeout=timeout)

        return result

@dojo_namespace.route("/<dojo>/modules")
class GetDojoModules(Resource):
    @dojo_route
    def get(self, dojo):
        modules = [
            dict(id=module.id,
                 module_index=module.module_index,
                 name=module.name,
                 description=module.description)
            for module in dojo.modules if module.visible()
        ]
        return {"success": True, "modules": modules}


@dojo_namespace.route("/<dojo>/<module>/challenges")
class GetDojoModuleChallenges(Resource):
    @dojo_route
    def get(self, dojo, module):
        challenges = [
            dict(id=challenge.id,
                 challenge_id=challenge.challenge_id,
                 module_index=challenge.module_index,
                 challenge_index=challenge.challenge_index,
                 name=challenge.name,
                 description=challenge.description)
            for challenge in module.visible_challenges()
        ]
        return {"success": True, "challenges": challenges}
