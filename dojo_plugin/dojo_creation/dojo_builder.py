import yaml

from schema import Schema, Optional, Regex, Or, SchemaError

from ..models import Dojos
from .builder_utils import (
    ID_REGEX,
    UNIQUE_ID_REGEX,
    IMAGE_REGEX,
    FILE_PATH_REGEX,
    FILE_URL_REGEX,
    BASE_SPEC,
    import_one,
)
from .module_builder import modules_from_spec


DOJO_SPEC = Schema({
    **BASE_SPEC,

    Optional("password"): Regex(r"^[\S ]{8,128}$"),

    Optional("type"): ID_REGEX,
    Optional("award"): {
        Optional("emoji"): Regex(r"^\S$"),
        Optional("belt"): IMAGE_REGEX
    },

    Optional("show_scoreboard"): bool,


    Optional("import"): {
        "dojo": UNIQUE_ID_REGEX,
    },


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


DOJO_ATTRIBUTES = ["id", "name", "description", "password", "type", "award", "pages", "show_scoreboard"]


def import_dojo(dojo_data):
    # TODO: we probably don't need to restrict imports to official dojos
    imported_dojo = import_one(
        Dojos.from_id(dojo_data["import"]["dojo"]).filter_by(official=True),
        f"Import dojo `{dojo_data['import']['dojo']}` does not exist"
    )

    for attr in DOJO_ATTRIBUTES:
        if attr not in dojo_data:
            dojo_data[attr] = getattr(imported_dojo, attr)

    # Modules will be initialized at the module layer, and challenges at the challenge layer
    if not dojo_data["modules"]:
        dojo_data["modules"] = [{"import": {"module": module.id}} for module in imported_dojo.modules]
    

def dojo_from_spec(data: dict, *, dojo=None) -> Dojos:
    try:
        dojo_data = DOJO_SPEC.validate(data)
    except SchemaError as e:
        raise AssertionError(f"Invalid dojo specification: {e}")

    if "import" in dojo_data:
        import_dojo(dojo_data)

    dojo_kwargs = {attr: dojo_data.get(attr) for attr in DOJO_ATTRIBUTES}
    if dojo is None:
        dojo = Dojos(**dojo_kwargs)
    else:
        for name, value in dojo_kwargs.items():
            setattr(dojo, name, value)
    
    assert dojo_data.get("id") is not None, "Dojo id must be defined"
    
    dojo.modules = modules_from_spec(dojo, dojo_data)

    return dojo