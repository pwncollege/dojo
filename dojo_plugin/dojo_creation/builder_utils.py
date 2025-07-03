from schema import Optional, Regex, Or, Use
import datetime
from sqlalchemy.orm.exc import NoResultFound


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

SURVEY = {
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
}

BASE_SPEC = {
    **ID_NAME_DESCRIPTION,
    **VISIBILITY,

    Optional("image"): IMAGE_REGEX,
    Optional("allow_privileged"): bool,
    Optional("importable"): bool,
    Optional("auxiliary", default={}, ignore_extra_keys=True): dict,

    **SURVEY,
}
"""
Dictionary for specification fields that are defined identically in all three layers of the specification schema
"""


def import_one(query, error_message):
    try:
        o = query.one()
        assert o.importable, f"Import disallowed for {o}."
        return o
    except NoResultFound:
        raise AssertionError(error_message)

def first_present(key, *dicts, required=False):
    for d in dicts:
        if d and key in d:
            return d[key]
    if required:
        raise KeyError(f"Required key '{key}' not found in data.")
    return None

def get_visibility(cls, *dicts):
    visibility = first_present("visibility", *dicts)

    if visibility:
        start = visibility["start"].astimezone(datetime.timezone.utc) if "start" in visibility else None
        stop = visibility["stop"].astimezone(datetime.timezone.utc) if "stop" in visibility else None
        assert start or stop, "`start` or `stop` value must be present under visibility"
        return cls(start=start, stop=stop)

    return None