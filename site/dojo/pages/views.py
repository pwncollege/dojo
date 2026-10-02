from flask import Blueprint, abort, redirect, send_from_directory, url_for

from ..config import THEME_STATIC
from .dojos import listing as dojo_listing
from .settings import settings_page

views = Blueprint("views", __name__)
challenges = Blueprint("challenges", __name__)


def static_html(route):
    if route != "index":
        abort(404)
    return dojo_listing("index.html")


def themes(path):
    return send_from_directory(THEME_STATIC, path, max_age=3600)


views.add_url_rule("/", "static_html", static_html, defaults={"route": "index"})
# the second rule is what keeps url_for("views.static_html", route="/") == "/"
views.add_url_rule("/<path:route>", "static_html", static_html)
views.add_url_rule("/settings", "settings", settings_page)
views.add_url_rule("/themes/dojo_theme/static/<path:path>", "themes", themes)


@challenges.route("/challenges")
def listing():
    return redirect(url_for("pwncollege_dojos.listing"), code=301)
