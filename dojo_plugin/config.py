import warnings
import logging
import ast
import os
import pathlib
import json
import socket

from sqlalchemy.exc import IntegrityError
from CTFd.models import db, Admins, Pages
from CTFd.utils import config, set_config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DOJOS_DIR = pathlib.Path("/var/dojos")

WORKSPACE_NODES = {
    int(node_id): node_key
    for node_id, node_key in
    json.load(pathlib.Path("/var/workspace_nodes.json").open()).items()
}

def create_seccomp():
    seccomp = json.load(pathlib.Path("/etc/docker/seccomp.json").open())

    seccomp["syscalls"].append({
        "names": [
            "clone",
            "sethostname",
            "setns",
            "unshare",
        ],
        "action": "SCMP_ACT_ALLOW",
    })

    READ_IMPLIES_EXEC = 0x0400000
    ADDR_NO_RANDOMIZE = 0x0040000

    existing_personality_values = []
    for syscalls in seccomp["syscalls"]:
        if "personality" not in syscalls["names"]:
            continue
        if syscalls["action"] != "SCMP_ACT_ALLOW":
            continue
        assert len(syscalls["args"]) == 1
        arg = syscalls["args"][0]
        assert list(arg.keys()) == ["index", "value", "op"]
        assert arg["index"] == 0, arg
        assert arg["op"] == "SCMP_CMP_EQ"
        existing_personality_values.append(arg["value"])

    new_personality_values = []
    for new_flag in [READ_IMPLIES_EXEC, ADDR_NO_RANDOMIZE]:
        for value in [0, *existing_personality_values]:
            new_value = value | new_flag
            if new_value not in existing_personality_values:
                new_personality_values.append(new_value)
                existing_personality_values.append(new_value)

    for new_value in new_personality_values:
        seccomp["syscalls"].append({
            "names": ["personality"],
            "action": "SCMP_ACT_ALLOW",
            "args": [
                {
                    "index": 0,
                    "value": new_value,
                    "op": "SCMP_CMP_EQ",
                },
            ],
        })

    return json.dumps(seccomp)
SECCOMP = create_seccomp()

USER_FIREWALL_ALLOWED = {
    host: socket.gethostbyname(host)
    for host in pathlib.Path("/var/user_firewall.allowed").read_text().split()
}

DOJO_HOST = os.getenv("DOJO_HOST")
WORKSPACE_SECRET = os.environ.get("WORKSPACE_SECRET")
HOST_DATA_PATH = os.getenv("HOST_DATA_PATH")
MAIL_SERVER = os.getenv("MAIL_SERVER")
MAIL_PORT = os.getenv("MAIL_PORT")
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_ADDRESS = os.getenv("MAIL_ADDRESS")
DOCKER_USERNAME = os.getenv("DOCKER_USERNAME")
DOCKER_TOKEN = os.getenv("DOCKER_TOKEN")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
INTERNET_FOR_ALL = bool(ast.literal_eval(os.getenv("INTERNET_FOR_ALL") or "False"))
WINDOWS_VM_ENABLED = os.getenv("WINDOWS_VM") == "full"

missing_errors = ["DOJO_HOST", "HOST_DATA_PATH"]
for config_option in missing_errors:
    config_value = globals()[config_option]
    if not config_value:
        raise RuntimeError(f"Configuration Error: {config_option} must be set in the environment")

def bootstrap():
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
    set_config("mail_tls", MAIL_PORT == "465" or MAIL_PORT == "587")

    if not config.is_setup():
        admin = Admins(
            name="admin",
            email="admin@example.com",
            password="admin",
            type="admin",
            hidden=True,
        )
        try:
            db.session.add(admin)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

        page = Pages(title=None, route="index", content="", draft=False)
        try:
            db.session.add(page)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

        set_config("setup", True)

    db.session.commit()
