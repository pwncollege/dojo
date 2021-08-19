from CTFd.models import db, Admins, Pages, Flags
from CTFd.utils import config, get_config, set_config

from .docker_challenge import DockerChallenges
from .utils import challenge_paths


def bootstrap():
    set_config("ctf_name", "pwn.college")
    set_config("ctf_description", "pwn.college")
    set_config("user_mode", "users")

    set_config("challenge_visibility", "public")
    set_config("registration_visibility", "public")
    set_config("score_visibility", "public")
    set_config("account_visibility", "public")

    set_config("ctf_theme", "pwncollege_theme")

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

    for path in challenge_paths():
        name = path.name
        category = path.parent.name

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
