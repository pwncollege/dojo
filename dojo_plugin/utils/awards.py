import functools
import inspect

from CTFd.cache import cache
from CTFd.models import db
from flask import abort

from .discord import get_discord_roles, get_discord_member, add_role, send_message
from .background_stats import get_public_cached_stat
from .public_stats import lock_public_stats_visibility
from .users import can_view_user, refresh_user
from ..models import (
    Dojos,
    Belts,
    Emojis,
    DiscordUsers,
    UserVisibilityUpdates,
)
from .feed import publish_belt_earned, publish_emoji_earned


BELT_ORDER = [ "orange", "yellow", "green", "purple", "blue", "brown", "red", "black" ]
CACHE_KEY_BELTS = "stats:belts"
CACHE_KEY_EMOJIS = "stats:emojis"
BELT_REQUIREMENTS = {
    "orange": "intro-to-cybersecurity",
    "yellow": "program-security",
    "green": "system-security",
    "blue": "software-exploitation",
}

def get_user_emojis(user):
    emojis = [ ]
    for dojo in Dojos.query.all():
        emoji = dojo.award and dojo.award.get('emoji', None)
        if not emoji:
            continue
        if dojo.challenges and dojo.completed(user):
            emojis.append((emoji, dojo.name or dojo.reference_id, dojo.hex_dojo_id))
    return emojis

def get_belts(user=None):
    lock_public_stats_visibility()
    user = refresh_user(user)
    visibility_update = (
        UserVisibilityUpdates.query.filter_by(user_id=user.id).first()
        if user is not None
        else None
    )
    visibility_pending = visibility_update is not None
    cached = get_public_cached_stat(CACHE_KEY_BELTS)
    if cached:
        result = dict(dates={}, users={}, ranks={})
        for color in BELT_ORDER:
            result["dates"][color] = {int(k): v for k, v in cached.get("dates", {}).get(color, {}).items()}
            result["ranks"][color] = cached.get("ranks", {}).get(color, [])
        result["users"] = {int(k): v for k, v in cached.get("users", {}).items()}
    else:
        result = dict(dates={}, users={}, ranks={})
        for color in reversed(BELT_ORDER):
            result["dates"][color] = {}
            result["ranks"][color] = []

    if user and (user.hidden or visibility_pending) and can_view_user(user):
        user_belts = Belts.query.filter(Belts.user == user, Belts.name.in_(BELT_ORDER)).all()
        if user_belts:
            belt = max(user_belts, key=lambda item: BELT_ORDER.index(item.name))
            result["dates"][belt.name][user.id] = str(belt.date)
            result["users"][user.id] = {
                "handle": user.name,
                "site": user.website,
                "color": belt.name,
                "date": str(belt.date),
            }

    return result


def get_private_emojis(user, viewable_dojos):
    result = []
    seen = {}
    emojis = (
        Emojis.query
        .filter(Emojis.user == user)
        .order_by(Emojis.date, Emojis.name.desc())
        .all()
    )

    for award in emojis:
        if award.category and award.category not in viewable_dojos:
            continue

        key = (award.category, award.icon)
        if key in seen:
            if award.name == "CUSTOM":
                entry = seen[key]
                entry["count"] += 1
                entry["text"] += f"\n{award.description}"
            continue

        dojo = viewable_dojos.get(award.category)
        emoji = award.icon
        if not emoji:
            if not dojo or not dojo.award or not dojo.award.get("emoji"):
                continue
            emoji = dojo.award["emoji"]

        entry = {
            "text": award.description,
            "emoji": emoji,
            "count": 1,
            "url": "#" if dojo is None else f"/dojo/{dojo.reference_id}",
            "stale": "STALE" in award.name,
            "category": award.category,
        }
        result.append(entry)
        seen[key] = entry

    return result


def get_viewable_emojis(user):
    lock_public_stats_visibility()
    user = refresh_user(user)
    cached = get_public_cached_stat(CACHE_KEY_EMOJIS)
    visibility_update = (
        UserVisibilityUpdates.query.filter_by(user_id=user.id).first()
        if user is not None
        else None
    )
    visibility_pending = visibility_update is not None
    include_private = (
        user
        and (user.hidden or visibility_pending)
        and can_view_user(user)
    )
    if not cached and not include_private:
        return {}

    viewable_dojos = {
        dojo.hex_dojo_id: dojo
        for dojo in Dojos.viewable(user=user).where(Dojos.data["type"].astext != "example")
    }

    if cached:
        result = {}
        for user_id_str, emoji_list in cached.get("emojis", {}).items():
            filtered = []
            for emoji_entry in emoji_list:
                category = emoji_entry["category"]
                emoji = emoji_entry["emoji"]
                if category and category not in viewable_dojos:
                    continue
                if not emoji:
                    if not category:
                        continue
                    if not viewable_dojos[category].award or not viewable_dojos[category].award.get("emoji"):
                        continue
                    emoji = viewable_dojos[category].award["emoji"]
                filtered.append({
                    "text": emoji_entry["text"],
                    "emoji": emoji,
                    "count": emoji_entry["count"],
                    "url": emoji_entry["url"],
                    "stale": emoji_entry["stale"],
                    "category": emoji_entry["category"]
                })
            if filtered:
                result[int(user_id_str)] = filtered
    else:
        result = {}

    if include_private:
        private_emojis = get_private_emojis(user, viewable_dojos)
        if private_emojis:
            result[user.id] = private_emojis

    return result

def update_awards(user):
    current_belts = [belt.name for belt in Belts.query.filter_by(user=user)]
    for belt, dojo_id in BELT_REQUIREMENTS.items():
        if belt in current_belts:
            continue
        dojo = Dojos.query.filter(Dojos.official, Dojos.id == dojo_id).first()
        if not (dojo and dojo.completed(user)):
            break
        db.session.add(Belts(user=user, name=belt))
        db.session.commit()
        current_belts.append(belt)
        
        belt_display = belt.title() + " Belt"
        publish_belt_earned(user, belt, belt_display, dojo)

    discord_user = DiscordUsers.query.filter_by(user=user).first()
    discord_member = discord_user and get_discord_member(discord_user.discord_id)
    discord_roles = get_discord_roles()
    for belt in BELT_REQUIREMENTS:
        if belt not in current_belts:
            continue
        belt_role = belt.title() + " Belt"
        missing_role = discord_member and discord_roles.get(belt_role) not in discord_member["roles"]
        if not missing_role:
            continue
        add_role(discord_user.discord_id, belt_role)
        send_message(f"<@{discord_user.discord_id}> earned their {belt_role}! :tada:", "belting-ceremony")
        cache.delete_memoized(get_discord_member, discord_user.discord_id)

    current_emojis = get_user_emojis(user)
    for emoji,dojo_display_name,hex_dojo_id in current_emojis:
        emoji_award = Emojis.query.filter(Emojis.user==user, Emojis.category==hex_dojo_id, Emojis.name=="CURRENT").first()
        if emoji_award:
            continue
        
        dojo = Dojos.query.filter_by(dojo_id=Dojos.hex_to_int(hex_dojo_id)).first()
        if not dojo:
            continue
            
        display_name = dojo.name or dojo.reference_id
        description = f"Awarded for completing the {display_name} dojo."
        
        if emoji_award := Emojis.query.filter(Emojis.user==user, Emojis.category==hex_dojo_id, Emojis.name=="STALE").first():
            emoji_award.name = "CURRENT"
        else:
            db.session.add(Emojis(user=user, name="CURRENT", description=description, category=hex_dojo_id, icon=None))
        db.session.commit()
        
        if dojo.official or dojo.data.get("type") == "public":
            publish_emoji_earned(user, emoji, display_name, description, 
                               dojo_id=dojo.reference_id, dojo_name=display_name)

def grant_award(user, emoji, description, category):
    db.session.add(Emojis(user=user, name="CUSTOM", description=description, category=category, icon=emoji))
    db.session.commit()


def dojo_gives_awards(func):
    signature = inspect.signature(func)
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound_args = signature.bind(*args, **kwargs)
        bound_args.apply_defaults()

        dojo = bound_args.arguments["dojo"]
        if "grant_awards" not in dojo.permissions:
            abort(403)
        return func(*bound_args.args, **bound_args.kwargs)
    return wrapper
