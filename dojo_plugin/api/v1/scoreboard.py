import logging

from flask import request, url_for
from flask_restx import Namespace, Resource
from flask_sqlalchemy import Pagination
from CTFd.utils.user import get_current_user

from ...models import Dojos, DojoModules
from ...utils.dojo import dojo_route
from ...utils.awards import get_belts, get_viewable_emojis
from ...utils.background_stats import get_cached_stat
from ...utils.crews import aggregate_crews, parse_crew_tag

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


def model_cache_key(model, kind, duration):
    if isinstance(model, Dojos):
        return f"stats:{kind}:dojo:{model.dojo_id}:{duration}"
    if isinstance(model, DojoModules):
        return f"stats:{kind}:module:{model.dojo_id}:{model.module_index}:{duration}"
    return None


def get_scoreboard_for(model, duration):
    cache_key = model_cache_key(model, "scoreboard", duration)
    if cache_key is None:
        return []
    return get_cached_stat(cache_key) or []


def get_crews_for(model, duration):
    cache_key = model_cache_key(model, "crews", duration)
    if cache_key is None:
        return []
    cached = get_cached_stat(cache_key)
    if cached is not None:
        return cached
    return aggregate_crews(get_scoreboard_for(model, duration))


def standing_entry(item, belt_data, emojis):
    if not item:
        return None
    user_id = item["user_id"]
    belt_color = belt_data["users"].get(user_id, {"color": "white"})["color"]
    result = {key: item[key] for key in item.keys()}
    result.pop("challenges", None)
    parsed = parse_crew_tag(result.get("name"))
    result.update({
        "url": url_for("pwncollege_users.view_other", user_id=user_id),
        "symbol": email_symbol_asset(result.pop("email")),
        "belt": url_for("pwncollege_belts.view_belt", color=belt_color),
        "badges": emojis.get(user_id, []),
        "crew": parsed and {"tag": parsed["tag"], "key": parsed["key"], "base_name": parsed["base_name"]},
    })
    return result


def page_numbers(total, page, per_page):
    pagination = Pagination(None, page, per_page, total, None)
    return set(number for number in pagination.iter_pages() if number)


def get_scoreboard_page(model, duration=None, page=1, per_page=20):
    belt_data = get_belts()
    results = get_scoreboard_for(model, duration)

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    user = get_current_user()
    emojis = get_viewable_emojis(user)

    standings_list = []
    for item in results[start_idx:end_idx]:
        entry = standing_entry(item, belt_data, emojis)
        if entry is not None:
            standings_list.append(entry)

    result = {
        "standings": standings_list,
    }

    pages = page_numbers(len(results), page, per_page)

    if user and not user.hidden:
        me = None
        for item in results:
            if item["user_id"] == user.id:
                me = standing_entry(item, belt_data, emojis)
                break
        if me:
            pages.add((me["rank"] - 1) // per_page + 1)
            result["me"] = me

    result["pages"] = sorted(pages)

    return result


def get_crew_scoreboard_page(model, duration=None, page=1, per_page=20, mode="cumulative"):
    belt_data = get_belts()
    user = get_current_user()
    emojis = get_viewable_emojis(user)
    crews = get_crews_for(model, duration)

    if mode == "unique" and all(crew.get("unique_rank") is not None for crew in crews):
        crews = sorted(crews, key=lambda crew: crew["unique_rank"])

    def crew_rank(crew):
        return crew["unique_rank"] if mode == "unique" and crew.get("unique_rank") is not None else crew["rank"]

    def crew_entry(crew):
        return {
            "rank": crew_rank(crew),
            "tag": crew["tag"],
            "key": crew["key"],
            "score": crew["score"],
            "unique": crew.get("unique"),
            "members": [
                entry for entry in (standing_entry(member, belt_data, emojis) for member in crew["members"])
                if entry is not None
            ],
        }

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    result = {
        "standings": [crew_entry(crew) for crew in crews[start_idx:end_idx]],
        "mode": mode,
    }

    pages = page_numbers(len(crews), page, per_page)

    if user and not user.hidden:
        parsed = parse_crew_tag(user.name)
        if parsed:
            my_crew = next((crew for crew in crews if crew["key"] == parsed["key"]), None)
            if my_crew:
                pages.add((crew_rank(my_crew) - 1) // per_page + 1)
                result["me_crew"] = crew_entry(my_crew)

    result["pages"] = sorted(pages)

    if not crews:
        result["board_empty"] = not get_scoreboard_for(model, duration)

    return result


def crew_mode_arg():
    mode = request.args.get("mode", "cumulative")
    return mode if mode in ("cumulative", "unique") else "cumulative"


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


@scoreboard_namespace.route("/<dojo>/_/crews/<int:duration>/<int:page>")
class ScoreboardDojoCrews(Resource):
    @dojo_route
    def get(self, dojo, duration, page):
        return get_crew_scoreboard_page(dojo, duration=duration, page=page, mode=crew_mode_arg())


@scoreboard_namespace.route("/<dojo>/<module>/crews/<int:duration>/<int:page>")
class ScoreboardModuleCrews(Resource):
    @dojo_route
    def get(self, dojo, module, duration, page):
        return get_crew_scoreboard_page(module, duration=duration, page=page, mode=crew_mode_arg())
