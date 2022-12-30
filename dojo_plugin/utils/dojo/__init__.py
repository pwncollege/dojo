import os
import subprocess
import tempfile
import datetime
import functools
import contextlib
import inspect

import yaml
from schema import Schema, Optional, Regex, Or, SchemaError
from flask import g
from CTFd.models import db
from CTFd.utils.user import get_current_user

from ...models import Dojos, PrivateDojos, OfficialDojos, DojoUsers, DojoModules, DojoChallenges, DojoChallengeRuntimes, DojoChallengeDurations


DOJO_SPEC = Schema({
    "id": Regex(r"^[a-z0-9-]{1,32}$"),
    "name": Regex(r"^[\S ]{1,128}$"),
    Optional("description"): str,

    Optional("password"): Regex(r"^[\S ]{8,128}$"),

    Optional("from"): {
        "dojo": Regex(r"^[\S ]{1,128}$"),
    },

    Optional("modules", default=[]): [{
        "id": Regex(r"^[a-z0-9-]{1,32}$"),
        "name": Regex(r"^[\S ]{1,128}$"),
        Optional("description"): str,

        Optional("start"): datetime.datetime,
        Optional("stop"): datetime.datetime,

        Optional("from"): {
            "dojo": Regex(r"^[\S ]{1,128}$"),
            "module": Regex(r"^[\S ]{1,128}$"),
        },

        Optional("challenges", default=[]): [{
            "id": Regex(r"^[a-z0-9-]{1,32}$"),
            "name": Regex(r"^[\S ]{1,128}$"),
            Optional("description"): str,

            Optional("image", default="pwncollege-challenge"): Regex(r"^[\S ]{1, 256}$"),
            Optional("path"): Regex(r"^[^\s\.\/][^\s\.]{,255}$"),

            Optional("start"): datetime.datetime,
            Optional("stop"): datetime.datetime,

            Optional("from"): {
                "dojo": Regex(r"^[\S ]{1,128}$"),
                "module": Regex(r"^[\S ]{1,128}$"),
                "challenge": Regex(r"^[\S ]{1,128}$"),
            },
        }],

        Optional("resources", default=[]): [{
            "type": Or("markdown", "video", "slides"),
            "name": Regex(r"^[\S ]{1,128}$"),
            "data": str,
        }],
    }],
})


def load_dojo(data, *,
              dojo=None,
              dojo_id=None,
              dojo_type=None):

    data = DOJO_SPEC.validate(data)

    dojo_id = dojo_id or (dojo.dojo_id if dojo else None)
    dojo_type = dojo_type or (dojo.type if dojo else data["type"])

    dojo_cls = {
        "official": OfficialDojos,
        "private": PrivateDojos,
    }[dojo_type]

    dojo_kwargs = dict(
        dojo_id=dojo_id,
        type=dojo_type,
        id=data.get("id"),
        name=data.get("name"),
        description=data.get("description"),
    )

    if dojo_cls is PrivateDojos:
        dojo_kwargs["password"] = data.get("password")

    # TODO: for all references: index -> name

    if dojo_id is not None:
        Dojos.query.filter_by(dojo_id=dojo_id).delete()

    dojo = dojo_cls(**dojo_kwargs)

    dojo.modules = [
        DojoModules(
            id=module.get("id"),
            name=module.get("name"),
            description=module.get("description"),
            challenges=[
                DojoChallenges(
                    id=challenge.get("id"),
                    name=challenge.get("name"),
                    description=challenge.get("description"),
                )
                for challenge in module["challenges"]
            ]
        )
        for module in data["modules"]
    ]

    # TODO: for all references: name -> index

    return dojo


def load_dojo_dir(dojo_dir, **kwargs):
    dojo_yml_path = dojo_dir / "dojo.yml"
    assert dojo_yml_path.exists(), "Missing file: `dojo.yml`"

    for path in dojo_dir.rglob("*"):
        assert dojo_dir in path.resolve().parents, f"Error: symlink `{path}` references path outside of the dojo"

    data = yaml.safe_load(dojo_yml_path.read_text())
    return load_dojo(data, **kwargs)


def dojo_clone(repository):
    clone_dir = tempfile.TemporaryDirectory()
    subprocess.run(["git", "clone", repository, d.name],
                   env={"GIT_TERMINAL_PROMPT": "0"},
                   check=True,
                   capture_output=True)
    return clone_dir


def dojo_accessible(dojo_id):
    return Dojos.viewable(user=get_current_user()).filter_by(id=dojo_id).first()


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
