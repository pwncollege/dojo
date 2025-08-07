import json
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import redis
from flask import current_app
from CTFd.models import Users

logger = logging.getLogger(__name__)

FEED_KEY = "activity_feed:events"


def get_redis_client() -> redis.Redis:
    try:
        redis_url = current_app.config.get("REDIS_URL")
        if not redis_url:
            logger.error(f"REDIS_URL not found in config. Config keys: {list(current_app.config.keys())[:10]}")
            redis_url = "redis://cache:6379"
        return redis.from_url(redis_url, decode_responses=True)
    except Exception as e:
        logger.error(f"Failed to create Redis client: {e}")
        return redis.from_url("redis://cache:6379", decode_responses=True)


def create_event(
    event_type: str,
    user: Users,
    data: Dict[str, Any],
    ttl: Optional[int] = None
) -> Optional[str]:
    if user.hidden:
        logger.debug(f"Skipping event for hidden user {user.id}")
        return None
    
    # Get user's belts and emojis
    from ..models import Belts, Emojis
    user_belts = [belt.name for belt in Belts.query.filter_by(user=user)]
    user_emojis = [emoji.name for emoji in Emojis.query.filter_by(user=user)]
    
    logger.debug(f"User {user.name} has belts: {user_belts}")
    
    # Get highest belt (order: white, yellow, blue, orange, green, black)
    belt_order = ["white", "yellow", "blue", "orange", "green", "black"]
    highest_belt = None
    for belt in reversed(belt_order):
        if belt in user_belts:
            highest_belt = belt
            break
    
    logger.debug(f"User {user.name} highest belt: {highest_belt}")
    
    event_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    
    event = {
        "id": event_id,
        "type": event_type,
        "timestamp": timestamp,
        "user_id": user.id,
        "user_name": user.name,
        "user_belt": highest_belt,
        "user_emojis": user_emojis,
        "data": data
    }
    
    try:
        r = get_redis_client()
        score = time.time()
        
        r.zadd(FEED_KEY, {json.dumps(event): score})
        
        from ..config import FEED_MAX_EVENTS, FEED_EVENT_TTL
        r.zremrangebyrank(FEED_KEY, 0, -FEED_MAX_EVENTS - 1)
        
        r.publish("activity_feed:live", json.dumps(event))
        
        if ttl is None:
            ttl = FEED_EVENT_TTL
        
        cutoff = time.time() - ttl
        r.zremrangebyscore(FEED_KEY, "-inf", cutoff)
        
        logger.info(f"Published {event_type} event for user {user.name}")
        return event_id
        
    except Exception as e:
        logger.error(f"Failed to publish event: {e}")
        return None


def get_recent_events(limit: int = 50, offset: int = 0) -> List[Dict]:
    try:
        r = get_redis_client()
        
        from ..config import FEED_EVENT_TTL
        cutoff = time.time() - FEED_EVENT_TTL
        r.zremrangebyscore(FEED_KEY, "-inf", cutoff)
        
        events = r.zrevrange(FEED_KEY, offset, offset + limit - 1)
        
        return [json.loads(event) for event in events]
        
    except Exception as e:
        logger.error(f"Failed to get events: {e}")
        return []


def publish_container_start(user: Users, mode: str, challenge_data: Dict) -> Optional[str]:
    data = {
        "mode": mode,
        "challenge_id": challenge_data.get("id"),
        "challenge_name": challenge_data.get("name"),
        "module_id": challenge_data.get("module_id"),
        "module_name": challenge_data.get("module_name"),
        "dojo_id": challenge_data.get("dojo_id"),
        "dojo_name": challenge_data.get("dojo_name")
    }
    return create_event("container_start", user, data)


def publish_challenge_solve(user: Users, dojo_challenge: Any, dojo: Any, module: Any, points: int, first_blood: bool = False) -> Optional[str]:
    data = {
        "challenge_id": dojo_challenge.challenge_id,
        "challenge_name": dojo_challenge.name,
        "module_id": module.id if module else None,
        "module_name": module.name if module else None,
        "dojo_id": dojo.reference_id if dojo else None,
        "dojo_name": dojo.name if dojo else None,
        "points": points,
        "first_blood": first_blood
    }
    return create_event("challenge_solve", user, data)


def publish_emoji_earned(user: Users, emoji: str, emoji_name: str, reason: str) -> Optional[str]:
    data = {
        "emoji": emoji,
        "emoji_name": emoji_name,
        "reason": reason
    }
    return create_event("emoji_earned", user, data)


def publish_belt_earned(user: Users, belt: str, belt_name: str, dojo: Any) -> Optional[str]:
    data = {
        "belt": belt,
        "belt_name": belt_name,
        "dojo_id": dojo.reference_id if dojo else None,
        "dojo_name": dojo.name if dojo else None
    }
    return create_event("belt_earned", user, data)


def publish_dojo_update(user: Users, dojo: Any, summary: str, changes: Dict) -> Optional[str]:
    data = {
        "dojo_id": dojo.reference_id,
        "dojo_name": dojo.name,
        "summary": summary,
        "changes": changes
    }
    return create_event("dojo_update", user, data)