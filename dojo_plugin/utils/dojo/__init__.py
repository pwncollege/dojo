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
from schema import Schema, Optional, Regex, Or, SchemaError
from flask import abort
from CTFd.models import db, Challenges, Flags
from CTFd.utils.user import get_current_user

from ...models import Dojos, DojoUsers, DojoModules, DojoChallenges, DojoResources, DojoChallengeVisibilities, DojoResourceVisibilities
from ...utils import DOJOS_DIR, get_current_container


ID_REGEX = Regex(r"^[a-z0-9-]{1,32}$")
UNIQUE_ID_REGEX = Regex(r"^[a-z0-9-~]{1,128}$")
NAME_REGEX = Regex(r"^[\S ]{1,128}$")

ID_NAME_DESCRIPTION = {
    Optional("id"): ID_REGEX,
    Optional("name"): NAME_REGEX,
    Optional("description"): str,
}

VISIBILITY = {
    Optional("visibility", default={}): {
        Optional("start"): datetime.datetime,
        Optional("stop"): datetime.datetime,
    }
}

DOJO_SPEC = Schema({
    **ID_NAME_DESCRIPTION,

    Optional("password"): Regex(r"^[\S ]{8,128}$"),

    **VISIBILITY,

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

            # Optional("image", default="pwncollege-challenge"): Regex(r"^[\S ]{1, 256}$"),
            # Optional("path"): Regex(r"^[^\s\.\/][^\s\.]{,255}$"),

            **VISIBILITY,

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


def load_dojo(data, *, dojo=None):

    try:
        data = DOJO_SPEC.validate(data)
    except SchemaError as e:
        raise AssertionError(e)

    dojo_kwargs = dict(
        id=data.get("id"),
        name=data.get("name"),
        description=data.get("description"),
        password=data.get("password"),
    )

    if dojo is None:
        dojo = Dojos(**dojo_kwargs)
    else:
        if dojo.id != dojo_kwargs["id"]:
            Challenges.query.filter_by(category=dojo.id).update(dict(category=dojo_kwargs["id"]))
        for name, value in dojo_kwargs.items():
            setattr(dojo, name, value)

    existing_challenges = {(challenge.module.id, challenge.id): challenge.challenge for challenge in dojo.challenges}
    def challenge(module_id, challenge_id):
        if (module_id, challenge_id) in existing_challenges:
            return existing_challenges[(module_id, challenge_id)]
        result = (Challenges.query.filter_by(category=dojo.id, name=f"{module_id}:{challenge_id}").first() or
                  Challenges(type="dojo", category=dojo.id, name=f"{module_id}:{challenge_id}", flags=[Flags(type="dojo")]))
        return result

    def visibility(cls, *args):
        start = None
        stop = None
        for arg in args:
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
                    challenge=challenge(module_data.get("id"), challenge_data.get("id")),
                    visibility=visibility(DojoChallengeVisibilities, data, module_data, challenge_data),
                )
                for challenge_data in module_data["challenges"]
            ],
            resources = [
                DojoResources(
                    **{kwarg: resource_data.get(kwarg) for kwarg in ["type", "name", "data"]},
                    visibility=visibility(DojoResourceVisibilities, data, module_data, resource_data),
                )
                for resource_data in module_data["resources"]
            ],
        )
        for module_data in data["modules"]
    ]

    return dojo


def load_dojo_dir(dojo_dir, **kwargs):
    dojo_yml_path = dojo_dir / "dojo.yml"
    assert dojo_yml_path.exists(), "Missing file: `dojo.yml`"

    for path in dojo_dir.rglob("*"):
        assert dojo_dir in path.resolve().parents, f"Error: symlink `{path}` references path outside of the dojo"

    data = yaml.safe_load(dojo_yml_path.read_text())
    return load_dojo(data, **kwargs)


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


def get_current_dojo_challenge():
    container = get_current_container()
    if not container:
        return None

    return (
        DojoChallenges.query
        .filter_by(id=container.labels.get("challenge"))
        .join(Dojos, Dojos.dojo_id==Dojos.hex_to_int(container.labels.get("dojo")))
        .first()
    )
