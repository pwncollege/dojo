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

def calculate_scoreboard_sync(model, duration):
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

def get_scoreboard_for(model, duration):
    from ...utils.background_stats import get_cached_stat, BACKGROUND_STATS_ENABLED, BACKGROUND_STATS_FALLBACK
    import logging
    logger = logging.getLogger(__name__)

    if BACKGROUND_STATS_ENABLED:
        if isinstance(model, Dojos):
            cache_key = f"stats:scoreboard:dojo:{model.dojo_id}:{duration}"
        elif isinstance(model, DojoModules):
            cache_key = f"stats:scoreboard:module:{model.dojo_id}:{model.module_index}:{duration}"
        else:
            return calculate_scoreboard_sync(model, duration)

        logger.info(f"get_scoreboard_for: checking cache key {cache_key}")
        cached = get_cached_stat(cache_key)
        logger.info(f"get_scoreboard_for: cached={cached is not None}, len={len(cached) if cached else 0}, fallback={BACKGROUND_STATS_FALLBACK}")

        if cached:
            logger.info(f"Returning cached scoreboard with {len(cached)} entries")
            return cached

        if BACKGROUND_STATS_FALLBACK:
            logger.info(f"Cache miss/empty, falling back to sync calculation")
            return calculate_scoreboard_sync(model, duration)
        else:
            logger.info(f"Cache miss/empty, no fallback, returning []")
            return []

    return calculate_scoreboard_sync(model, duration)

def invalidate_scoreboard_cache():
    cache.delete_memoized(get_scoreboard_for)

def publish_dojo_stats_event(dojo_id_int):
    from ...utils.background_stats import publish_stat_event, BACKGROUND_STATS_ENABLED
    if BACKGROUND_STATS_ENABLED:
        publish_stat_event("dojo_stats_update", {"dojo_id": dojo_id_int})

def publish_scoreboard_event(model_type, model_id):
    from ...utils.background_stats import publish_stat_event, BACKGROUND_STATS_ENABLED
    if BACKGROUND_STATS_ENABLED:
        publish_stat_event("scoreboard_update", {"model_type": model_type, "model_id": model_id})

def publish_scores_event():
    from ...utils.background_stats import publish_stat_event, BACKGROUND_STATS_ENABLED
    if BACKGROUND_STATS_ENABLED:
        publish_stat_event("scores_update", {})

def publish_belts_event():
    from ...utils.background_stats import publish_stat_event, BACKGROUND_STATS_ENABLED
    if BACKGROUND_STATS_ENABLED:
        publish_stat_event("belts_update", {})

def publish_emojis_event():
    from ...utils.background_stats import publish_stat_event, BACKGROUND_STATS_ENABLED
    if BACKGROUND_STATS_ENABLED:
        publish_stat_event("emojis_update", {})

# handle cache invalidation for new solves, dojo creation, dojo challenge creation
def _queue_stat_events_for_publish():
    from flask import g
    if not hasattr(g, '_pending_stat_events'):
        g._pending_stat_events = []
    return g._pending_stat_events

def _publish_queued_events():
    from flask import g
    import logging
    logger = logging.getLogger(__name__)

    if hasattr(g, '_pending_stat_events'):
        count = len(g._pending_stat_events)
        if count > 0:
            logger.info(f"Publishing {count} queued stat events after request")
        for event_func in g._pending_stat_events:
            event_func()
        g._pending_stat_events = []

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
        import logging
        logger = logging.getLogger(__name__)

        dojo_challenges = DojoChallenges.query.filter_by(challenge_id=target.challenge_id).all()
        logger.info(f"Solve listener fired: challenge_id={target.challenge_id}, found {len(dojo_challenges)} dojo(s)")

        for dojo_challenge in dojo_challenges:
            dojo_id = dojo_challenge.dojo.dojo_id
            module_id = {"dojo_id": dojo_challenge.dojo.dojo_id, "module_index": dojo_challenge.module.module_index}
            logger.info(f"Queueing events for dojo {dojo_challenge.dojo.reference_id} (dojo_id={dojo_id})")
            _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
            _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
            _queue_stat_events_for_publish().append(lambda m_id=module_id: publish_scoreboard_event("module", m_id))
        _queue_stat_events_for_publish().append(publish_scores_event)
    elif isinstance(target, Dojos):
        dojo_id = target.dojo_id
        _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
        _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
        _queue_stat_events_for_publish().append(publish_scores_event)
    elif isinstance(target, Belts):
        _queue_stat_events_for_publish().append(publish_belts_event)
    elif isinstance(target, Emojis):
        _queue_stat_events_for_publish().append(publish_emojis_event)

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
            dojo_id = target.dojo_id
            _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
            _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
            _queue_stat_events_for_publish().append(publish_scores_event)
        elif isinstance(target, DojoChallenges):
            dojo_id = target.dojo.dojo_id
            module_id = {"dojo_id": target.dojo.dojo_id, "module_index": target.module.module_index}
            _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
            _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_scoreboard_event("dojo", d_id))
            _queue_stat_events_for_publish().append(lambda m_id=module_id: publish_scoreboard_event("module", m_id))
        elif isinstance(target, DojoModules):
            dojo_id = target.dojo.dojo_id
            module_id = {"dojo_id": target.dojo.dojo_id, "module_index": target.module_index}
            _queue_stat_events_for_publish().append(lambda d_id=dojo_id: publish_dojo_stats_event(d_id))
            _queue_stat_events_for_publish().append(lambda m_id=module_id: publish_scoreboard_event("module", m_id))
        elif isinstance(target, Belts):
            _queue_stat_events_for_publish().append(publish_belts_event)
        elif isinstance(target, Emojis):
            _queue_stat_events_for_publish().append(publish_emojis_event)

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

    standings_list = []
    for item in pagination.items:
        s = standing(item)
        if s is not None:
            standings_list.append(s)

    result = {
        "standings": standings_list,
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
