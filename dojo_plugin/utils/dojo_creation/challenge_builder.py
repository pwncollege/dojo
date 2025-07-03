from schema import Schema, Optional, SchemaError

from ...models import Dojos, DojoChallenges, DojoChallengeVisibilities, Challenges, Flags
from CTFd.utils.user import is_admin
from .builder_utils import (
    ID_REGEX,
    UNIQUE_ID_REGEX,
    BASE_SPEC,
    import_one,
    first_present,
    get_visibility,
)


CHALLENGE_SPEC = Schema([{
    **BASE_SPEC,
    
    Optional("progression_locked"): bool,
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
}])




def get_challenge(dojo, module_id, challenge_id, transfer) -> Challenges:
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


def import_challenge(challenge_data, module_data, dojo_data) -> DojoChallenges:
    # Handles the heirarchy of imports
    import_data = (
        first_present("dojo", challenge_data["import"], module_data["import"], dojo_data["import"]),
        first_present("module", challenge_data["import"], module_data["import"]), # No need to check dojo_data imports because module can never be defined there
        challenge_data["import"]["challenge"],
    )

    imported_challenge = import_one(DojoChallenges.from_id(*import_data), f"{'/'.join(import_data)} does not exist")
    for attr in ["id", "name", "description"]:
        if attr not in challenge_data:
            challenge_data[attr] = getattr(imported_challenge, attr)

    # TODO: maybe we should track the entire import
    challenge_data["image"] = imported_challenge.data.get("image")
    return imported_challenge



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

        path_override = None
        challenge_id = challenge_data.get("id")
        if "import" in challenge_data:
            imported_challenge = import_challenge(*data_priority_chain) # import has to be done before DojoChallenges creation because it modifies challenge_data
            path_override = str(imported_challenge.path)
            ctfd_challenge = imported_challenge.challenge
        elif challenge_id in existing_challenges:
            ctfd_challenge = existing_challenges[challenge_id]
        else:
            ctfd_challenge = get_challenge(dojo, module_id, challenge_data.get("id"), transfer=challenge_data.get("transfer"))
        
        result.append(
            DojoChallenges(
                **{kwarg: challenge_data.get(kwarg) for kwarg in ["id", "name", "description"]},
                image=first_present("image", *data_priority_chain),
                allow_privileged=first_present("allow_privileged", *data_priority_chain, DojoChallenges.data_defaults),
                importable=first_present("importable", *data_priority_chain, DojoChallenges.data_defaults),
                progression_locked=first_present("progression_locked", challenge_data, DojoChallenges.data_defaults),
                survey=first_present("survey", *data_priority_chain),
                visibility=get_visibility(DojoChallengeVisibilities, *data_priority_chain),
                path_override=path_override,
                challenge=ctfd_challenge,
            )
        )
    return result