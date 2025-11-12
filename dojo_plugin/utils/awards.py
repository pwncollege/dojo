import datetime

from CTFd.cache import cache
from CTFd.models import db, Users
from flask import url_for

from .discord import get_discord_roles, get_discord_member, add_role, send_message
from ..models import Dojos, Belts, Emojis, DiscordUsers, Medals
from .feed import publish_belt_earned, publish_emoji_earned


BELT_ORDER = [ "orange", "yellow", "green", "purple", "blue", "brown", "red", "black" ]
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

def get_belts():
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

def get_viewable_emojis(user):
    result = { }
    viewable_dojos = {
        dojo.hex_dojo_id: dojo
        for dojo in Dojos.viewable(user=user).where(Dojos.data["type"].astext != "example")
    }
    
    emojis = (
        Emojis.query
        .join(Users)
        .filter(~Users.hidden, db.or_(Emojis.category.in_(viewable_dojos.keys()), Emojis.category == None))
        .order_by(Emojis.date, Emojis.name.desc())  # Order by date, then name DESC (STALE < CURRENT < legacy emojis)
        .with_entities(
            Emojis.name,
            Emojis.description,
            Emojis.category,
            Users.id.label("user_id"),
        )
    )

    medals = (
        Medals.query
        .join(Users)
        .filter(~Users.hidden)
        .order_by(Medals.date)
        .with_entities(
            Medals.name,
            Medals.description,
            Medals.category,
            Users.id.label("user_id"),
        )
    )
    
    seen = set()
    for emoji in emojis:
        key = (emoji.user_id, emoji.category)
        if key in seen:
            continue
        seen.add(key)
            
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

    # combine descriptions for medals.
    awarded_medals = {}
    seen = set()
    for medal in medals:
        key = (medal.user_id, medal.category)
        if key in seen:
            continue
        seen.add(key)

        match medal.name:
            case "EVENT_1":
                index = 0
            case "EVENT_2":
                index = 1
            case "EVENT_3":
                index = 2
            case "EVENT_STALE":
                index = 3
            case _:
                continue

        awarded_medals.setdefault(medal.user_id, ["", "", "", ""])
        awarded_medals[medal.user_id][index] += (("\n" if awarded_medals[medal.user_id][index] != "" else "") + medal.description)

    for id, medal in awarded_medals.items():
        for description, emoji in zip(medal, ["🥇", "🥈", "🥉", "🏅"]):
            if description == "":
                continue
            result.setdefault(id, []).append({
                "text": description,
                "emoji": emoji,
                "count": 1,
                "url": "#",
                "stale": emoji == "🏅",
            })

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
            
def grant_event_award(user, event: str, place: int) -> bool:
    """
    Grants an event award to a user.

    `place` must be one of `{1, 2, 3}`.

    Returns if the operation succeeded.
    """
    placeStr = "first" if place == 1 else "second" if place == 2 else "third" if place == 3 else None
    if placeStr is None:
        return False
    db.session.add(Medals(user=user, name=f"EVENT_{place}", description=f"Awarded for ranking {placeStr} in {event}.", category=event))
    db.session.commit()
    return True


def revoke_event_award(user, event: str) -> bool:
    """
    Revokes an event award from a user.

    Returns if the operation succeeded.
    """
    award = Medals.query.filter_by(user=user, category=event).first()
    if not award:
        return False
    db.session.delete(award)
    db.session.commit()
    return True


def prune_event_awards(event: str) -> int:
    num_pruned = 0
    for medal in Medals.query.where(Medals.category == event):
        if medal.name != "EVENT_STALE":
            num_pruned += 1
            medal.name = "EVENT_STALE"
    db.session.commit()
    return num_pruned
