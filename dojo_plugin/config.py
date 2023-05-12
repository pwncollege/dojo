import warnings
import logging
import ast
import os

from CTFd.models import db, Admins, Pages
from CTFd.cache import cache
from CTFd.utils import config, set_config
from .utils import multiprocess_lock, load_dojo

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DOJO_HOST = os.getenv("DOJO_HOST")
HOST_DATA_PATH = os.getenv("HOST_DATA_PATH")
MAIL_SERVER = os.getenv("MAIL_SERVER")
MAIL_PORT = os.getenv("MAIL_PORT")
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_ADDRESS = os.getenv("MAIL_ADDRESS")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
BINARY_NINJA_API_KEY = os.getenv("BINARY_NINJA_API_KEY")
INTERNET_FOR_ALL = bool(ast.literal_eval(os.getenv("INTERNET_FOR_ALL") or "False"))

missing_errors = ["DOJO_HOST", "HOST_DATA_PATH"]
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
    from .pages.discord import discord_reputation
    from .utils import CHALLENGES_DIR, DOJOS_DIR, DATA_DIR, INDEX_HTML
    from .utils.dojo import load_dojo_dir

    set_config("ctf_name", "pwn.college")
    set_config("ctf_description", "pwn.college")
    set_config("user_mode", "users")

    set_config("challenge_visibility", "public")
    set_config("registration_visibility", "public")
    set_config("score_visibility", "public")
    set_config("account_visibility", "public")

    set_config("ctf_theme", "dojo_theme")

    set_config("mail_server", MAIL_SERVER)
    set_config("mail_port", MAIL_PORT)
    set_config("mail_username", MAIL_USERNAME)
    set_config("mail_password", MAIL_PASSWORD)
    set_config("mailfrom_addr", MAIL_ADDRESS)
    set_config("mail_useauth", bool(MAIL_USERNAME))
    set_config("mail_tls", MAIL_PORT == "587")

    cache.delete_memoized(discord_reputation)
    discord_reputation()

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

    Pages.query.filter_by(route="index").update(dict(content=INDEX_HTML))
    db.session.commit()