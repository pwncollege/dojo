import json
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Any

import redis
from flask import current_app
from CTFd.models import Users

def get_redis_client() -> redis.Redis:
    redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
    return redis.from_url(redis_url, decode_responses=True)

def create_event(event_type: str, user: Users, data: Dict[str, Any]) -> Optional[str]:
    if user.hidden:
        return None
    
    from ..models import Belts, Emojis
    from ..utils.awards import BELT_ORDER
    
    user_belts = [b.name for b in Belts.query.filter_by(user=user)]
    highest_belt = next((b for b in reversed(BELT_ORDER) if b in user_belts), None)
    user_emojis = [e.name for e in Emojis.query.filter_by(user=user)]
    
    event = {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user.id,
        "user_name": user.name,
        "user_belt": highest_belt,
        "user_emojis": user_emojis,
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

def get_recent_events(limit: int = 50, offset: int = 0, dojo_id: str | None = None):
    try:
        r = get_redis_client()
        from ..config import FEED_EVENT_TTL
        r.zremrangebyscore("activity_feed:events", "-inf", time.time() - FEED_EVENT_TTL)
        events = r.zrevrange("activity_feed:events", offset, offset + limit - 1)
        parsed_events = [json.loads(e) for e in events]
        if dojo_id:
            return [
                event for event in parsed_events
                if event.get("data", {}).get("dojo_id") == dojo_id
            ]
        return parsed_events
    except (redis.RedisError, redis.ConnectionError, json.JSONDecodeError):
        return []

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
