import warnings
import logging
import ast
import os
import pathlib
import json
import socket

logger = logging.getLogger(__name__)

DOJOS_DIR = pathlib.Path("/var/dojos")
CTF_NAME = "pwn.college"
THEME_ROOT = pathlib.Path(__file__).resolve().parents[1] / "dojo_theme"
THEME_STATIC = THEME_ROOT / "static"
THEME_TEMPLATES = THEME_ROOT / "templates"

FEED_EVENT_TTL = int(os.environ.get("FEED_EVENT_TTL", "86400"))
FEED_MAX_EVENTS = int(os.environ.get("FEED_MAX_EVENTS", "1000"))
FEED_BATCH_SIZE = int(os.environ.get("FEED_BATCH_SIZE", "50"))

WORKSPACE_NODES = {
    int(node_id): node_key
    for node_id, node_key in
    json.load(pathlib.Path("/var/workspace_nodes.json").open()).items()
}

def create_seccomp():
    seccomp = json.load(pathlib.Path("/etc/docker/seccomp.json").open())

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

def first_ipv4_address(hostname):
    try:
        return sorted(set(info[4][0] for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET)))[0]
    except Exception as e:
        warnings.warn(f"Could not resolve IPv4 address for {hostname}: {e}")
        return None

USER_FIREWALL_ALLOWED = {
    host: first_ipv4_address(host) or "0.0.0.0"
    for host in pathlib.Path("/var/user_firewall.allowed").read_text().split()
}

DOJO_HOST = os.getenv("DOJO_HOST")
WORKSPACE_SECRET = os.environ.get("WORKSPACE_SECRET")
DOJO_SSH_SERVICE_KEY = os.environ.get("DOJO_SSH_SERVICE_KEY")
HOST_DATA_PATH = os.getenv("HOST_DATA_PATH")
MAIL_SERVER = os.getenv("MAIL_SERVER")
MAIL_PORT = os.getenv("MAIL_PORT")
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_ADDRESS = os.getenv("MAIL_ADDRESS")
CORS_ORIGINS = os.getenv("CORS_ORIGINS")
DOCKER_USERNAME = os.getenv("DOCKER_USERNAME")
DOCKER_TOKEN = os.getenv("DOCKER_TOKEN")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
INTERNET_FOR_ALL = bool(ast.literal_eval(os.getenv("INTERNET_FOR_ALL") or "False"))
MAC_HOSTNAME = os.getenv("MAC_HOSTNAME")
MAC_USERNAME = os.getenv("MAC_USERNAME")
LITELLM_URL = "http://litellm:4000"
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY")
LITELLM_USER_KEY_SECRET = os.getenv("LITELLM_USER_KEY_SECRET")
LITELLM_USER_BUDGET_LIMITS = json.loads(os.getenv("LITELLM_USER_BUDGET_LIMITS") or "[]")

missing_errors = ["DOJO_HOST", "HOST_DATA_PATH"]
for config_option in missing_errors:
    config_value = globals()[config_option]
    if not config_value:
        raise RuntimeError(f"Configuration Error: {config_option} must be set in the environment")
