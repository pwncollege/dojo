import sys

import requests
from flask import request, Blueprint, redirect, abort, current_app
from sqlalchemy.exc import IntegrityError
from itsdangerous.url_safe import URLSafeTimedSerializer
from CTFd.models import db
from CTFd.cache import cache
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from .config import VIRTUAL_HOST, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID


OAUTH_ENDPOINT = "https://discord.com/api/oauth2"
API_ENDPOINT = "https://discord.com/api/v9"
REDIRECT_URI = f"https://{VIRTUAL_HOST}/discord/redirect"


class DiscordUsers(db.Model):
    __tablename__ = "discord_users"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    discord_id = db.Column(db.Text, unique=True)


def bot_join_server():
    # "Server Members Intent" also required
    params = dict(client_id=DISCORD_CLIENT_ID, scope="bot", permissions=268437504, guild_id=DISCORD_GUILD_ID)
    url = requests.Request("GET", f"{OAUTH_ENDPOINT}/authorize", params=params).prepare().url
    return url


def oauth_url(user_id, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]

    serializer = URLSafeTimedSerializer(secret, "DISCORD_OAUTH")

    state = serializer.dumps(user_id)
    params = dict(client_id=DISCORD_CLIENT_ID, redirect_uri=REDIRECT_URI, response_type="code", scope="identify", state=state)
    url = requests.Request("GET", f"{OAUTH_ENDPOINT}/authorize", params=params).prepare().url
    return url


def unserialize_oauth_state(state, *, secret=None):
    if secret is None:
        secret = current_app.config["SECRET_KEY"]

    serializer = URLSafeTimedSerializer(secret, "DISCORD_OAUTH")

    user_id = serializer.loads(state, max_age=60)
    return user_id


def get_discord_id(auth_code):
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
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

    response = requests.get(f"{API_ENDPOINT}/users/{discord_id}", headers=headers)
    return response.json()


def add_role(user_id, role_name):
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    }

    response = requests.get(f"{API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/roles", headers=headers)
    roles = response.json()

    roles = [role for role in roles if role["name"] == role_name]
    assert len(roles) == 1
    role_id = roles[0]["id"]

    response = requests.put(f"{API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/members/{user_id}/roles/{role_id}", headers=headers)
    response.raise_for_status()


def discord_avatar_asset(discord_user):
    if not discord_user:
        return "plugins/pwncollege_plugin/assets/settings/discord_logo.svg"
    discord_id = discord_user["id"]
    discord_avatar = discord_user["avatar"]
    return f"https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png"


@cache.memoize(timeout=1800)
def discord_reputation():
    result = {}
    offset = 0
    while True:
        url = f"https://yagpdb.xyz/api/{DISCORD_GUILD_ID}/reputation/leaderboard"
        params = {
            "limit": 100,
            "offset": offset,
        }
        response = requests.get(url, params=params)
        for row in response.json():
            result[str(row["user_id"])] = row["points"]
        if len(response.json()) != 100:
            break
        offset += 100
    return result


discord = Blueprint("discord", __name__)


@discord.route("/discord/connect")
@authed_only
def discord_connect():
    if not DISCORD_CLIENT_ID:
        abort(501)

    user_id = get_current_user().id
    return redirect(oauth_url(user_id))


@discord.route("/discord/redirect")
@authed_only
def discord_redirect():
    if not DISCORD_CLIENT_ID:
        abort(501)

    state = request.args.get("state")
    code = request.args.get("code")

    if not state or not code:
        abort(400)

    try:
        redirect_user_id = unserialize_oauth_state(state)
        user_id = get_current_user().id
        assert user_id == redirect_user_id, (user_id, redirect_user_id)
        discord_id = get_discord_id(code)
    except Exception as e:
        print(f"ERROR: Discord redirect failed: {e}", file=sys.stderr, flush=True)
        return {"success": False, "error": "Discord redirect failed"}, 400

    try:
        existing_discord_user = DiscordUsers.query.filter_by(user_id=user_id).first()
        if not existing_discord_user:
            discord_user = DiscordUsers(user_id=user_id, discord_id=discord_id)
            db.session.add(discord_user)
        else:
            existing_discord_user.discord_id = discord_id
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Discord user already in use"}, 400

    return redirect("/settings#discord")
