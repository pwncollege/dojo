import collections

from flask import render_template
from CTFd.models import db, Solves, Challenges
from CTFd.utils import config, get_config
from CTFd.utils.helpers import get_infos
from CTFd.utils.scores import get_standings
from CTFd.utils.user import is_admin
from CTFd.utils.modes import get_model
from CTFd.utils.config.visibility import scores_visible
from CTFd.utils.decorators.visibility import check_score_visibility

from .belts import get_belts


def email_group_asset(email):
    if email.endswith("@asu.edu"):
        group = "fork.png"
    elif email.endswith(".edu"):
        group = "student.png"
    else:
        group = "hacker.png"
    return f"plugins/pwncollege_plugin/assets/scoreboard/{group}"


def belt_asset(color):
    if color == "blue":
        belt = "blue.svg"
    elif color == "yellow":
        belt = "yellow.svg"
    else:
        belt = "white.svg"
    return f"plugins/pwncollege_plugin/assets/scoreboard/{belt}"


@check_score_visibility
def scoreboard_listing():
    infos = get_infos()

    if config.is_scoreboard_frozen():
        infos.append("Scoreboard has been frozen")

    if is_admin() is True and scores_visible() is False:
        infos.append("Scores are not currently visible to users")

    Model = get_model()
    standings = get_standings(fields=[Model.email])

    belts = {
        user_id: color
        for color, users in get_belts()["colors"].items()
        for user_id in users
    }

    return render_template(
        "scoreboard.html",
        infos=infos,
        standings=standings,
        belts=belts,
        email_group_asset=email_group_asset,
        belt_asset=belt_asset,
    )
