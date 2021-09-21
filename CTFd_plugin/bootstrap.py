import re

from flask_restx import Namespace, Resource
from CTFd.models import db, Admins, Pages, Flags
from CTFd.utils import config, get_config, set_config
from CTFd.utils.decorators import admins_only

from .docker_challenge import DockerChallenges
from .utils import CHALLENGES_DIR


bootstrap_namespace = Namespace(
    "bootstrap", description="Endpoint to manage bootstrapping"
)


@bootstrap_namespace.route("")
class Bootstrap(Resource):
    @admins_only
    def get(self):
        self.bootstrap()
        return {"success": True}

    @staticmethod
    def bootstrap():
        set_config("ctf_name", "pwn.college")
        set_config("ctf_description", "pwn.college")
        set_config("user_mode", "users")

        set_config("challenge_visibility", "public")
        set_config("registration_visibility", "public")
        set_config("score_visibility", "public")
        set_config("account_visibility", "public")

        set_config("ctf_theme", "pwncollege_theme")

        with open(CHALLENGES_DIR / "modules.yml") as f:
            modules = f.read()
        set_config("modules", modules)

        with open(CHALLENGES_DIR / "students.yml") as f:
            students = f.read()
        set_config("students", students)

        if not config.is_setup():
            admin = Admins(
                name="admin",
                email="admin@example.com",
                password="admin",
                type="admin",
                hidden=True,
            )
            page = Pages(title=None, route="index", content="", draft=False)

            db.session.add(admin)
            db.session.add(page)
            db.session.commit()

            set_config("setup", True)

        def natural_key(text):
            def atof(text):
                try:
                    retval = float(text)
                except ValueError:
                    retval = text
                return retval

            return [
                atof(c)
                for c in re.split(r"[+-]?([0-9]+(?:[.][0-9]*)?|[.][0-9]+)", text)
            ]

        challenges = sorted(
            ((path.parent.name, path.name) for path in CHALLENGES_DIR.glob("*/*")),
            key=lambda k: (k[0], natural_key(k[1])),
        )
        for category, name in challenges:
            if name.startswith(".") or name.startswith("_"):
                continue
            if category.startswith(".") or category.startswith("_"):
                continue

            challenge = DockerChallenges.query.filter_by(
                name=name, category=category
            ).first()
            if challenge:
                continue

            challenge = DockerChallenges(
                name=name,
                category=category,
                description="",
                value=1,
                state="visible",
                docker_image_name="pwncollege_challenge",
            )
            db.session.add(challenge)
            db.session.commit()

            global_flag_file = CHALLENGES_DIR / category / name / "_global" / "_flag"
            if global_flag_file.exists():
                with open(global_flag_file, 'r') as fp:
                    flag_txt = fp.read().strip()
                flag = Flags(
                    challenge_id=challenge.id,
                    type="static",
                    content=flag_txt,
                    data="",
                )
            else:
                flag = Flags(
                    challenge_id=challenge.id,
                    type="user",
                    content="",
                    data="cheater",
                )
            db.session.add(flag)
            db.session.commit()
