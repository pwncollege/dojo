import collections
import contextlib
import datetime
import math
import pytz
import json

import redis

from flask import url_for, abort, current_app
from flask_restx import Namespace, Resource
from flask_sqlalchemy import Pagination
from CTFd.cache import cache
from CTFd.models import db, Solves, Challenges, Users, Submissions, Awards
from CTFd.utils.user import get_current_user
from CTFd.utils.modes import get_model, generate_account_url
from sqlalchemy import event
from sqlalchemy.orm.session import Session

from ...models import Dojos, DojoChallenges, DojoUsers, DojoMembers, DojoAdmins, DojoStudents, DojoModules, DojoChallengeVisibilities, Belts, Emojis
from ...utils.dojo import dojo_route, dojo_accessible
from ...utils.awards import get_belts, get_viewable_emojis

SCOREBOARD_CACHE_TIMEOUT_SECONDS = 60 * 60 * 2 # two hours make to cache all scoreboards
scoreboard_namespace = Namespace("scoreboard")

def email_symbol_asset(email):
    if email.endswith("@asu.edu"):
        group = "fork.png"
    elif ".edu" in email.split("@")[1]:
        group = "student.png"
    else:
        group = "hacker.png"
    return url_for("views.themes", path=f"img/dojo/{group}")

@cache.memoize(timeout=SCOREBOARD_CACHE_TIMEOUT_SECONDS)
def get_scoreboard_for(model, duration):
    duration_filter = (
        Solves.date >= datetime.datetime.utcnow() - datetime.timedelta(days=duration)
        if duration else True
    )
    required_filter = DojoChallenges.required == True
    solves = db.func.count().label("solves")
    rank = (
        db.func.row_number()
        .over(order_by=(solves.desc(), db.func.max(Solves.id)))
        .label("rank")
    )
    user_entities = [Solves.user_id, Users.name, Users.email]
    query = (
        model.solves()
        .filter(duration_filter)
        .filter(required_filter)
        .group_by(*user_entities)
        .order_by(rank)
        .with_entities(rank, solves, *user_entities)
    )

    row_results = query.all()
    results = [{key: getattr(item, key) for key in item.keys()} for item in row_results]
    return results

def invalidate_scoreboard_cache():
    cache.delete_memoized(get_scoreboard_for)

def publish_dojo_stats_event(dojo_id_int):
    from ...utils.background_stats import publish_stat_event, BACKGROUND_STATS_ENABLED
    if BACKGROUND_STATS_ENABLED:
        publish_stat_event("dojo_stats_update", {"dojo_id": dojo_id_int})

# handle cache invalidation for new solves, dojo creation, dojo challenge creation
@event.listens_for(Dojos, 'after_insert', propagate=True)
@event.listens_for(Dojos, 'after_delete', propagate=True)
@event.listens_for(Solves, 'after_insert', propagate=True)
@event.listens_for(Solves, 'after_delete', propagate=True)
@event.listens_for(Awards, 'after_insert', propagate=True)
@event.listens_for(Awards, 'after_delete', propagate=True)
@event.listens_for(Belts, 'after_insert', propagate=True)
@event.listens_for(Belts, 'after_delete', propagate=True)
@event.listens_for(Emojis, 'after_insert', propagate=True)
@event.listens_for(Emojis, 'after_delete', propagate=True)
def hook_object_creation(mapper, connection, target):
    invalidate_scoreboard_cache()

    if isinstance(target, Solves):
        dojo_challenge = DojoChallenges.query.filter_by(challenge_id=target.challenge_id).first()
        if dojo_challenge:
            publish_dojo_stats_event(dojo_challenge.dojo.dojo_id)
    elif isinstance(target, Dojos):
        publish_dojo_stats_event(target.dojo_id)

@event.listens_for(Users, 'after_update', propagate=True)
@event.listens_for(Dojos, 'after_update', propagate=True)
@event.listens_for(DojoUsers, 'after_update', propagate=True)
@event.listens_for(DojoMembers, 'after_update', propagate=True)
@event.listens_for(DojoAdmins, 'after_update', propagate=True)
@event.listens_for(DojoStudents, 'after_update', propagate=True)
@event.listens_for(DojoModules, 'after_update', propagate=True)
@event.listens_for(DojoChallenges, 'after_update', propagate=True)
@event.listens_for(DojoChallengeVisibilities, 'after_update', propagate=True)
@event.listens_for(Belts, 'after_update', propagate=True)
@event.listens_for(Emojis, 'after_update', propagate=True)
def hook_object_update(mapper, connection, target):
    if Session.object_session(target).is_modified(target, include_collections=False):
        invalidate_scoreboard_cache()

        if isinstance(target, Dojos):
            publish_dojo_stats_event(target.dojo_id)
        elif isinstance(target, DojoChallenges):
            publish_dojo_stats_event(target.dojo.dojo_id)
        elif isinstance(target, DojoModules):
            publish_dojo_stats_event(target.dojo.dojo_id)

def get_scoreboard_page(model, duration=None, page=1, per_page=20):
    belt_data = get_belts()
    results = get_scoreboard_for(model, duration)

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    pagination = Pagination(None, page, per_page, len(results), results[start_idx:end_idx])
    user = get_current_user()
    emojis = get_viewable_emojis(user)

    def standing(item):
        if not item:
            return
        user_id = item["user_id"]
        belt_color = belt_data["users"].get(user_id, {"color": "white"})["color"]
        result = {key: item[key] for key in item.keys()}
        result.update({
            "url": url_for("pwncollege_users.view_other", user_id=user_id),
            "symbol": email_symbol_asset(result.pop("email")),
            "belt": url_for("pwncollege_belts.view_belt", color=belt_color),
            "badges": emojis.get(user_id, [])
        })
        return result

    result = {
        "standings": [standing(item) for item in pagination.items],
    }

    pages = set(page for page in pagination.iter_pages() if page)

    if user and not user.hidden:
        me = None
        for r in results:
            if r["user_id"] == user.id:
                me = standing(r)
                break
        if me:
            pages.add((me["rank"] - 1) // per_page + 1)
            result["me"] = me

    result["pages"] = sorted(pages)

    return result


@scoreboard_namespace.route("/<dojo>/_/<int:duration>/<int:page>")
class ScoreboardDojo(Resource):
    @dojo_route
    def get(self, dojo, duration, page):
        return get_scoreboard_page(dojo, duration=duration, page=page)

@scoreboard_namespace.route("/<dojo>/<module>/<int:duration>/<int:page>")
class ScoreboardModule(Resource):
    @dojo_route
    def get(self, dojo, module, duration, page):
        return get_scoreboard_page(module, duration=duration, page=page)
