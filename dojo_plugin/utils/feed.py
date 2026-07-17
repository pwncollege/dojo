import json
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Any

import redis
from flask import current_app
from CTFd.models import db, Users

from ..models import (
    PublicStatsVisibilityGuard,
    UserVisibilityUpdates,
    UserVisibilityVersions,
)
from .public_stats import lock_public_stats_visibility

def get_redis_client() -> redis.Redis:
    redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
    return redis.from_url(redis_url, decode_responses=True)

def create_event(event_type: str, user: Users, data: Dict[str, Any]) -> Optional[str]:
    lock_public_stats_visibility()
    user = Users.query.populate_existing().filter_by(id=user.id).first()
    if (
        user is None
        or user.hidden
        or user.banned
        or UserVisibilityUpdates.query.filter_by(user_id=user.id).first() is not None
    ):
        return None
    
    from ..models import Belts, Emojis
    from ..utils.awards import BELT_ORDER
    
    user_belts = [b.name for b in Belts.query.filter_by(user=user)]
    highest_belt = next((b for b in reversed(BELT_ORDER) if b in user_belts), None)
    user_emojis = [e.name for e in Emojis.query.filter_by(user=user)]
    visibility_revision = UserVisibilityVersions.query.with_entities(
        UserVisibilityVersions.revision
    ).filter_by(user_id=user.id).scalar() or 0
    
    event = {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id,
        "user_name": user.name,
        "user_belt": highest_belt,
        "user_emojis": user_emojis,
        "visibility_revision": visibility_revision,
        "data": data
    }
    
    try:
        r = get_redis_client()
        score = time.time()
        r.zadd("activity_feed:events", {json.dumps(event): score})
        
        from ..config import FEED_MAX_EVENTS, FEED_EVENT_TTL
        r.zremrangebyrank("activity_feed:events", 0, -FEED_MAX_EVENTS - 1)
        r.zremrangebyscore("activity_feed:events", "-inf", time.time() - FEED_EVENT_TTL)
        r.publish("activity_feed:live", json.dumps(event))
        
        return event["id"]
    except (redis.RedisError, redis.ConnectionError):
        return None

def public_feed_events(events):
    lock_public_stats_visibility()
    events = [
        event
        for event in events
        if isinstance(event, dict)
        and isinstance(event.get("user_id"), int)
        and not isinstance(event["user_id"], bool)
        and isinstance(event.get("visibility_revision"), int)
        and not isinstance(event["visibility_revision"], bool)
    ]
    user_ids = {event["user_id"] for event in events}
    visible_users = {
        user_id: visibility_revision or 0
        for user_id, visibility_revision in Users.query.populate_existing()
        .outerjoin(
            UserVisibilityUpdates,
            UserVisibilityUpdates.user_id == Users.id,
        )
        .outerjoin(
            UserVisibilityVersions,
            UserVisibilityVersions.user_id == Users.id,
        )
        .filter(
            Users.id.in_(user_ids),
            ~Users.hidden,
            ~Users.banned,
            UserVisibilityUpdates.user_id.is_(None),
        )
        .with_entities(Users.id, UserVisibilityVersions.revision)
    }
    return [
        event
        for event in events
        if visible_users.get(event["user_id"]) == event["visibility_revision"]
    ]


def is_public_feed_event(event):
    if not isinstance(event, dict):
        return False
    user_id = event.get("user_id")
    visibility_revision = event.get("visibility_revision")
    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or not isinstance(visibility_revision, int)
        or isinstance(visibility_revision, bool)
    ):
        return False
    guard = PublicStatsVisibilityGuard.__table__
    users = Users.__table__
    updates = UserVisibilityUpdates.__table__
    visibility_versions = UserVisibilityVersions.__table__
    with db.engine.begin() as connection:
        connection.execute(
            db.select([guard.c.id])
            .where(guard.c.id == 1)
            .with_for_update(read=True)
        ).scalar()
        return connection.execute(
            db.select([users.c.id])
            .select_from(
                users.outerjoin(
                    visibility_versions,
                    visibility_versions.c.user_id == users.c.id,
                )
            )
            .where(
                users.c.id == user_id,
                ~users.c.hidden,
                ~users.c.banned,
                db.func.coalesce(visibility_versions.c.revision, 0)
                == visibility_revision,
                ~db.exists().where(updates.c.user_id == users.c.id),
            )
        ).scalar() is not None


def get_recent_events(limit: int = 50, offset: int = 0):
    lock_public_stats_visibility()
    try:
        r = get_redis_client()
        from ..config import FEED_EVENT_TTL
        r.zremrangebyscore("activity_feed:events", "-inf", time.time() - FEED_EVENT_TTL)
        events = public_feed_events(
            [json.loads(event) for event in r.zrevrange("activity_feed:events", 0, -1)]
        )
        return events[offset:offset + limit]
    except (redis.RedisError, redis.ConnectionError, json.JSONDecodeError):
        return []


def remove_user_events(user_id):
    try:
        redis_client = get_redis_client()
        cursor = 0
        while True:
            cursor, entries = redis_client.zscan(
                "activity_feed:events", cursor=cursor, count=100
            )
            matches = []
            for entry, _score in entries:
                try:
                    event = json.loads(entry)
                    if isinstance(event, dict) and event.get("user_id") == user_id:
                        matches.append(entry)
                except (TypeError, json.JSONDecodeError):
                    continue
            if matches:
                redis_client.zrem("activity_feed:events", *matches)
            if cursor == 0:
                break
        return True
    except (redis.RedisError, redis.ConnectionError):
        return False

def publish_container_start(user: Users, mode: str, challenge_data: Dict) -> Optional[str]:
    return create_event("container_start", user, challenge_data | {"mode": mode})

def publish_challenge_solve(user: Users, dojo_challenge: Any, dojo: Any, module: Any, points: int, first_blood: bool = False) -> Optional[str]:
    return create_event("challenge_solve", user, {
        "challenge_id": dojo_challenge.challenge_id,
        "challenge_name": dojo_challenge.name,
        "module_id": module.id if module else None,
        "module_name": module.name if module else None,
        "dojo_id": dojo.reference_id if dojo else None,
        "dojo_name": dojo.name if dojo else None,
        "points": points,
        "first_blood": first_blood
    })

def publish_emoji_earned(user: Users, emoji: str, emoji_name: str, reason: str, dojo_id: str = None, dojo_name: str = None) -> Optional[str]:
    return create_event("emoji_earned", user, {
        "emoji": emoji, "emoji_name": emoji_name, "reason": reason,
        "dojo_id": dojo_id, "dojo_name": dojo_name
    })

def publish_belt_earned(user: Users, belt: str, belt_name: str, dojo: Any) -> Optional[str]:
    return create_event("belt_earned", user, {
        "belt": belt, "belt_name": belt_name,
        "dojo_id": dojo.reference_id if dojo else None,
        "dojo_name": dojo.name if dojo else None
    })

def publish_dojo_update(user: Users, dojo: Any, summary: str, changes: Dict) -> Optional[str]:
    return create_event("dojo_update", user, {
        "dojo_id": dojo.reference_id, "dojo_name": dojo.name,
        "summary": summary, "changes": changes
    })
