import sys

import requests
from flask import request, Blueprint, url_for, redirect, abort, current_app
from sqlalchemy.exc import IntegrityError
from itsdangerous.url_safe import URLSafeTimedSerializer
from CTFd.models import db, Users, Challenges, Solves
from CTFd.cache import cache
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from ..models import DiscordUsers
from ..config import VIRTUAL_HOST, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID
from ..utils import belt_challenges


OAUTH_ENDPOINT = "https://discord.com/api/oauth2"
API_ENDPOINT = "https://discord.com/api/v9"
REDIRECT_URI = f"https://{VIRTUAL_HOST}/discord/redirect"


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
    return response.json()


@cache.memoize(timeout=1800)
def get_discord_roles():
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    }
    roles = requests.get(f"{API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/roles", headers=headers).json()
    return {role["name"]: role["id"] for role in roles}


def add_role(discord_id, role_name):
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
    }
    role_id = get_discord_roles()[role_name]
    response = requests.put(f"{API_ENDPOINT}/guilds/{DISCORD_GUILD_ID}/members/{discord_id}/roles/{role_id}", headers=headers)
    response.raise_for_status()


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


def maybe_award_belt(user_id, *, ignore_challenge_id=None):
    if not DISCORD_BOT_TOKEN:
        return

    discord_user = DiscordUsers.query.filter_by(user_id=user_id).first()
    if not discord_user:
        return

    discord_id = discord_user.discord_id
    user = get_discord_user(user_id)
    roles = get_discord_roles()

    for color, challenges in belt_challenges().items():
        belt_name = f"{color.title()} Belt"

        if ignore_challenge_id is not None:
            challenges = challenges.filter(Challenges.id != ignore_challenge_id)

        belted_user = (
            db.session.query(Users.id)
            .filter(Users.id == user_id)
            .join(Solves, Users.id == Solves.user_id)
            .filter(Solves.challenge_id.in_(challenges.subquery()))
            .group_by(Users.id)
            .having(db.func.count() == challenges.count())
        ).first()
        if not belted_user:
            continue

        role_id = roles[belt_name]
        if role_id in user["roles"]:
            continue

        # TODO: add_role when we have confirmed that this feature is working as expected
        # add_role(discord_id, belt_name)
        send_message(f"<@{discord_id}> has earned their {belt_name}! :tada:", "belting-ceremony")
        cache.delete_memoized(get_discord_user, user_id)


def discord_avatar_asset(discord_user):
    if not discord_user:
        return url_for("views.themes", path="img/dojo/discord_logo.svg")
    discord_id = discord_user["user"]["id"]
    discord_avatar = discord_user["user"]["avatar"]
    return f"https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png"


@cache.memoize(timeout=1800)
def discord_reputation():
    if not DISCORD_GUILD_ID:
        return {}

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
        cache.delete_memoized(get_discord_user, user_id)
        maybe_award_belt(user_id)
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Discord user already in use"}, 400

    return redirect("/settings#discord")
