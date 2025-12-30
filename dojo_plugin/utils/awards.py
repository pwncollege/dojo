import datetime

from CTFd.cache import cache
from CTFd.models import db, Users
from flask import url_for

from .discord import get_discord_roles, get_discord_member, add_role, send_message
from .background_stats import get_cached_stat, BACKGROUND_STATS_ENABLED, BACKGROUND_STATS_FALLBACK
from ..models import Dojos, Belts, Emojis, DiscordUsers
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

def calculate_belts():
    result = dict(dates={}, users={}, ranks={})
    for color in reversed(BELT_ORDER):
        result["dates"][color] = {}
        result["ranks"][color] = []

    belts = (
        Belts.query
        .join(Users)
        .filter(Belts.name.in_(BELT_ORDER), ~Users.hidden)
        .with_entities(
            Belts.date,
            Belts.name.label("color"),
            Users.id.label("user_id"),
            Users.name.label("handle"),
            Users.website.label("site"),
        )
    ).all()
    belts.sort(key=lambda belt: (-BELT_ORDER.index(belt.color), belt.date))

    for belt in belts:
        result["dates"][belt.color][belt.user_id] = str(belt.date)
        if belt.user_id not in result["users"]:
            result["users"][belt.user_id] = dict(
                handle=belt.handle,
                site=belt.site,
                color=belt.color,
                date=str(belt.date)
            )
            result["ranks"][belt.color].append(belt.user_id)

    return result

def get_belts():
    if BACKGROUND_STATS_ENABLED:
        cached = get_cached_stat(CACHE_KEY_BELTS)
        if cached:
            result = dict(dates={}, users={}, ranks={})
            for color in BELT_ORDER:
                result["dates"][color] = {int(k): v for k, v in cached.get("dates", {}).get(color, {}).items()}
                result["ranks"][color] = cached.get("ranks", {}).get(color, [])
            result["users"] = {int(k): v for k, v in cached.get("users", {}).items()}
            return result

        if not BACKGROUND_STATS_FALLBACK:
            result = dict(dates={}, users={}, ranks={})
            for color in reversed(BELT_ORDER):
                result["dates"][color] = {}
                result["ranks"][color] = []
            return result

    return calculate_belts()

def calculate_viewable_emojis(user):
    result = { }
    viewable_dojos = {
        dojo.hex_dojo_id: dojo
        for dojo in Dojos.viewable(user=user).where(Dojos.data["type"].astext != "example")
    }

    emojis = (
        Emojis.query
        .join(Users)
        .filter(~Users.hidden, db.or_(Emojis.category.in_(viewable_dojos.keys()), Emojis.category == None))
        .order_by(Emojis.date, Emojis.name.desc())
        .with_entities(
            Emojis.name,
            Emojis.description,
            Emojis.category,
            Users.id.label("user_id"),
        )
    )

    seen = set()
    for emoji in emojis:
        key = (emoji.user_id, emoji.category)
        if key in seen:
            continue

        if emoji.category is None:
            emoji_symbol = emoji.name
            url = "#"
        else:
            dojo = viewable_dojos.get(emoji.category)
            if not dojo or not dojo.award or not dojo.award.get('emoji'):
                continue
            emoji_symbol = dojo.award.get('emoji')
            url = url_for("pwncollege_dojo.listing", dojo=dojo.reference_id)

        is_stale = emoji.name == "STALE"

        result.setdefault(emoji.user_id, []).append({
            "text": emoji.description,
            "emoji": emoji_symbol,
            "count": 1,
            "url": url,
            "stale": is_stale,
        })
        seen.add(key)

    return result

def get_viewable_emojis(user):
    if BACKGROUND_STATS_ENABLED:
        cached = get_cached_stat(CACHE_KEY_EMOJIS)
        if cached:
            viewable_dojos = {
                dojo.hex_dojo_id: dojo
                for dojo in Dojos.viewable(user=user).where(Dojos.data["type"].astext != "example")
            }

            result = {}
            for user_id_str, emoji_list in cached.get("emojis", {}).items():
                filtered = []
                for emoji_entry in emoji_list:
                    category = emoji_entry.get("category")
                    if category is None:
                        filtered.append({
                            "text": emoji_entry["text"],
                            "emoji": emoji_entry["emoji"],
                            "count": 1,
                            "url": "#",
                            "stale": False,
                        })
                    elif category in viewable_dojos:
                        dojo = viewable_dojos[category]
                        if not dojo.award or not dojo.award.get('emoji'):
                            continue
                        filtered.append({
                            "text": emoji_entry["text"],
                            "emoji": dojo.award.get('emoji'),
                            "count": 1,
                            "url": url_for("pwncollege_dojo.listing", dojo=dojo.reference_id),
                            "stale": emoji_entry.get("stale", False),
                        })
                if filtered:
                    result[int(user_id_str)] = filtered
            return result

        if not BACKGROUND_STATS_FALLBACK:
            return {}

    return calculate_viewable_emojis(user)

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
        emoji_award = Emojis.query.filter(Emojis.user==user, Emojis.category==hex_dojo_id, Emojis.name != "STALE").first()
        if emoji_award:
            continue
        
        dojo = Dojos.query.filter_by(dojo_id=Dojos.hex_to_int(hex_dojo_id)).first()
        if not dojo:
            continue
            
        display_name = dojo.name or dojo.reference_id
        description = f"Awarded for completing the {display_name} dojo."
        db.session.add(Emojis(user=user, name="CURRENT", description=description, category=hex_dojo_id))
        db.session.commit()
        
        if dojo.official or dojo.data.get("type") == "public":
            publish_emoji_earned(user, emoji, display_name, description, 
                               dojo_id=dojo.reference_id, dojo_name=display_name)
