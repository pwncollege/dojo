import os
import re

from flask import request, render_template
from flask_restx import Namespace, Resource
from sqlalchemy.exc import IntegrityError
from wtforms import StringField
from CTFd.models import db, UserTokens
from CTFd.forms import BaseForm
from CTFd.forms.fields import SubmitField
from CTFd.utils import get_config
from CTFd.utils.decorators import authed_only
from CTFd.utils.helpers import get_infos, markup
from CTFd.utils.user import get_current_user


class SSHKeys(db.Model):
    __tablename__ = "ssh_keys"
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    value = db.Column(db.Text, unique=True)


class SSHKeyForm(BaseForm):
    key = StringField("SSH Key")
    submit = SubmitField("Update")


@authed_only
def ssh_key_settings():
    infos = get_infos()

    user = get_current_user()
    name = user.name
    email = user.email
    website = user.website
    affiliation = user.affiliation
    country = user.country

    tokens = UserTokens.query.filter_by(user_id=user.id).all()

    key = SSHKeys.query.filter_by(user_id=user.id).first()
    key = key.value if key else None

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
        key=key,
        prevent_name_change=prevent_name_change,
        infos=infos,
    )


ssh_key_namespace = Namespace(
    "keys", description="Endpoint to manage users' public SSH keys"
)


@ssh_key_namespace.route("")
class UpdateKey(Resource):
    @authed_only
    def patch(self):
        data = request.get_json()
        key_value = data.get("key", "")

        if key_value:
            key_re = "ssh-rsa AAAA[0-9A-Za-z+/]+[=]{0,2}"
            key_match = re.match(key_re, key_value)
            if not key_match:
                return (
                    {
                        "success": False,
                        "errors": {
                            "key": "Invalid public key<br>Expected format: %s" % key_re
                        },
                    },
                    400,
                )
            key_value = key_match.group()

        user = get_current_user()

        try:
            existing_key = SSHKeys.query.filter_by(user_id=user.id).first()
            if not existing_key:
                key = SSHKeys(user_id=user.id, value=key_value)
                db.session.add(key)
            else:
                existing_key.value = key_value
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return (
                {"success": False, "errors": {"key": "Public key already in use"}},
                400,
            )

        return {"success": True}
