from collections import deque
import hashlib
import json
import time

import redis
from flask import Response, request, current_app
from flask_restx import Namespace, Resource
from ...utils.feed import (
    FEED_CHANNEL,
    LEGACY_FEED_EVENTS_KEY,
    feed_cursor_sort_key,
    filter_visible_feed_events,
    get_feed_entries_after,
    get_feed_retention_settings,
    get_feed_snapshot,
    get_latest_feed_cursor,
    get_latest_legacy_feed_cursor,
    get_legacy_feed_entries_after,
    migrate_feed_event,
    normalize_feed_cursor,
    normalize_legacy_feed_cursor,
    parse_feed_event,
    parse_stream_event,
    set_feed_event_score,
)

feed_namespace = Namespace("feed", description="Activity feed endpoints")


def stream_feed_events(redis_url, cursor=None, legacy_cursor=None, app=None):
    pubsub = None
    try:
        max_events, event_ttl, _, _ = get_feed_retention_settings()
        r = redis.from_url(redis_url, decode_responses=False)
        pubsub = r.pubsub()
        cursor = normalize_feed_cursor(cursor)
        if cursor is None:
            cursor = get_latest_feed_cursor(r)
        starting_cursor = cursor
        legacy_cursor = normalize_legacy_feed_cursor(legacy_cursor)
        if legacy_cursor is None:
            legacy_cursor = get_latest_legacy_feed_cursor(r)
        pubsub.subscribe(FEED_CHANNEL)
        pending_messages = deque()
        while True:
            subscription_message = pubsub.get_message(timeout=1)
            if subscription_message:
                if subscription_message["type"] in (
                    "subscribe",
                    b"subscribe",
                ):
                    break
                if subscription_message["type"] in ("message", b"message"):
                    pending_messages.append(subscription_message)
        yield (
            f"data: {json.dumps({'type': 'connected', 'cursor': cursor, 'legacy_cursor': legacy_cursor}, allow_nan=False)}\n\n"
        )
        last_heartbeat = time.time()
        catchup_complete = False
        seen_event_ids = set()
        seen_event_order = deque()
        seen_payloads = set()
        seen_payload_order = deque()
        seen_limit = max(max_events * 2, 1_000)

        def remember(seen, order, value):
            if value in seen:
                return False
            seen.add(value)
            order.append(value)
            if len(order) > seen_limit:
                seen.remove(order.popleft())
            return True

        def visible_events(events):
            if app is None:
                return filter_visible_feed_events(events)
            with app.app_context():
                return filter_visible_feed_events(events)

        def payload_fingerprint(raw_event):
            if isinstance(raw_event, str):
                raw_event = raw_event.encode()
            if not isinstance(raw_event, bytes):
                raw_event = repr(raw_event).encode()
            return hashlib.sha256(raw_event).digest()

        def advance_legacy_cursor(score):
            nonlocal legacy_cursor
            normalized = normalize_legacy_feed_cursor(score)
            if normalized is None:
                return
            if float(normalized) > float(legacy_cursor):
                legacy_cursor = normalized

        def serialize_event(event, event_cursor):
            event["cursor"] = event_cursor
            event["legacy_cursor"] = legacy_cursor
            return (
                f"id: {event_cursor}\n"
                f"data: {json.dumps(event, allow_nan=False)}\n\n"
            )

        def advance_event_cursor(event_cursor):
            nonlocal cursor
            event_key = feed_cursor_sort_key(event_cursor)
            if event_key > feed_cursor_sort_key(cursor):
                cursor = event_cursor
                return cursor
            if event_key > feed_cursor_sort_key(starting_cursor):
                return cursor
            return None

        def replay_retained_through(max_cursor):
            nonlocal cursor
            while feed_cursor_sort_key(cursor) < feed_cursor_sort_key(max_cursor):
                retained_entries = get_feed_entries_after(
                    r,
                    cursor,
                    max_cursor=max_cursor,
                )
                if not retained_entries:
                    break
                cutoff_score = time.time() - event_ttl
                retained_events = []
                for raw_cursor, fields in retained_entries:
                    retained_cursor = normalize_feed_cursor(raw_cursor)
                    if retained_cursor is None:
                        continue
                    cursor = retained_cursor
                    try:
                        retained_event = parse_stream_event(cursor, fields)
                    except (
                        UnicodeError,
                        json.JSONDecodeError,
                        TypeError,
                        ValueError,
                        RecursionError,
                    ):
                        continue
                    if float(retained_event["feed_score"]) < cutoff_score:
                        continue
                    retained_events.append(retained_event)
                for retained_event in visible_events(retained_events):
                    if not visible_events([retained_event]):
                        continue
                    if not remember(
                        seen_event_ids,
                        seen_event_order,
                        retained_event["id"],
                    ):
                        continue
                    yield serialize_event(
                        retained_event,
                        retained_event["cursor"],
                    )

        while True:
            entries = (
                get_feed_entries_after(r, cursor)
                if not catchup_complete
                else []
            )
            if entries:
                cutoff_score = time.time() - event_ttl
                parsed_events = []
                for raw_cursor, fields in entries:
                    next_cursor = normalize_feed_cursor(raw_cursor)
                    if next_cursor is None:
                        continue
                    cursor = next_cursor
                    try:
                        event = parse_stream_event(cursor, fields)
                    except (
                        UnicodeError,
                        json.JSONDecodeError,
                        TypeError,
                        ValueError,
                        RecursionError,
                    ):
                        continue
                    if float(event["feed_score"]) < cutoff_score:
                        continue
                    parsed_events.append(event)
                for event in visible_events(parsed_events):
                    if not visible_events([event]):
                        continue
                    if not remember(
                        seen_event_ids,
                        seen_event_order,
                        event["id"],
                    ):
                        continue
                    yield serialize_event(event, event["cursor"])
                continue

            legacy_entries = (
                get_legacy_feed_entries_after(
                    r,
                    legacy_cursor,
                    count=max(max_events, 1),
                )
                if not catchup_complete and max_events > 0
                else []
            )
            legacy_event_emitted = False
            cutoff_score = time.time() - event_ttl
            parsed_legacy_events = []
            for raw_event, score in legacy_entries:
                fingerprint = payload_fingerprint(raw_event)
                if fingerprint in seen_payloads:
                    continue
                remember(seen_payloads, seen_payload_order, fingerprint)
                advance_legacy_cursor(score)
                if score < cutoff_score:
                    continue
                try:
                    event = parse_feed_event(raw_event)
                except (
                    UnicodeError,
                    json.JSONDecodeError,
                    TypeError,
                    ValueError,
                    OverflowError,
                    RecursionError,
                ):
                    continue
                set_feed_event_score(event, score=score)
                parsed_legacy_events.append(event)
            for event in visible_events(parsed_legacy_events):
                if event["id"] in seen_event_ids:
                    continue
                event_cursor, _ = migrate_feed_event(
                    r,
                    event["id"],
                    event["feed_score"],
                )
                yield from replay_retained_through(event_cursor)
                if event["id"] in seen_event_ids:
                    continue
                delivery_cursor = advance_event_cursor(event_cursor)
                if delivery_cursor is None:
                    continue
                if not visible_events([event]):
                    continue
                remember(seen_event_ids, seen_event_order, event["id"])
                legacy_event_emitted = True
                yield serialize_event(event, delivery_cursor)
            if legacy_event_emitted:
                continue
            catchup_complete = True

            message = (
                pending_messages.popleft()
                if pending_messages
                else pubsub.get_message(timeout=1)
            )
            if message and message["type"] in ("message", b"message"):
                raw_event = message["data"]
                fingerprint = payload_fingerprint(raw_event)
                if fingerprint in seen_payloads:
                    continue
                remember(seen_payloads, seen_payload_order, fingerprint)
                try:
                    event = parse_feed_event(raw_event)
                except (
                    UnicodeError,
                    json.JSONDecodeError,
                    TypeError,
                    ValueError,
                    OverflowError,
                    RecursionError,
                ):
                    continue
                legacy_score = r.zscore(LEGACY_FEED_EVENTS_KEY, raw_event)
                if legacy_score is not None:
                    advance_legacy_cursor(legacy_score)
                if legacy_score is None:
                    set_feed_event_score(event)
                else:
                    set_feed_event_score(event, score=legacy_score)
                if not visible_events([event]):
                    continue
                if event["id"] in seen_event_ids:
                    continue
                event_cursor, _ = migrate_feed_event(
                    r,
                    event["id"],
                    event["feed_score"],
                )
                yield from replay_retained_through(event_cursor)
                if event["id"] in seen_event_ids:
                    continue
                delivery_cursor = advance_event_cursor(event_cursor)
                if delivery_cursor is None:
                    continue
                if not visible_events([event]):
                    continue
                remember(seen_event_ids, seen_event_order, event["id"])
                yield serialize_event(event, delivery_cursor)
            if time.time() - last_heartbeat > 30:
                yield (
                    f"data: {json.dumps({'type': 'heartbeat', 'cursor': cursor, 'legacy_cursor': legacy_cursor}, allow_nan=False)}\n\n"
                )
                last_heartbeat = time.time()
    finally:
        if pubsub is not None:
            pubsub.close()


@feed_namespace.route("/events")
class FeedEvents(Resource):
    def get(self):
        try:
            limit = max(min(int(request.args.get("limit", 50)), 100), 0)
            offset = max(int(request.args.get("offset", 0)), 0)
        except (ValueError, TypeError):
            limit, offset = 50, 0
        events, cursor, legacy_cursor = get_feed_snapshot(
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "data": events,
            "meta": {
                "limit": limit,
                "offset": offset,
                "count": len(events),
                "cursor": cursor,
                "legacy_cursor": legacy_cursor,
            },
        }


@feed_namespace.route("/stream")
class FeedStream(Resource):
    def get(self):
        app = current_app._get_current_object()
        redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
        requested_cursor = request.args.get("cursor") or request.headers.get(
            "Last-Event-ID"
        )
        cursor = normalize_feed_cursor(requested_cursor)
        if requested_cursor is not None and cursor is None:
            cursor = "0-0"
        requested_legacy_cursor = request.args.get("legacy_cursor")
        legacy_cursor = normalize_legacy_feed_cursor(requested_legacy_cursor)
        if requested_legacy_cursor is not None and legacy_cursor is None:
            legacy_cursor = "0.0"

        return Response(
            stream_feed_events(redis_url, cursor, legacy_cursor, app=app),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
