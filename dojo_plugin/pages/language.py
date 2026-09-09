from flask import Blueprint, redirect, request

from ..i18n import LANGUAGE_COOKIE, LANGUAGE_COOKIE_MAX_AGE, selectable_language

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

    response = redirect(target)
    response.set_cookie(LANGUAGE_COOKIE, selected,
                        max_age=LANGUAGE_COOKIE_MAX_AGE,
                        samesite="Lax",
                        secure=request.is_secure)
    return response
