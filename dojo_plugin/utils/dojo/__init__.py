from schema import Schema, Optional, Regex, Or, SchemaError

from CTFd.models import db

from ...models import PublicDojos, PrivateDojos, DojoModules, DojoChallenges, DojoChallengeRuntimes, DojoChallengeDurations


DOJO_SPEC = Schema({
    "name": Regex(r"^[\S ]{1,128}$"),
    Optional("description"): str,
    Optional("type", default="public"): Or("public", "private"),

    Optional("password"): Regex(r"^[\S ]{8,128}$"),

    Optional("from"): {
        "dojo": Regex(r"^[\S ]{1,128}$"),
    },

    Optional("modules", default=[]): [{
        "name": Regex(r"^[\S ]{1,128}$"),
        Optional("description"): str,

        Optional("start"): datetime.datetime,
        Optional("stop"): datetime.datetime,

        Optional("from"): {
            "dojo": Regex(r"^[\S ]{1,128}$"),
            "module": Regex(r"^[\S ]{1,128}$"),
        },

        Optional("challenges", default=[]):  [{
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
    }],
})


def load_dojo(data, *, dojo_id=None):
    data = DOJO_SPEC.validate(data)

    dojo_cls = {
        "public": PublicDojos,
        "private": PrivateDojos,
    }[data["type"]]

    dojo_kwargs = dict(
        id=dojo_id,
        name=data.get("name"),
        description=data.get("description")
    )

    if dojo_cls is PrivateDojos:
        assert "password" in data, "Missing key: 'password'"
        dojo_kwargs["password"] = data["password"]

    dojo = db.session.merge(dojo_cls(**dojo_kwargs))

    # TODO: for all references: index -> name

    dojo.modules = [
        DojoModules(
            name=module.get("name"),
            description=module.get("description"),
            challenges=[
                DojoChallenges(
                    name=challenge.get("name"),
                    description=challenge.get("description"),
                )
                for challenge in module["challenges"]
            ]
        )
        for module in data["modules"]
    ]

    # TODO: for all references: name -> index

    db.session.commit()
