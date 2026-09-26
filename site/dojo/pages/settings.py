from flask import render_template, url_for
from markupsafe import Markup

from ..utils.countries import COUNTRIES
from ..utils.decorators import authed_only
from ..utils.user import get_current_user

from ..models import SSHKeys, DiscordUsers, Tokens, get_config
from ..config import DISCORD_CLIENT_ID
from ..utils.discord import get_discord_member, discord_avatar_asset


@authed_only
def settings_page():
    infos = []

    user = get_current_user()
    tokens = Tokens.query.filter_by(user_id=user.id).all()

    ssh_keys = SSHKeys.query.filter_by(user_id=user.id).all()

    discord_member = get_discord_member(DiscordUsers.query.filter_by(user=user)
                                        .with_entities(DiscordUsers.discord_id).scalar())

    if get_config("verify_emails") and not user.verified:
        confirm_url = Markup(url_for("auth.confirm"))
        infos.append(
            Markup(
                "Your email address isn't confirmed!<br>"
                "Please check your email to confirm your email address.<br><br>"
                f'To have the confirmation email resent please <a href="{confirm_url}">click here</a>.'
            )
        )

    return render_template(
        "settings.html",
        user=user,
        tokens=tokens,
        ssh_keys=[key.value for key in ssh_keys],
        discord_enabled=bool(DISCORD_CLIENT_ID),
        discord_member=discord_member,
        discord_avatar_asset=discord_avatar_asset,
        infos=infos,
        countries=COUNTRIES,
    )
