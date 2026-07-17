import json
import math
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Any

import redis
from flask import current_app
from CTFd.models import Users, db

MAX_SAFE_USER_ID = 9_007_199_254_740_991
MAX_FEED_JSON_DEPTH = 64
MAX_REDIS_STREAM_ID_COMPONENT = 18_446_744_073_709_551_615
MAX_REDIS_LUA_INTEGER = 9_007_199_254_740_991
MAX_FEED_EVENT_COUNT = MAX_REDIS_LUA_INTEGER // 2
MAX_FEED_TTL_SECONDS = MAX_REDIS_LUA_INTEGER // 1_000
DOJO_REFERENCE_PATTERN = re.compile(r"^[a-z0-9-]{1,32}(?:~[0-9a-f]{8})?$")
CONTENT_ID_PATTERN = re.compile(r"^[a-z0-9-]{1,32}$")
FEED_CURSOR_PATTERN = re.compile(r"^[0-9]{1,20}-[0-9]{1,20}$")
TERMINAL_FEED_CURSOR = (
    f"{MAX_REDIS_STREAM_ID_COMPONENT}-{MAX_REDIS_STREAM_ID_COMPONENT}"
)
FEED_STREAM_KEY = "activity_feed:events:v2"
LEGACY_FEED_EVENTS_KEY = "activity_feed:events"
FEED_CHANNEL = "activity_feed:live"
FEED_EVENT_CURSOR_HASH_KEY = "activity_feed:event-cursors:v2"
FEED_EVENT_CURSOR_INDEX_KEY = "activity_feed:event-cursor-index:v2"
FEED_CURSOR_CACHE_MIN_EVENTS = 1_000
FEED_CURSOR_CACHE_MIN_TTL = 300
MISSING_FEED_SCORE = object()
APPEND_FEED_EVENT_SCRIPT = """
local MAX_LUA_INTEGER = 9007199254740991
local MAX_TTL = 9007199254740
local function bounded_integer(value, maximum, label)
    local number = tonumber(value)
    if not number or number ~= math.floor(number) or number < 0 or number > maximum then
        return nil, redis.error_reply('Invalid ' .. label)
    end
    return number, nil
end
local function ensure_type(key, expected)
    local key_type = redis.call('TYPE', key).ok
    if key_type ~= 'none' and key_type ~= expected then
        return redis.error_reply('WRONGTYPE ' .. key)
    end
end
local function prune_cursor_cache(hash_key, index_key, current_ms, max_entries, ttl)
    local expired = redis.call('ZRANGEBYSCORE', index_key, '-inf', current_ms - ttl * 1000)
    for _, event_id in ipairs(expired) do
        redis.call('HDEL', hash_key, event_id)
        redis.call('ZREM', index_key, event_id)
    end
    local overflow = redis.call('ZCARD', index_key) - max_entries
    if overflow > 0 then
        local oldest = redis.call('ZRANGE', index_key, 0, overflow - 1)
        for _, event_id in ipairs(oldest) do
            redis.call('HDEL', hash_key, event_id)
            redis.call('ZREM', index_key, event_id)
        end
    end
    redis.call('EXPIRE', hash_key, ttl)
    redis.call('EXPIRE', index_key, ttl)
end
for first = 1, #KEYS do
    for second = first + 1, #KEYS do
        if KEYS[first] == KEYS[second] then
            return redis.error_reply('Feed keys must be distinct')
        end
    end
end
if #KEYS ~= 5 or not ARGV[1] or not ARGV[4] or ARGV[4] == '' then
    return redis.error_reply('Invalid feed append arguments')
end
local max_events, argument_error = bounded_integer(ARGV[2], MAX_LUA_INTEGER / 2, 'feed max events')
if argument_error then return argument_error end
local ttl
ttl, argument_error = bounded_integer(ARGV[3], MAX_TTL, 'feed TTL')
if argument_error then return argument_error end
local cursor_cache_max
cursor_cache_max, argument_error = bounded_integer(ARGV[5], MAX_LUA_INTEGER, 'feed cursor cache size')
if argument_error or cursor_cache_max < 1 then return argument_error or redis.error_reply('Invalid feed cursor cache size') end
local cursor_cache_ttl
cursor_cache_ttl, argument_error = bounded_integer(ARGV[6], MAX_TTL, 'feed cursor cache TTL')
if argument_error or cursor_cache_ttl < 1 then return argument_error or redis.error_reply('Invalid feed cursor cache TTL') end
local type_error = ensure_type(KEYS[1], 'stream')
if type_error then return type_error end
type_error = ensure_type(KEYS[3], 'hash')
if type_error then return type_error end
type_error = ensure_type(KEYS[4], 'zset')
if type_error then return type_error end
type_error = ensure_type(KEYS[5], 'zset')
if type_error then return type_error end
local server_time = redis.call('TIME')
local current_ms = tonumber(server_time[1]) * 1000 + math.floor(tonumber(server_time[2]) / 1000)
local current_seconds = tonumber(server_time[1]) + tonumber(server_time[2]) / 1000000
local current_score = server_time[1] .. '.' .. string.format('%06d', tonumber(server_time[2]))
local stream_id = redis.call('XADD', KEYS[1], '*', 'event', ARGV[1], 'score', current_score)
redis.call('HSET', KEYS[3], ARGV[4], stream_id)
redis.call('ZADD', KEYS[4], current_ms, ARGV[4])
redis.call('ZADD', KEYS[5], current_seconds, ARGV[1])
redis.call('XTRIM', KEYS[1], 'MAXLEN', '=', max_events)
local cutoff = math.max(0, current_ms - ttl * 1000)
if ttl == 0 then
    redis.call('XTRIM', KEYS[1], 'MAXLEN', '=', 0)
else
    redis.call('XTRIM', KEYS[1], 'MINID', '=', string.format('%.0f-0', cutoff))
end
if max_events == 0 or ttl == 0 then
    redis.call('ZREMRANGEBYRANK', KEYS[5], 0, -1)
else
    redis.call('ZREMRANGEBYRANK', KEYS[5], 0, -max_events - 1)
    redis.call('ZREMRANGEBYSCORE', KEYS[5], '-inf', current_seconds - ttl)
end
prune_cursor_cache(KEYS[3], KEYS[4], current_ms, cursor_cache_max, cursor_cache_ttl)
redis.pcall('PUBLISH', KEYS[2], ARGV[1])
return stream_id
"""
MIGRATE_FEED_EVENT_SCRIPT = """
local MAX_LUA_INTEGER = 9007199254740991
local MAX_TTL = 9007199254740
local function bounded_integer(value, maximum, label)
    local number = tonumber(value)
    if not number or number ~= math.floor(number) or number < 0 or number > maximum then
        return nil, redis.error_reply('Invalid ' .. label)
    end
    return number, nil
end
local function ensure_type(key, expected)
    local key_type = redis.call('TYPE', key).ok
    if key_type ~= 'none' and key_type ~= expected then
        return redis.error_reply('WRONGTYPE ' .. key)
    end
end
local function prune_cursor_cache(hash_key, index_key, current_ms, max_entries, ttl)
    local expired = redis.call('ZRANGEBYSCORE', index_key, '-inf', current_ms - ttl * 1000)
    for _, event_id in ipairs(expired) do
        redis.call('HDEL', hash_key, event_id)
        redis.call('ZREM', index_key, event_id)
    end
    local overflow = redis.call('ZCARD', index_key) - max_entries
    if overflow > 0 then
        local oldest = redis.call('ZRANGE', index_key, 0, overflow - 1)
        for _, event_id in ipairs(oldest) do
            redis.call('HDEL', hash_key, event_id)
            redis.call('ZREM', index_key, event_id)
        end
    end
    redis.call('EXPIRE', hash_key, ttl)
    redis.call('EXPIRE', index_key, ttl)
end
for first = 1, #KEYS do
    for second = first + 1, #KEYS do
        if KEYS[first] == KEYS[second] then
            return redis.error_reply('Feed keys must be distinct')
        end
    end
end
if #KEYS ~= 3 or not ARGV[1] or ARGV[1] == '' then
    return redis.error_reply('Invalid feed migration arguments')
end
local cursor_cache_max, argument_error = bounded_integer(ARGV[3], MAX_LUA_INTEGER, 'feed cursor cache size')
if argument_error or cursor_cache_max < 1 then return argument_error or redis.error_reply('Invalid feed cursor cache size') end
local cursor_cache_ttl
cursor_cache_ttl, argument_error = bounded_integer(ARGV[4], MAX_TTL, 'feed cursor cache TTL')
if argument_error or cursor_cache_ttl < 1 then return argument_error or redis.error_reply('Invalid feed cursor cache TTL') end
local type_error = ensure_type(KEYS[1], 'stream')
if type_error then return type_error end
type_error = ensure_type(KEYS[2], 'hash')
if type_error then return type_error end
type_error = ensure_type(KEYS[3], 'zset')
if type_error then return type_error end
local existing_cursor = redis.call('HGET', KEYS[2], ARGV[1])
if existing_cursor then return {existing_cursor, 0} end
local occurrence_score = tonumber(ARGV[2])
if not occurrence_score or occurrence_score ~= occurrence_score or occurrence_score < 0 or occurrence_score > MAX_LUA_INTEGER then
    return redis.error_reply('Invalid feed occurrence score')
end
local server_time = redis.call('TIME')
local current_ms = tonumber(server_time[1]) * 1000 + math.floor(tonumber(server_time[2]) / 1000)
local stream_id = redis.call('XADD', KEYS[1], '*', 'migration', ARGV[1], 'score', ARGV[2])
redis.call('XDEL', KEYS[1], stream_id)
redis.call('HSET', KEYS[2], ARGV[1], stream_id)
redis.call('ZADD', KEYS[3], current_ms, ARGV[1])
prune_cursor_cache(KEYS[2], KEYS[3], current_ms, cursor_cache_max, cursor_cache_ttl)
return {stream_id, 1}
"""


def validate_feed_string(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("Feed event contains a surrogate code point")


def validate_feed_json(value: Any) -> None:
    pending = [(value, 0, False)]
    active_containers = set()
    while pending:
        current, depth, leaving = pending.pop()
        if leaving:
            active_containers.remove(id(current))
            continue
        if isinstance(current, str):
            validate_feed_string(current)
            continue
        if current is None or isinstance(current, (bool, int)):
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                raise ValueError("Feed event contains a non-finite number")
            continue
        if not isinstance(current, (list, dict)):
            raise TypeError("Feed event contains a non-JSON value")
        if depth >= MAX_FEED_JSON_DEPTH:
            raise ValueError("Feed event exceeds the maximum JSON depth")

        container_id = id(current)
        if container_id in active_containers:
            raise ValueError("Feed event contains a circular reference")
        active_containers.add(container_id)
        pending.append((current, depth, True))
        if isinstance(current, list):
            pending.extend((item, depth + 1, False) for item in current)
        else:
            for key in current:
                if not isinstance(key, str):
                    raise TypeError("Feed event keys must be strings")
                validate_feed_string(key)
            pending.extend((item, depth + 1, False) for item in current.values())


def validate_feed_event(event: Dict[str, Any]) -> None:
    validate_feed_json(event)
    if not isinstance(event.get("id"), str) or not 1 <= len(event["id"]) <= 256:
        raise ValueError("Feed event ID must be a non-empty string")
    if not isinstance(event.get("type"), str):
        raise TypeError("Feed event type must be a string")
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str):
        raise TypeError("Feed event timestamp must be a string")
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Feed event timestamp must be ISO 8601") from error
    if not isinstance(event.get("user_name"), str):
        raise TypeError("Feed event user name must be a string")
    if event.get("user_belt") is not None and not isinstance(event["user_belt"], str):
        raise TypeError("Feed event belt must be a string or null")
    user_emojis = event.get("user_emojis")
    if not isinstance(user_emojis, list) or not all(isinstance(emoji, str) for emoji in user_emojis):
        raise TypeError("Feed event emojis must be a list of strings")


def normalize_feed_label(*values: Any) -> Optional[str]:
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (int, float)):
            try:
                return json.dumps(value, allow_nan=False)
            except ValueError:
                continue
    return None


def normalize_feed_event(event: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(event, dict):
        raise TypeError("Feed event must be an object")
    validate_feed_event(event)

    event = dict(event)
    user_id = event.get("user_id")
    event["user_profile_id"] = (
        user_id
        if isinstance(user_id, int)
        and not isinstance(user_id, bool)
        and 1 <= user_id <= MAX_SAFE_USER_ID
        else None
    )

    data = event.get("data")
    data = dict(data) if isinstance(data, dict) else {}
    for source, target, pattern in (
        ("dojo_id", "dojo_path_id", DOJO_REFERENCE_PATTERN),
        ("module_id", "module_path_id", CONTENT_ID_PATTERN),
        ("challenge_reference_id", "challenge_path_id", CONTENT_ID_PATTERN),
    ):
        value = data.get(source)
        data[target] = (
            value
            if isinstance(value, str) and pattern.fullmatch(value)
            else None
        )
    data["dojo_label"] = normalize_feed_label(data.get("dojo_name"), data.get("dojo_id"))
    data["module_label"] = normalize_feed_label(data.get("module_name"), data.get("module_id"))
    data["challenge_label"] = normalize_feed_label(
        data.get("challenge_name"),
        data.get("challenge_reference_id"),
        data.get("challenge_id"),
    )
    event["data"] = data
    return event


def get_redis_client() -> redis.Redis:
    redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
    return redis.from_url(redis_url, decode_responses=False)


def parse_feed_event(raw_event: Any) -> Dict[str, Any]:
    if isinstance(raw_event, bytes):
        raw_event = raw_event.decode("utf-8")
    if not isinstance(raw_event, str):
        raise TypeError("Feed event payload must be text")
    return normalize_feed_event(json.loads(raw_event))


def normalize_feed_cursor(cursor: Any) -> Optional[str]:
    if isinstance(cursor, bytes):
        cursor = cursor.decode("ascii")
    if not isinstance(cursor, str) or not FEED_CURSOR_PATTERN.fullmatch(cursor):
        return None
    milliseconds, sequence = map(int, cursor.split("-", 1))
    if max(milliseconds, sequence) > MAX_REDIS_STREAM_ID_COMPONENT:
        return None
    return f"{milliseconds}-{sequence}"


def feed_cursor_sort_key(cursor: Any):
    cursor = normalize_feed_cursor(cursor)
    if cursor is None:
        raise ValueError("Feed cursor is invalid")
    return tuple(map(int, cursor.split("-", 1)))


def normalize_legacy_feed_cursor(cursor: Any) -> Optional[str]:
    if isinstance(cursor, bytes):
        cursor = cursor.decode("ascii")
    if isinstance(cursor, (int, float)) and not isinstance(cursor, bool):
        cursor = repr(cursor)
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 64:
        return None
    try:
        score = float(cursor)
    except ValueError:
        return None
    if not math.isfinite(score) or score < 0:
        return None
    return repr(score)


def get_feed_retention_settings():
    from ..config import FEED_MAX_EVENTS, FEED_EVENT_TTL

    for value, maximum, label in (
        (FEED_MAX_EVENTS, MAX_FEED_EVENT_COUNT, "FEED_MAX_EVENTS"),
        (FEED_EVENT_TTL, MAX_FEED_TTL_SECONDS, "FEED_EVENT_TTL"),
    ):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value > maximum
        ):
            raise ValueError(f"{label} is outside the supported Redis range")
    cursor_cache_max = max(
        FEED_MAX_EVENTS * 2,
        FEED_CURSOR_CACHE_MIN_EVENTS,
    )
    cursor_cache_ttl = max(FEED_EVENT_TTL, FEED_CURSOR_CACHE_MIN_TTL)
    return (
        FEED_MAX_EVENTS,
        FEED_EVENT_TTL,
        cursor_cache_max,
        cursor_cache_ttl,
    )


def get_feed_event_score(event: Dict[str, Any]) -> Optional[str]:
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return normalize_legacy_feed_cursor(parsed.timestamp())
    except (OverflowError, ValueError):
        return None


def set_feed_event_score(
    event: Dict[str, Any],
    score: Any = MISSING_FEED_SCORE,
    cursor: Any = None,
) -> Dict[str, Any]:
    if score is MISSING_FEED_SCORE:
        normalized_score = get_feed_event_score(event)
    else:
        normalized_score = normalize_legacy_feed_cursor(score)
        if normalized_score is None:
            raise ValueError("Feed event occurrence score is invalid")
    if normalized_score is None and cursor is not None:
        normalized_cursor = normalize_feed_cursor(cursor)
        if normalized_cursor is not None:
            milliseconds = int(normalized_cursor.split("-", 1)[0])
            normalized_score = normalize_legacy_feed_cursor(milliseconds / 1_000)
    if normalized_score is None:
        raise ValueError("Feed event occurrence score is invalid")
    event["feed_score"] = normalized_score
    return event


def parse_stream_event(cursor: Any, fields: Dict[Any, Any]) -> Dict[str, Any]:
    cursor = normalize_feed_cursor(cursor)
    if cursor is None:
        raise ValueError("Feed stream cursor is invalid")
    if not isinstance(fields, dict):
        raise TypeError("Feed stream fields must be an object")
    raw_event = fields.get(b"event", fields.get("event"))
    event = parse_feed_event(raw_event)
    event["cursor"] = cursor
    if b"score" in fields or "score" in fields:
        score = fields.get(b"score", fields.get("score"))
        return set_feed_event_score(event, score=score, cursor=cursor)
    return set_feed_event_score(event, cursor=cursor)


def filter_visible_feed_events(events):
    events = list(events)
    if not events:
        return []

    try:
        from sqlalchemy import and_, or_, select
        from ..models import Dojos

        user_ids = {
            event.get("user_id")
            for event in events
            if isinstance(event.get("user_id"), int)
            and not isinstance(event.get("user_id"), bool)
            and 1 <= event["user_id"] <= MAX_SAFE_USER_ID
        }
        dojo_references = {
            event.get("data", {}).get("dojo_id")
            for event in events
            if isinstance(event.get("data"), dict)
            and isinstance(event["data"].get("dojo_id"), str)
            and DOJO_REFERENCE_PATTERN.fullmatch(event["data"]["dojo_id"])
        }
        official_ids = {
            reference
            for reference in dojo_references
            if "~" not in reference
        }
        referenced_dojo_ids = set()
        reference_identities = {}
        for reference in dojo_references - official_ids:
            dojo_id, hexadecimal_id = reference.split("~", 1)
            numeric_id = int.from_bytes(
                bytes.fromhex(hexadecimal_id),
                "big",
                signed=True,
            )
            referenced_dojo_ids.add(numeric_id)
            reference_identities[reference] = (dojo_id, numeric_id)

        conditions = []
        if official_ids:
            conditions.append(and_(Dojos.official, Dojos.id.in_(official_ids)))
        if referenced_dojo_ids:
            conditions.append(Dojos.dojo_id.in_(referenced_dojo_ids))
        with db.engine.connect() as connection:
            transaction = connection.begin()
            try:
                user_rows = (
                    connection.execute(
                        select(Users.id, Users.hidden, Users.banned)
                        .where(Users.id.in_(user_ids))
                    ).all()
                    if user_ids
                    else []
                )
                dojo_rows = (
                    connection.execute(
                        select(Dojos.id, Dojos.dojo_id, Dojos.official)
                        .where(Dojos.globally_visible(), or_(*conditions))
                    ).all()
                    if conditions
                    else []
                )
            finally:
                transaction.rollback()

        hidden_user_ids = {
            row[0]
            for row in user_rows
            if row[1] or row[2]
        }
        visible_dojo_references = set()
        if dojo_rows:
            visible_official_ids = {
                row[0]
                for row in dojo_rows
                if row[2]
            }
            visible_identities = {
                (row[0], row[1])
                for row in dojo_rows
            }
            visible_dojo_references.update(official_ids & visible_official_ids)
            visible_dojo_references.update(
                reference
                for reference, identity in reference_identities.items()
                if identity in visible_identities
            )

        visible_events = []
        for event in events:
            user_id = event.get("user_id")
            if user_id in hidden_user_ids:
                continue
            data = event.get("data")
            dojo_reference = data.get("dojo_id") if isinstance(data, dict) else None
            if (
                isinstance(dojo_reference, str)
                and DOJO_REFERENCE_PATTERN.fullmatch(dojo_reference)
                and dojo_reference not in visible_dojo_references
            ):
                continue
            visible_events.append(event)
        return visible_events
    except Exception:
        current_app.logger.exception("Unable to verify activity feed visibility")
        return []


def create_event(event_type: str, user: Users, data: Dict[str, Any]) -> Optional[str]:
    try:
        if user.hidden or user.banned:
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
            "data": data,
        }

        validate_feed_event(event)
        event_json = json.dumps(event, allow_nan=False)
        r = get_redis_client()
        (
            max_events,
            event_ttl,
            cursor_cache_max,
            cursor_cache_ttl,
        ) = get_feed_retention_settings()
        r.eval(
            APPEND_FEED_EVENT_SCRIPT,
            5,
            FEED_STREAM_KEY,
            FEED_CHANNEL,
            FEED_EVENT_CURSOR_HASH_KEY,
            FEED_EVENT_CURSOR_INDEX_KEY,
            LEGACY_FEED_EVENTS_KEY,
            event_json,
            max_events,
            event_ttl,
            event["id"],
            cursor_cache_max,
            cursor_cache_ttl,
        )
        return event["id"]
    except Exception:
        current_app.logger.exception("Unable to create activity feed event")
        return None


def get_feed_snapshot(limit: int = 50, offset: int = 0):
    try:
        r = get_redis_client()
        limit = max(limit, 0)
        offset = max(offset, 0)
        max_raw_events, event_ttl, _, _ = get_feed_retention_settings()
        if max_raw_events == 0:
            return [], "0-0", "0.0"

        pipeline = r.pipeline(transaction=True)
        pipeline.xrevrange(FEED_STREAM_KEY, max="+", min="-", count=max_raw_events)
        pipeline.zrevrange(
            LEGACY_FEED_EVENTS_KEY,
            0,
            max_raw_events - 1,
            withscores=True,
        )
        stream_entries, legacy_entries = pipeline.execute()
        latest_cursor = (
            normalize_feed_cursor(stream_entries[0][0])
            if stream_entries
            else "0-0"
        )
        latest_legacy_cursor = (
            normalize_legacy_feed_cursor(legacy_entries[0][1])
            if legacy_entries
            else "0.0"
        )
        cutoff_score = time.time() - event_ttl
        candidates = []
        for cursor, fields in stream_entries:
            try:
                normalized_cursor = normalize_feed_cursor(cursor)
                if normalized_cursor is None:
                    continue
                event = parse_stream_event(normalized_cursor, fields)
                score = float(event["feed_score"])
                if score < cutoff_score:
                    continue
                _, sequence = map(int, normalized_cursor.split("-", 1))
            except (
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
                OverflowError,
                RecursionError,
            ):
                continue
            candidates.append(((score, sequence, 1), event))

        for raw_event, score in legacy_entries:
            try:
                if score < cutoff_score:
                    continue
                event = parse_feed_event(raw_event)
                set_feed_event_score(event, score=score)
            except (
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
                OverflowError,
                RecursionError,
            ):
                continue
            candidates.append(((score, 0, 0), event))

        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        if limit == 0:
            return (
                [],
                latest_cursor or "0-0",
                latest_legacy_cursor or "0.0",
            )
        visible_candidates = filter_visible_feed_events(
            event for _, event in candidates
        )
        events = []
        event_ids = set()
        for event in visible_candidates:
            if event["id"] in event_ids:
                continue
            event_ids.add(event["id"])
            if len(event_ids) <= offset:
                continue
            events.append(event)
            if len(events) >= limit:
                break
        return (
            events,
            latest_cursor or "0-0",
            latest_legacy_cursor or "0.0",
        )
    except Exception:
        current_app.logger.exception("Unable to read activity feed snapshot")
        return [], "0-0", "0.0"


def get_recent_events(limit: int = 50, offset: int = 0):
    return get_feed_snapshot(limit=limit, offset=offset)[0]


def get_latest_feed_cursor(redis_client) -> str:
    entries = redis_client.xrevrange(
        FEED_STREAM_KEY,
        max="+",
        min="-",
        count=1,
    )
    if not entries:
        return "0-0"
    return normalize_feed_cursor(entries[0][0]) or "0-0"


def get_latest_legacy_feed_cursor(redis_client) -> str:
    entries = redis_client.zrevrange(
        LEGACY_FEED_EVENTS_KEY,
        0,
        0,
        withscores=True,
    )
    if not entries:
        return "0.0"
    return normalize_legacy_feed_cursor(entries[0][1]) or "0.0"


def get_feed_entries_after(
    redis_client,
    cursor: str,
    count: int = 100,
    max_cursor: str = "+",
):
    cursor = normalize_feed_cursor(cursor)
    if cursor is None:
        raise ValueError("Feed cursor is invalid")
    if cursor == TERMINAL_FEED_CURSOR:
        return []
    if max_cursor != "+":
        max_cursor = normalize_feed_cursor(max_cursor)
        if max_cursor is None:
            raise ValueError("Maximum feed cursor is invalid")
        if feed_cursor_sort_key(max_cursor) <= feed_cursor_sort_key(cursor):
            return []
    return redis_client.xrange(
        FEED_STREAM_KEY,
        min=f"({cursor}",
        max=max_cursor,
        count=max(count, 1),
    )


def get_legacy_feed_entries_after(
    redis_client,
    cursor: str,
    count: int = 100,
):
    cursor = normalize_legacy_feed_cursor(cursor)
    if cursor is None:
        raise ValueError("Legacy feed cursor is invalid")
    entries = redis_client.zrevrangebyscore(
        LEGACY_FEED_EVENTS_KEY,
        "+inf",
        cursor,
        start=0,
        num=max(count, 1),
        withscores=True,
    )
    return list(reversed(entries))


def migrate_feed_event(redis_client, event_id: str, occurrence_score: Any):
    normalized_score = normalize_legacy_feed_cursor(occurrence_score)
    if normalized_score is None:
        raise ValueError("Feed event occurrence score is invalid")
    _, _, cursor_cache_max, cursor_cache_ttl = get_feed_retention_settings()
    result = redis_client.eval(
        MIGRATE_FEED_EVENT_SCRIPT,
        3,
        FEED_STREAM_KEY,
        FEED_EVENT_CURSOR_HASH_KEY,
        FEED_EVENT_CURSOR_INDEX_KEY,
        event_id,
        normalized_score,
        cursor_cache_max,
        cursor_cache_ttl,
    )
    cursor = normalize_feed_cursor(result[0])
    if cursor is None:
        raise ValueError("Migrated feed cursor is invalid")
    return cursor, bool(result[1])


def create_dojo_event(
    event_type: str,
    user: Users,
    dojo: Any,
    data: Dict[str, Any],
) -> Optional[str]:
    try:
        if dojo is None or not dojo.globally_visible():
            return None
        return create_event(event_type, user, data)
    except Exception:
        current_app.logger.exception("Unable to create dojo activity feed event")
        return None


def publish_container_start(
    user: Users,
    mode: str,
    dojo: Any,
    challenge_data: Dict,
) -> Optional[str]:
    try:
        return create_dojo_event(
            "container_start",
            user,
            dojo,
            challenge_data | {"mode": mode},
        )
    except Exception:
        current_app.logger.exception("Unable to create container feed event")
        return None


def publish_challenge_solve(
    user: Users,
    dojo_challenge: Any,
    dojo: Any,
    module: Any,
    points: int,
    first_blood: bool = False,
) -> Optional[str]:
    try:
        return create_dojo_event("challenge_solve", user, dojo, {
            "challenge_id": dojo_challenge.challenge_id,
            "challenge_reference_id": dojo_challenge.id,
            "challenge_name": dojo_challenge.name,
            "module_id": module.id if module else None,
            "module_name": module.name if module else None,
            "dojo_id": dojo.reference_id,
            "dojo_name": dojo.name,
            "points": points,
            "first_blood": first_blood,
        })
    except Exception:
        current_app.logger.exception("Unable to create solve feed event")
        return None


def publish_emoji_earned(
    user: Users,
    emoji: str,
    emoji_name: str,
    reason: str,
    dojo: Any = None,
    dojo_id: str = None,
    dojo_name: str = None,
) -> Optional[str]:
    try:
        data = {
            "emoji": emoji,
            "emoji_name": emoji_name,
            "reason": reason,
            "dojo_id": dojo.reference_id if dojo else dojo_id,
            "dojo_name": dojo.name if dojo else dojo_name,
        }
        return (
            create_dojo_event("emoji_earned", user, dojo, data)
            if dojo
            else create_event("emoji_earned", user, data)
        )
    except Exception:
        current_app.logger.exception("Unable to create emoji feed event")
        return None


def publish_belt_earned(
    user: Users,
    belt: str,
    belt_name: str,
    dojo: Any,
) -> Optional[str]:
    try:
        return create_dojo_event("belt_earned", user, dojo, {
            "belt": belt,
            "belt_name": belt_name,
            "dojo_id": dojo.reference_id,
            "dojo_name": dojo.name,
        })
    except Exception:
        current_app.logger.exception("Unable to create belt feed event")
        return None


def publish_dojo_update(
    user: Users,
    dojo: Any,
    summary: str,
    changes: Dict,
) -> Optional[str]:
    try:
        return create_dojo_event("dojo_update", user, dojo, {
            "dojo_id": dojo.reference_id,
            "dojo_name": dojo.name,
            "summary": summary,
            "changes": changes,
        })
    except Exception:
        current_app.logger.exception("Unable to create dojo update feed event")
        return None
