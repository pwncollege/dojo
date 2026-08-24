from flask import Blueprint, redirect, request
from CTFd.models import db
from CTFd.utils.user import authed, get_current_user

from ..i18n import LANGUAGE_COOKIE, LANGUAGE_COOKIE_MAX_AGE, selectable_language
from ..models import UserPreferences

language = Blueprint("pwncollege_language", __name__)


def safe_next(target):
    if not target or not target.startswith("/") or target.startswith("//") or target.startswith("/\\"):
        return "/"
    return target


@language.route("/language", methods=["POST"])
def set_language():
    selected = selectable_language(request.form.get("language"))
    target = safe_next(request.form.get("next"))
    if not selected:
        return redirect(target)

    if authed():
        user = get_current_user()
        preferences = UserPreferences.query.filter_by(user_id=user.id).first()
        if preferences:
            preferences.language = selected
        else:
            db.session.add(UserPreferences(user_id=user.id, language=selected))
        db.session.commit()

    response = redirect(target)
    response.set_cookie(LANGUAGE_COOKIE, selected,
                        max_age=LANGUAGE_COOKIE_MAX_AGE,
                        samesite="Lax",
                        httponly=False)
    return response
