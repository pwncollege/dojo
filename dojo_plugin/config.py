import warnings
import logging
import os

from CTFd.models import db, Admins, Pages
from CTFd.cache import cache
from CTFd.utils import config, set_config
from .utils import multiprocess_lock, load_dojo

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

VIRTUAL_HOST = os.getenv("VIRTUAL_HOST")
HOST_DATA_PATH = os.getenv("HOST_DATA_PATH")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
BINARY_NINJA_API_KEY = os.getenv("BINARY_NINJA_API_KEY")

missing_errors = ["VIRTUAL_HOST", "HOST_DATA_PATH"]
missing_warnings = ["DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "BINARY_NINJA_API_KEY"]

for config_option in missing_errors:
    config_value = globals()[config_option]
    if not config_value:
        raise RuntimeError(f"Configuration Error: {config_option} must be set in the environment")

for config_option in missing_warnings:
    config_value = globals()[config_option]
    if not config_value:
        warnings.warn(f"Configuration Warning: {config_option} is not set in the environment")


@multiprocess_lock
def bootstrap():
    from .models import Dojos
    from .pages.discord import discord_reputation
    from .utils import CHALLENGES_DIR, DOJOS_DIR
    from .utils.dojo import load_dojo_dir

    set_config("ctf_name", "pwn.college")
    set_config("ctf_description", "pwn.college")
    set_config("user_mode", "users")

    set_config("challenge_visibility", "public")
    set_config("registration_visibility", "public")
    set_config("score_visibility", "public")
    set_config("account_visibility", "public")

    set_config("ctf_theme", "dojo_theme")

    set_config("mailfrom_addr", f"hacker@{VIRTUAL_HOST}")
    set_config("mail_server", f"mailserver")
    set_config("mail_port", 587)
    set_config("mail_useauth", True)
    set_config("mail_username", f"hacker@{VIRTUAL_HOST}")
    set_config("mail_password", "hacker")

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

    # for dojo_dir in DOJOS_DIR.glob("*/"):
    #     logger.info(f"Loading dojo: {dojo_dir}")
    #     existing_dojo = Dojos.resolve_from_unique_name(dojo_dir.name)
    #     dojo = load_dojo_dir(dojo_dir, dojo=existing_dojo)
    #     db.session.add(dojo)
    #     db.session.commit()
