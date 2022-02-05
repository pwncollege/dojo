from flask import url_for, render_template
from CTFd.models import UserTokens
from CTFd.utils import get_config
from CTFd.utils.helpers import get_infos, markup
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

from ..models import PrivateDojos, SSHKeys
from ..utils import user_dojos, active_dojo_id
from ..config import DISCORD_CLIENT_ID
from .discord import get_discord_user, discord_avatar_asset


@authed_only
def settings_override():
    infos = get_infos()

    user = get_current_user()
    name = user.name
    email = user.email
    website = user.website
    affiliation = user.affiliation
    country = user.country

    tokens = UserTokens.query.filter_by(user_id=user.id).all()

    ssh_key = SSHKeys.query.filter_by(user_id=user.id).first()
    ssh_key = ssh_key.value if ssh_key else None

    private_dojos = user_dojos(user.id)
    active_dojo = active_dojo_id(user.id)
    user_dojo = PrivateDojos.query.filter_by(id=user.id).first()

    discord_user = get_discord_user(user.id)

    prevent_name_change = get_config("prevent_name_change")

    if get_config("verify_emails") and not user.verified:
        confirm_url = markup(url_for("auth.confirm"))
        infos.append(
            markup(
                "Your email address isn't confirmed!<br>"
                "Please check your email to confirm your email address.<br><br>"
                f'To have the confirmation email resent please <a href="{confirm_url}">click here</a>.'
            )
        )

    return render_template(
        "settings.html",
        name=name,
        email=email,
        website=website,
        affiliation=affiliation,
        country=country,
        tokens=tokens,
        ssh_key=ssh_key,
        private_dojos=private_dojos,
        active_dojo=active_dojo,
        user_dojo=user_dojo,
        discord_enabled=bool(DISCORD_CLIENT_ID),
        discord_user=discord_user,
        discord_avatar_asset=discord_avatar_asset,
        prevent_name_change=prevent_name_change,
        infos=infos,
    )
