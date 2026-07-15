import json
import time
import os
import logging
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timezone

import redis
from flask import current_app
from CTFd.models import db

logger = logging.getLogger(__name__)

REDIS_STREAM_NAME = "stat:events"
CONSUMER_GROUP = "stats-workers"
CONSUMER_NAME = f"worker-{os.getpid()}"

DAILY_RESTART_HOUR_UTC = 12

_redis_client: Optional[redis.Redis] = None

CACHE_WRITE_SCRIPT = """
local current_updated = tonumber(redis.call('GET', KEYS[2]) or '')
local current_version = tonumber(redis.call('GET', KEYS[3]) or '')
local incoming_updated = tonumber(ARGV[2])
local incoming_version = tonumber(ARGV[3])

if incoming_version then
    if current_version then
        if current_version > incoming_version then
            return 2
        end
        if current_version == incoming_version and current_updated and current_updated > incoming_updated then
            return 2
        end
    end
elseif current_updated and current_updated > incoming_updated then
    return 2
end

redis.call('SET', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[2])
if incoming_version then
    redis.call('SET', KEYS[3], ARGV[3])
else
    redis.call('DEL', KEYS[3])
end
return 1
"""


class DailyRestartException(Exception):
    pass


def should_daily_restart(start_time: float) -> bool:
    now = datetime.now(timezone.utc)
    if now.hour != DAILY_RESTART_HOUR_UTC:
        return False
    hours_running = (time.time() - start_time) / 3600
    return hours_running >= 1


def get_message_timestamp(message_id: str) -> float:
    timestamp_ms = int(message_id.split('-')[0])
    return timestamp_ms / 1000.0


def is_event_stale(cache_key: str, event_timestamp: float) -> bool:
    cache_updated = get_cache_updated_at(cache_key)
    if cache_updated and event_timestamp < cache_updated:
        logger.info(f"Skipping stale event for {cache_key} (event: {event_timestamp}, cache: {cache_updated})")
        return True
    return False


def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client

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

def consume_stat_events(
    handler: Callable[[str, Dict[str, Any], float], None],
    batch_size: int = 10,
    block_ms: int = 5000,
    start_time: Optional[float] = None,
    maintenance_handler: Optional[Callable[[], None]] = None,
    maintenance_interval: float = 5,
):
    r = get_redis_client()
    if start_time is None:
        start_time = time.time()

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
    next_maintenance = time.monotonic()

    while True:
        if should_daily_restart(start_time):
            logger.info(f"Daily restart triggered at UTC hour {DAILY_RESTART_HOUR_UTC}")
            raise DailyRestartException("Scheduled daily restart for cache refresh")
        if maintenance_handler and time.monotonic() >= next_maintenance:
            next_maintenance = time.monotonic() + maintenance_interval
            try:
                maintenance_handler()
            except Exception as error:
                logger.error("Stats maintenance failed: %s", error, exc_info=True)
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
                        event_timestamp = get_message_timestamp(message_id)
                        queue_time_ms = (get_redis_time(r) - event_timestamp) * 1000

                        logger.info(f"Processing event: {event_type} {queue_time_ms=:.0f} payload={payload}")
                        start = time.time()
                        handler(event_type, payload, event_timestamp)
                        processing_time_ms = (time.time() - start) * 1000

                        r.xackdel(REDIS_STREAM_NAME, CONSUMER_GROUP, message_id)
                        logger.info(f"Processed event {message_id}: {event_type} {queue_time_ms=:.0f} {processing_time_ms=:.0f}")
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

def get_redis_time(r: redis.Redis) -> float:
    redis_time = r.time()
    return float(redis_time[0]) + float(redis_time[1]) / 1_000_000


def get_cache_watermark() -> float:
    return get_redis_time(get_redis_client())


def get_stats_revision() -> int:
    from ..models import DojoStatsRevisions

    version = (
        db.session.query(DojoStatsRevisions.version)
        .filter_by(id=1)
        .scalar()
    )
    return int(version or 0)


def calculate_authoritative_stat(calculate, attempts=3):
    data = None
    represented_version = 0
    calculation_started_at = 0
    for _ in range(attempts):
        calculation_started_at = get_cache_watermark()
        represented_version = get_stats_revision()
        data = calculate()
        if get_stats_revision() == represented_version:
            break
    return data, represented_version, calculation_started_at


def set_cached_stat(
    key: str,
    data: Dict[str, Any],
    updated_at: Optional[float] = None,
    version: Optional[int] = None,
):
    try:
        r = get_redis_client()
        if updated_at is None:
            updated_at = get_redis_time(r)
        return bool(r.eval(
            CACHE_WRITE_SCRIPT,
            3,
            key,
            f"{key}:updated",
            f"{key}:version",
            json.dumps(data),
            str(updated_at),
            "" if version is None else str(version),
        ))
    except (redis.RedisError, redis.ConnectionError):
        return False

def get_cache_updated_at(key: str) -> Optional[float]:
    try:
        r = get_redis_client()
        updated = r.get(f"{key}:updated")
        if updated:
            return float(updated)
        return None
    except (redis.RedisError, redis.ConnectionError, ValueError):
        return None


def get_cache_version(key: str) -> Optional[int]:
    try:
        version = get_redis_client().get(f"{key}:version")
        if version is not None:
            return int(version)
        return None
    except (redis.RedisError, redis.ConnectionError, ValueError):
        return None

def invalidate_cached_stat(key: str):
    try:
        r = get_redis_client()
        r.delete(key, f"{key}:updated", f"{key}:version")
    except (redis.RedisError, redis.ConnectionError):
        pass
