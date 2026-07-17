import base64
import json
import re
import time
import uuid
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

import requests
from utils import (
    DOJO_URL,
    create_dojo_yml,
    db_sql,
    dojo_run,
    login,
    solve_challenge,
    start_challenge,
    wait_for_background_worker,
    workspace_run,
)
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


FEED_EVENT_TYPES = {
    "container_start",
    "challenge_solve",
    "emoji_earned",
    "belt_earned",
    "dojo_update",
}
FEED_TEST_BELT = "orange"
MAX_SAFE_USER_ID = 9_007_199_254_740_991
DOJO_REFERENCE_PATTERN = re.compile(r"^[a-z0-9-]{1,32}(?:~[0-9a-f]{8})?$")
CONTENT_ID_PATTERN = re.compile(r"^[a-z0-9-]{1,32}$")
RAW_JSON_MARKER = "feed-raw-json-marker"
RAW_BYTES_MARKER = "feed-raw-bytes-marker"
XSS_PAYLOAD = '<svg data-feed-xss="1" onload="alert(1)">'


class FeedCardParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = {}
        self.card = None
        self.div_depth = 0
        self.link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.card is None:
            event_id = attrs.get("data-event-id")
            if event_id is None:
                return
            self.card = {"elements": [], "images": [], "links": [], "text": []}
            self.cards[event_id] = self.card

        self.card["elements"].append((tag, attrs))
        if tag == "div":
            self.div_depth += 1
        elif tag == "a":
            self.link = {"href": attrs.get("href"), "text": []}
            self.card["links"].append(self.link)
        elif tag == "img":
            self.card["images"].append(attrs)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if tag == "a":
            self.link = None
        elif tag == "div":
            self.div_depth -= 1
            if self.div_depth == 0:
                self.card = None
                self.link = None

    def handle_data(self, data):
        if self.card is None:
            return
        self.card["text"].append(data)
        if self.link is not None:
            self.link["text"].append(data)


def publish_feed_events(user_name, events):
    payload = base64.b64encode(json.dumps({"user_name": user_name, "events": events}).encode()).decode()
    code = f"""
import base64
import json

from CTFd.models import Users
from CTFd.plugins.dojo_plugin.utils.feed import create_event

payload = json.loads(base64.b64decode("{payload}"))
user = Users.query.filter_by(name=payload["user_name"]).one()
event_ids = [create_event(event["type"], user, event["data"]) for event in payload["events"]]
print("FEED_EVENT_IDS=" + json.dumps(event_ids))
"""
    encoded = base64.b64encode(code.encode()).decode()
    result = dojo_run("dojo", "flask", input=f'import base64; exec(base64.b64decode("{encoded}").decode())\n')
    match = re.search(r"FEED_EVENT_IDS=(\[[^\r\n]+\])", result.stdout)
    assert match, f"Feed event IDs not found in dojo flask output: {result.stdout}"
    event_ids = json.loads(match.group(1))
    assert all(event_ids), f"Failed to publish feed events: {result.stdout}"
    return event_ids


def publish_raw_feed_events(user_name, events, *, legacy=False):
    payload = base64.b64encode(json.dumps({
        "user_name": user_name,
        "events": events,
        "legacy": legacy,
    }).encode()).decode()
    code = f"""
import base64
import json
import time
import uuid
from datetime import datetime, timezone

from CTFd.plugins.dojo_plugin.config import FEED_EVENT_TTL, FEED_MAX_EVENTS
from CTFd.plugins.dojo_plugin.utils.feed import (
    APPEND_FEED_EVENT_SCRIPT,
    FEED_CHANNEL,
    FEED_CURSOR_CACHE_MIN_EVENTS,
    FEED_CURSOR_CACHE_MIN_TTL,
    FEED_EVENT_CURSOR_HASH_KEY,
    FEED_EVENT_CURSOR_INDEX_KEY,
    FEED_STREAM_KEY,
    LEGACY_FEED_EVENTS_KEY,
    get_redis_client,
)

payload = json.loads(base64.b64decode("{payload}"))
redis_client = get_redis_client()
event_ids = []
for source in payload["events"]:
    transport_event_id = str(uuid.uuid4())
    event = {{
        "id": transport_event_id,
        "type": source["type"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_name": payload["user_name"],
        "user_belt": "{FEED_TEST_BELT}",
        "user_emojis": [],
        "data": source["data"],
    }}
    if "user_id" in source:
        event["user_id"] = source["user_id"]
    if "user_profile_id" in source:
        event["user_profile_id"] = source["user_profile_id"]
    event.update(source.get("top_level", {{}}))
    raw_event = json.dumps(event, allow_nan=False)
    if "raw_json_literal" in source:
        marker = json.dumps(source["raw_json_marker"])
        assert raw_event.count(marker) == 1
        raw_event = raw_event.replace(marker, source["raw_json_literal"])
    if "raw_bytes_literal" in source:
        raw_event = raw_event.encode()
        marker = json.dumps(source["raw_bytes_marker"]).encode()
        assert raw_event.count(marker) == 1
        raw_event = raw_event.replace(
            marker,
            base64.b64decode(source["raw_bytes_literal"]),
        )
    if payload["legacy"]:
        score = time.time()
        redis_client.zadd(LEGACY_FEED_EVENTS_KEY, {{raw_event: score}})
        redis_client.zremrangebyrank(
            LEGACY_FEED_EVENTS_KEY,
            0,
            -FEED_MAX_EVENTS - 1,
        )
        redis_client.zremrangebyscore(
            LEGACY_FEED_EVENTS_KEY,
            "-inf",
            time.time() - FEED_EVENT_TTL,
        )
        redis_client.publish(FEED_CHANNEL, raw_event)
    else:
        redis_client.eval(
            APPEND_FEED_EVENT_SCRIPT,
            5,
            FEED_STREAM_KEY,
            FEED_CHANNEL,
            FEED_EVENT_CURSOR_HASH_KEY,
            FEED_EVENT_CURSOR_INDEX_KEY,
            LEGACY_FEED_EVENTS_KEY,
            raw_event,
            FEED_MAX_EVENTS,
            FEED_EVENT_TTL,
            transport_event_id,
            max(FEED_MAX_EVENTS * 2, FEED_CURSOR_CACHE_MIN_EVENTS),
            max(FEED_EVENT_TTL, FEED_CURSOR_CACHE_MIN_TTL),
        )
    event_ids.append(transport_event_id)
print("FEED_EVENT_IDS=" + json.dumps(event_ids))
"""
    encoded = base64.b64encode(code.encode()).decode()
    result = dojo_run("dojo", "flask", input=f'import base64; exec(base64.b64decode("{encoded}").decode())\n')
    match = re.search(r"FEED_EVENT_IDS=(\[[^\r\n]+\])", result.stdout)
    assert match, f"Feed event IDs not found in dojo flask output: {result.stdout}"
    return json.loads(match.group(1))


def publish_legacy_feed_events(user_name, events):
    return publish_raw_feed_events(user_name, events, legacy=True)


def publish_feed_event_batches(publisher, user_name, batches):
    events = [event for batch in batches for event in batch]
    event_ids = publisher(user_name, events)
    published_batches = []
    offset = 0
    for batch in batches:
        published_batches.append(event_ids[offset:offset + len(batch)])
        offset += len(batch)
    assert offset == len(event_ids)
    return published_batches


def prepare_feed_test(user_name, dojo_id, module_id, challenge_reference_id):
    payload = base64.b64encode(json.dumps({
        "user_name": user_name,
        "dojo_id": dojo_id,
        "module_id": module_id,
        "challenge_reference_id": challenge_reference_id,
    }).encode()).decode()
    code = f"""
import base64
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import CTFd.plugins.dojo_plugin as dojo_plugin
from flask import current_app
from requests.exceptions import ConnectionError as RequestsConnectionError
from CTFd.models import Solves, Users, db
from CTFd.plugins.challenges import BaseChallenge
from CTFd.plugins.dojo_plugin import config as feed_config
from CTFd.plugins.dojo_plugin.api.v1 import feed as feed_api
from CTFd.plugins.dojo_plugin.config import FEED_MAX_EVENTS
from CTFd.plugins.dojo_plugin.models import Belts, DojoChallenges, Dojos
from CTFd.plugins.dojo_plugin.utils import feed, serialize_user_flag
from CTFd.utils.security.csrf import generate_nonce
from CTFd.utils.security.signing import hmac

payload = json.loads(base64.b64decode("{payload}"))
user = Users.query.filter_by(name=payload["user_name"]).one()
if not Belts.query.filter_by(user=user, name="{FEED_TEST_BELT}").first():
    db.session.add(Belts(user=user, name="{FEED_TEST_BELT}"))
    db.session.commit()
challenge = DojoChallenges.from_id(
    payload["dojo_id"], payload["module_id"], payload["challenge_reference_id"]
).one()
visibility_dojo = Dojos()
visibility_dojo.official = False
visibility_dojo.data = {{"type": "public"}}
visibility_dojo.password = "protected-password"
assert visibility_dojo.globally_visible() is False
visibility_dojo.password = None
assert visibility_dojo.globally_visible() is True
visibility_dojo.data = {{"type": "topic"}}
assert visibility_dojo.globally_visible() is False
visibility_dojo.official = True
visibility_dojo.password = "official-password"
assert visibility_dojo.globally_visible() is True
visibility_dojo.official = False
visibility_dojo.id = f"feed-visibility-{{uuid.uuid4().hex[:8]}}"
visibility_dojo.name = "Feed visibility probe"
visibility_dojo.data = {{"type": "public"}}
visibility_dojo.password = None
db.session.add(visibility_dojo)
db.session.commit()
visibility_probe = {{
    "user_id": user.id,
    "data": {{"dojo_id": visibility_dojo.reference_id}},
}}
assert feed.filter_visible_feed_events([visibility_probe]) == [visibility_probe]
checked_out_connections = db.engine.pool.checkedout()
user.hidden = True
assert db.session.is_modified(user)
assert feed.filter_visible_feed_events([visibility_probe]) == [visibility_probe]
assert user in db.session
assert user.hidden is True
assert db.session.is_modified(user)
assert db.engine.pool.checkedout() == checked_out_connections
db.session.rollback()
visibility_dojo.password = "protected"
db.session.commit()
assert feed.filter_visible_feed_events([visibility_probe]) == []
visibility_dojo.password = None
visibility_dojo.data = {{"type": "private"}}
db.session.commit()
assert feed.filter_visible_feed_events([visibility_probe]) == []
visibility_dojo.data = {{"type": "public"}}
db.session.commit()
user.hidden = True
db.session.commit()
assert feed.filter_visible_feed_events([visibility_probe]) == []
user.hidden = False
user.banned = True
db.session.commit()
assert feed.filter_visible_feed_events([visibility_probe]) == []
user.banned = False
db.session.delete(visibility_dojo)
db.session.commit()
with patch.object(feed, "get_redis_client") as get_redis_client:
    user.hidden = True
    assert feed.create_event("dojo_update", user, {{}}) is None
    user.hidden = False
    user.banned = True
    assert feed.create_event("dojo_update", user, {{}}) is None
    user.banned = False
    deeply_nested = None
    for _ in range(1_100):
        deeply_nested = [deeply_nested]
    results = [
        feed.create_event("dojo_update", user, {{"nested": [float("nan")]}}),
        feed.create_event("dojo_update", user, {{"nested": {{1: "invalid key"}}}}),
        feed.create_event("dojo_update", user, {{"nested": deeply_nested}}),
        feed.create_event("\\ud800", user, {{}}),
        feed.create_event("dojo_update", user, {{"nested": "\\ud800"}}),
        feed.create_event("dojo_update", user, {{"\\udfff": "invalid key"}}),
    ]
    assert results == [None, None, None, None, None, None]
    get_redis_client.assert_not_called()

redis_client = feed.get_redis_client()
redis_version = redis_client.info("server")["redis_version"]
if isinstance(redis_version, bytes):
    redis_version = redis_version.decode()
assert int(redis_version.split(".", 1)[0]) >= 8
atomic_suffix = uuid.uuid4().hex
atomic_stream_key = f"activity_feed:test:atomic:{{atomic_suffix}}"
atomic_channel = f"activity_feed:test:atomic-live:{{atomic_suffix}}"
atomic_cursor_hash_key = f"activity_feed:test:atomic-cursors:{{atomic_suffix}}"
atomic_cursor_index_key = f"activity_feed:test:atomic-index:{{atomic_suffix}}"
atomic_legacy_key = f"activity_feed:test:atomic-legacy:{{atomic_suffix}}"

def wait_for_subscription(pubsub):
    deadline = time.time() + 5
    while time.time() < deadline:
        message = pubsub.get_message(timeout=1)
        if message and message["type"] in ("subscribe", b"subscribe"):
            return
    raise AssertionError("Redis Pub/Sub subscription was not acknowledged")

atomic_pubsub = redis_client.pubsub()
atomic_pubsub.subscribe(atomic_channel)
wait_for_subscription(atomic_pubsub)
old_cursor = f"{{int((time.time() - 120) * 1000)}}-0"
redis_client.xadd(
    atomic_stream_key,
    {{"event": json.dumps({{"sequence": "old"}})}},
    id=old_cursor,
)

def append_atomic_event(sequence):
    return redis_client.eval(
        feed.APPEND_FEED_EVENT_SCRIPT,
        5,
        atomic_stream_key,
        atomic_channel,
        atomic_cursor_hash_key,
        atomic_cursor_index_key,
        atomic_legacy_key,
        json.dumps({{"sequence": sequence}}),
        3,
        60,
        str(sequence),
        100,
        60,
    )

try:
    with ThreadPoolExecutor(max_workers=8) as executor:
        appended_cursors = list(executor.map(append_atomic_event, range(24)))
    stream_rows = redis_client.xrange(atomic_stream_key)
    assert len(stream_rows) == 3
    stream_cursors = [row[0] for row in stream_rows]
    assert old_cursor.encode() not in stream_cursors
    assert stream_cursors == sorted(
        appended_cursors,
        key=lambda cursor: tuple(map(int, cursor.decode().split("-", 1))),
    )[-3:]
    assert redis_client.hlen(atomic_cursor_hash_key) == len(appended_cursors)
    assert redis_client.zcard(atomic_cursor_index_key) == len(appended_cursors)
    assert redis_client.zcard(atomic_legacy_key) == 3
    retained_rows_before_migration = redis_client.xrange(atomic_stream_key)
    near_expiry_score = time.time() - 59
    migrated_cursor, migration_created = redis_client.eval(
        feed.MIGRATE_FEED_EVENT_SCRIPT,
        3,
        atomic_stream_key,
        atomic_cursor_hash_key,
        atomic_cursor_index_key,
        "near-expiry-legacy",
        repr(near_expiry_score),
        100,
        60,
    )
    assert migration_created == 1
    assert redis_client.xrange(atomic_stream_key) == retained_rows_before_migration
    assert redis_client.hget(
        atomic_cursor_hash_key,
        "near-expiry-legacy",
    ) == migrated_cursor
    published_messages = []
    deadline = time.time() + 5
    while len(published_messages) < len(appended_cursors) and time.time() < deadline:
        message = atomic_pubsub.get_message(timeout=1)
        if message and message["type"] in ("message", b"message"):
            published_messages.append(message["data"])
    assert len(published_messages) == len(appended_cursors)

    def append_zero_retention_event(event_id, max_events, ttl):
        raw_event = json.dumps({{"id": event_id}})
        event_cursor = redis_client.eval(
            feed.APPEND_FEED_EVENT_SCRIPT,
            5,
            atomic_stream_key,
            atomic_channel,
            atomic_cursor_hash_key,
            atomic_cursor_index_key,
            atomic_legacy_key,
            raw_event,
            max_events,
            ttl,
            event_id,
            100,
            60,
        )
        deadline = time.time() + 5
        while time.time() < deadline:
            message = atomic_pubsub.get_message(timeout=1)
            if message and message["type"] in ("message", b"message"):
                assert message["data"] == raw_event.encode()
                break
        else:
            raise AssertionError("Zero-retention event was not published")
        assert redis_client.hget(atomic_cursor_hash_key, event_id) == event_cursor
        return event_cursor

    zero_max_cursor = append_zero_retention_event("zero-max", 0, 60)
    assert redis_client.xlen(atomic_stream_key) == 0
    assert redis_client.zcard(atomic_legacy_key) == 0
    duplicate_result = redis_client.eval(
        feed.MIGRATE_FEED_EVENT_SCRIPT,
        3,
        atomic_stream_key,
        atomic_cursor_hash_key,
        atomic_cursor_index_key,
        "zero-max",
        repr(time.time() - 59),
        100,
        60,
    )
    assert duplicate_result == [zero_max_cursor, 0]
    assert redis_client.xlen(atomic_stream_key) == 0
    append_zero_retention_event("zero-ttl", 3, 0)
    assert redis_client.xlen(atomic_stream_key) == 0
    assert redis_client.zcard(atomic_legacy_key) == 0
finally:
    atomic_pubsub.close()
    redis_client.delete(
        atomic_stream_key,
        atomic_cursor_hash_key,
        atomic_cursor_index_key,
        atomic_legacy_key,
    )

failure_stream_key = f"activity_feed:test:failure:{{atomic_suffix}}"
failure_channel = f"activity_feed:test:failure-live:{{atomic_suffix}}"
failure_cursor_hash_key = f"activity_feed:test:failure-cursors:{{atomic_suffix}}"
failure_cursor_index_key = f"activity_feed:test:failure-index:{{atomic_suffix}}"
failure_legacy_key = f"activity_feed:test:failure-legacy:{{atomic_suffix}}"
failure_pubsub = redis_client.pubsub()
failure_pubsub.subscribe(failure_channel)
wait_for_subscription(failure_pubsub)
redis_client.set(failure_stream_key, "unchanged")
try:
    try:
        redis_client.eval(
            feed.APPEND_FEED_EVENT_SCRIPT,
            5,
            failure_stream_key,
            failure_channel,
            failure_cursor_hash_key,
            failure_cursor_index_key,
            failure_legacy_key,
            "event",
            3,
            60,
            "failure-event",
            100,
            60,
        )
    except Exception:
        pass
    else:
        raise AssertionError("Atomic append accepted a non-stream key")
    assert redis_client.get(failure_stream_key) == b"unchanged"
    assert redis_client.exists(failure_cursor_hash_key) == 0
    assert redis_client.exists(failure_cursor_index_key) == 0
    assert redis_client.exists(failure_legacy_key) == 0
    assert failure_pubsub.get_message(timeout=0.1) is None
finally:
    failure_pubsub.close()
    redis_client.delete(
        failure_stream_key,
        failure_cursor_hash_key,
        failure_cursor_index_key,
        failure_legacy_key,
    )

bounds_suffix = uuid.uuid4().hex
bounds_keys = [f"activity_feed:test:bounds:{{bounds_suffix}}:{{index}}" for index in range(5)]
try:
    for invalid_arguments in (
        (feed.MAX_REDIS_LUA_INTEGER, 60, "event", 100, 60),
        (3, feed.MAX_FEED_TTL_SECONDS + 1, "event", 100, 60),
        (3, 60, "event", feed.MAX_REDIS_LUA_INTEGER + 1, 60),
        (3, 60, "event", 100, feed.MAX_FEED_TTL_SECONDS + 1),
    ):
        try:
            redis_client.eval(
                feed.APPEND_FEED_EVENT_SCRIPT,
                5,
                *bounds_keys,
                "event",
                *invalid_arguments,
            )
        except Exception:
            pass
        else:
            raise AssertionError("Atomic append accepted unsafe numeric bounds")
        assert redis_client.exists(*bounds_keys) == 0

    try:
        redis_client.eval(
            feed.APPEND_FEED_EVENT_SCRIPT,
            5,
            bounds_keys[0],
            bounds_keys[1],
            bounds_keys[0],
            bounds_keys[3],
            bounds_keys[4],
            "event",
            3,
            60,
            "event",
            100,
            60,
        )
    except Exception:
        pass
    else:
        raise AssertionError("Atomic append accepted aliased storage keys")
    assert redis_client.exists(*bounds_keys) == 0

    for migration_arguments in (
        ("event", "nan", 100, 60),
        ("event", "1", feed.MAX_REDIS_LUA_INTEGER + 1, 60),
        ("event", "1", 100, feed.MAX_FEED_TTL_SECONDS + 1),
    ):
        try:
            redis_client.eval(
                feed.MIGRATE_FEED_EVENT_SCRIPT,
                3,
                *bounds_keys[:3],
                *migration_arguments,
            )
        except Exception:
            pass
        else:
            raise AssertionError("Feed migration accepted unsafe arguments")
        assert redis_client.exists(*bounds_keys[:3]) == 0
finally:
    redis_client.delete(*bounds_keys)

for config_name, invalid_value in (
    ("FEED_MAX_EVENTS", feed.MAX_FEED_EVENT_COUNT + 1),
    ("FEED_EVENT_TTL", feed.MAX_FEED_TTL_SECONDS + 1),
    ("FEED_MAX_EVENTS", True),
):
    with patch.object(feed_config, config_name, invalid_value):
        try:
            feed.get_feed_retention_settings()
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted unsafe {{config_name}}")

shared_challenge = SimpleNamespace(id=91_337, value=100)
shared_user = SimpleNamespace(id=81_337)
public_dojo = SimpleNamespace(
    official=False,
    data={{"type": "public"}},
    reference_id="public-dojo",
    globally_visible=MagicMock(return_value=True),
)
private_dojo = SimpleNamespace(
    official=False,
    data={{"type": "topic"}},
    reference_id="private-dojo",
    globally_visible=MagicMock(return_value=False),
)
public_module = SimpleNamespace(dojo=public_dojo, id="public-module")
private_module = SimpleNamespace(dojo=private_dojo, id="private-module")
public_association = SimpleNamespace(
    challenge_id=shared_challenge.id,
    id="public-reference",
    module=public_module,
    dojo=public_dojo,
)
private_association = SimpleNamespace(
    challenge_id=shared_challenge.id,
    id="private-reference",
    module=private_module,
    dojo=private_dojo,
)

class RoutedRequest:
    form = {{}}

    def __init__(self, data):
        self.data = data

    def get_json(self, silent=False):
        return self.data

class ExactAssociationQuery:
    def __init__(self, association):
        self.association = association

    def filter(self, *args):
        return self

    def first(self):
        return self.association

exact_query = ExactAssociationQuery(public_association)
exact_dojo_challenges = SimpleNamespace(
    from_id=MagicMock(return_value=exact_query),
    visible=MagicMock(return_value=True),
)
exact_route = {{
    "dojo_id": "public-dojo",
    "module_id": "public-module",
    "challenge_reference_id": "public-reference",
}}
with (
    patch.object(dojo_plugin, "dojo_accessible", return_value=public_dojo),
    patch.object(dojo_plugin, "DojoChallenges", exact_dojo_challenges),
):
    resolved, supplied = dojo_plugin.get_request_dojo_challenge(
        RoutedRequest(exact_route), shared_challenge
    )
    assert supplied is True
    assert resolved is public_association
    resolved, supplied = dojo_plugin.get_request_dojo_challenge(
        RoutedRequest(exact_route), SimpleNamespace(id=shared_challenge.id + 1)
    )
    assert supplied is True
    assert resolved is None
exact_dojo_challenges.from_id.assert_called_with(
    "public-dojo", "public-module", "public-reference"
)

partial_route = {{"dojo_id": "public-dojo"}}
with patch.object(dojo_plugin, "dojo_accessible") as accessible:
    assert dojo_plugin.get_request_dojo_challenge(
        RoutedRequest(partial_route), shared_challenge
    ) == (None, True)
accessible.assert_not_called()

malformed_routes = (
    dict(exact_route, dojo_id="public-dojo~nothex"),
    dict(exact_route, dojo_id="public-dojo~0000000"),
    dict(exact_route, module_id=7),
    dict(exact_route, module_id="UPPERCASE"),
    dict(exact_route, challenge_reference_id=None),
    dict(exact_route, challenge_reference_id="challenge/reference"),
)
with patch.object(dojo_plugin, "dojo_accessible") as accessible:
    for malformed_route in malformed_routes:
        assert dojo_plugin.get_request_dojo_challenge(
            RoutedRequest(malformed_route), shared_challenge
        ) == (None, True)
accessible.assert_not_called()

noncanonical_route = dict(exact_route, dojo_id="public-dojo~00000001")
with patch.object(dojo_plugin, "dojo_accessible", return_value=public_dojo):
    assert dojo_plugin.get_request_dojo_challenge(
        RoutedRequest(noncanonical_route), shared_challenge
    ) == (None, True)

tampered_route = dict(exact_route, challenge_reference_id="missing-reference")
missing_query = ExactAssociationQuery(None)
with (
    patch.object(dojo_plugin, "dojo_accessible", return_value=public_dojo),
    patch.object(
        dojo_plugin,
        "DojoChallenges",
        SimpleNamespace(
            from_id=MagicMock(return_value=missing_query),
            visible=MagicMock(return_value=True),
        ),
    ),
):
    assert dojo_plugin.get_request_dojo_challenge(
        RoutedRequest(tampered_route), shared_challenge
    ) == (None, True)

for invalid_route in (
    partial_route,
    *malformed_routes,
    noncanonical_route,
    tampered_route,
):
    with (
        patch.object(BaseChallenge, "solve"),
        patch.object(dojo_plugin, "dojo_accessible", return_value=public_dojo),
        patch.object(
            dojo_plugin,
            "DojoChallenges",
            SimpleNamespace(
                from_id=MagicMock(return_value=missing_query),
                visible=MagicMock(return_value=True),
            ),
        ),
        patch.object(dojo_plugin, "get_current_dojo_challenge", return_value=public_association) as current_challenge,
        patch.object(dojo_plugin, "update_awards"),
        patch.object(dojo_plugin, "publish_challenge_solve") as publish_solve,
    ):
        dojo_plugin.DojoChallenge.solve(
            shared_user, None, shared_challenge, RoutedRequest(invalid_route)
        )
    current_challenge.assert_not_called()
    publish_solve.assert_not_called()

with (
    patch.object(BaseChallenge, "solve") as base_solve,
    patch.object(
        dojo_plugin,
        "update_awards",
        side_effect=RuntimeError("award update failure"),
    ) as award_update,
    patch.object(dojo_plugin, "publish_challenge_solve") as publish_solve,
):
    try:
        dojo_plugin.DojoChallenge.solve(
            shared_user,
            None,
            shared_challenge,
            RoutedRequest(exact_route),
        )
    except RuntimeError as error:
        assert str(error) == "award update failure"
    else:
        raise AssertionError("Award update failure did not preserve native semantics")
base_solve.assert_called_once()
award_update.assert_called_once_with(shared_user)
publish_solve.assert_not_called()

app = current_app._get_current_object()
attribution_failures = (
    ("transport", RequestsConnectionError("container transport failure")),
    ("decoding", json.JSONDecodeError("container response failure", "", 0)),
    ("unexpected", RuntimeError("unexpected container lookup failure")),
)
for failure_name, failure in attribution_failures:
    attribution_user_name = (
        f"attribution-{{failure_name}}-{{payload['user_name']}}"
    )
    attribution_user = Users(
        name=attribution_user_name,
        email=f"{{attribution_user_name}}@example.com",
        password=f"password-{{payload['user_name']}}",
    )
    db.session.add(attribution_user)
    db.session.commit()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["id"] = attribution_user.id
            session["nonce"] = generate_nonce()
            session["hash"] = hmac(attribution_user.password)
            csrf_token = session["nonce"]
        attribution_flag = serialize_user_flag(
            attribution_user.account_id,
            challenge.challenge_id,
        )
        with (
            patch.object(
                dojo_plugin,
                "get_current_dojo_challenge",
                side_effect=failure,
            ) as current_challenge,
            patch.object(dojo_plugin, "publish_challenge_solve") as publish_solve,
        ):
            response = client.post(
                "/api/v1/challenges/attempt",
                json={{
                    "challenge_id": challenge.challenge_id,
                    "submission": attribution_flag,
                }},
                headers={{"CSRF-Token": csrf_token}},
            )
        assert response.status_code == 200
        assert response.get_json()["data"]["status"] == "correct"
        current_challenge.assert_called_once()
        assert current_challenge.call_args.args[0].id == attribution_user.id
        publish_solve.assert_not_called()
        assert Solves.query.filter_by(
            user_id=attribution_user.id,
            challenge_id=challenge.challenge_id,
        ).count() == 1
        assert not [
            event for event in feed.get_recent_events(limit=FEED_MAX_EVENTS)
            if event["type"] == "challenge_solve"
            and event["user_name"] == attribution_user_name
        ]

        response = client.post(
            "/api/v1/challenges/attempt",
            json={{
                "challenge_id": challenge.challenge_id,
                "submission": attribution_flag,
            }},
            headers={{"CSRF-Token": csrf_token}},
        )
        assert response.status_code == 200
        assert response.get_json()["data"]["status"] == "already_solved"

exact_native_route = {{
    "dojo_id": challenge.dojo.reference_id,
    "module_id": challenge.module.id,
    "challenge_reference_id": challenge.id,
}}
request_resolver_probe = MagicMock(
    side_effect=RuntimeError("request resolver failure")
)
access_probe = MagicMock(side_effect=RuntimeError("dojo access failure"))
association_query_probe = MagicMock(
    side_effect=RuntimeError("association query failure")
)
first_blood_query = MagicMock()
first_blood_query.filter_by.side_effect = RuntimeError("first blood query failure")
decoration_probe = MagicMock(side_effect=RuntimeError("decoration failure"))
redis_probe = MagicMock(side_effect=RuntimeError("redis failure"))
publication_probe = MagicMock(side_effect=RuntimeError("publication failure"))
optional_pipeline_failures = (
    (
        "request-resolver",
        patch.object(
            dojo_plugin,
            "get_request_dojo_challenge",
            request_resolver_probe,
        ),
        request_resolver_probe,
    ),
    (
        "access",
        patch.object(dojo_plugin, "dojo_accessible", access_probe),
        access_probe,
    ),
    (
        "association-query",
        patch.object(
            dojo_plugin.DojoChallenges,
            "from_id",
            association_query_probe,
        ),
        association_query_probe,
    ),
    (
        "first-blood",
        patch.object(
            dojo_plugin,
            "Solves",
            SimpleNamespace(query=first_blood_query),
        ),
        first_blood_query.filter_by,
    ),
    (
        "decoration",
        patch.object(feed, "validate_feed_event", decoration_probe),
        decoration_probe,
    ),
    (
        "redis",
        patch.object(feed, "get_redis_client", redis_probe),
        redis_probe,
    ),
    (
        "publication",
        patch.object(
            dojo_plugin,
            "publish_challenge_solve",
            publication_probe,
        ),
        publication_probe,
    ),
)
for failure_name, failure_patch, failure_probe in optional_pipeline_failures:
    failure_user_name = f"optional-{{failure_name}}-{{payload['user_name']}}"
    failure_user = Users(
        name=failure_user_name,
        email=f"{{failure_user_name}}@example.com",
        password=f"password-{{payload['user_name']}}",
    )
    db.session.add(failure_user)
    db.session.commit()
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["id"] = failure_user.id
            session["nonce"] = generate_nonce()
            session["hash"] = hmac(failure_user.password)
            csrf_token = session["nonce"]
        failure_flag = serialize_user_flag(
            failure_user.account_id,
            challenge.challenge_id,
        )
        with failure_patch:
            response = client.post(
                "/api/v1/challenges/attempt",
                json={{
                    "challenge_id": challenge.challenge_id,
                    "submission": failure_flag,
                    **exact_native_route,
                }},
                headers={{"CSRF-Token": csrf_token}},
            )
        assert response.status_code == 200
        assert response.get_json()["data"]["status"] == "correct"
        failure_probe.assert_called()
        assert Solves.query.filter_by(
            user_id=failure_user.id,
            challenge_id=challenge.challenge_id,
        ).count() == 1
        assert not [
            event for event in feed.get_recent_events(limit=FEED_MAX_EVENTS)
            if event["type"] == "challenge_solve"
            and event["user_name"] == failure_user_name
        ]

        response = client.post(
            "/api/v1/challenges/attempt",
            json={{
                "challenge_id": challenge.challenge_id,
                "submission": failure_flag,
                **exact_native_route,
            }},
            headers={{"CSRF-Token": csrf_token}},
        )
        assert response.status_code == 200
        assert response.get_json()["data"]["status"] == "already_solved"

class AmbiguousAssociationQuery:
    def __init__(self, first_association):
        self.first_association = first_association
        self.filter_calls = 0

    def filter_by(self, **kwargs):
        self.filter_calls += 1
        return self

    def first(self):
        return self.first_association

for routed_association, arbitrary_first_association in (
    (private_association, public_association),
    (public_association, private_association),
):
    ambiguous_query = AmbiguousAssociationQuery(arbitrary_first_association)
    solves_query = MagicMock()
    solves_query.filter_by.return_value.count.return_value = 1
    with (
        patch.object(BaseChallenge, "solve"),
        patch.object(dojo_plugin, "DojoChallenges", SimpleNamespace(query=ambiguous_query)),
        patch.object(dojo_plugin, "Solves", SimpleNamespace(query=solves_query)),
        patch.object(dojo_plugin, "get_current_dojo_challenge", return_value=routed_association),
        patch.object(dojo_plugin, "update_awards"),
        patch.object(dojo_plugin, "publish_challenge_solve") as publish_solve,
    ):
        dojo_plugin.DojoChallenge.solve(shared_user, None, shared_challenge, None)
    assert ambiguous_query.filter_calls == 0
    if routed_association is private_association:
        publish_solve.assert_not_called()
    else:
        publish_solve.assert_called_once_with(
            shared_user,
            public_association,
            public_dojo,
            public_module,
            shared_challenge.value,
            True,
        )

class StubPubSub:
    def __init__(self, failure=None):
        self.failure = failure
        self.close_calls = 0
        self.subscribed = False
        self.acknowledged = False

    def subscribe(self, channel):
        if self.failure == "subscribe":
            raise RuntimeError("subscribe failure")
        self.subscribed = True

    def get_message(self, timeout):
        if self.subscribed and not self.acknowledged:
            self.acknowledged = True
            return {{"type": "subscribe"}}
        if self.failure == "message":
            raise RuntimeError("message failure")
        return None

    def close(self):
        self.close_calls += 1

class StubRedis:
    def __init__(self, pubsub):
        self.stub_pubsub = pubsub

    def pubsub(self):
        return self.stub_pubsub

    def xrevrange(self, *args, **kwargs):
        return []

    def xrange(self, *args, **kwargs):
        return []

    def zrevrange(self, *args, **kwargs):
        return []

    def zrevrangebyscore(self, *args, **kwargs):
        return []

immediate_pubsub = StubPubSub()
with patch.object(feed_api.redis, "from_url", return_value=StubRedis(immediate_pubsub)):
    immediate_generator = feed_api.stream_feed_events("redis://stub")
    assert next(immediate_generator).startswith("data: ")
    immediate_generator.close()
    immediate_generator.close()
assert immediate_pubsub.close_calls == 1

subscribe_pubsub = StubPubSub("subscribe")
with patch.object(feed_api.redis, "from_url", return_value=StubRedis(subscribe_pubsub)):
    subscribe_generator = feed_api.stream_feed_events("redis://stub")
    try:
        next(subscribe_generator)
    except RuntimeError as error:
        assert str(error) == "subscribe failure"
    else:
        raise AssertionError("Subscribe failure did not escape the feed generator")
assert subscribe_pubsub.close_calls == 1

message_pubsub = StubPubSub("message")
with patch.object(feed_api.redis, "from_url", return_value=StubRedis(message_pubsub)):
    message_generator = feed_api.stream_feed_events("redis://stub")
    assert next(message_generator).startswith("data: ")
    try:
        next(message_generator)
    except RuntimeError as error:
        assert str(error) == "message failure"
    else:
        raise AssertionError("Message failure did not escape the feed generator")
assert message_pubsub.close_calls == 1

assert feed.normalize_feed_cursor("0001-0002") == "1-2"
assert feed.normalize_feed_cursor("18446744073709551615-0") is not None
assert feed.normalize_feed_cursor("18446744073709551616-0") is None
assert feed.normalize_feed_cursor("1-" + "0" * 21) is None
assert feed.normalize_legacy_feed_cursor("0001.500") == "1.5"
assert feed.normalize_legacy_feed_cursor("nan") is None
assert feed.normalize_legacy_feed_cursor("-1") is None

def make_history_event(event_id):
    return json.dumps({{
        "id": event_id,
        "type": "dojo_update",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "user_name": payload["user_name"],
        "user_belt": None,
        "user_emojis": [],
        "data": {{}},
    }})

def parse_sse_event(message):
    lines = message.strip().splitlines()
    event_id = next(line[4:] for line in lines if line.startswith("id: "))
    data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
    return event_id, data

def cursor_sort_key(cursor):
    return tuple(map(int, cursor.split("-", 1)))

class ReplayPubSub(StubPubSub):
    def __init__(self, on_subscribe=None):
        super().__init__()
        self.on_subscribe = on_subscribe

    def subscribe(self, channel):
        super().subscribe(channel)
        if self.on_subscribe:
            self.on_subscribe()

class ReplayRedis:
    def __init__(self, entries, pubsub):
        self.entries = entries
        self.stub_pubsub = pubsub

    def pubsub(self):
        return self.stub_pubsub

    def xrevrange(self, *args, **kwargs):
        return list(reversed(self.entries[-kwargs.get("count", 1):]))

    def xrange(self, key, min, max, count):
        cursor = min[1:]
        max_cursor = None if max == "+" else cursor_sort_key(max)
        return [
            entry for entry in self.entries
            if cursor_sort_key(entry[0]) > cursor_sort_key(cursor)
            and (
                max_cursor is None
                or cursor_sort_key(entry[0]) <= max_cursor
            )
        ][:count]

    def zrevrange(self, *args, **kwargs):
        return []

    def zrevrangebyscore(self, *args, **kwargs):
        return []

now_milliseconds = int(time.time() * 1000)
snapshot_cursor = f"{{now_milliseconds}}-0"
gap_cursor = f"{{now_milliseconds + 1}}-0"
gap_entry = (
    gap_cursor,
    {{
        b"event": make_history_event("snapshot-subscribe-gap").encode(),
        b"score": str((now_milliseconds + 1) / 1000).encode(),
    }},
)
gap_entries = []
gap_pubsub = ReplayPubSub(on_subscribe=lambda: gap_entries.append(gap_entry))
gap_redis = ReplayRedis(gap_entries, gap_pubsub)
with patch.object(feed_api.redis, "from_url", return_value=gap_redis):
    gap_generator = feed_api.stream_feed_events("redis://stub", snapshot_cursor)
    connected = json.loads(next(gap_generator).split("data: ", 1)[1])
    assert connected["cursor"] == snapshot_cursor
    gap_event_id, gap_event = parse_sse_event(next(gap_generator))
    assert gap_event_id == gap_cursor
    assert gap_event["id"] == "snapshot-subscribe-gap"
    assert gap_event["cursor"] == gap_cursor
    gap_generator.close()
assert gap_pubsub.close_calls == 1

malformed_cursor = f"{{now_milliseconds + 2}}-0"
replay_cursor_1 = f"{{now_milliseconds + 3}}-0"
replay_cursor_2 = f"{{now_milliseconds + 4}}-0"
gap_entries.extend([
    (malformed_cursor, {{
        b"event": b"malformed",
        b"score": str((now_milliseconds + 2) / 1000).encode(),
    }}),
    (
        replay_cursor_1,
        {{
            b"event": make_history_event("disconnected-1").encode(),
            b"score": str((now_milliseconds + 3) / 1000).encode(),
        }},
    ),
    (
        replay_cursor_2,
        {{
            b"event": make_history_event("disconnected-2").encode(),
            b"score": str((now_milliseconds + 4) / 1000).encode(),
        }},
    ),
])
replay_pubsub = ReplayPubSub()
with patch.object(
    feed_api.redis,
    "from_url",
    return_value=ReplayRedis(gap_entries, replay_pubsub),
):
    replay_generator = feed_api.stream_feed_events("redis://stub", gap_cursor)
    assert json.loads(next(replay_generator).split("data: ", 1)[1])["cursor"] == gap_cursor
    replay_events = [parse_sse_event(next(replay_generator)) for _ in range(2)]
    replay_generator.close()
assert [event_id for event_id, _ in replay_events] == [
    replay_cursor_1,
    replay_cursor_2,
]
assert [event["id"] for _, event in replay_events] == [
    "disconnected-1",
    "disconnected-2",
]
assert replay_pubsub.close_calls == 1

class QueuePubSub(StubPubSub):
    def __init__(self, messages=None, on_subscribe=None, on_message=None):
        super().__init__()
        self.messages = list(messages or [])
        self.on_subscribe = on_subscribe
        self.on_message = on_message

    def subscribe(self, channel):
        super().subscribe(channel)
        if self.on_subscribe:
            self.on_subscribe()

    def get_message(self, timeout):
        if not self.acknowledged:
            return super().get_message(timeout)
        if not self.messages:
            return None
        raw_event = self.messages.pop(0)
        if self.on_message:
            self.on_message(raw_event)
        return {{"type": "message", "data": raw_event}}

class HybridRedis:
    def __init__(self, cursor_base):
        self.cursor_base = cursor_base
        self.cursor_sequence = 0
        self.stream_entries = []
        self.legacy_entries = []
        self.event_cursors = {{}}
        self.migrated_event_ids = []
        self.before_migrate = None
        self.stub_pubsub = QueuePubSub()

    @staticmethod
    def raw_bytes(raw_event):
        return raw_event.encode() if isinstance(raw_event, str) else raw_event

    def pubsub(self):
        return self.stub_pubsub

    def xrevrange(self, key, max, min, count):
        return list(reversed(self.stream_entries[-count:]))

    def xrange(self, key, min, max, count):
        cursor = min[1:]
        max_cursor = None if max == "+" else cursor_sort_key(max)
        return [
            entry for entry in self.stream_entries
            if cursor_sort_key(entry[0]) > cursor_sort_key(cursor)
            and (
                max_cursor is None
                or cursor_sort_key(entry[0]) <= max_cursor
            )
        ][:count]

    def zrevrange(self, key, start, end, withscores):
        rows = sorted(self.legacy_entries, key=lambda row: row[1], reverse=True)
        return rows[start:end + 1]

    def zrevrangebyscore(self, key, max, min, start, num, withscores):
        rows = [
            row for row in self.legacy_entries
            if row[1] >= float(min)
        ]
        return sorted(rows, key=lambda row: row[1], reverse=True)[start:start + num]

    def zscore(self, key, raw_event):
        raw_event = self.raw_bytes(raw_event)
        for candidate, score in self.legacy_entries:
            if self.raw_bytes(candidate) == raw_event:
                return score
        return None

    def eval(self, script, key_count, *args):
        assert script == feed.MIGRATE_FEED_EVENT_SCRIPT
        assert key_count == 3
        event_id = args[3]
        occurrence_score = args[4]
        assert float(occurrence_score) >= 0
        self.migrated_event_ids.append(event_id)
        if event_id in self.event_cursors:
            return [self.event_cursors[event_id].encode(), 0]
        if self.before_migrate is not None:
            before_migrate = self.before_migrate
            self.before_migrate = None
            before_migrate()
        self.cursor_sequence += 1
        cursor = f"{{self.cursor_base + self.cursor_sequence}}-0"
        self.event_cursors[event_id] = cursor
        return [cursor.encode(), 1]

subscription_gap_event = make_history_event("subscription-ack-gap")
subscription_gap_redis = HybridRedis(now_milliseconds + 50)
subscription_gap_pubsub = QueuePubSub()
subscription_gap_redis.stub_pubsub = subscription_gap_pubsub
subscription_gap_injected = False

def inject_subscription_gap(*args, **kwargs):
    global subscription_gap_injected
    assert subscription_gap_pubsub.acknowledged
    if not subscription_gap_injected:
        subscription_gap_injected = True
        subscription_gap_pubsub.messages.append(subscription_gap_event)
    return []

subscription_gap_redis.zrevrangebyscore = inject_subscription_gap
with patch.object(
    feed_api.redis,
    "from_url",
    return_value=subscription_gap_redis,
):
    subscription_gap_generator = feed_api.stream_feed_events(
        "redis://stub",
        "0-0",
        "0.0",
    )
    next(subscription_gap_generator)
    subscription_gap_delivery = parse_sse_event(
        next(subscription_gap_generator)
    )
    subscription_gap_generator.close()
assert subscription_gap_delivery[1]["id"] == "subscription-ack-gap"
assert subscription_gap_pubsub.close_calls == 1

class TerminalCursorRedis:
    def __init__(self):
        self.xrange_calls = 0

    def xrange(self, *args, **kwargs):
        self.xrange_calls += 1
        raise AssertionError("Terminal cursor reached Redis XRANGE")

terminal_cursor_redis = TerminalCursorRedis()
terminal_cursor = (
    f"{{feed.MAX_REDIS_STREAM_ID_COMPONENT}}-"
    f"{{feed.MAX_REDIS_STREAM_ID_COMPONENT}}"
)
assert feed.get_feed_entries_after(terminal_cursor_redis, terminal_cursor) == []
assert terminal_cursor_redis.xrange_calls == 0

visibility_redis = HybridRedis(now_milliseconds + 75)
visibility_redis.cursor_sequence = 1
invisible_stream_event = make_history_event("invisible-stream")
invisible_legacy_event = make_history_event("invisible-legacy")
visible_live_event = make_history_event("visible-live-after-hidden")
visibility_redis.stream_entries.append((
    f"{{now_milliseconds + 76}}-0",
    {{
        b"event": invisible_stream_event.encode(),
        b"score": str((now_milliseconds + 76) / 1000).encode(),
    }},
))
visibility_redis.legacy_entries.append(
    (invisible_legacy_event, (now_milliseconds + 77) / 1000)
)
visibility_pubsub = QueuePubSub([visible_live_event])
visibility_redis.stub_pubsub = visibility_pubsub
with (
    patch.object(
        feed_api,
        "filter_visible_feed_events",
        side_effect=lambda events: [
            event for event in events
            if not event["id"].startswith("invisible-")
        ],
    ),
    patch.object(feed_api.redis, "from_url", return_value=visibility_redis),
):
    visibility_generator = feed_api.stream_feed_events(
        "redis://stub",
        "0-0",
        "0.0",
    )
    next(visibility_generator)
    visible_delivery = parse_sse_event(next(visibility_generator))
    visibility_generator.close()
assert visible_delivery[1]["id"] == "visible-live-after-hidden"
assert "invisible-legacy" not in visibility_redis.migrated_event_ids
assert "visible-live-after-hidden" in visibility_redis.migrated_event_ids
assert visibility_pubsub.close_calls == 1

def run_zero_retention_replay(max_events, ttl, prefix):
    raw_events = [
        make_history_event(f"{{prefix}}-{{index}}")
        for index in range(3)
    ]
    hybrid_redis = HybridRedis(now_milliseconds + 100)
    first_pubsub = QueuePubSub([raw_events[0], raw_events[0], raw_events[1]])
    hybrid_redis.stub_pubsub = first_pubsub
    with (
        patch.object(feed_config, "FEED_MAX_EVENTS", max_events),
        patch.object(feed_config, "FEED_EVENT_TTL", ttl),
        patch.object(feed_api.redis, "from_url", return_value=hybrid_redis),
    ):
        generator = feed_api.stream_feed_events(
            "redis://stub",
            "0-0",
            "0.0",
        )
        next(generator)
        delivered = [parse_sse_event(next(generator)) for _ in range(2)]
        generator.close()
    assert [event["id"] for _, event in delivered] == [
        f"{{prefix}}-0",
        f"{{prefix}}-1",
    ]
    assert hybrid_redis.stream_entries == []
    assert first_pubsub.close_calls == 1

    reconnect_pubsub = QueuePubSub([raw_events[1], raw_events[2]])
    hybrid_redis.stub_pubsub = reconnect_pubsub
    with (
        patch.object(feed_config, "FEED_MAX_EVENTS", max_events),
        patch.object(feed_config, "FEED_EVENT_TTL", ttl),
        patch.object(feed_api.redis, "from_url", return_value=hybrid_redis),
    ):
        reconnect_generator = feed_api.stream_feed_events(
            "redis://stub",
            delivered[-1][0],
            "0.0",
        )
        next(reconnect_generator)
        reconnected = parse_sse_event(next(reconnect_generator))
        reconnect_generator.close()
    assert reconnected[1]["id"] == f"{{prefix}}-2"
    assert reconnect_pubsub.close_calls == 1

run_zero_retention_replay(0, 86_400, "zero-max")
run_zero_retention_replay(10, 0, "zero-ttl")

mixed_redis = HybridRedis(now_milliseconds + 200)
legacy_score = time.time()
legacy_boundary = make_history_event("legacy-boundary")
legacy_gap = make_history_event("legacy-handoff-gap")
legacy_live = make_history_event("legacy-live-fallback")
legacy_disconnected = make_history_event("legacy-disconnected")
mixed_redis.legacy_entries.append((legacy_boundary, legacy_score))
mixed_pubsub = QueuePubSub(
    [legacy_gap, legacy_live],
    on_subscribe=lambda: mixed_redis.legacy_entries.append(
        (legacy_gap, legacy_score + 1)
    ),
)
mixed_redis.stub_pubsub = mixed_pubsub
with patch.object(feed_api.redis, "from_url", return_value=mixed_redis):
    mixed_generator = feed_api.stream_feed_events(
        "redis://stub",
        "0-0",
        repr(legacy_score),
    )
    next(mixed_generator)
    mixed_delivered = [parse_sse_event(next(mixed_generator)) for _ in range(3)]
    mixed_generator.close()
assert [event["id"] for _, event in mixed_delivered] == [
    "legacy-boundary",
    "legacy-handoff-gap",
    "legacy-live-fallback",
]
assert mixed_pubsub.close_calls == 1

mixed_redis.legacy_entries.extend([
    ("malformed-legacy", legacy_score + 2),
    (legacy_disconnected, legacy_score + 3),
])
mixed_reconnect_pubsub = QueuePubSub()
mixed_redis.stub_pubsub = mixed_reconnect_pubsub
with patch.object(feed_api.redis, "from_url", return_value=mixed_redis):
    mixed_reconnect_generator = feed_api.stream_feed_events(
        "redis://stub",
        mixed_delivered[-1][0],
        repr(legacy_score + 1),
    )
    next(mixed_reconnect_generator)
    mixed_reconnected = parse_sse_event(next(mixed_reconnect_generator))
    mixed_reconnect_generator.close()
assert mixed_reconnected[1]["id"] == "legacy-disconnected"
assert mixed_reconnected[1]["legacy_cursor"] == repr(legacy_score + 3)
assert mixed_reconnect_pubsub.close_calls == 1

reconciled_redis = HybridRedis(now_milliseconds + 300)
reconciled_legacy = make_history_event("reconciled-legacy")
reconciled_new = make_history_event("reconciled-new")
reconciled_legacy_score = time.time()
reconciled_pubsub = QueuePubSub(
    [reconciled_legacy],
    on_message=lambda raw_event: reconciled_redis.legacy_entries.append(
        (raw_event, reconciled_legacy_score)
    ),
)
reconciled_redis.stub_pubsub = reconciled_pubsub

def publish_new_before_legacy_migration():
    reconciled_redis.cursor_sequence += 1
    new_cursor = f"{{reconciled_redis.cursor_base + reconciled_redis.cursor_sequence}}-0"
    reconciled_redis.event_cursors["reconciled-new"] = new_cursor
    reconciled_redis.stream_entries.append(
        (new_cursor, {{
            b"event": reconciled_new.encode(),
            b"score": str((now_milliseconds + 301) / 1000).encode(),
        }})
    )
    reconciled_pubsub.messages.append(reconciled_new)

reconciled_redis.before_migrate = publish_new_before_legacy_migration
with patch.object(feed_api.redis, "from_url", return_value=reconciled_redis):
    reconciled_generator = feed_api.stream_feed_events(
        "redis://stub",
        "0-0",
        "0.0",
    )
    next(reconciled_generator)
    reconciled_first = parse_sse_event(next(reconciled_generator))
    reconciled_generator.close()
assert reconciled_first[1]["id"] == "reconciled-new"
assert reconciled_pubsub.close_calls == 1

reconciled_reconnect_pubsub = QueuePubSub()
reconciled_redis.stub_pubsub = reconciled_reconnect_pubsub
with patch.object(feed_api.redis, "from_url", return_value=reconciled_redis):
    reconciled_reconnect_generator = feed_api.stream_feed_events(
        "redis://stub",
        reconciled_first[0],
        "0.0",
    )
    next(reconciled_reconnect_generator)
    reconciled_second = parse_sse_event(next(reconciled_reconnect_generator))
    reconciled_reconnect_generator.close()
assert reconciled_second[1]["id"] == "reconciled-legacy"
assert cursor_sort_key(reconciled_second[0]) > cursor_sort_key(reconciled_first[0])
assert reconciled_reconnect_pubsub.close_calls == 1

ordered_redis = HybridRedis(now_milliseconds + 400)
ordered_new_1 = make_history_event("ordered-new-1")
ordered_legacy = make_history_event("ordered-legacy")
ordered_new_2 = make_history_event("ordered-new-2")
ordered_redis.cursor_sequence = 2
ordered_redis.event_cursors.update({{
    "ordered-new-1": f"{{now_milliseconds + 301}}-0",
    "ordered-new-2": f"{{now_milliseconds + 302}}-0",
}})
ordered_pubsub = QueuePubSub([
    ordered_new_1,
    ordered_legacy,
    ordered_new_2,
])
ordered_redis.stub_pubsub = ordered_pubsub
with patch.object(feed_api.redis, "from_url", return_value=ordered_redis):
    ordered_generator = feed_api.stream_feed_events(
        "redis://stub",
        "0-0",
        "0.0",
    )
    next(ordered_generator)
    ordered_events = [parse_sse_event(next(ordered_generator)) for _ in range(3)]
    ordered_generator.close()
assert [event["id"] for _, event in ordered_events] == [
    "ordered-new-1",
    "ordered-legacy",
    "ordered-new-2",
]
assert [cursor_sort_key(cursor) for cursor, _ in ordered_events] == sorted(
    cursor_sort_key(cursor) for cursor, _ in ordered_events
)
assert ordered_pubsub.close_calls == 1

class HistoryPipeline:
    def __init__(self, redis_client):
        self.redis_client = redis_client

    def xrevrange(self, key, max, min, count):
        self.redis_client.calls.append(("xrevrange", key, max, min, count))
        return self

    def zrevrange(self, key, start, end, withscores):
        self.redis_client.calls.append(
            ("zrevrange", key, start, end, withscores)
        )
        return self

    def execute(self):
        self.redis_client.calls.append(("execute",))
        return self.redis_client.stream_rows, self.redis_client.legacy_rows

class HistoryRedis:
    def __init__(self, stream_rows, legacy_rows):
        self.stream_rows = stream_rows
        self.legacy_rows = legacy_rows
        self.calls = []

    def pipeline(self, transaction):
        self.calls.append(("pipeline", transaction))
        return HistoryPipeline(self)

latest_history_cursor = f"{{now_milliseconds + 10}}-0"
history_stream_rows = [
    (latest_history_cursor, {{b"event": b"\\xff"}}),
    (
        f"{{now_milliseconds + 9}}-0",
        {{
            b"event": make_history_event("history-0").encode(),
            b"score": str((now_milliseconds + 8) / 1000).encode(),
        }},
    ),
    (
        f"{{now_milliseconds + 8}}-0",
        {{
            b"event": make_history_event("history-old-fresh-cursor").encode(),
            b"score": str((now_milliseconds + 4) / 1000).encode(),
        }},
    ),
    (
        f"{{now_milliseconds + 5}}-0",
        {{
            b"event": make_history_event("history-2").encode(),
            b"score": str((now_milliseconds + 5) / 1000).encode(),
        }},
    ),
]
history_legacy_rows = [
    (make_history_event("history-0"), (now_milliseconds + 8) / 1000),
    (make_history_event("history-1"), (now_milliseconds + 7) / 1000),
    ("malformed-between", (now_milliseconds + 6) / 1000),
    (make_history_event("malformed-score"), float("inf")),
]

def history_ids(limit, offset):
    history_redis = HistoryRedis(history_stream_rows, history_legacy_rows)
    with patch.object(feed, "get_redis_client", return_value=history_redis):
        events, cursor, legacy_cursor = feed.get_feed_snapshot(
            limit=limit,
            offset=offset,
        )
    assert cursor == latest_history_cursor
    assert legacy_cursor == repr((now_milliseconds + 8) / 1000)
    assert history_redis.calls == [
        ("pipeline", True),
        (
            "xrevrange",
            feed.FEED_STREAM_KEY,
            "+",
            "-",
            FEED_MAX_EVENTS,
        ),
        (
            "zrevrange",
            feed.LEGACY_FEED_EVENTS_KEY,
            0,
            FEED_MAX_EVENTS - 1,
            True,
        ),
        ("execute",),
    ]
    return [event["id"] for event in events]

assert history_ids(1, 0) == ["history-0"]
assert history_ids(1, 1) == ["history-1"]
assert history_ids(1, 2) == ["history-2"]
assert history_ids(1, 3) == ["history-old-fresh-cursor"]
assert history_ids(2, 0) == ["history-0", "history-1"]
assert history_ids(2, 1) == ["history-1", "history-2"]
assert history_ids(4, 0) == [
    "history-0",
    "history-1",
    "history-2",
    "history-old-fresh-cursor",
]

legacy_only_redis = HistoryRedis([], [
    (make_history_event("legacy-newer"), (now_milliseconds + 2) / 1000),
    (make_history_event("legacy-older"), (now_milliseconds + 1) / 1000),
])
with patch.object(feed, "get_redis_client", return_value=legacy_only_redis):
    legacy_events, stream_cursor, legacy_cursor = feed.get_feed_snapshot(limit=2)
assert [event["id"] for event in legacy_events] == ["legacy-newer", "legacy-older"]
assert stream_cursor == "0-0"
assert legacy_cursor == repr((now_milliseconds + 2) / 1000)

near_expiry_now = now_milliseconds / 1000
near_expiry_score = near_expiry_now - 9.5
near_expiry_raw = make_history_event("near-expiry-original-age")
with (
    patch.object(feed_config, "FEED_EVENT_TTL", 10),
    patch.object(feed.time, "time", return_value=near_expiry_now),
    patch.object(
        feed,
        "get_redis_client",
        return_value=HistoryRedis([], [(near_expiry_raw, near_expiry_score)]),
    ),
):
    near_expiry_events, _, _ = feed.get_feed_snapshot(limit=1)
assert [event["id"] for event in near_expiry_events] == [
    "near-expiry-original-age"
]
with (
    patch.object(feed_config, "FEED_EVENT_TTL", 10),
    patch.object(feed.time, "time", return_value=near_expiry_now + 1),
    patch.object(
        feed,
        "get_redis_client",
        return_value=HistoryRedis([], [(near_expiry_raw, near_expiry_score)]),
    ),
):
    expired_events, _, _ = feed.get_feed_snapshot(limit=1)
assert expired_events == []

all_malformed_redis = HistoryRedis(
    [
        (
            f"{{now_milliseconds + index}}-0",
            {{b"event": b"malformed"}},
        )
        for index in range(FEED_MAX_EVENTS)
    ],
    [
        (f"all-malformed-{{index}}", (now_milliseconds - index) / 1000)
        for index in range(FEED_MAX_EVENTS)
    ],
)
with patch.object(feed, "get_redis_client", return_value=all_malformed_redis):
    assert feed.get_recent_events(limit=1) == []
assert all_malformed_redis.calls[-1] == ("execute",)
print("FEED_TEST_DATA=" + json.dumps({{
    "challenge_id": challenge.challenge_id,
    "dojo_reference_id": challenge.dojo.reference_id,
    "user_id": user.id,
}}))
"""
    encoded = base64.b64encode(code.encode()).decode()
    result = dojo_run("dojo", "flask", input=f'import base64; exec(base64.b64decode("{encoded}").decode())\n')
    match = re.search(r"FEED_TEST_DATA=(\{[^\r\n]+\})", result.stdout)
    assert match, f"Feed test data not found in dojo flask output: {result.stdout}"
    data = json.loads(match.group(1))
    return data["dojo_reference_id"], data["challenge_id"], data["user_id"]


def submit_browser_challenge(
    dojo_id,
    module_id,
    challenge_reference_id,
    challenge_id,
    submission,
    *,
    session,
    expected_status,
    route_data=None,
):
    payload = {
        "challenge_id": challenge_id,
        "submission": submission,
    }
    payload.update(
        route_data
        if route_data is not None
        else {
            "dojo_id": dojo_id,
            "module_id": module_id,
            "challenge_reference_id": challenge_reference_id,
        }
    )
    response = session.post(
        f"{DOJO_URL.rstrip('/')}/api/v1/challenges/attempt",
        json=payload,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is True
    assert result["data"]["status"] == expected_status
    assert isinstance(result["data"]["message"], str)
    return result


def get_user_feed_event(user_name, event_type):
    response = requests.get(f"{DOJO_URL.rstrip('/')}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    matches = [
        event for event in response.json()["data"]
        if event["type"] == event_type and event["user_name"] == user_name
    ]
    assert matches, f"No {event_type} feed event found for {user_name}"
    return matches[0]


def assert_production_challenge_event(event, dojo_id, mode=None):
    data = event["data"]
    assert isinstance(data["challenge_id"], int)
    assert data["challenge_reference_id"] == "flag"
    assert data["module_id"] == "welcome"
    assert data["dojo_id"] == dojo_id
    if mode is not None:
        assert data["mode"] == mode


def make_feed_events(prefix, dojo_id, challenge_id, fallback_types, legacy_challenge_types=frozenset()):
    def dojo_name(event_type):
        return None if event_type in fallback_types else f"{prefix} {event_type}"

    events = [
        {
            "type": "container_start",
            "data": {
                "mode": "standard",
                "dojo_id": dojo_id,
                "dojo_name": dojo_name("container_start"),
                "module_id": "welcome",
                "module_name": f"{prefix} module start",
                "challenge_id": challenge_id,
                "challenge_name": f"{prefix} challenge start",
            },
        },
        {
            "type": "challenge_solve",
            "data": {
                "dojo_id": dojo_id,
                "dojo_name": dojo_name("challenge_solve"),
                "module_id": "welcome",
                "module_name": f"{prefix} module solve",
                "challenge_id": challenge_id,
                "challenge_name": f"{prefix} challenge solve",
                "first_blood": False,
            },
        },
        {
            "type": "emoji_earned",
            "data": {
                "emoji": "🧪",
                "dojo_id": dojo_id,
                "dojo_name": dojo_name("emoji_earned"),
                "reason": f"{prefix} emoji reason",
            },
        },
        {
            "type": "belt_earned",
            "data": {
                "belt": "orange",
                "belt_name": f"{prefix} belt",
                "dojo_id": dojo_id,
                "dojo_name": dojo_name("belt_earned"),
            },
        },
        {
            "type": "dojo_update",
            "data": {
                "dojo_id": dojo_id,
                "dojo_name": dojo_name("dojo_update"),
                "summary": f"{prefix} update summary",
                "changes": {},
            },
        },
    ]
    for event in events[:2]:
        if event["type"] not in legacy_challenge_types:
            event["data"]["challenge_reference_id"] = "flag"
    return events


def make_partial_feed_events(prefix, dojo_id, challenge_id):
    events = make_feed_events(prefix, dojo_id, challenge_id, set())
    events[0]["data"].pop("dojo_id")
    events[1]["data"].pop("module_id")
    for event in events[2:]:
        event["data"].pop("dojo_id")

    for event in events:
        event["data"]["dojo_name"] = f'{prefix} {event["type"]} {XSS_PAYLOAD}'
    events[0]["data"]["module_name"] = f"{prefix} module {XSS_PAYLOAD}"
    events[0]["data"]["challenge_name"] = f"{prefix} challenge {XSS_PAYLOAD}"
    events[1]["data"]["module_name"] = f"{prefix} module {XSS_PAYLOAD}"
    events[1]["data"]["challenge_name"] = f"{prefix} challenge {XSS_PAYLOAD}"
    events[2]["data"]["emoji"] = XSS_PAYLOAD
    events[3]["data"]["belt_name"] = XSS_PAYLOAD
    events[4]["data"]["summary"] = XSS_PAYLOAD
    return events


def make_identifier_feed_events(
    prefix,
    dojo_id,
    module_id,
    challenge_reference_id,
    challenge_id,
    *,
    names,
):
    events = make_feed_events(prefix, dojo_id, challenge_id, set())
    for event in events:
        event["data"]["dojo_id"] = dojo_id
        if not names:
            event["data"].pop("dojo_name")
    for event in events[:2]:
        event["data"]["module_id"] = module_id
        event["data"]["challenge_reference_id"] = challenge_reference_id
        if not names:
            event["data"].pop("module_name")
            event["data"].pop("challenge_name")
    return events


def feed_subscriber_count():
    result = dojo_run(
        "docker", "exec", "cache", "redis-cli", "--raw", "PUBSUB", "NUMSUB", "activity_feed:live"
    )
    return int(result.stdout.strip().splitlines()[-1])


def database_transaction_counts():
    counts = db_sql("""
SELECT
    count(*) FILTER (WHERE state = 'active'),
    count(*) FILTER (WHERE state = 'idle in transaction')
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid()
""").strip()
    return tuple(map(int, counts.split("|")))


def minimum_database_transaction_counts(samples=10):
    counts = []
    for _ in range(samples):
        counts.append(database_transaction_counts())
        time.sleep(0.1)
    return tuple(min(values) for values in zip(*counts, strict=True))


def next_feed_stream_data(lines, event_id=None):
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode()
        if not line.startswith("data: "):
            continue
        data = json.loads(line[6:])
        if event_id is None or data.get("id") == event_id:
            return data
    raise AssertionError("Activity feed stream closed before the expected event")


def set_dojo_password(dojo_id, password):
    payload = base64.b64encode(json.dumps({
        "dojo_id": dojo_id,
        "password": password,
    }).encode()).decode()
    code = f"""
import base64
import json

from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import Dojos

payload = json.loads(base64.b64decode("{payload}"))
dojo = Dojos.from_id(payload["dojo_id"]).one()
dojo.password = payload["password"]
db.session.commit()
"""
    encoded = base64.b64encode(code.encode()).decode()
    dojo_run(
        "dojo",
        "flask",
        input=f'import base64; exec(base64.b64decode("{encoded}").decode())\n',
    )


def internal_url(url_root, *segments):
    return f'{url_root.rstrip("/")}/' + "/".join(quote(str(segment), safe="-._~") for segment in segments)


def feed_url(url_root, dojo_id, module_id=None, challenge_reference_id=None):
    segments = [dojo_id]
    if module_id is not None:
        segments.append(module_id)
    if challenge_reference_id is not None:
        segments.append(challenge_reference_id)
    return internal_url(url_root, *segments)


def normalized_text(value):
    return " ".join(str(value).split())


def canonical_dojo_reference(value):
    return isinstance(value, str) and DOJO_REFERENCE_PATTERN.fullmatch(value) is not None


def canonical_content_id(value):
    return isinstance(value, str) and CONTENT_ID_PATTERN.fullmatch(value) is not None


def normalized_label(*values):
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


def location_expectations(data, url_root):
    linked = []
    unlinked = []
    dojo_label = normalized_label(data.get("dojo_name"), data.get("dojo_id"))
    if dojo_label is not None:
        if canonical_dojo_reference(data.get("dojo_id")):
            linked.append((dojo_label, feed_url(url_root, data["dojo_id"])))
        else:
            unlinked.append(dojo_label)

    module_label = normalized_label(data.get("module_name"), data.get("module_id"))
    if module_label is not None:
        if canonical_dojo_reference(data.get("dojo_id")) and canonical_content_id(data.get("module_id")):
            linked.append((module_label, feed_url(url_root, data["dojo_id"], data["module_id"])))
        else:
            unlinked.append(module_label)

    challenge_label = normalized_label(
        data.get("challenge_name"),
        data.get("challenge_reference_id"),
        data.get("challenge_id"),
    )
    if challenge_label is not None:
        if (
            canonical_dojo_reference(data.get("dojo_id"))
            and canonical_content_id(data.get("module_id"))
            and canonical_content_id(data.get("challenge_reference_id"))
        ):
            linked.append((
                challenge_label,
                feed_url(url_root, data["dojo_id"], data["module_id"], data["challenge_reference_id"]),
            ))
        else:
            unlinked.append(challenge_label)
    return linked, unlinked


def valid_user_id(user_id):
    return (
        isinstance(user_id, int)
        and not isinstance(user_id, bool)
        and 1 <= user_id <= MAX_SAFE_USER_ID
    )


def find_browser_card(browser, event_id):
    return browser.execute_script("""
        return Array.from(document.querySelectorAll('[data-event-id]'))
            .find(card => card.dataset.eventId === arguments[0]) || null;
    """, event_id)


def assert_browser_card(browser, event, event_id, user_name, user_id, url_root=""):
    card = WebDriverWait(browser, 10).until(
        lambda driver: find_browser_card(driver, event_id)
    )
    links = card.find_elements(By.TAG_NAME, "a")
    images = card.find_elements(By.TAG_NAME, "img")
    expected_filter_id = str(user_id) if valid_user_id(user_id) else ""
    assert card.get_attribute("data-user-id") == expected_filter_id
    assert float(card.get_attribute("data-feed-score")) >= 0
    belt_url = urljoin(browser.current_url, internal_url(url_root, "belt", f"{FEED_TEST_BELT}.svg"))
    assert len([image for image in images if image.get_attribute("src") == belt_url]) == 1
    if valid_user_id(user_id):
        profile_url = urljoin(browser.current_url, internal_url(url_root, "hacker", user_id))
        wrong_profile_url = urljoin(browser.current_url, internal_url(url_root, "hacker", user_name))
        assert len([link for link in links if link.get_attribute("href") == profile_url]) == 1
        if profile_url != wrong_profile_url:
            assert not [link for link in links if link.get_attribute("href") == wrong_profile_url]
    else:
        assert not [link for link in links if normalized_text(link.text) == normalized_text(user_name)]
        assert normalized_text(user_name) in normalized_text(card.text)

    linked, unlinked = location_expectations(event["data"], url_root)
    for text, path in linked:
        matches = [link for link in links if normalized_text(link.text) == normalized_text(text)]
        assert len(matches) == 1, f"Expected one {text!r} link, found {len(matches)} in: {card.text}"
        assert matches[0].get_attribute("href") == urljoin(browser.current_url, path)
    for text in unlinked:
        assert not [link for link in links if normalized_text(link.text) == normalized_text(text)]
        assert normalized_text(text) in normalized_text(card.text)

    url_elements = [(link, "href") for link in links] + [(image, "src") for image in images]
    for element, attribute in url_elements:
        assert "/undefined" not in element.get_attribute(attribute)
    assert not card.find_elements(By.CSS_SELECTOR, "[data-feed-xss]")
    if XSS_PAYLOAD in json.dumps(event["data"]):
        assert normalized_text(XSS_PAYLOAD) in normalized_text(card.text)


def assert_feed_event_batch(browser, events, event_ids, user_name, user_id, url_root=""):
    for event, event_id in zip(events, event_ids, strict=True):
        assert_browser_card(browser, event, event_id, user_name, user_id, url_root)


def assert_server_card(card, event, user_name, user_id, url_root):
    card_text = normalized_text("".join(card["text"]))
    links = [
        {"href": link["href"], "text": normalized_text("".join(link["text"]))}
        for link in card["links"]
    ]
    root_attributes = card["elements"][0][1]
    expected_filter_id = str(user_id) if valid_user_id(user_id) else ""
    assert root_attributes["data-user-id"] == expected_filter_id
    assert float(root_attributes["data-feed-score"]) >= 0
    assert len([
        image for image in card["images"]
        if image.get("src") == internal_url(url_root, "belt", f"{FEED_TEST_BELT}.svg")
    ]) == 1
    if valid_user_id(user_id):
        profile_url = internal_url(url_root, "hacker", user_id)
        wrong_profile_url = internal_url(url_root, "hacker", user_name)
        assert len([link for link in links if link["href"] == profile_url]) == 1
        if profile_url != wrong_profile_url:
            assert not [link for link in links if link["href"] == wrong_profile_url]
    else:
        assert not [link for link in links if link["text"] == normalized_text(user_name)]
        assert normalized_text(user_name) in card_text

    linked, unlinked = location_expectations(event["data"], url_root)
    for text, path in linked:
        matches = [link for link in links if link["text"] == normalized_text(text)]
        assert len(matches) == 1, f"Expected one {text!r} link in: {card_text}"
        assert matches[0]["href"] == path
    for text in unlinked:
        assert not [link for link in links if link["text"] == normalized_text(text)]
        assert normalized_text(text) in card_text

    urls = [link["href"] for link in links] + [image.get("src", "") for image in card["images"]]
    assert not [url for url in urls if "/undefined" in url]
    for _, attrs in card["elements"]:
        assert "data-feed-xss" not in attrs
        assert not [name for name in attrs if name.lower().startswith("on")]
    if XSS_PAYLOAD in json.dumps(event["data"]):
        assert normalized_text(XSS_PAYLOAD) in card_text


def get_server_rendered_cards(url_root):
    headers = {"X-Forwarded-Prefix": url_root} if url_root else {}
    response = requests.get(f"{DOJO_URL.rstrip('/')}/feed", headers=headers)
    assert response.status_code == 200
    assert f"'urlRoot': {json.dumps(url_root)}" in response.text

    parser = FeedCardParser()
    parser.feed(response.text)
    return parser.cards


def assert_server_rendered_links(events, event_ids, user_name, user_id, url_root):
    cards = get_server_rendered_cards(url_root)
    for event, event_id in zip(events, event_ids, strict=True):
        assert event_id in cards
        assert_server_card(cards[event_id], event, user_name, user_id, url_root)


def assert_root_and_prefixed_server_rendered_links(events, event_ids, user_name, user_id):
    for url_root in ("", "/ctf"):
        assert_server_rendered_links(events, event_ids, user_name, user_id, url_root)


def assert_root_and_prefixed_server_batches(batches):
    for url_root in ("", "/ctf"):
        cards = get_server_rendered_cards(url_root)
        for events, event_ids, user_name, user_id in batches:
            for event, event_id in zip(events, event_ids, strict=True):
                assert event_id in cards
                assert_server_card(cards[event_id], event, user_name, user_id, url_root)


def assert_server_rejections_and_batches(absent_event_ids, absent_texts, batches):
    for url_root in ("", "/ctf"):
        cards = get_server_rendered_cards(url_root)
        assert not set(absent_event_ids) & cards.keys()
        rendered_text = " ".join(
            normalized_text("".join(card["text"]))
            for card in cards.values()
        )
        assert not [text for text in absent_texts if text in rendered_text]
        for events, event_ids, user_name, user_id in batches:
            for event, event_id in zip(events, event_ids, strict=True):
                assert event_id in cards
                assert_server_card(cards[event_id], event, user_name, user_id, url_root)


def assert_challenge_route(dojo_id, challenge_id):
    challenge_reference_id = "flag"
    response = requests.get(
        f"{DOJO_URL.rstrip('/')}{feed_url('', dojo_id, 'welcome', challenge_reference_id)}"
    )
    assert response.status_code == 200
    assert f'data-challenge-id="{challenge_reference_id}"' in response.text
    assert f'document.querySelector(\'[data-challenge-id="{challenge_reference_id}"]\')' in response.text

    numeric_response = requests.get(
        f"{DOJO_URL.rstrip('/')}{feed_url('', dojo_id, 'welcome', challenge_id)}"
    )
    assert numeric_response.status_code == 404


def capture_prefixed_stream_url(browser):
    return browser.execute_script("""
        window.__feedStreamUrls = [];
        const NativeEventSource = window.EventSource;
        window.EventSource = class {
            static CLOSED = NativeEventSource.CLOSED;
            constructor(url) {
                window.__feedStreamUrls.push(String(url));
                this.readyState = 0;
            }
            close() {
                this.readyState = NativeEventSource.CLOSED;
            }
        };
        let hidden = true;
        Object.defineProperty(document, 'hidden', {configurable: true, get: () => hidden});
        document.dispatchEvent(new Event('visibilitychange'));
        hidden = false;
        document.dispatchEvent(new Event('visibilitychange'));
        return window.__feedStreamUrls[0];
    """)


def assert_filtered_reconnects(browser, allowed_event, other_event):
    result = browser.execute_script("""
        const allowedEvent = arguments[0];
        const otherEvent = arguments[1];
        const NativeEventSource = window.EventSource;
        const nativeSetTimeout = window.setTimeout;
        const nativeClearTimeout = window.clearTimeout;
        const reconnectTimers = [];
        const eventSources = [];

        class FakeEventSource {
            static CLOSED = NativeEventSource.CLOSED;
            constructor(url) {
                this.url = String(url);
                this.readyState = 0;
                eventSources.push(this);
            }
            close() {
                this.readyState = FakeEventSource.CLOSED;
            }
        }

        window.EventSource = FakeEventSource;
        window.setTimeout = (callback, delay, ...args) => {
            if (delay === 3000) {
                const timer = {
                    cancelled: false,
                    run: () => callback(...args),
                };
                reconnectTimers.push(timer);
                return timer;
            }
            return nativeSetTimeout.call(window, callback, delay, ...args);
        };
        window.clearTimeout = timer => {
            if (reconnectTimers.includes(timer)) {
                timer.cancelled = true;
                return;
            }
            nativeClearTimeout.call(window, timer);
        };

        const cursorSeed = Date.now() + 10000;
        const deliverFilteredEvents = (source, suffix, cursorOffset) => {
            const allowedId = `${allowedEvent.id}-${suffix}-allowed`;
            const otherId = `${otherEvent.id}-${suffix}-other`;
            const allowedCursor = `${cursorSeed + cursorOffset}-0`;
            const otherCursor = `${cursorSeed + cursorOffset + 1}-0`;
            const allowedLegacyCursor = String(cursorSeed + cursorOffset);
            const otherLegacyCursor = String(cursorSeed + cursorOffset + 1);
            source.onmessage({
                data: JSON.stringify({
                    ...allowedEvent,
                    id: allowedId,
                    cursor: allowedCursor,
                    legacy_cursor: allowedLegacyCursor,
                    feed_score: String((cursorSeed + cursorOffset) / 1000),
                }),
                lastEventId: allowedCursor,
            });
            source.onmessage({
                data: JSON.stringify({
                    ...otherEvent,
                    id: otherId,
                    cursor: otherCursor,
                    legacy_cursor: otherLegacyCursor,
                    feed_score: String((cursorSeed + cursorOffset + 1) / 1000),
                }),
                lastEventId: otherCursor,
            });
            return {
                allowedId,
                otherId,
                cursor: otherCursor,
                legacyCursor: otherLegacyCursor,
            };
        };

        let hidden = true;
        Object.defineProperty(document, 'hidden', {configurable: true, get: () => hidden});
        document.dispatchEvent(new Event('visibilitychange'));
        hidden = false;
        document.dispatchEvent(new Event('visibilitychange'));

        const initialSource = eventSources[0];
        initialSource.onopen();
        const initialIds = deliverFilteredEvents(initialSource, 'initial', 0);
        initialSource.onerror();
        const hiddenTimer = reconnectTimers[0];

        hidden = true;
        document.dispatchEvent(new Event('visibilitychange'));
        hiddenTimer.run();
        const sourceCountWhileHidden = eventSources.length;

        hidden = false;
        document.dispatchEvent(new Event('visibilitychange'));
        document.dispatchEvent(new Event('visibilitychange'));
        const resumedSource = eventSources[1];
        resumedSource.onopen();
        const sourceCountAfterVisible = eventSources.length;
        hiddenTimer.run();

        const staleAllowedId = `${allowedEvent.id}-stale-allowed`;
        initialSource.onmessage({
            data: JSON.stringify({...allowedEvent, id: staleAllowedId}),
        });
        initialSource.onerror();
        const resumedOpenAfterStaleError = resumedSource.readyState !== FakeEventSource.CLOSED;
        const timerCountAfterStaleError = reconnectTimers.length;
        const resumedIds = deliverFilteredEvents(resumedSource, 'resumed', 10);

        resumedSource.onerror();
        const reconnectTimer = reconnectTimers[1];
        reconnectTimer.run();
        reconnectTimer.run();
        const reconnectedSource = eventSources[2];
        reconnectedSource.onopen();
        resumedSource.onerror();
        const reconnectedOpenAfterStaleError = (
            reconnectedSource.readyState !== FakeEventSource.CLOSED
        );
        const reconnectedIds = deliverFilteredEvents(
            reconnectedSource,
            'reconnected',
            20,
        );
        const lateOldId = `${allowedEvent.id}-late-old-allowed`;
        const lateOldCursor = `${cursorSeed + 30}-0`;
        reconnectedSource.onmessage({
            data: JSON.stringify({
                ...allowedEvent,
                id: lateOldId,
                cursor: lateOldCursor,
                legacy_cursor: String(cursorSeed + 30),
                feed_score: String((cursorSeed - 100) / 1000),
            }),
            lastEventId: lateOldCursor,
        });
        const displayedIds = Array.from(
            document.querySelectorAll('[data-event-id]')
        ).map(card => card.dataset.eventId);

        reconnectedSource.onerror();
        const unloadTimer = reconnectTimers[2];
        window.dispatchEvent(new Event('beforeunload'));
        unloadTimer.run();
        hidden = true;
        document.dispatchEvent(new Event('visibilitychange'));
        hidden = false;
        document.dispatchEvent(new Event('visibilitychange'));

        const hasCard = id => Boolean(document.querySelector(`[data-event-id="${id}"]`));
        const state = {
            sourceCount: eventSources.length,
            sourceCountWhileHidden,
            sourceCountAfterVisible,
            hiddenTimerCancelled: hiddenTimer.cancelled,
            unloadTimerCancelled: unloadTimer.cancelled,
            resumedOpenAfterStaleError,
            reconnectedOpenAfterStaleError,
            timerCountAfterStaleError,
            initialUrlHasCursor: /\\/stream\\?cursor=[0-9]+-[0-9]+&legacy_cursor=[0-9.]+$/.test(
                initialSource.url
            ),
            resumedUrlHasLatestCursor: resumedSource.url.endsWith(
                `?cursor=${initialIds.cursor}`
                + `&legacy_cursor=${initialIds.legacyCursor}`
            ),
            reconnectedUrlHasLatestCursor: reconnectedSource.url.endsWith(
                `?cursor=${resumedIds.cursor}`
                + `&legacy_cursor=${resumedIds.legacyCursor}`
            ),
            staleMessageIgnored: !hasCard(staleAllowedId),
            initialAllowed: hasCard(initialIds.allowedId),
            initialOther: hasCard(initialIds.otherId),
            resumedAllowed: hasCard(resumedIds.allowedId),
            resumedOther: hasCard(resumedIds.otherId),
            reconnectedAllowed: hasCard(reconnectedIds.allowedId),
            reconnectedOther: hasCard(reconnectedIds.otherId),
            lateOldSortedBelowNewer: (
                displayedIds.indexOf(lateOldId)
                > displayedIds.indexOf(initialIds.allowedId)
            ),
        };
        window.EventSource = NativeEventSource;
        window.setTimeout = nativeSetTimeout;
        window.clearTimeout = nativeClearTimeout;
        return state;
    """, allowed_event, other_event)
    assert result == {
        "sourceCount": 3,
        "sourceCountWhileHidden": 1,
        "sourceCountAfterVisible": 2,
        "hiddenTimerCancelled": True,
        "unloadTimerCancelled": True,
        "resumedOpenAfterStaleError": True,
        "reconnectedOpenAfterStaleError": True,
        "timerCountAfterStaleError": 1,
        "initialUrlHasCursor": True,
        "resumedUrlHasLatestCursor": True,
        "reconnectedUrlHasLatestCursor": True,
        "staleMessageIgnored": True,
        "initialAllowed": True,
        "initialOther": False,
        "resumedAllowed": True,
        "resumedOther": False,
        "reconnectedAllowed": True,
        "reconnectedOther": False,
        "lateOldSortedBelowNewer": True,
    }


def test_feed_stream_visibility_releases_database_connections(welcome_dojo):
    stream_count = 24
    stream_url = f"{DOJO_URL.rstrip('/')}/pwncollege_api/v1/feed/stream"
    baseline_subscribers = feed_subscriber_count()
    baseline_transactions = minimum_database_transaction_counts()
    streams = []
    try:
        for _ in range(stream_count):
            response = requests.get(
                stream_url,
                stream=True,
                timeout=(3, 10),
            )
            assert response.status_code == 200
            lines = response.iter_lines(chunk_size=1)
            connected = next_feed_stream_data(lines)
            assert connected["type"] == "connected"
            streams.append((response, lines))

        deadline = time.time() + 5
        while time.time() < deadline:
            if feed_subscriber_count() >= baseline_subscribers + stream_count:
                break
            time.sleep(0.05)
        assert feed_subscriber_count() >= baseline_subscribers + stream_count

        sentinel_event = make_feed_events(
            "Connection Pool Sentinel",
            welcome_dojo,
            0,
            set(),
        )[4]
        sentinel_id = publish_raw_feed_events(
            f"feed-pool-{uuid.uuid4().hex[:8]}",
            [sentinel_event],
        )[0]
        for _, lines in streams:
            event = next_feed_stream_data(lines, sentinel_id)
            assert event["id"] == sentinel_id

        for path in (
            "/pwncollege_api/v1/feed/events",
            "/pwncollege_api/v1/dojos",
        ):
            started = time.monotonic()
            response = requests.get(
                f"{DOJO_URL.rstrip('/')}{path}",
                timeout=5,
            )
            elapsed = time.monotonic() - started
            assert response.status_code == 200
            assert elapsed < 5

        live_transactions = minimum_database_transaction_counts()
        assert live_transactions[0] <= baseline_transactions[0]
        assert live_transactions[1] <= baseline_transactions[1]
    finally:
        for response, _ in streams:
            response.close()
        try:
            publish_raw_feed_events(
                f"feed-pool-cleanup-{uuid.uuid4().hex[:8]}",
                [
                    make_feed_events(
                        "Connection Pool Cleanup",
                        welcome_dojo,
                        0,
                        set(),
                    )[4]
                ],
            )
        except Exception:
            pass

    deadline = time.time() + 10
    while time.time() < deadline:
        if feed_subscriber_count() <= baseline_subscribers:
            break
        time.sleep(0.1)
    assert feed_subscriber_count() <= baseline_subscribers
    final_transactions = minimum_database_transaction_counts()
    assert final_transactions[0] <= baseline_transactions[0]
    assert final_transactions[1] <= baseline_transactions[1]


def test_feed_dojo_links(welcome_dojo, random_private_dojo):
    user_name = str(900_000_000 + uuid.uuid4().int % 100_000_000)
    user_session = login(user_name, user_name, register=True)
    fixture_dojo_reference = welcome_dojo
    welcome_dojo, challenge_id, user_id = prepare_feed_test(
        user_name,
        welcome_dojo,
        "welcome",
        "flag",
    )
    assert welcome_dojo == fixture_dojo_reference.split("~", 1)[0]
    assert_challenge_route(welcome_dojo, challenge_id)
    assert user_id != int(user_name)

    start_challenge(welcome_dojo, "welcome", "flag", session=user_session)
    wait_for_background_worker(timeout=1)
    container_event = get_user_feed_event(user_name, "container_start")
    assert_production_challenge_event(container_event, welcome_dojo, "assessment")
    assert container_event["data"]["challenge_id"] == challenge_id
    assert container_event["user_belt"] == FEED_TEST_BELT
    assert container_event["user_id"] == user_id

    solve_challenge(
        welcome_dojo,
        "welcome",
        "flag",
        session=user_session,
        user=user_name,
    )
    wait_for_background_worker(timeout=1)
    solve_event = get_user_feed_event(user_name, "challenge_solve")
    assert_production_challenge_event(solve_event, welcome_dojo)
    assert solve_event["data"]["challenge_id"] == challenge_id
    assert solve_event["user_belt"] == FEED_TEST_BELT
    assert solve_event["user_id"] == user_id
    production_events = [container_event, solve_event]
    production_event_ids = [event["id"] for event in production_events]

    initial_events = make_feed_events(
        "Initial",
        welcome_dojo,
        challenge_id,
        {"challenge_solve", "belt_earned"},
        {"challenge_solve"},
    )
    initial_partial_events = make_partial_feed_events("Initial Partial", welcome_dojo, challenge_id)
    initial_events += initial_partial_events
    initial_event_ids = publish_feed_events(user_name, initial_events)
    assert_root_and_prefixed_server_rendered_links(
        production_events + initial_events,
        production_event_ids + initial_event_ids,
        user_name,
        user_id,
    )

    missing_user_events = make_feed_events("Missing User", welcome_dojo, challenge_id, set())

    identity_cases = []
    for prefix, raw_user_id, spoofed_profile_id in (
        ("Float User", 1.0, 1),
        ("Boolean User", True, 1),
        ("Maximum User", MAX_SAFE_USER_ID, None),
        ("Unsafe User", MAX_SAFE_USER_ID + 1, 1),
    ):
        events = make_feed_events(prefix, welcome_dojo, challenge_id, set())
        for event in events:
            event["user_id"] = raw_user_id
            event["user_profile_id"] = spoofed_profile_id
        identity_cases.append((events, raw_user_id))

    identity_event_ids = publish_feed_event_batches(
        publish_raw_feed_events,
        user_name,
        [events for events, _ in identity_cases],
    )
    identity_cases = [
        (events, event_ids, raw_user_id)
        for (events, raw_user_id), event_ids in zip(identity_cases, identity_event_ids, strict=True)
    ]
    assert_root_and_prefixed_server_batches([
        (events, event_ids, user_name, raw_user_id)
        for events, event_ids, raw_user_id in identity_cases
    ])

    response = requests.get(f"{DOJO_URL.rstrip('/')}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    normalized_events = {event["id"]: event for event in response.json()["data"]}
    for _, event_ids, raw_user_id in identity_cases:
        expected_profile_id = raw_user_id if valid_user_id(raw_user_id) else None
        for event_id in event_ids:
            assert normalized_events[event_id]["user_profile_id"] == expected_profile_id

    assert "~" in random_private_dojo
    assert canonical_dojo_reference(random_private_dojo)
    identifier_cases = [
        make_identifier_feed_events("Numeric IDs", 123, 7, 9, challenge_id, names=True),
        make_identifier_feed_events("Zero IDs", 0, 0, 0, challenge_id, names=False),
        make_identifier_feed_events("Boolean IDs", True, True, True, challenge_id, names=False),
        make_identifier_feed_events(
            "Malformed IDs",
            "dojo~12345678~deadbeef",
            "UPPER",
            "bad_value",
            challenge_id,
            names=False,
        ),
        make_identifier_feed_events(
            "Canonical Boundary",
            welcome_dojo,
            "m" * 32,
            "c" * 32,
            challenge_id,
            names=True,
        ),
    ]
    for case_number, events in enumerate(identifier_cases):
        for event in events:
            event["user_id"] = user_id
            event["user_profile_id"] = MAX_SAFE_USER_ID
            event["data"].update({
                "dojo_path_id": "spoof-dojo",
                "module_path_id": "spoof-module",
                "challenge_path_id": "spoof-challenge",
                "dojo_label": f"spoof dojo {case_number}",
                "module_label": f"spoof module {case_number}",
                "challenge_label": f"spoof challenge {case_number}",
            })

    watcher_options = FirefoxOptions()
    watcher_options.add_argument("--headless")
    watcher = Firefox(options=watcher_options)

    try:
        subscribers_before = feed_subscriber_count()
        watcher.get(f"{DOJO_URL}/feed")
        for events, event_ids, raw_user_id in identity_cases:
            assert_feed_event_batch(watcher, events, event_ids, user_name, raw_user_id)
        WebDriverWait(watcher, 10).until(lambda _: feed_subscriber_count() > subscribers_before)

        live_identity_ids = publish_feed_event_batches(
            publish_raw_feed_events,
            user_name,
            [events for events, _, _ in identity_cases],
        )
        for (events, _, raw_user_id), event_ids in zip(identity_cases, live_identity_ids, strict=True):
            assert_feed_event_batch(watcher, events, event_ids, user_name, raw_user_id)

        live_events = make_feed_events(
            "Live",
            welcome_dojo,
            challenge_id,
            {"container_start", "emoji_earned", "dojo_update"},
            {"container_start"},
        )
        live_event_ids = publish_feed_events(user_name, live_events)
        assert_feed_event_batch(watcher, live_events, live_event_ids, user_name, user_id)

        zero_user_events = make_feed_events("Zero User", welcome_dojo, challenge_id, set())
        for event in zero_user_events:
            event["user_id"] = 0

        nonfinite_events = make_feed_events("Nonfinite", welcome_dojo, challenge_id, set())[:4]
        for event, literal in zip(
            nonfinite_events,
            ("1e400", "NaN", "Infinity", "-Infinity"),
            strict=True,
        ):
            event["user_id"] = user_id
            event["data"]["nonfinite"] = {"nested": [RAW_JSON_MARKER]}
            event["raw_json_marker"] = RAW_JSON_MARKER
            event["raw_json_literal"] = literal

        deeply_nested_events = [
            make_feed_events("Deeply Nested", welcome_dojo, challenge_id, set())[0]
        ]
        deeply_nested_events[0]["user_id"] = user_id
        deeply_nested_events[0]["data"]["deeply_nested"] = RAW_JSON_MARKER
        deeply_nested_events[0]["raw_json_marker"] = RAW_JSON_MARKER
        deeply_nested_events[0]["raw_json_literal"] = (
            "[" * 1_100 + "null" + "]" * 1_100
        )

        invalid_utf8_events = [
            make_feed_events("Invalid UTF-8", welcome_dojo, challenge_id, set())[0]
        ]
        invalid_utf8_events[0]["user_id"] = user_id
        invalid_utf8_events[0]["data"]["invalid_utf8"] = RAW_BYTES_MARKER
        invalid_utf8_events[0]["raw_bytes_marker"] = RAW_BYTES_MARKER
        invalid_utf8_events[0]["raw_bytes_literal"] = base64.b64encode(b'"\xff"').decode()

        surrogate_events = make_feed_events(
            "Unpaired Surrogate",
            welcome_dojo,
            challenge_id,
            set(),
        )[:3]
        for event in surrogate_events:
            event["user_id"] = user_id
        surrogate_events[0]["data"]["surrogate_value"] = "\ud800"
        surrogate_events[1]["data"]["\udfff"] = "surrogate key"
        surrogate_events[2]["top_level"] = {"user_name": "\ud800"}

        malformed_envelope_events = make_feed_events(
            "Malformed Envelope",
            welcome_dojo,
            challenge_id,
            set(),
        )[:4]
        malformed_envelope_names = []
        for event, (field, value) in zip(
            malformed_envelope_events,
            (
                ("timestamp", ["invalid"]),
                ("user_belt", 7),
                ("user_emojis", {"invalid": True}),
                ("id", ["invalid"]),
            ),
            strict=True,
        ):
            malformed_name = f"Malformed top-level {field} {uuid.uuid4()}"
            malformed_envelope_names.append(malformed_name)
            event["user_id"] = user_id
            event["top_level"] = {field: value, "user_name": malformed_name}

        hostile_event_id = 'feed"]'
        hostile_id_event = [make_feed_events("Hostile ID", welcome_dojo, challenge_id, set())[0]]
        hostile_id_event[0]["user_id"] = user_id
        hostile_id_event[0]["top_level"] = {"id": hostile_event_id}
        finite_sentinel = [make_feed_events("Finite Sentinel", welcome_dojo, challenge_id, set())[4]]
        finite_sentinel[0]["user_id"] = user_id
        (
            zero_user_event_ids,
            nonfinite_event_ids,
            deeply_nested_event_ids,
            hostile_id_transport_ids,
            malformed_envelope_transport_ids,
            invalid_utf8_event_ids,
            surrogate_event_ids,
            finite_sentinel_ids,
            malformed_id_transport_ids,
        ) = publish_feed_event_batches(
            publish_raw_feed_events,
            user_name,
            [
                zero_user_events,
                nonfinite_events,
                deeply_nested_events,
                hostile_id_event,
                malformed_envelope_events[:3],
                invalid_utf8_events,
                surrogate_events,
                finite_sentinel,
                malformed_envelope_events[3:],
            ],
        )
        assert_feed_event_batch(watcher, zero_user_events, zero_user_event_ids, user_name, 0)
        assert len(hostile_id_transport_ids) == 1
        assert uuid.UUID(hostile_id_transport_ids[0])
        assert hostile_id_transport_ids != [hostile_event_id]
        assert all(uuid.UUID(event_id) for event_id in (
            malformed_envelope_transport_ids + malformed_id_transport_ids
        ))
        hostile_id_event_ids = [hostile_event_id]
        assert_feed_event_batch(
            watcher,
            hostile_id_event,
            hostile_id_event_ids,
            user_name,
            user_id,
        )
        assert_feed_event_batch(
            watcher,
            finite_sentinel,
            finite_sentinel_ids,
            user_name,
            user_id,
        )
        browser_feed_text = watcher.find_element(By.ID, "events-list").text
        assert not [name for name in malformed_envelope_names if name in browser_feed_text]
        assert not [
            event_id
            for event_id in (
                nonfinite_event_ids
                + deeply_nested_event_ids
                + invalid_utf8_event_ids
                + surrogate_event_ids
            )
            if watcher.find_elements(By.CSS_SELECTOR, f'[data-event-id="{event_id}"]')
        ]

        response = requests.get(f"{DOJO_URL.rstrip('/')}/pwncollege_api/v1/feed/events")
        assert response.status_code == 200
        history_event_ids = {event["id"] for event in response.json()["data"]}
        history_user_names = {event["user_name"] for event in response.json()["data"]}
        assert finite_sentinel_ids[0] in history_event_ids
        assert hostile_event_id in history_event_ids
        rejected_event_ids = (
            nonfinite_event_ids
            + deeply_nested_event_ids
            + invalid_utf8_event_ids
            + surrogate_event_ids
        )
        assert not set(rejected_event_ids) & history_event_ids
        assert not set(malformed_envelope_names) & history_user_names

        expected_history_prefix = [
            finite_sentinel_ids[0],
            hostile_event_id,
            *reversed(zero_user_event_ids),
        ]

        def get_history_ids(limit, offset):
            page_response = requests.get(
                f"{DOJO_URL.rstrip('/')}/pwncollege_api/v1/feed/events",
                params={"limit": limit, "offset": offset},
            )
            assert page_response.status_code == 200
            page = page_response.json()
            cursor = page["meta"].pop("cursor")
            legacy_cursor = page["meta"].pop("legacy_cursor")
            assert re.fullmatch(r"[0-9]+-[0-9]+", cursor)
            assert float(legacy_cursor) >= 0
            assert page["meta"] == {
                "limit": limit,
                "offset": offset,
                "count": len(page["data"]),
            }
            return [event["id"] for event in page["data"]]

        for offset, event_id in enumerate(expected_history_prefix[:3]):
            assert get_history_ids(1, offset) == [event_id]
        assert get_history_ids(2, 0) == expected_history_prefix[:2]
        assert get_history_ids(2, 2) == expected_history_prefix[2:4]
        assert get_history_ids(4, 0) == expected_history_prefix[:4]

        assert_server_rejections_and_batches(
            rejected_event_ids,
            malformed_envelope_names,
            [
                (hostile_id_event, hostile_id_event_ids, user_name, user_id),
                (finite_sentinel, finite_sentinel_ids, user_name, user_id),
            ],
        )

        identifier_event_ids = publish_feed_event_batches(
            publish_raw_feed_events,
            user_name,
            identifier_cases[:4],
        )
        for events, event_ids in zip(identifier_cases[:4], identifier_event_ids, strict=True):
            assert_feed_event_batch(watcher, events, event_ids, user_name, user_id)
        assert_root_and_prefixed_server_batches([
            (events, event_ids, user_name, user_id)
            for events, event_ids in zip(identifier_cases[:4], identifier_event_ids, strict=True)
        ])

        canonical_identifier_events = identifier_cases[4]
        canonical_identifier_ids = publish_raw_feed_events(user_name, canonical_identifier_events)
        assert_feed_event_batch(
            watcher,
            canonical_identifier_events,
            canonical_identifier_ids,
            user_name,
            user_id,
        )
        assert_root_and_prefixed_server_rendered_links(
            canonical_identifier_events,
            canonical_identifier_ids,
            user_name,
            user_id,
        )

        watcher.execute_script("init.urlRoot = '/ctf'")
        prefixed_identifier_ids = publish_feed_event_batches(
            publish_raw_feed_events,
            user_name,
            identifier_cases,
        )
        for events, event_ids in zip(identifier_cases, prefixed_identifier_ids, strict=True):
            assert_feed_event_batch(watcher, events, event_ids, user_name, user_id, "/ctf")

        prefixed_named_events = make_feed_events("Prefixed Named", welcome_dojo, challenge_id, set())
        prefixed_fallback_events = make_feed_events(
            "Prefixed Fallback",
            welcome_dojo,
            challenge_id,
            FEED_EVENT_TYPES,
            {"container_start", "challenge_solve"},
        )
        prefixed_partial_events = make_partial_feed_events("Prefixed Partial", welcome_dojo, challenge_id)
        prefixed_event_batches = [
            prefixed_named_events,
            prefixed_fallback_events,
            prefixed_partial_events,
        ]
        prefixed_event_ids = publish_feed_event_batches(
            publish_feed_events,
            user_name,
            prefixed_event_batches,
        )
        for events, event_ids in zip(prefixed_event_batches, prefixed_event_ids, strict=True):
            assert_feed_event_batch(watcher, events, event_ids, user_name, user_id, "/ctf")

        malformed_user_events = make_feed_events("Malformed User", welcome_dojo, challenge_id, set())
        for event in malformed_user_events:
            event["user_id"] = user_name
        negative_user_events = make_feed_events("Negative User", welcome_dojo, challenge_id, set())
        for event in negative_user_events:
            event["user_id"] = -1
        prefixed_raw_batches = [
            *[events for events, _, _ in identity_cases],
            missing_user_events,
            malformed_user_events,
            negative_user_events,
        ]
        prefixed_raw_ids = publish_feed_event_batches(
            publish_raw_feed_events,
            user_name,
            prefixed_raw_batches,
        )
        prefixed_identity_ids = prefixed_raw_ids[:len(identity_cases)]
        missing_user_event_ids, malformed_user_event_ids, negative_user_event_ids = prefixed_raw_ids[-3:]
        assert_feed_event_batch(
            watcher,
            missing_user_events,
            missing_user_event_ids,
            user_name,
            None,
            "/ctf",
        )
        assert_feed_event_batch(
            watcher,
            malformed_user_events,
            malformed_user_event_ids,
            user_name,
            user_name,
            "/ctf",
        )
        assert_feed_event_batch(
            watcher,
            negative_user_events,
            negative_user_event_ids,
            user_name,
            -1,
            "/ctf",
        )
        assert_root_and_prefixed_server_batches([
            (missing_user_events, missing_user_event_ids, user_name, None),
            (malformed_user_events, malformed_user_event_ids, user_name, user_name),
            (negative_user_events, negative_user_event_ids, user_name, -1),
        ])

        for (events, _, raw_user_id), event_ids in zip(identity_cases, prefixed_identity_ids, strict=True):
            assert_feed_event_batch(watcher, events, event_ids, user_name, raw_user_id, "/ctf")

        assert re.fullmatch(
            r"/ctf/pwncollege_api/v1/feed/stream\?cursor=[0-9]+-[0-9]+&legacy_cursor=[0-9.]+",
            capture_prefixed_stream_url(watcher),
        )

    finally:
        watcher.quit()


def test_feed_user_filter_reconnects(welcome_dojo):
    user_name = str(800_000_000 + uuid.uuid4().int % 100_000_000)
    login(user_name, user_name, register=True)
    other_user_name = f"other-{user_name}"
    fixture_dojo_reference = welcome_dojo
    welcome_dojo, challenge_id, user_id = prepare_feed_test(
        user_name,
        welcome_dojo,
        "welcome",
        "flag",
    )
    assert welcome_dojo == fixture_dojo_reference.split("~", 1)[0]
    other_user_id = user_id + 1

    initial_allowed = [make_feed_events("Filter Initial Allowed", welcome_dojo, challenge_id, set())[0]]
    initial_other = [make_feed_events("Filter Initial Other", welcome_dojo, challenge_id, set())[0]]
    initial_allowed[0]["user_id"] = user_id
    initial_other[0]["user_id"] = other_user_id
    initial_other[0]["top_level"] = {"user_name": other_user_name}
    initial_allowed_ids, initial_other_ids = publish_feed_event_batches(
        publish_raw_feed_events,
        user_name,
        [initial_allowed, initial_other],
    )

    options = FirefoxOptions()
    options.add_argument("--headless")
    browser = Firefox(options=options)
    try:
        subscribers_before = feed_subscriber_count()
        browser.get(f"{DOJO_URL.rstrip('/')}/feed?users={user_id}")
        assert_feed_event_batch(
            browser,
            initial_allowed,
            initial_allowed_ids,
            user_name,
            user_id,
        )
        assert not browser.find_elements(
            By.CSS_SELECTOR,
            f'[data-event-id="{initial_other_ids[0]}"]',
        )
        WebDriverWait(browser, 10).until(lambda _: feed_subscriber_count() > subscribers_before)

        live_allowed = [make_feed_events("Filter Live Allowed", welcome_dojo, challenge_id, set())[0]]
        live_other = [make_feed_events("Filter Live Other", welcome_dojo, challenge_id, set())[0]]
        live_allowed[0]["user_id"] = user_id
        live_other[0]["user_id"] = other_user_id
        live_other[0]["top_level"] = {"user_name": other_user_name}
        live_other_ids, live_allowed_ids = publish_feed_event_batches(
            publish_raw_feed_events,
            user_name,
            [live_other, live_allowed],
        )
        assert_feed_event_batch(
            browser,
            live_allowed,
            live_allowed_ids,
            user_name,
            user_id,
        )
        assert not browser.find_elements(
            By.CSS_SELECTOR,
            f'[data-event-id="{live_other_ids[0]}"]',
        )

        browser.execute_script("""
            window.__feedTestHidden = true;
            Object.defineProperty(document, 'hidden', {
                configurable: true,
                get: () => window.__feedTestHidden,
            });
            document.dispatchEvent(new Event('visibilitychange'));
        """)
        disconnected_events = make_feed_events(
            "Filter Disconnected",
            welcome_dojo,
            challenge_id,
            set(),
        )[:2]
        for event in disconnected_events:
            event["user_id"] = user_id
        disconnected_ids = publish_raw_feed_events(user_name, disconnected_events)
        assert not any(
            find_browser_card(browser, event_id) for event_id in disconnected_ids
        )
        browser.execute_script("""
            window.__feedTestHidden = false;
            document.dispatchEvent(new Event('visibilitychange'));
        """)
        assert_feed_event_batch(
            browser,
            disconnected_events,
            disconnected_ids,
            user_name,
            user_id,
        )
        rendered_event_ids = browser.execute_script("""
            return Array.from(document.querySelectorAll('[data-event-id]'))
                .map(card => card.dataset.eventId);
        """)
        assert rendered_event_ids.count(disconnected_ids[0]) == 1
        assert rendered_event_ids.count(disconnected_ids[1]) == 1
        assert rendered_event_ids.index(disconnected_ids[1]) < rendered_event_ids.index(
            disconnected_ids[0]
        )

        response = requests.get(f"{DOJO_URL.rstrip('/')}/pwncollege_api/v1/feed/events")
        assert response.status_code == 200
        events = {event["id"]: event for event in response.json()["data"]}
        assert_filtered_reconnects(
            browser,
            events[live_allowed_ids[0]],
            events[live_other_ids[0]],
        )
    finally:
        browser.quit()


def test_shared_challenge_solve_uses_routed_association(admin_session, welcome_dojo):
    suffix = uuid.uuid4().hex[:8]
    public_dojo = create_dojo_yml(f"""
id: feed-public-{suffix}
type: public
modules:
  - id: public-module
    challenges:
      - id: public-challenge
        import:
          dojo: {welcome_dojo}
          module: welcome
          challenge: flag
""", session=admin_session)
    private_dojo = create_dojo_yml(f"""
id: feed-private-{suffix}
type: topic
modules:
  - id: private-module
    challenges:
      - id: private-challenge
        import:
          dojo: {public_dojo}
          module: public-module
          challenge: public-challenge
""", session=admin_session)

    route_cases = [
        {
            "user_name": str(500_000_000 + uuid.uuid4().int % 100_000_000),
            "container_route": (public_dojo, "public-module", "public-challenge"),
            "submission_route": (private_dojo, "private-module", "private-challenge"),
            "published": False,
        },
        {
            "user_name": str(600_000_000 + uuid.uuid4().int % 100_000_000),
            "container_route": (private_dojo, "private-module", "private-challenge"),
            "submission_route": (public_dojo, "public-module", "public-challenge"),
            "published": True,
        },
        {
            "user_name": str(700_000_000 + uuid.uuid4().int % 100_000_000),
            "container_route": (public_dojo, "public-module", "public-challenge"),
            "submission_route": (public_dojo, "public-module", "public-challenge"),
            "route_data": {"dojo_id": public_dojo},
            "published": False,
        },
        {
            "user_name": str(800_000_000 + uuid.uuid4().int % 100_000_000),
            "container_route": (public_dojo, "public-module", "public-challenge"),
            "submission_route": (public_dojo, "public-module", "public-challenge"),
            "route_data": {
                "dojo_id": public_dojo,
                "module_id": "public-module",
                "challenge_reference_id": "missing-reference",
            },
            "published": False,
        },
        {
            "user_name": str(900_000_000 + uuid.uuid4().int % 100_000_000),
            "container_route": (public_dojo, "public-module", "public-challenge"),
            "submission_route": (public_dojo, "public-module", "public-challenge"),
            "route_data": {
                "dojo_id": f"{public_dojo.split('~', 1)[0]}~nothex",
                "module_id": "public-module",
                "challenge_reference_id": "public-challenge",
            },
            "published": False,
        },
    ]
    for case in route_cases:
        case["session"] = login(
            case["user_name"], case["user_name"], register=True
        )
        join_response = case["session"].get(f"{DOJO_URL}/dojo/{private_dojo}/join/")
        assert join_response.status_code == 200

    route_pages = {}
    for dojo_id, module_id, challenge_reference_id in (
        (public_dojo, "public-module", "public-challenge"),
        (private_dojo, "private-module", "private-challenge"),
    ):
        response = route_cases[0]["session"].get(
            f"{DOJO_URL.rstrip('/')}/{dojo_id}/{module_id}"
        )
        assert response.status_code == 200
        challenge_ids = {
            int(challenge_id)
            for challenge_id in re.findall(
                r'<input id="challenge-id" type="hidden" value="(\d+)">',
                response.text,
            )
        }
        assert len(challenge_ids) == 1
        route_pages[(dojo_id, module_id, challenge_reference_id)] = challenge_ids.pop()
        assert f'<input id="module" type="hidden" value="{module_id}">' in response.text
        assert (
            f'<input id="challenge" type="hidden" '
            f'value="{challenge_reference_id}">'
        ) in response.text
        assert (
            f'data-dojo-id="{dojo_id}" data-module-id="{module_id}" '
            f'data-challenge-reference-id="{challenge_reference_id}"'
        ) in response.text
    assert len(set(route_pages.values())) == 1
    challenge_id = next(iter(route_pages.values()))

    options = FirefoxOptions()
    options.add_argument("--headless")
    watcher = Firefox(options=options)
    try:
        subscribers_before = feed_subscriber_count()
        watcher.get(f"{DOJO_URL}/feed")
        WebDriverWait(watcher, 10).until(
            lambda _: feed_subscriber_count() > subscribers_before
        )

        for case in route_cases:
            start_challenge(*case["container_route"], session=case["session"])
            submission = workspace_run(
                "cat /flag", user=case["user_name"], root=True
            ).stdout.strip()
            submit_browser_challenge(
                *case["submission_route"],
                challenge_id,
                submission,
                session=case["session"],
                expected_status="correct",
                route_data=case.get("route_data"),
            )
            submit_browser_challenge(
                *case["submission_route"],
                challenge_id,
                submission,
                session=case["session"],
                expected_status="already_solved",
                route_data=case.get("route_data"),
            )

        sentinel_event = make_feed_events(
            "Shared Route Sentinel", public_dojo, 0, set()
        )[4]
        sentinel_id = publish_raw_feed_events(
            route_cases[-1]["user_name"], [sentinel_event]
        )[0]
        WebDriverWait(watcher, 10).until(
            lambda driver: find_browser_card(driver, sentinel_id)
        )

        response = requests.get(f"{DOJO_URL.rstrip('/')}/pwncollege_api/v1/feed/events")
        assert response.status_code == 200
        history = response.json()["data"]
        public_events = []
        for case in route_cases:
            solve_events = [
                event for event in history
                if event["type"] == "challenge_solve"
                and event["user_name"] == case["user_name"]
            ]
            if not case["published"]:
                assert solve_events == []
                continue
            assert len(solve_events) == 1
            event = solve_events[0]
            assert event["data"]["dojo_id"] == public_dojo
            assert event["data"]["module_id"] == "public-module"
            assert event["data"]["challenge_reference_id"] == "public-challenge"
            assert event["data"]["challenge_id"] == challenge_id
            public_events.append(event)

        for event in public_events:
            card = WebDriverWait(watcher, 10).until(
                lambda driver, event_id=event["id"]: find_browser_card(driver, event_id)
            )
            route_url = urljoin(
                watcher.current_url,
                feed_url("", public_dojo, "public-module", "public-challenge"),
            )
            assert len([
                link for link in card.find_elements(By.TAG_NAME, "a")
                if link.get_attribute("href") == route_url
            ]) == 1

        cards = watcher.find_elements(By.CSS_SELECTOR, ".event-card")
        for case in route_cases:
            solve_cards = [
                card for card in cards
                if case["user_name"] in card.text
                and card.find_elements(By.CSS_SELECTOR, ".fa-flag-checkered")
            ]
            assert len(solve_cards) == int(case["published"])
    finally:
        watcher.quit()


def test_private_dojo_events_not_shown(random_private_dojo, random_user_name, random_user_session):
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    initial_events = response.json()["data"]
    initial_count = len(initial_events)

    start_data = {
        "dojo": random_private_dojo,
        "module": "test-module",
        "challenge": "test-challenge"
    }
    response = random_user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json=start_data)
    assert response.status_code == 200
    wait_for_background_worker(timeout=1)

    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    events_after = response.json()["data"]

    found_event = False
    for event in events_after:
        if event.get("user_name") == random_user_name:
            found_event = True
            break

    assert not found_event, "Private dojo events should NOT appear in the feed!"
    assert len(events_after) == initial_count, f"Event count changed! Before: {initial_count}, After: {len(events_after)}"


def test_password_protected_public_dojo_events_not_shown(admin_session, welcome_dojo):
    suffix = uuid.uuid4().hex[:8]
    password = f"feed-pass-{suffix}"
    protected_dojo = create_dojo_yml(f"""
id: feed-protected-{suffix}
type: public
password: {password}
modules:
  - id: protected-module
    challenges:
      - id: protected-challenge
        import:
          dojo: {welcome_dojo}
          module: welcome
          challenge: flag
""", session=admin_session)
    user_name = f"feed-protected-user-{suffix}"
    user_session = login(user_name, user_name, register=True)
    join_response = user_session.get(
        f"{DOJO_URL.rstrip('/')}/dojo/{protected_dojo}/join/{password}"
    )
    assert join_response.status_code == 200
    module_response = user_session.get(
        f"{DOJO_URL.rstrip('/')}/{protected_dojo}/protected-module"
    )
    assert module_response.status_code == 200
    challenge_ids = re.findall(
        r'<input id="challenge-id" type="hidden" value="(\d+)">',
        module_response.text,
    )
    assert len(challenge_ids) == 1
    challenge_id = int(challenge_ids[0])

    options = FirefoxOptions()
    options.add_argument("--headless")
    watcher = Firefox(options=options)
    try:
        subscribers_before = feed_subscriber_count()
        watcher.get(f"{DOJO_URL.rstrip('/')}/feed")
        WebDriverWait(watcher, 10).until(
            lambda _: feed_subscriber_count() > subscribers_before
        )

        start_challenge(
            protected_dojo,
            "protected-module",
            "protected-challenge",
            session=user_session,
        )
        submission = workspace_run(
            "cat /flag",
            user=user_name,
            root=True,
        ).stdout.strip()
        submit_browser_challenge(
            protected_dojo,
            "protected-module",
            "protected-challenge",
            challenge_id,
            submission,
            session=user_session,
            expected_status="correct",
        )

        legacy_protected_event = make_feed_events(
            "Legacy Protected",
            protected_dojo,
            challenge_id,
            set(),
        )[4]
        legacy_protected_id = publish_legacy_feed_events(
            user_name,
            [legacy_protected_event],
        )[0]

        transition_event = make_feed_events(
            "Visibility Transition",
            protected_dojo,
            challenge_id,
            set(),
        )[4]
        set_dojo_password(protected_dojo, None)
        try:
            transition_event_id = publish_legacy_feed_events(
                user_name,
                [transition_event],
            )[0]
            WebDriverWait(watcher, 10).until(
                lambda driver: find_browser_card(driver, transition_event_id)
            )
        finally:
            set_dojo_password(protected_dojo, password)

        watcher.get(f"{DOJO_URL.rstrip('/')}/feed")
        assert find_browser_card(watcher, transition_event_id) is None

        sentinel_event = make_feed_events(
            "Protected Sentinel",
            welcome_dojo,
            challenge_id,
            set(),
        )[4]
        sentinel_id = publish_raw_feed_events(
            f"protected-sentinel-{suffix}",
            [sentinel_event],
        )[0]
        WebDriverWait(watcher, 10).until(
            lambda driver: find_browser_card(driver, sentinel_id)
        )

        response = requests.get(
            f"{DOJO_URL.rstrip('/')}/pwncollege_api/v1/feed/events"
        )
        assert response.status_code == 200
        leaked_events = [
            event for event in response.json()["data"]
            if event["user_name"] == user_name
            and event["type"] in {"container_start", "challenge_solve"}
            and event["data"].get("dojo_id") == protected_dojo
        ]
        assert leaked_events == []
        assert legacy_protected_id not in {
            event["id"] for event in response.json()["data"]
        }
        assert transition_event_id not in {
            event["id"] for event in response.json()["data"]
        }
        assert find_browser_card(watcher, legacy_protected_id) is None
        assert not [
            card for card in watcher.find_elements(By.CSS_SELECTOR, ".event-card")
            if user_name in card.text
            and card.find_elements(
                By.CSS_SELECTOR,
                ".fa-play-circle, .fa-flag-checkered",
            )
        ]
    finally:
        watcher.quit()
