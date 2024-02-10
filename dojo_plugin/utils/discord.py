import requests
from flask import url_for
from CTFd.cache import cache

from ..models import DiscordUsers
from ..config import DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID


OAUTH_ENDPOINT = "https://discord.com/api/oauth2"
API_ENDPOINT = "https://discord.com/api/v9"


def discord_request(endpoint, method="GET", **json):
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    json = json or None
    response = requests.request(method, f"{API_ENDPOINT}{endpoint}", headers=headers, json=json)
    response.raise_for_status()
    if "application/json" in response.headers.get("Content-Type", ""):
        return response.json()
    else:
        return response.content


def guild_request(endpoint, method="GET", **json):
    return discord_request(f"/guilds/{DISCORD_GUILD_ID}{endpoint}", method=method, **json)


def get_bot_join_server_url():
    # "Server Members Intent" also required
    params = dict(client_id=DISCORD_CLIENT_ID, scope="bot", permissions=268437504, guild_id=DISCORD_GUILD_ID)
    url = requests.Request("GET", f"{OAUTH_ENDPOINT}/authorize", params=params).prepare().url
    return url


def discord_avatar_asset(discord_user):
    if not discord_user:
        return url_for("views.themes", path="img/dojo/discord_logo.svg")
    discord_id = discord_user["user"]["id"]
    discord_avatar = discord_user["user"]["avatar"]
    return f"https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png"


def get_discord_id(auth_code):
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": url_for("discord.discord_redirect", _external=True),
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    response = requests.post(f"{OAUTH_ENDPOINT}/token", data=data, headers=headers)
    access_token = response.json()["access_token"]

    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    response = requests.get(f"{API_ENDPOINT}/users/@me", headers=headers)
    discord_id = response.json()["id"]
    return discord_id


@cache.memoize(timeout=3600)
def get_discord_user(user_id):
    if not DISCORD_BOT_TOKEN:
        return

    discord_user = DiscordUsers.query.filter_by(user_id=user_id).first()
    if not discord_user:
        return False
    try:
        result = guild_request(f"/members/{discord_user.discord_id}")
    except requests.exceptions.RequestException:
        return None
    if result.get("message") == "Unknown Member":
        return None
    return result


@cache.memoize(timeout=3600)
def get_discord_roles():
    if not DISCORD_BOT_TOKEN:
        return {}
    roles = guild_request("/roles")
    return {role["name"]: role["id"] for role in roles}


def send_message(message, channel_name):
    channel_ids = [channel["id"] for channel in guild_request("/channels") if channel["name"] == channel_name]
    assert len(channel_ids) == 1
    channel_id = channel_ids[0]
    discord_request(f"/channels/{channel_id}/messages", method="POST", content=message)


def add_role(discord_id, role_name):
    role_id = get_discord_roles()[role_name]
    guild_request(f"/members/{discord_id}/roles/{role_id}", method="PUT")
