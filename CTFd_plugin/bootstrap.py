import os
import re

from flask_restx import Namespace, Resource
from CTFd.models import db, Admins, Pages, Flags
from CTFd.cache import cache
from CTFd.utils import config, set_config
from CTFd.utils.decorators import admins_only

from .docker_challenge import DockerChallenges
from .private_dojo import validate_dojo_data
from .discord import discord_reputation
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

        modules_path = CHALLENGES_DIR / "modules.yml"
        modules = modules_path.read_text() if modules_path.exists() else (
            """
            - name: Introduction
              permalink: introduction
              lectures:
                - name: "Introduction: What is Computer Systems Security"
                  video: bJTThdqui0g
                  playlist: PL-ymxv0nOtqrxUaIefx0qEC7_155oPEb7
                  slides: 1YlTxeZg03P234EgG4E4JNGcit6LZovAxfYGL1YSLwfc
            """
        )
        validate_dojo_data(modules)
        set_config("modules", modules)

        students_path = CHALLENGES_DIR / "students.yml"
        students = students_path.read_text() if students_path.exists() else "[]"
        set_config("students", students)

        memes_path = CHALLENGES_DIR / "memes.yml"
        memes = memes_path.read_text() if memes_path.exists() else "[]"
        set_config("memes", memes)

        cache.delete_memoized(discord_reputation)
        discord_reputation()

        if not config.is_setup():
            admin_password = os.urandom(8).hex()
            admin = Admins(
                name="admin",
                email="admin@example.com",
                password=admin_password,
                type="admin",
                hidden=True,
            )
            page = Pages(title=None, route="index", content="", draft=False)

            db.session.add(admin)
            db.session.add(page)
            db.session.commit()

            with open("/var/data/initial_credentials", "w") as f:
                f.write(f"admin:{admin_password}\n")

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

            flag = Flags(
                challenge_id=challenge.id,
                type="user",
                content="",
                data="cheater",
            )
            db.session.add(flag)
            db.session.commit()
