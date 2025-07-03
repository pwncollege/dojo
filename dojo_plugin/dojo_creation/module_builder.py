from schema import Schema, Optional, Or, SchemaError

from ..models import DojoModules, DojoResources, DojoModuleVisibilities, DojoResourceVisibilities
from .builder_utils import (
    ID_REGEX,
    UNIQUE_ID_REGEX,
    NAME_REGEX,
    VISIBILITY,
    BASE_SPEC,
    import_one,
    first_present,
    get_visibility,
)
from .challenge_builder import challenges_from_spec



MODULE_SPEC = Schema([{
    **BASE_SPEC,

    Optional("import"): {
        Optional("dojo"): UNIQUE_ID_REGEX,
        "module": ID_REGEX,
    },
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
        first_present("dojo", module_data["import"], dojo_data["import"]),
        module_data["import"]["module"],
    )

    imported_module = import_one(DojoModules.from_id(*import_data), f"{'/'.join(import_data)} does not exist")
    for attr in ["id", "name", "description"]:
        if attr not in module_data:
            module_data[attr] = getattr(imported_module, attr)

    # The idea here is that once it reaches challenges_from_spec it will process the actual challenge importing
    if not module_data["challenges"]:
        module_data["challenges"] = [{"import": {"challenge": challenge.id}} for challenge in imported_module.challenges]
    
    if not module_data["resources"]:
        module_data["resources"] = [
            {
                attr: getattr(resource, attr) for attr in RESOURCE_ATTRIBUTES if getattr(resource, attr, None) is not None
            } for resource in imported_module.resources
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