import logging

from flask import url_for
from flask_restx import Namespace, Resource
from flask_sqlalchemy import Pagination
from CTFd.utils.user import get_current_user

from ...models import Dojos, DojoModules
from ...utils.dojo import dojo_route
from ...utils.awards import get_belts, get_viewable_emojis
from ...utils.background_stats import get_cached_stat

logger = logging.getLogger(__name__)

scoreboard_namespace = Namespace("scoreboard")


def email_symbol_asset(email):
    if email.endswith("@asu.edu"):
        group = "fork.png"
    elif ".edu" in email.split("@")[1]:
        group = "student.png"
    else:
        group = "hacker.png"
    return url_for("views.themes", path=f"img/dojo/{group}")


def get_scoreboard_for(model, duration):
    if isinstance(model, Dojos):
        cache_key = f"stats:scoreboard:dojo:{model.dojo_id}:{duration}"
    elif isinstance(model, DojoModules):
        cache_key = f"stats:scoreboard:module:{model.dojo_id}:{model.module_index}:{duration}"
    else:
        return []

    logger.info(f"get_scoreboard_for: checking cache key {cache_key}")
    cached = get_cached_stat(cache_key)
    logger.info(f"get_scoreboard_for: cached={cached is not None}, len={len(cached) if cached else 0}")

    if cached:
        logger.info(f"Returning cached scoreboard with {len(cached)} entries")
        return cached

    logger.info(f"Cache miss/empty, returning []")
    return []


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
