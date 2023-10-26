import requests
from flask import url_for
from CTFd.cache import cache

from ..models import DiscordUsers
from ..config import DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID


OAUTH_ENDPOINT = "https://discord.com/api/oauth2"
API_ENDPOINT = "https://discord.com/api/v9"


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


@cache.memoize(timeout=1800)
def get_discord_user(user_id):
    if not DISCORD_BOT_TOKEN:
        return

    discord_user = DiscordUsers.query.filter_by(user_id=user_id).first()
    if not discord_user:
        return

    discord_id = discord_user.discord_id

    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    }
    response = requests.get(f"{API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/members/{discord_id}", headers=headers)
    result = response.json()
    if result.get("message") == "Unknown Member":
        return

    return result


@cache.memoize(timeout=1800)
def get_discord_roles():
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    }
    roles = requests.get(f"{API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/roles", headers=headers).json()
    return {role["name"]: role["id"] for role in roles}


def send_message(message, channel_name):
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    }

    channels = requests.get(f"{API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/channels", headers=headers).json()
    channels = [channel for channel in channels if channel["name"] == channel_name]
    assert len(channels) == 1
    channel_id = channels[0]["id"]

    response = requests.post(f"{API_ENDPOINT}/channels/{channel_id}/messages", headers=headers, json=dict(content=message))
    response.raise_for_status()


def add_role(discord_id, role_name):
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    }
    role_id = get_discord_roles()[role_name]
    response = requests.put(f"{API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/members/{discord_id}/roles/{role_id}", headers=headers)
    response.raise_for_status()
