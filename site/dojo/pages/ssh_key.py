import datetime

from flask import Blueprint, render_template
from sqlalchemy.exc import IntegrityError
from CTFd.models import db
from CTFd.utils.decorators import authed_only
from CTFd.utils.user import get_current_user

from ..models import SSHKeyLinkRequests, SSHKeys
from ..utils.ssh_onboarding import ssh_link_token_digest


ssh_key = Blueprint("pwncollege_ssh_key", __name__)


@ssh_key.route("/ssh/link/<token>")
@authed_only
def link_ssh_key(token):
    user = get_current_user()
    link_request = SSHKeyLinkRequests.query.filter_by(token_digest=ssh_link_token_digest(token)).first()
    status = "missing"
    error = None

    if not link_request:
        error = "This SSH key link is invalid."
    elif link_request.consumed:
        status = "linked"
    elif link_request.expiration < datetime.datetime.utcnow():
        status = "expired"
        error = "This SSH key link has expired."
    else:
        try:
            db.session.add(SSHKeys(user_id=user.id, value=link_request.key_value))
            link_request.user_id = user.id
            link_request.consumed = datetime.datetime.utcnow()
            db.session.commit()
            status = "linked"
        except IntegrityError:
            db.session.rollback()
            status = "duplicate"
            error = "This SSH key is already linked to an account."

    return render_template(
        "ssh_key_link.html",
        status=status,
        error=error,
        link_request=link_request,
        user=user,
    )
