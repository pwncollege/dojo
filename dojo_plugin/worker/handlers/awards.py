import logging
from flask import url_for
from CTFd.models import db, Users
from ...models import Dojos, Belts, Emojis
from ...utils.awards import BELT_ORDER
from ...utils.background_stats import set_cached_stat, is_event_stale
from . import register_handler

logger = logging.getLogger(__name__)

CACHE_KEY_BELTS = "stats:belts"
CACHE_KEY_EMOJIS = "stats:emojis"

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

def calculate_emojis():
    dojos_by_hex = {
        dojo.hex_dojo_id: {
            "reference_id": dojo.reference_id,
            "emoji": dojo.award.get("emoji") if dojo.award else None,
            "is_public": dojo.official or dojo.data.get("type") == "public",
            "is_example": dojo.data.get("type") == "example",
        }
        for dojo in Dojos.query.all()
        if dojo.award and dojo.award.get("emoji")
    }

    emojis = (
        Emojis.query
        .join(Users)
        .filter(~Users.hidden)
        .order_by(Emojis.date, Emojis.name.desc())
        .with_entities(
            Emojis.name,
            Emojis.description,
            Emojis.category,
            Users.id.label("user_id"),
        )
    ).all()

    result = {}
    seen = set()
    for emoji in emojis:
        key = (emoji.user_id, emoji.category)
        if key in seen:
            continue

        if emoji.category is None:
            emoji_entry = {
                "text": emoji.description,
                "emoji": emoji.name,
                "count": 1,
                "url": "#",
                "stale": False,
                "category": None,
            }
            duplicate = False
            for entry in result.setdefault(emoji.user_id, []):
                if entry.get("emoji") == emoji.name and entry.get("category") is not None:
                    duplicate = True
                    entry["count"] += 1
                    entry["text"] += f"\n{emoji.description}"
                    break
            if not duplicate:
                result.setdefault(emoji.user_id, []).append(emoji_entry)
        else:
            dojo_info = dojos_by_hex.get(emoji.category)
            if not dojo_info or not dojo_info["emoji"]:
                continue
            emoji_entry = {
                "text": emoji.description,
                "emoji": dojo_info["emoji"],
                "count": 1,
                "url": f"/dojo/{dojo_info['reference_id']}",
                "stale": emoji.name == "STALE",
                "category": emoji.category,
                "is_public": dojo_info["is_public"],
                "is_example": dojo_info["is_example"],
            }
            result.setdefault(emoji.user_id, []).append(emoji_entry)

        if emoji.category:
            seen.add(key)

    return {"emojis": result, "dojos": dojos_by_hex}

@register_handler("belts_update")
def handle_belts_update(payload, event_timestamp=None):
    if event_timestamp and is_event_stale(CACHE_KEY_BELTS, event_timestamp):
        return

    db.session.expire_all()
    db.session.commit()

    try:
        logger.info("Calculating belts...")
        belt_data = calculate_belts()
        set_cached_stat(CACHE_KEY_BELTS, belt_data)
        user_count = len(belt_data["users"])
        logger.info(f"Successfully updated belts cache ({user_count} users with belts)")
    except Exception as e:
        logger.error(f"Error calculating belts: {e}", exc_info=True)

@register_handler("emojis_update")
def handle_emojis_update(payload, event_timestamp=None):
    if event_timestamp and is_event_stale(CACHE_KEY_EMOJIS, event_timestamp):
        return

    db.session.expire_all()
    db.session.commit()

    try:
        logger.info("Calculating emojis...")
        emoji_data = calculate_emojis()
        set_cached_stat(CACHE_KEY_EMOJIS, emoji_data)
        user_count = len(emoji_data["emojis"])
        logger.info(f"Successfully updated emojis cache ({user_count} users with emojis)")
    except Exception as e:
        logger.error(f"Error calculating emojis: {e}", exc_info=True)

def initialize_all_belts():
    logger.info("Initializing belts...")
    try:
        belt_data = calculate_belts()
        set_cached_stat(CACHE_KEY_BELTS, belt_data)
        user_count = len(belt_data["users"])
        logger.info(f"Initialized belts ({user_count} users with belts)")
    except Exception as e:
        logger.error(f"Error initializing belts: {e}", exc_info=True)

def initialize_all_emojis():
    logger.info("Initializing emojis...")
    try:
        emoji_data = calculate_emojis()
        set_cached_stat(CACHE_KEY_EMOJIS, emoji_data)
        user_count = len(emoji_data["emojis"])
        logger.info(f"Initialized emojis ({user_count} users with emojis)")
    except Exception as e:
        logger.error(f"Error initializing emojis: {e}", exc_info=True)
