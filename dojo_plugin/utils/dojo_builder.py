import datetime
import typing
import yaml

from pathlib import Path
from schema import Schema, Optional, Regex, Or, Use, SchemaError

from typing import Any
from dojo_plugin.models import Dojos, DojoModules, DojoChallenges, DojoResources, DojoChallengeVisibilities, DojoModuleVisibilities, DojoResourceVisibilities, Challenges, Flags
from sqlalchemy.orm.exc import NoResultFound
from CTFd.utils.user import is_admin


ID_REGEX = Regex(r"^[a-z0-9-]{1,32}$")
UNIQUE_ID_REGEX = Regex(r"^[a-z0-9-~]{1,128}$")
NAME_REGEX = Regex(r"^[\S ]{1,128}$")
IMAGE_REGEX = Regex(r"^[\S]{1,256}$")
FILE_PATH_REGEX = Regex(r"^[A-Za-z0-9_][A-Za-z0-9-_./]*$")
FILE_URL_REGEX = Regex(r"^https://www.dropbox.com/[a-zA-Z0-9]*/[a-zA-Z0-9]*/[a-zA-Z0-9]*/[a-zA-Z0-9.-_]*?rlkey=[a-zA-Z0-9]*&dl=1")
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
        Optional("belt"): IMAGE_REGEX
    },

    Optional("image"): IMAGE_REGEX,
    Optional("allow_privileged"): bool,
    Optional("importable"): bool,

    Optional("import"): {
        "dojo": UNIQUE_ID_REGEX,
    },

    Optional("auxiliary", default={}, ignore_extra_keys=True): dict,

    Optional("survey"): Or(
        {
            "type": "multiplechoice",
            "prompt": str,
            Optional("probability"): float,
            "options": [str],
        },
        {
            "type": "thumb",
            "prompt": str,
            Optional("probability"): float,
        },
        {
            "type": "freeform",
            "prompt": str,
            Optional("probability"): float,
        },
    ),

    Optional("pages", default=[]): [str],
    Optional("files", default=[]): [Or(
        {
            "type": "download",
            "path": FILE_PATH_REGEX,
            "url": FILE_URL_REGEX,
        },
        {
            "type": "text",
            "path": FILE_PATH_REGEX,
            "content": str,
        }
    )],

    Optional("modules", default=[]): list, # Defer module validation until later
})
"""
This is the validation Schema that parses the dojo.yaml file during dojo initialization.

In order to create a valid dojo.yaml, it must conform to the schema defined here.
"""


def dojo_from_spec(data: dict[str, Any], *, dojo_dir:typing.Optional[Path]=None, dojo:typing.Optional[Dojos]=None) -> Dojos:
    try:
        dojo_data = DOJO_SPEC.validate(data)
    except SchemaError as e:
        raise AssertionError(f"Invalid dojo specification: {e}")

    # def assert_importable(o):
    #     assert o.importable, f"Import disallowed for {o}."
    #     if isinstance(o, Dojos):
    #         for m in o.module:
    #             assert_importable(m)
    #     if isinstance(o, DojoModules):
    #         for c in o.challenges:
    #             assert_importable(c)

    def assert_import_one(query, error_message):
        """
        Since dojos are queried by id, this ensures that only one dojo matches the id, as well as making sure that dojo is importable.
        """
        try:
            o = query.one()
            assert o.importable, f"Import disallowed for {o}."
            return o
        except NoResultFound:
            raise AssertionError(error_message)

    # TODO: we probably don't need to restrict imports to official dojos
    import_dojo = (
        assert_import_one(Dojos.from_id(dojo_data["import"]["dojo"]).filter_by(official=True),
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
    def challenge(module_id: str, challenge_id: str, transfer: typing.Optional[dict[str, Any]]) -> Challenges:
        """
        Retrieves or creates a dojo challenge object based on the given module and challenge identifiers.
    
        This function performs the following logic:
          - If the challenge has already been retrieved (cached in `existing_challenges`), it is returned immediately.
          - If a challenge matching the `module_id` and `challenge_id` exists in the database, it is returned.
          - If a `transfer` is provided, the function attempts to locate the challenge in the source dojo, validate transfer permissions,
            and return a modified version scoped to the current dojo.
          - If no existing or transferrable challenge is found, a new challenge instance is created and returned (but not committed).
        """
        if (module_id, challenge_id) in existing_challenges: # Don't re-query for challenges that are already in the dojo 
            return existing_challenges[(module_id, challenge_id)]
        if chal := Challenges.query.filter_by(category=dojo.hex_dojo_id, name=f"{module_id}:{challenge_id}").first():
            return chal
        if transfer:
            assert dojo.official or (is_admin() and not Dojos.from_id(dojo.id).first()), "Transfer Error: transfers can only be utilized by official dojos or by system admins during dojo creation"
            old_dojo_id, old_module_id, old_challenge_id = transfer["dojo"], transfer["module"], transfer["challenge"]
            old_dojo = Dojos.from_id(old_dojo_id).first()
            assert old_dojo, f"Transfer Error: unable to find source dojo in database for {old_dojo_id}:{old_module_id}:{old_challenge_id}"
            old_challenge = Challenges.query.filter_by(category=old_dojo.hex_dojo_id, name=f"{old_module_id}:{old_challenge_id}").first()
            assert old_challenge, f"Transfer Error: unable to find source module/challenge in database for {old_dojo_id}:{old_module_id}:{old_challenge_id}"
            old_challenge.category = dojo.hex_dojo_id
            old_challenge.name = f"{module_id}:{challenge_id}"
            return old_challenge
        return Challenges(type="dojo", category=dojo.hex_dojo_id, name=f"{module_id}:{challenge_id}", flags=[Flags(type="dojo")])

    def visibility(cls, *args):
        """
        Constructs a visibility window from one or more argument dictionaries.

        This method scans the provided dictionaries for a nested "visibility" key containing
        optional "start" and "stop" datetime values. The latest non-`None` values found take priority and are used
        to create a new instance of `cls` with UTC-normalized timestamps.
        """ 
        start = None
        stop = None
        for arg in args:
            start = arg.get("visibility", {}).get("start") or start
            stop = arg.get("visibility", {}).get("stop") or stop
        if start or stop:
            start = start.astimezone(datetime.timezone.utc) if start else None
            stop = stop.astimezone(datetime.timezone.utc) if stop else None
            return cls(start=start, stop=stop)

    _missing = object()
    def shadow(attr, *datas, default=_missing, default_dict=None):
        """
        Looks for `attr` in the given datas (in reverse order), returning the first found value.

        If not found:
          - Returns `default` if explicitly provided
          - Returns `default_dict[attr]` if present
          - Otherwise raises KeyError.
        """
        for data in reversed(datas):
            if attr in data:
                return data[attr]
        if default is not _missing:
            return default
        elif default_dict and attr in default_dict:
            return default_dict[attr]
        raise KeyError(f"Missing `{attr}` in `{datas}`")

    def import_ids(attrs: list[str], *datas) -> tuple:
        """
        Resolves the import sources by extracting the "import" attribute from the `datas` and extracting all of the attributes under `import` which are specified by `attr`
        """
        datas_import = [data.get("import", {}) for data in datas]
        return tuple(shadow(attr, *datas_import) for attr in attrs)
    
    def build_dojo_resources(module_data):
        if "resources" not in module_data:
            return None 
        return [
            DojoResources(
                **{kwarg: resource_data.get(kwarg) for kwarg in ["name", "type", "content", "video", "playlist", "slides"]},
                visibility=visibility(DojoResourceVisibilities, dojo_data, module_data, resource_data),
            )
            for resource_data in module_data["resources"]
        ]
    dojo.modules = modules_from_spec(dojo_data["modules"])
    

    
    # FIXME address imports later 
    if "modules" in dojo_data else [
        DojoModules(
            default=module,
            visibility=visibility(DojoModuleVisibilities, dojo_data, module_data),
        )
        for module in (import_dojo.modules if import_dojo else [])
    ]

    if dojo_dir:
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

        course_yml_path = dojo_dir / "course.yml"
        if course_yml_path.exists():
            course = yaml.safe_load(course_yml_path.read_text())

            if "discord_role" in course and not dojo.official:
                raise AssertionError("Unofficial dojos cannot have a discord role")

            dojo.course = course

            students_yml_path = dojo_dir / "students.yml"
            if students_yml_path.exists():
                students = yaml.safe_load(students_yml_path.read_text())
                dojo.course["students"] = students

            syllabus_path = dojo_dir / "SYLLABUS.md"
            if "syllabus" not in dojo.course and syllabus_path.exists():
                dojo.course["syllabus"] = syllabus_path.read_text()

            grade_path = dojo_dir / "grade.py"
            if grade_path.exists():
                dojo.course["grade_code"] = grade_path.read_text()

        if dojo_data.get("pages"):
            dojo.pages = dojo_data["pages"]

    return dojo



MODULE_SPEC = Schema([{
    **ID_NAME_DESCRIPTION,
    **VISIBILITY,

    Optional("image"): IMAGE_REGEX,
    Optional("allow_privileged"): bool,
    Optional("importable"): bool,

    Optional("import"): {
        Optional("dojo"): UNIQUE_ID_REGEX,
        "module": ID_REGEX,
    },

    Optional("survey"): Or(
        {
            "type": "multiplechoice",
            "prompt": str,
            Optional("probability"): float,
            "options": [str],
        },
        {
            "type": "thumb",
            "prompt": str,
            Optional("probability"): float,
        },
        {
            "type": "freeform",
            "prompt": str,
            Optional("probability"): float,
        },
    ),


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

    Optional("auxiliary", default={}, ignore_extra_keys=True): dict,

    Optional("challenges", default=[]): list, # Defer challenge validation
}])


def modules_from_spec(raw_module_data):
    try:
        module_list = MODULE_SPEC.validate(raw_module_data)
    except SchemaError as e:
        raise AssertionError(f"Invalid module specification: {e}")    


    return [
        DojoModules(
            **{kwarg: module_data.get(kwarg) for kwarg in ["id", "name", "description"]},
            resources = build_dojo_resources(module_data),
            default=(assert_import_one(DojoModules.from_id(*import_ids(["dojo", "module"], dojo_data, module_data)),
                                f"Import module `{'/'.join(import_ids(['dojo', 'module'], dojo_data, module_data))}` does not exist")
                     if "import" in module_data else None),
            visibility=visibility(DojoModuleVisibilities, dojo_data, module_data),

            challenges=challenges_from_spec(module_data["challenges"]),
        )
        for module_data in module_list
    ]



CHALLENGE_SPEC = Schema([{
    **ID_NAME_DESCRIPTION,
    **VISIBILITY,

    Optional("image"): IMAGE_REGEX,
    Optional("allow_privileged"): bool,
    Optional("importable"): bool,
    Optional("progression_locked"): bool,
    Optional("auxiliary", default={}, ignore_extra_keys=True): dict,
    # Optional("path"): Regex(r"^[^\s\.\/][^\s\.]{,255}$"),

    Optional("import"): {
        Optional("dojo"): UNIQUE_ID_REGEX,
        Optional("module"): ID_REGEX,
        "challenge": ID_REGEX,
    },

    Optional("transfer"): {
        Optional("dojo"): UNIQUE_ID_REGEX,
        Optional("module"): ID_REGEX,
        "challenge": ID_REGEX,
    },

    Optional("survey"): Or(
        {
            "type": "multiplechoice",
            "prompt": str,
            Optional("probability"): float,
            "options": [str],
        },
        {
            "type": "thumb",
            "prompt": str,
            Optional("probability"): float,
        },
        {
            "type": "freeform",
            "prompt": str,
            Optional("probability"): float,
        },
    )
}])


def first_present_or_none(key, *dicts):
    for d in dicts:
        if key in d:
            return d[key]
    return None

def get_visibility(cls, *dicts):
    visibility = first_present_or_none("visibility", *dicts)

    if visibility:
        start = visibility["start"].astimezone(datetime.timezone.utc) if "start" in visibility else None
        stop = visibility["stop"].astimezone(datetime.timezone.utc) if "stop" in visibility else None
        assert start or stop, "`start` or `stop` value must be present under visibility"
        return cls(start=start, stop=stop)

    return None


def challenges_from_spec(raw_challenge_data, defaults):
    try:
        challenge_list = CHALLENGE_SPEC.validate(raw_challenge_data)
    except SchemaError as e:
        raise AssertionError(f"Invalid challenge specification: {e}")    

    return [
        DojoChallenges(
            **{kwarg: challenge_data.get(kwarg) for kwarg in ["id", "name", "description"]},
            image=first_present_or_none("image", challenge_data, defaults),
            allow_privileged=first_present_or_none("allow_privileged", challenge_data, defaults, DojoChallenges.data_defaults),
            importable=first_present_or_none("importable", challenge_data, defaults, DojoChallenges.data_defaults),
            challenge=challenge(
                module_data.get("id"), challenge_data.get("id"), transfer=challenge_data.get("transfer", None)
            ) if "import" not in challenge_data else None,
            progression_locked=challenge_data.get("progression_locked"),
            visibility=get_visibility(DojoChallengeVisibilities, challenge_data, defaults),
            survey=first_present_or_none("survey", challenge_data, defaults),
            # TODO Handle imports seperately
        )
        for challenge_data in challenge_list
    ]
    