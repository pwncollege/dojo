import collections

from flask import render_template
from CTFd.models import db, Solves, Challenges
from CTFd.cache import cache, make_cache_key
from CTFd.utils import config, get_config
from CTFd.utils.helpers import get_infos
from CTFd.utils.scores import get_standings
from CTFd.utils.user import is_admin
from CTFd.utils.modes import get_model
from CTFd.utils.config.visibility import scores_visible
from CTFd.utils.decorators.visibility import check_score_visibility


def email_group_asset(email):
    if email.endswith("@asu.edu"):
        group = "fork.png"
    elif email.endswith(".edu"):
        group = "student.png"
    else:
        group = "hacker.png"
    return f"plugins/CTFd-pwn-college-plugin/assets/scoreboard/{group}"


def get_category_standings(admin=False):
    Model = get_model()

    scores = (
        Solves.query.join(Challenges, Challenges.id == Solves.challenge_id)
        .filter(Challenges.state == "visible")
        .join(Model, Model.id == Solves.account_id)
        .filter(Model.hidden == False)
    )

    freeze = get_config("freeze")
    if not admin and freeze:
        scores = scores.filter(Solves.date < unix_time_to_utc(freeze))

    scores = scores.group_by(Challenges.category, Solves.account_id).with_entities(
        Challenges.category,
        Solves.account_id,
        Model.name,
        Model.email,
        db.func.count(),
        db.func.max(Solves.date),
    )

    result = collections.defaultdict(list)
    for category, account_id, name, email, count, date in scores:
        result[category].append(
            {
                "account_id": account_id,
                "name": name,
                "email": email,
                "score": count,
                "date": date,
            }
        )

    for ranks in result.values():
        ranks.sort(key=lambda k: (-1 * k["score"], k["date"]))

    return result


@check_score_visibility
@cache.cached(timeout=60, key_prefix=make_cache_key)
def scoreboard_listing():
    infos = get_infos()

    if config.is_scoreboard_frozen():
        infos.append("Scoreboard has been frozen")

    if is_admin() is True and scores_visible() is False:
        infos.append("Scores are not currently visible to users")

    Model = get_model()
    standings = get_standings(fields=[Model.email])

    category_standings = get_category_standings()

    return render_template(
        "scoreboard.html",
        standings=standings,
        category_standings=category_standings,
        infos=infos,
        email_group_asset=email_group_asset,
    )
