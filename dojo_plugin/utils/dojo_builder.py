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


def import_one(query, error_message):
    try:
        o = query.one()
        assert o.importable, f"Import disallowed for {o}."
        return o
    except NoResultFound:
        raise AssertionError(error_message)


def import_dojo(dojo_data):
    # TODO: we probably don't need to restrict imports to official dojos
    imported_dojo = import_one(
        Dojos.from_id(dojo_data["import"]["dojo"]).filter_by(official=True),
        f"Import dojo `{dojo_data['import']['dojo']}` does not exist"
    )

    for attr in ["id", "name", "description", "password", "type", "award"]:
        if attr not in dojo_data:
            dojo_data[attr] = getattr(import_dojo, attr)

    


def dojo_from_spec(data: dict, *, dojo_dir=None, dojo=None) -> Dojos:
    try:
        dojo_data = DOJO_SPEC.validate(data)
    except SchemaError as e:
        raise AssertionError(f"Invalid dojo specification: {e}")

    if "import" in dojo_data:
        import_dojo(dojo_data)

    if dojo is None:
        dojo = Dojos(**dojo_kwargs)
    else:
        for name, value in dojo_kwargs.items():
            setattr(dojo, name, value)
    
    dojo.modules = modules_from_spec(dojo, dojo_data)
    


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

def first_present(key, *dicts):
    for d in dicts:
        if key in d:
            return d[key]
    return None

def get_visibility(cls, *dicts):
    visibility = first_present("visibility", *dicts)

    if visibility:
        start = visibility["start"].astimezone(datetime.timezone.utc) if "start" in visibility else None
        stop = visibility["stop"].astimezone(datetime.timezone.utc) if "stop" in visibility else None
        assert start or stop, "`start` or `stop` value must be present under visibility"
        return cls(start=start, stop=stop)

    return None



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



RESOURCE_ATTRIBUTES = ["name", "type", "content", "video", "playlist", "slides"]
def build_dojo_resources(module_data, dojo_data):
    if "resources" not in module_data:
        return None 

    return [
        DojoResources(
            **{attr: resource_data.get(attr) for attr in RESOURCE_ATTRIBUTES},
            visibility=get_visibility(DojoResourceVisibilities, resource_data, module_data, dojo_data),
        )
        for resource_data in module_data["resources"]
    ]


def import_module(module_data, dojo_data):
    import_data = (
        module_data["import"]["module"],
        first_present("dojo", module_data["import"], dojo_data["import"]),
    )

    imported_module = import_one(DojoModules.from_id(*import_data), f"{'/'.join(import_data)} does not exist")
    for attr in ["id", "name", "description"]:
        if attr not in module_data:
            module_data[attr] = getattr(imported_module, attr)

    if "challenges" not in module_data:
        # The idea here is that once it reaches challenges_from_spec it will process the actual challenge importing
        module_data["challenges"] = [{"import": {"challenge": challenge.id}} for challenge in import_module.challenges]
    
    if "resources" not in module_data:
        module_data["resources"] = [
            {
                attr: getattr(resource, attr) for attr in RESOURCE_ATTRIBUTES if getattr(resource, attr, None) is not None
            } for resource in import_module.resources
        ]


def modules_from_spec(dojo, dojo_data):
    try:
        module_list = MODULE_SPEC.validate(dojo_data["modules"])
    except SchemaError as e:
        raise AssertionError(f"Invalid module specification: {e}")    
    
    result = []
    for module_data in module_list:
        if "import" in module_data:
            import_module(module_data, dojo_data)
        result.append(
            DojoModules(
                **{kwarg: module_data.get(kwarg) for kwarg in ["id", "name", "description"]},
                resources=build_dojo_resources(module_data, dojo_data),
                visibility=get_visibility(DojoModuleVisibilities, module_data, dojo_data),
                challenges=challenges_from_spec(dojo, dojo_data, module_data),
            )
        )
    return result



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




def get_challenge(dojo, module_id, challenge_id, transfer) -> Challenges:
    """
    Retrieves or creates a dojo challenge object based on the given module and challenge identifiers.

    This function performs the following logic:
      - If the challenge has already been retrieved (cached in `existing_challenges`), it is returned immediately.
      - If a challenge matching the `module_id` and `challenge_id` exists in the database, it is returned.
      - If a `transfer` is provided, the function attempts to locate the challenge in the source dojo, validate transfer permissions,
        and return a modified version scoped to the current dojo.
      - If no existing or transferrable challenge is found, a new challenge instance is created and returned (but not committed).
    """
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


def import_challenge(challenge_data, module_data, dojo_data) -> Challenges:
    # Handles the heirarchy of imports
    import_data = (
        challenge_data["import"]["challenge"],
        first_present("module", challenge_data["import"], module_data["import"]), # No need to check dojo_data imports because module can never be defined there
        first_present("dojo", challenge_data["import"], module_data["import"], dojo_data["import"]),
    )

    imported_challenge = import_one(DojoChallenges.from_id(*import_data), f"{'/'.join(import_data)} does not exist")
    for attr in ["id", "name", "description"]:
        if attr not in challenge_data:
            challenge_data[attr] = getattr(imported_challenge, attr)

    # TODO: maybe we should track the entire import
    challenge_data["image"] = imported_challenge.data.get("image")
    challenge_data["path_override"] = str(imported_challenge.path)
    return imported_challenge.challenge



def challenges_from_spec(dojo, dojo_data, module_data) -> list[DojoChallenges]:
    try:
        challenge_list = CHALLENGE_SPEC.validate(module_data["challenges"])
    except SchemaError as e:
        raise AssertionError(f"Invalid challenge specification: {e}")    
    
    module_id = module_data["id"]

    # This is for caching existing challenges to improve performance of updating a dojo
    existing_module = next((module for module in dojo.modules if module.id == module_id), None)
    existing_challenges = {challenge.id: challenge.challenge for challenge in existing_module.challenges} if existing_module else {}

    result = []
    for challenge_data in challenge_list:    
        data_priority_chain = (challenge_data, module_data, dojo_data)
        challenge_id = challenge_data.get("id")

        if "import" in challenge_data:
            challenge = import_challenge(*data_priority_chain) # import has to be done before DojoChallenges creation because it modifies challenge_data
        elif challenge_id in existing_challenges:
            challenge = existing_challenges[challenge_id]
        else:
            challenge = get_challenge(dojo, module_id, challenge_data.get("id"), transfer=challenge_data.get("transfer"))
        
        result.append(
            DojoChallenges(
                **{kwarg: challenge_data.get(kwarg) for kwarg in ["id", "name", "description"]},
                image=first_present("image", *data_priority_chain),
                allow_privileged=first_present("allow_privileged", *data_priority_chain, DojoChallenges.data_defaults),
                importable=first_present("importable", *data_priority_chain, DojoChallenges.data_defaults),
                progression_locked=first_present("progression_locked", challenge_data, DojoChallenges.data_defaults),
                survey=first_present("survey", *data_priority_chain),
                visibility=get_visibility(DojoChallengeVisibilities, *data_priority_chain),
                challenge=challenge
            )
        )
    return result