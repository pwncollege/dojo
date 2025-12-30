import json
import time
import os
import logging
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timezone

import redis
from flask import current_app

logger = logging.getLogger(__name__)

REDIS_STREAM_NAME = "stat:events"
CONSUMER_GROUP = "stats-workers"
CONSUMER_NAME = f"worker-{os.getpid()}"

def get_redis_client() -> redis.Redis:
    redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
    return redis.from_url(redis_url, decode_responses=True)

def publish_stat_event(event_type: str, payload: Dict[str, Any]) -> Optional[str]:
    try:
        r = get_redis_client()
        event = {
            "type": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        message_id = r.xadd(REDIS_STREAM_NAME, {"data": json.dumps(event)})
        logger.info(f"Published event {event_type} to stream: {message_id}")
        return message_id
    except (redis.RedisError, redis.ConnectionError) as e:
        logger.error(f"Failed to publish event {event_type}: {e}")
        return None

def consume_stat_events(handler: Callable[[str, Dict[str, Any]], None], batch_size: int = 10, block_ms: int = 5000):
    r = get_redis_client()

    def ensure_consumer_group():
        try:
            r.xgroup_create(REDIS_STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
            logger.info(f"Created consumer group {CONSUMER_GROUP} for stream {REDIS_STREAM_NAME}")
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            logger.info(f"Consumer group {CONSUMER_GROUP} already exists")

    ensure_consumer_group()
    logger.info(f"Worker {CONSUMER_NAME} waiting for events...")

    while True:
        try:
            messages = r.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {REDIS_STREAM_NAME: ">"},
                count=batch_size,
                block=block_ms
            )

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                logger.info(f"Received {len(stream_messages)} event(s) from stream")
                for message_id, message_data in stream_messages:
                    try:
                        event_data = json.loads(message_data["data"])
                        event_type = event_data["type"]
                        payload = event_data["payload"]

                        logger.info(f"Processing event: {event_type} with payload: {payload}")
                        handler(event_type, payload)

                        r.xack(REDIS_STREAM_NAME, CONSUMER_GROUP, message_id)
                        logger.info(f"Successfully processed and acknowledged event {message_id}")
                    except Exception as e:
                        logger.error(f"Error processing event {message_id}: {e}", exc_info=True)
        except redis.ResponseError as e:
            if "NOGROUP" in str(e):
                logger.warning(f"Consumer group was deleted, recreating...")
                ensure_consumer_group()
            else:
                logger.error(f"Redis error: {e}")
                time.sleep(1)
        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}")
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
            break

def get_cached_stat(key: str) -> Optional[Dict[str, Any]]:
    try:
        r = get_redis_client()
        data = r.get(key)
        if data:
            return json.loads(data)
        return None
    except (redis.RedisError, redis.ConnectionError, json.JSONDecodeError):
        return None

def set_cached_stat(key: str, data: Dict[str, Any], updated_at: Optional[float] = None):
    try:
        r = get_redis_client()
        r.set(key, json.dumps(data))

        if updated_at:
            r.set(f"{key}:updated", str(updated_at))
        else:
            r.set(f"{key}:updated", str(time.time()))
    except (redis.RedisError, redis.ConnectionError):
        pass

def get_cache_updated_at(key: str) -> Optional[float]:
    try:
        r = get_redis_client()
        updated = r.get(f"{key}:updated")
        if updated:
            return float(updated)
        return None
    except (redis.RedisError, redis.ConnectionError, ValueError):
        return None

def invalidate_cached_stat(key: str):
    try:
        r = get_redis_client()
        r.delete(key)
        r.delete(f"{key}:updated")
    except (redis.RedisError, redis.ConnectionError):
        pass
