import datetime

from CTFd.cache import cache
from CTFd.models import db
from flask import url_for
from ..models import Dojos, Belts, Emojis


BELT_REQUIREMENTS = {
    "orange": "intro-to-cybersecurity",
    "yellow": "program-security",
    "green": "system-security",
    "blue": "software-exploitation",
}

def belt_asset(color):
    belt = color + ".svg" if color in BELT_REQUIREMENTS else "white.svg"
    return url_for("views.themes", path=f"img/dojo/{belt}")

def get_user_belts(user):
    result = [ ]
    for belt, dojo_id in BELT_REQUIREMENTS.items():
        belt_award = Belts.query.filter_by(user=user, name=belt).first()
        if belt_award:
            continue

        dojo = Dojos.query.filter(Dojos.official, Dojos.id == dojo_id).first()
        if not dojo:
            # We are likely missing the correct dojos in the DB (e.g., custom deployment)
            break
        if not dojo.completed(user):
            break
        result.append(belt)
    return result

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
    result = {
        "dates": {},
        "users": {},
        "ranks": {},
    }

    for n,(color,dojo_id) in enumerate(BELT_REQUIREMENTS.items()):
        dojo = Dojos.query.filter_by(id=dojo_id).first()
        if not dojo:
            # We are likely missing the correct dojos in the DB (e.g., custom deployment)
            break

        result["dates"][color] = {}
        result["ranks"][color] = []

        for belt in Belts.query.filter_by(name=color).order_by(Belts.date):
            if belt.user.hidden:
                continue

            result["dates"][color][belt.user.id] = str(belt.date)
            result["users"][belt.user.id] = {
                "handle": belt.user.name,
                "site": belt.user.website,
                "color": color,
                "date": str(belt.date),
                "rank_id": n,
            }

    for user_id in result["users"]:
        result["ranks"][result["users"][user_id]["color"]].append(user_id)

    for rank in result["ranks"].values():
        rank.sort(key=lambda uid: result["users"][uid]["date"])

    return result

def update_awards(user):
    current_belts = get_user_belts(user)
    for belt in current_belts:
        belt_award = Belts.query.filter_by(user=user, name=belt).first()
        if belt_award:
            continue
        db.session.add(Belts(user=user, name=belt))
        db.session.commit()

    current_emojis = get_user_emojis(user)
    for emoji,dojo_name,dojo_id in current_emojis:
        # note: the category filter is critical, since SQL seems to be unable to query by emoji!
        emoji_award = Emojis.query.filter_by(user=user, name=emoji, category=dojo_id).first()
        if emoji_award:
            continue
        db.session.add(Emojis(user=user, name=emoji, description=f"Awarded for completing the {dojo_name} dojo.", category=dojo_id))
        db.session.commit()

def get_viewable_emojis(user):
    viewable_dojos = { dojo.hex_dojo_id:dojo for dojo in Dojos.viewable(user=user) }
    emojis = { }
    for emoji in Emojis.query.order_by(Emojis.date).all():
        if emoji.category and emoji.category not in viewable_dojos:
            continue

        emojis.setdefault(emoji.user.id, []).append({
            "text": emoji.description,
            "emoji": emoji.name,
            "count": 1,
            "url": url_for("pwncollege_dojo.listing", dojo=viewable_dojos[emoji.category].reference_id) if emoji.category else "#"
        })
    return emojis
