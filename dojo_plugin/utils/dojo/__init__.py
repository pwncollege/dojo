import os
import re
import subprocess
import tempfile
import datetime
import functools
import contextlib
import inspect
import pathlib

import yaml
import requests
from schema import Schema, Optional, Regex, Or, Use, SchemaError
from flask import abort
from sqlalchemy.orm.exc import NoResultFound
from CTFd.models import db, Users, Challenges, Flags, Solves
from CTFd.utils.user import get_current_user, is_admin

from ...models import Dojos, DojoUsers, DojoModules, DojoChallenges, DojoResources, DojoChallengeVisibilities, DojoResourceVisibilities
from ...utils import DOJOS_DIR, get_current_container


ID_REGEX = Regex(r"^[a-z0-9-]{1,32}$")
UNIQUE_ID_REGEX = Regex(r"^[a-z0-9-~]{1,128}$")
NAME_REGEX = Regex(r"^[\S ]{1,128}$")
DATE = Use(datetime.datetime.fromisoformat)

ID_NAME_DESCRIPTION = {
    Optional("id"): ID_REGEX,
    Optional("name"): NAME_REGEX,
    Optional("description"): str,
}

VISIBILITY = {
    Optional("visibility", default={}): {
        Optional("start"): DATE,
        Optional("stop"): DATE,
    }
}

DOJO_SPEC = Schema({
    **ID_NAME_DESCRIPTION,
    **VISIBILITY,

    Optional("password"): Regex(r"^[\S ]{8,128}$"),

    Optional("type"): ID_REGEX,
    Optional("award"): {
        Optional("emoji"): Regex(r"^\S$"),
    },

    Optional("import"): {
        "dojo": UNIQUE_ID_REGEX,
    },

    Optional("modules", default=[]): [{
        **ID_NAME_DESCRIPTION,
        **VISIBILITY,

        Optional("import"): {
            Optional("dojo"): UNIQUE_ID_REGEX,
            "module": ID_REGEX,
        },

        Optional("challenges", default=[]): [{
            **ID_NAME_DESCRIPTION,
            **VISIBILITY,

            # Optional("image", default="pwncollege-challenge"): Regex(r"^[\S ]{1, 256}$"),
            # Optional("path"): Regex(r"^[^\s\.\/][^\s\.]{,255}$"),

            Optional("import"): {
                Optional("dojo"): UNIQUE_ID_REGEX,
                Optional("module"): ID_REGEX,
                "challenge": ID_REGEX,
            },
        }],

        Optional("resources", default=[]): [Or(
            {
                "type": "markdown",
                "name": NAME_REGEX,
                "content": str,
                **VISIBILITY,
            },
            {
                "type": "lecture",
                "name": NAME_REGEX,
                Optional("video"): str,
                Optional("playlist"): str,
                Optional("slides"): str,
                **VISIBILITY,
            },
        )],
    }],
})


def load_dojo_dir(dojo_dir, *, dojo=None):
    dojo_yml_path = dojo_dir / "dojo.yml"
    assert dojo_yml_path.exists(), "Missing file: `dojo.yml`"

    for path in dojo_dir.rglob("*"):
        assert dojo_dir in path.resolve().parents, f"Error: symlink `{path}` references path outside of the dojo"

    data = yaml.safe_load(dojo_yml_path.read_text())

    # load module sub-yamls
    for n,module_data in enumerate(data.get("modules", [])):
        if "id" not in module_data:
            continue
        module_yml_path = dojo_dir / module_data["id"] / "module.yml"
        if not module_yml_path.exists():
            continue

        module_yml_data = yaml.safe_load(module_yml_path.read_text())
        merged_module_data = dict(module_yml_data)
        merged_module_data.update(module_data)
        print("A YML:", module_data)
        print("B YML:", module_yml_data)
        print("M YML:", merged_module_data)
        data["modules"][n] = merged_module_data

    try:
        dojo_data = DOJO_SPEC.validate(data)
    except SchemaError as e:
        raise AssertionError(e)  # TODO: this probably shouldn't be re-raised as an AssertionError

    def assert_one(query, error_message):
        try:
            return query.one()
        except NoResultFound:
            raise AssertionError(error_message)

    # TODO: we probably don't need to restrict imports to official dojos
    import_dojo = (
        assert_one(Dojos.from_id(dojo_data["import"]["dojo"]).filter_by(official=True),
                   "Import dojo `{dojo_data['import']['dojo']}` does not exist")
        if "import" in dojo_data else None
    )

    dojo_kwargs = {
        field: dojo_data.get(field, getattr(import_dojo, field, None))
        for field in ["id", "name", "description", "password", "type", "award"]
    }

    if dojo is None:
        dojo = Dojos(**dojo_kwargs)
    else:
        for name, value in dojo_kwargs.items():
            setattr(dojo, name, value)

    existing_challenges = {(challenge.module.id, challenge.id): challenge.challenge for challenge in dojo.challenges}
    def challenge(module_id, challenge_id):
        if (module_id, challenge_id) in existing_challenges:
            return existing_challenges[(module_id, challenge_id)]
        result = (Challenges.query.filter_by(category=dojo.hex_dojo_id, name=f"{module_id}:{challenge_id}").first() or
                  Challenges(type="dojo", category=dojo.hex_dojo_id, name=f"{module_id}:{challenge_id}", flags=[Flags(type="dojo")]))
        return result

    def visibility(cls, *args):
        start = None
        stop = None
        for arg in args:
            print(repr(arg), flush=True)
            print(repr(arg.get("visibility", {})), flush=True)
            start = arg.get("visibility", {}).get("start") or start
            stop = arg.get("visibility", {}).get("stop") or stop
        if start or stop:
            return cls(start=start, stop=stop)

    def import_ids(ids, *datas):
        results = {
            id: None
            for id in ids
        }
        for data in datas:
            for id, result in results.items():
                results[id] = data.get("import", {}).get(id, None) or result
        for id, result in results.items():
            assert result is not None, f"Missing `{id}` in import"
        return tuple(results.values())

    dojo.modules = [
        DojoModules(
            **{kwarg: module_data.get(kwarg) for kwarg in ["id", "name", "description"]},
            challenges=[
                DojoChallenges(
                    **{kwarg: challenge_data.get(kwarg) for kwarg in ["id", "name", "description"]},
                    challenge=challenge(module_data.get("id"), challenge_data.get("id")) if "import" not in challenge_data else None,
                    visibility=visibility(DojoChallengeVisibilities, dojo_data, module_data, challenge_data),
                    default=(assert_one(DojoChallenges.from_id(*import_ids(["dojo", "module", "challenge"], dojo_data, module_data, challenge_data)),
                                        f"Import challenge `{'/'.join(import_ids(['dojo', 'module', 'challenge'], dojo_data, module_data, challenge_data))}` does not exist")
                             if "import" in challenge_data else None),
                )
                for challenge_data in module_data["challenges"]
            ] if "challenges" in module_data else None,
            resources = [
                DojoResources(
                    **{kwarg: resource_data.get(kwarg) for kwarg in ["name", "type", "content", "video", "playlist", "slides"]},
                    visibility=visibility(DojoResourceVisibilities, dojo_data, module_data, resource_data),
                )
                for resource_data in module_data["resources"]
            ] if "resources" in module_data else None,
            default=(assert_one(DojoModules.from_id(*import_ids(["dojo", "module"], dojo_data, module_data)),
                                f"Import module `{'/'.join(import_ids(['dojo', 'module'], dojo_data, module_data))}` does not exist")
                     if "import" in module_data else None),
            default_visibility=visibility(dict, dojo_data, module_data),
        )
        for module_data in dojo_data["modules"]
    ] if "modules" in dojo_data else [
        DojoModules(
            default=module,
            default_visibility=visibility(dict, dojo_data),
        )
        for module in (import_dojo.modules if import_dojo else [])
    ]

    with dojo.located_at(dojo_dir):
        missing_challenge_paths = [
            challenge
            for module in dojo.modules
            for challenge in module.challenges
            if not challenge.path.exists()
        ]
        assert not missing_challenge_paths, "".join(
            f"Missing challenge path: {challenge.module.id}/{challenge.id}\n"
            for challenge in missing_challenge_paths)

    if dojo.official:
        # TODO: make course official
        course_yml_path = dojo_dir / "course.yml"
        if course_yml_path.exists():
            course = yaml.safe_load(course_yml_path.read_text())
            dojo.course = course

    return dojo


def generate_ssh_keypair():
    temp_dir = tempfile.TemporaryDirectory()
    key_dir = pathlib.Path(temp_dir.name)

    public_key = key_dir / "key.pub"
    private_key = key_dir / "key"

    subprocess.run(["ssh-keygen",
                    "-t", "ed25519",
                    "-P", "",
                    "-C", "",
                    "-f", str(private_key)],
                    check=True,
                    capture_output=True)

    return (public_key.read_text().strip(), private_key.read_text())


def dojo_clone(repository, private_key):
    tmp_dojos_dir = DOJOS_DIR / "tmp"
    tmp_dojos_dir.mkdir(exist_ok=True)
    clone_dir = tempfile.TemporaryDirectory(dir=tmp_dojos_dir)  # TODO: ignore_cleanup_errors=True

    key_file = tempfile.NamedTemporaryFile("w")
    key_file.write(private_key)
    key_file.flush()

    url = f"https://github.com/{repository}"
    if requests.head(url).status_code != 200:
        url = f"git@github.com:{repository}"
    subprocess.run(["git", "clone", url, clone_dir.name],
                   env={
                       "GIT_SSH_COMMAND": f"ssh -i {key_file.name}",
                       "GIT_TERMINAL_PROMPT": "0",
                   },
                   check=True,
                   capture_output=True)

    return clone_dir


def dojo_git_command(dojo, *args):
    key_file = tempfile.NamedTemporaryFile("w")
    key_file.write(dojo.private_key)
    key_file.flush()

    return subprocess.run(["git", "-C", str(dojo.path), *args],
                          env={
                              "GIT_SSH_COMMAND": f"ssh -i {key_file.name}",
                              "GIT_TERMINAL_PROMPT": "0",
                          },
                          check=True,
                          capture_output=True)


def dojo_update(dojo):
    dojo_git_command(dojo, "pull")
    return load_dojo_dir(dojo.path, dojo=dojo)


def dojo_accessible(id):
    if is_admin():
        return Dojos.from_id(id).first()
    return Dojos.viewable(id=id, user=get_current_user()).first()


def dojo_route(func):
    signature = inspect.signature(func)
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound_args = signature.bind(*args, **kwargs)
        bound_args.apply_defaults()

        dojo = dojo_accessible(bound_args.arguments["dojo"])
        if not dojo:
            abort(404)
        bound_args.arguments["dojo"] = dojo

        if "module" in bound_args.arguments:
            module = DojoModules.query.filter_by(dojo=dojo, id=bound_args.arguments["module"]).first()
            if module is None:
                abort(404)
            bound_args.arguments["module"] = module

        return func(*bound_args.args, **bound_args.kwargs)
    return wrapper


def get_current_dojo_challenge(user=None):
    container = get_current_container(user)
    if not container:
        return None

    return (
        DojoChallenges.query
        .filter(DojoChallenges.id == container.labels.get("dojo.challenge_id"),
                DojoChallenges.dojo == Dojos.from_id(container.labels.get("dojo.dojo_id")).first())
        .first()
    )


def dojo_scoreboard_data(dojo, module=None, duration=None, fields=None):
    fields = fields or []

    duration_filter = (
        Solves.date >= datetime.datetime.utcnow() - datetime.timedelta(days=duration)
        if duration else True
    )
    order_by = (db.func.count().desc(), db.func.max(Solves.id))
    result = (
        DojoChallenges.solves(dojo=dojo, module=module)
        .filter(DojoChallenges.visible(Solves.date), duration_filter)
        .group_by(Solves.user_id)
        .order_by(*order_by)
        .join(Users, Users.id == Solves.user_id)
        .with_entities(db.func.row_number().over(order_by=order_by).label("rank"),
                       db.func.count().label("solves"),
                       Solves.user_id,
                       *fields)
    )
    return result
