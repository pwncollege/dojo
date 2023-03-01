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
from schema import Schema, Optional, Regex, Or, Use, SchemaError
from flask import abort
from sqlalchemy.orm.exc import NoResultFound
from CTFd.models import db, Challenges, Flags
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
    Optional("deprecated_id"): int,  # TODO: remove

    Optional("import"): {
        "dojo": UNIQUE_ID_REGEX,
    },

    Optional("modules", default=[]): [{
        **ID_NAME_DESCRIPTION,
        **VISIBILITY,

        Optional("import"): {
            "dojo": UNIQUE_ID_REGEX,
            "module": ID_REGEX,
        },

        Optional("challenges", default=[]): [{
            **ID_NAME_DESCRIPTION,
            **VISIBILITY,

            # Optional("image", default="pwncollege-challenge"): Regex(r"^[\S ]{1, 256}$"),
            # Optional("path"): Regex(r"^[^\s\.\/][^\s\.]{,255}$"),

            Optional("import"): {
                "dojo": UNIQUE_ID_REGEX,
                "module": ID_REGEX,
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
        for field in ["id", "name", "description", "password", "type", "deprecated_id"]  # TODO: remove deprecated_id
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

    dojo.modules = [
        DojoModules(
            **{kwarg: module_data.get(kwarg) for kwarg in ["id", "name", "description"]},
            challenges=[
                DojoChallenges(
                    **{kwarg: challenge_data.get(kwarg) for kwarg in ["id", "name", "description"]},
                    challenge=challenge(module_data.get("id"), challenge_data.get("id")) if "import" not in challenge_data else None,
                    visibility=visibility(DojoChallengeVisibilities, dojo_data, module_data, challenge_data),
                    default=(assert_one(DojoChallenges.from_id(challenge_data["import"]["dojo"],
                                                               challenge_data["import"]["module"],
                                                               challenge_data["import"]["challenge"]),
                                        f"Import challenge `{challenge_data['import']['dojo']}/{challenge_data['import']['module']}/{challenge_data['import']['challenge']}` does not exist")
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
            default=(assert_one(DojoModules.from_id(module_data["import"]["dojo"],
                                                    module_data["import"]["module"]),
                                f"Import module `{module_data['import']['dojo']}/{module_data['import']['module']}` does not exist")
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

    subprocess.run(["git", "clone", f"git@github.com:{repository}", clone_dir.name],
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
    user = get_current_user()
    return Dojos.viewable(id=id, user=get_current_user()).first() or is_admin()


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


def get_current_dojo_challenge():
    container = get_current_container()
    if not container:
        return None

    return (
        DojoChallenges.query
        .filter(DojoChallenges.id == container.labels.get("challenge"),
                DojoChallenges.dojo == Dojos.from_id(container.labels.get("dojo")).first())
        .first()
    )
