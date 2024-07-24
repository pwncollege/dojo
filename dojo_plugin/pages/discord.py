import sys

import requests
from flask import request, Blueprint, url_for, redirect, abort, current_app
from sqlalchemy.exc import IntegrityError
from itsdangerous.url_safe import URLSafeTimedSerializer
from CTFd.models import db
from CTFd.cache import cache
from CTFd.utils.user import get_current_user
from CTFd.utils.decorators import authed_only

from ..models import DiscordUsers
from ..config import DISCORD_CLIENT_ID
from ..utils.discord import OAUTH_ENDPOINT, get_discord_id, get_discord_member, add_role
from ..utils.awards import update_awards


discord = Blueprint("discord", __name__)
discord_oauth_serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], "DISCORD_OAUTH")


@discord.route("/discord/connect")
@authed_only
def discord_connect():
    if not DISCORD_CLIENT_ID:
        abort(501)

    state = discord_oauth_serializer.dumps(get_current_user().id)
    params = dict(client_id=DISCORD_CLIENT_ID,
                  redirect_uri=url_for("discord.discord_redirect", _external=True),
                  response_type="code",
                  scope="identify",
                  state=state)
    oauth_url = requests.Request("GET", f"{OAUTH_ENDPOINT}/authorize", params=params).prepare().url

    return redirect(oauth_url)


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
        redirect_user_id = discord_oauth_serializer.loads(state, max_age=60)
        user = get_current_user()
        user_id = user.id
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
        cache.delete_memoized(get_discord_member, user_id)
        if get_discord_member(user_id):
            add_role(discord_id, "White Belt")
            update_awards(user)
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "Discord user already in use"}, 400

    return redirect("/settings#discord")
