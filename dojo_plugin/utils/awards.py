import datetime

from CTFd.cache import cache
from CTFd.models import db, Users
from flask import url_for

from .discord import get_discord_roles, get_discord_member, add_role, send_message
from ..models import Dojos, Belts, Emojis


BELT_ORDER = [ "orange", "yellow", "green", "purple", "blue", "brown", "red", "black" ]
BELT_REQUIREMENTS = {
    "orange": "intro-to-cybersecurity",
    "yellow": "program-security",
    "green": "system-security",
    "blue": "software-exploitation",
}
SPECIAL_EMOJIS = {
    "dojo_sensei": "🥋", # user hosts a dojo
    "bug_bounty": "🐞", # award for bug bounty
    "first_place": "🥇", # award for first place in an event
    "second_place": "🥈", # award for second place in an event
    "third_place": "🥉", # award for third place in an event
    "missing": "❌" # emoji used when, e.g., a dojo removed its emoji award
}

def belt_asset(color):
    belt = color + ".svg" if color in BELT_REQUIREMENTS else "white.svg"
    return url_for("views.themes", path=f"img/dojo/{belt}")

def get_user_emojis(user):
    emojis = [ ]
    for dojo in Dojos.query.all():
        emoji = dojo.award and dojo.award.get('emoji', None)
        if not emoji:
            continue
        if dojo.completed(user):
            emojis.append((emoji, dojo.name, dojo.hex_dojo_id))
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
        dojo.hex_dojo_id: dojo for dojo in
        Dojos.viewable(user=user).where(Dojos.data["type"] != "example")
    }
    viewable_dojo_urls = {
        k: url_for("pwncollege_dojo.listing", dojo=d.reference_id)
        for k,d in viewable_dojos.items()
    }
    emojis = (
        Emojis.query
        .join(Users)
        .filter(~Users.hidden, db.or_(Emojis.category.in_(viewable_dojo_urls.keys()), Emojis.category == None))
        .order_by(Emojis.date)
        .with_entities(
            Emojis.name,
            Emojis.description,
            Emojis.category,
            Users.id.label("user_id"),
        )
    )

    for emoji in emojis:
        # transitional logic --- will be removed
        if "for being a sensei" in emoji.description:
            name = "dojo_sensei"
        elif "first-place" in emoji.description:
            name = "first_place"
        elif "for finding" in emoji.description:
            name = "bug_bounty"
        elif "for breaking" in emoji.description:
            name = "bug_bounty"
        else:
            name = "completion"

        badge = (
            SPECIAL_EMOJIS.get(name) or
            viewable_dojos[emoji.category].data.get(
                'award', {}
            ).get('emoji') or
            # below here, the dojo _had_ an award and then got rid of it?
            SPECIAL_EMOJIS["missing"]
        )

        result.setdefault(emoji.user_id, []).append({
            "text": emoji.description,
            "emoji": badge,
            "count": 1,
            "url": viewable_dojo_urls.get(emoji.category, "#"),
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

    discord_member = get_discord_member(user.id)
    discord_roles = get_discord_roles()
    for belt in BELT_REQUIREMENTS:
        if belt not in current_belts:
            continue
        belt_role = belt.title() + " Belt"
        missing_role = discord_member and discord_roles.get(belt_role) not in discord_member["roles"]
        if not missing_role:
            continue
        user_mention = f"<@{discord_member['user']['id']}>"
        message = f"{user_mention} earned their {belt_role}! :tada:"
        add_role(discord_member["user"]["id"], belt_role)
        send_message(message, "belting-ceremony")
        cache.delete_memoized(get_discord_member, user.id)

    current_emojis = get_user_emojis(user)
    for emoji,dojo_name,dojo_id in current_emojis:
        # note: the category filter is critical, since SQL seems to be unable to query by emoji!
        emoji_award = Emojis.query.filter_by(user=user, name=emoji, category=dojo_id).first()
        if emoji_award:
            continue
        db.session.add(Emojis(user=user, name="completion", description=f"Awarded for completing the {dojo_name} dojo.", category=dojo_id))
        db.session.commit()
