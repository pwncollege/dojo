import json
import random
import socket
import string
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from queue import Empty, Queue

import pytest
import requests

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    create_dojo_yml,
    db_sql,
    dojo_run,
    flask_exec,
    get_user_id,
    login,
    make_dojo_official,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
    wait_for_background_worker,
)

FEED_EVENTS_URL = f"{DOJO_URL}/pwncollege_api/v1/feed/events"
FEED_STREAM_URL = f"{DOJO_URL}/pwncollege_api/v1/feed/stream"
FEED_PAGE_URL = f"{DOJO_URL}/feed"
SEARCH_URL = f"{DOJO_URL}/pwncollege_api/v1/search"
ACTIVITY_URL = f"{DOJO_URL}/pwncollege_api/v1/activity"

FEED_KEY = "activity_feed:events"
FEED_MAX_EVENTS = 1000
FEED_EVENT_TYPES = {"container_start", "challenge_solve", "emoji_earned", "belt_earned", "dojo_update"}
EVENT_KEYS = {"id", "type", "timestamp", "user_id", "user_name", "user_belt", "user_emojis", "data"}


def token(length=8):
    return "".join(random.choices(string.ascii_lowercase, k=length))


def new_user():
    name = token(16)
    return name, login(name, name, register=True)


def redis_cli(*args):
    result = dojo_run("docker", "exec", "cache", "redis-cli", *args, check=False)
    assert result.returncode == 0, f"redis-cli {args[0]} failed: {result.stderr}"
    return result.stdout.strip()


def redis_get(key):
    value = redis_cli("GET", key)
    return value or None


def fetch_feed(session=None, **params):
    response = (session or requests).get(FEED_EVENTS_URL, params=params)
    assert response.status_code == 200, f"Expected 200 from the feed API, got {response.status_code}"
    body = response.json()
    assert body["success"] is True, f"Expected success from the feed API, got {body}"
    return body


def poll_feed_event(predicate, timeout=20, limit=100):
    deadline = time.time() + timeout
    while True:
        for event in fetch_feed(limit=limit)["data"]:
            if predicate(event):
                return event
        if time.time() >= deadline:
            return None
        time.sleep(0.3)


def synthetic_event(user_name, index):
    return {
        "id": str(uuid.uuid4()),
        "type": "container_start",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": 1,
        "user_name": user_name,
        "user_belt": None,
        "user_emojis": [],
        "data": {
            "challenge_id": index,
            "challenge_name": "Synthetic Challenge",
            "module_id": "synthetic",
            "module_name": "Synthetic Module",
            "dojo_id": "synthetic",
            "dojo_name": "Synthetic Dojo",
            "mode": "assessment",
        },
    }


def zadd_events(scored_members):
    for start in range(0, len(scored_members), 100):
        args = []
        for score, member in scored_members[start:start + 100]:
            args += [f"{score:.6f}", member]
        redis_cli("ZADD", FEED_KEY, *args)


def search(query, session=None, **kwargs):
    response = (session or requests).get(SEARCH_URL, params={"q": query}, **kwargs)
    return response


def search_results(query, session=None):
    response = search(query, session=session)
    assert response.status_code == 200, f"Expected 200 for search {query!r}, got {response.status_code}"
    body = response.json()
    assert body["success"] is True, f"Expected success for search {query!r}, got {body}"
    return body["results"]


def marker_dojo(session, filename, spec_id, *, official):
    suffix = token()
    marker = f"Fsmark{suffix}"
    spec = (
        (TEST_DOJOS_LOCATION / filename).read_text()
        .replace(spec_id, f"{spec_id}-{suffix}")
        .replace("FSMARKER", marker)
    )
    reference_id = create_dojo_yml(spec, session=session)
    if official:
        make_dojo_official(reference_id, session)
        reference_id = f"{spec_id}-{suffix}"
    return {"rid": reference_id, "id": f"{spec_id}-{suffix}", "marker": marker}


def recent_solve_count(user_id):
    return int(db_sql(
        f"SELECT count(*) FROM submissions WHERE user_id = {user_id} AND type = 'correct' "
        "AND date >= NOW() - INTERVAL '365 days'"
    ))


class StreamReader:
    def __init__(self, session=None):
        self.response = (session or requests).get(
            FEED_STREAM_URL, stream=True, timeout=(10, 120), allow_redirects=False
        )
        self.payloads = Queue()
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        try:
            for line in self.response.iter_lines(decode_unicode=True):
                if line and line.startswith("data: "):
                    try:
                        self.payloads.put(json.loads(line[len("data: "):]))
                    except ValueError:
                        pass
        except Exception:
            pass

    def wait_for(self, predicate, timeout):
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                payload = self.payloads.get(timeout=remaining)
            except Empty:
                return None
            if predicate(payload):
                return payload

    def close(self):
        raw = getattr(self.response, "raw", None)
        connection = getattr(raw, "_connection", None) or getattr(raw, "connection", None)
        sock = getattr(connection, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        threading.Thread(target=self._close_response, daemon=True).start()

    def _close_response(self):
        try:
            self.response.close()
        except Exception:
            pass


@pytest.fixture(scope="module")
def feed_official_dojo(admin_session, example_dojo):
    return marker_dojo(admin_session, "feed_search_dojo.yml", "fs-dojo", official=True)


@pytest.fixture(scope="module")
def feed_hidden_dojo(admin_session, example_dojo):
    return marker_dojo(admin_session, "feed_search_dojo.yml", "fs-dojo", official=False)


@pytest.fixture(scope="module")
def feed_password_dojo(admin_session, example_dojo):
    return marker_dojo(admin_session, "feed_search_password_dojo.yml", "fs-pw-dojo", official=False)


@pytest.fixture(scope="module")
def feed_public_award_dojo(admin_session):
    suffix = token()
    spec = (TEST_DOJOS_LOCATION / "simple_award_dojo.yml").read_text().replace("simple-award", f"simple-award-{suffix}")
    return create_dojo_yml(spec, session=admin_session)


@pytest.fixture(scope="module")
def feed_private_award_dojo(admin_session):
    suffix = token()
    spec = (TEST_DOJOS_LOCATION / "feed_private_award_dojo.yml").read_text().replace("fs-award", f"fs-award-{suffix}")
    return create_dojo_yml(spec, session=admin_session)


@pytest.fixture(scope="module")
def feed_first_blood_dojo(admin_session):
    suffix = token()
    spec = (TEST_DOJOS_LOCATION / "feed_first_blood_dojo.yml").read_text().replace("fs-blood", f"fs-blood-{suffix}")
    return create_dojo_yml(spec, session=admin_session)


def test_feed_container_start_event_carries_challenge_context_and_mode(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        assessment = poll_feed_event(lambda e: e["type"] == "container_start" and e["user_name"] == name)
        assert assessment, f"no container_start event published for {name}"
        assert assessment["user_id"] == user_id, "event must be attributed to the starting user"

        data = assessment["data"]
        assert data["dojo_id"] == example_dojo, f"unexpected dojo_id {data['dojo_id']}"
        assert data["module_id"] == "hello", f"unexpected module_id {data['module_id']}"
        assert data["challenge_id"] == "apple", f"unexpected challenge_id {data['challenge_id']!r}"
        assert data["challenge_name"] == "Apple", f"unexpected challenge_name {data['challenge_name']}"
        assert data["module_name"], "module_name must be populated"
        assert data["dojo_name"], "dojo_name must be populated"
        assert data["mode"] == "assessment", f"a normal start must be assessment mode, got {data['mode']}"

        start_challenge(example_dojo, "hello", "apple", practice=True, session=session)
        practice = poll_feed_event(
            lambda e: e["type"] == "container_start" and e["user_name"] == name and e["data"]["mode"] == "practice"
        )
        assert practice, "practice starts must publish their own container_start event"
        assert practice["id"] != assessment["id"], "practice start must be a distinct event"
        assert practice["data"]["challenge_id"] == data["challenge_id"]
    finally:
        remove_workspace_container(name)


def test_feed_event_challenge_link_resolves(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)

    event = poll_feed_event(lambda e: e["type"] == "challenge_solve" and e["user_name"] == name)
    assert event, f"no challenge_solve event published for {name}"

    data = event["data"]
    link = f"{DOJO_URL}/{data['dojo_id']}/{data['module_id']}/{data['challenge_id']}"
    response = session.get(link)
    assert response.status_code == 200, f"feed event challenge link {link} does not resolve"


def test_feed_container_start_attributed_to_impersonated_user(example_dojo, admin_session, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    before = {event["id"] for event in fetch_feed(limit=100)["data"]}

    try:
        start_challenge(example_dojo, "hello", "apple", session=admin_session, as_user=user_id)
        event = poll_feed_event(
            lambda e: e["type"] == "container_start" and e["id"] not in before and e["user_id"] == user_id
        )
        assert event, "an as_user start must publish an event attributed to the impersonated user"
        assert event["user_name"] == name

        new_starts = [
            e for e in fetch_feed(limit=100)["data"]
            if e["id"] not in before and e["type"] == "container_start"
        ]
        mine = [e for e in new_starts if e["user_id"] == user_id]
        assert len(mine) == 1, f"expected exactly one new container_start for {name}, got {mine}"
        assert not [e for e in new_starts if e["user_name"] == "admin"], \
            "the impersonating admin must not be credited"
    finally:
        remove_workspace_container(name)


def test_feed_publishes_events_for_public_unofficial_dojo(feed_public_award_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{feed_public_award_dojo}/join/").status_code == 200

    try:
        start_challenge(feed_public_award_dojo, "hello", "apple", session=session)
        started = poll_feed_event(lambda e: e["type"] == "container_start" and e["user_name"] == name)
        assert started, "a public (non-official) dojo must publish container_start events"
        assert started["data"]["dojo_id"] == feed_public_award_dojo

        solve_challenge_offline(feed_public_award_dojo, "hello", "apple", session=session, user=name)
        solved = poll_feed_event(lambda e: e["type"] == "challenge_solve" and e["user_name"] == name)
        assert solved, "a public (non-official) dojo must publish challenge_solve events"

        data = solved["data"]
        assert data["dojo_id"] == feed_public_award_dojo
        assert data["module_id"] == "hello"
        assert data["challenge_id"] == "apple", f"unexpected challenge_id {data['challenge_id']!r}"
        assert "module_name" in data and "dojo_name" in data and "challenge_name" in data
        assert data["points"] is None or isinstance(data["points"], int)
        assert isinstance(data["first_blood"], bool), "solve events must carry a first_blood flag"
    finally:
        remove_workspace_container(name)


def test_feed_first_blood_flag_only_for_the_first_solver(feed_first_blood_dojo):
    first_name, first_session = new_user()
    second_name, second_session = new_user()
    for name, session in [(first_name, first_session), (second_name, second_session)]:
        assert session.get(f"{DOJO_URL}/dojo/{feed_first_blood_dojo}/join/").status_code == 200

    solve_challenge_offline(feed_first_blood_dojo, "hello", "apple", session=first_session, user=first_name)
    first_event = poll_feed_event(lambda e: e["type"] == "challenge_solve" and e["user_name"] == first_name)
    assert first_event, f"no challenge_solve event published for {first_name}"
    assert first_event["data"]["dojo_id"] == feed_first_blood_dojo
    assert first_event["data"]["first_blood"] is True, "the first global solver must get first_blood"

    solve_challenge_offline(feed_first_blood_dojo, "hello", "apple", session=second_session, user=second_name)
    second_event = poll_feed_event(lambda e: e["type"] == "challenge_solve" and e["user_name"] == second_name)
    assert second_event, f"no challenge_solve event published for {second_name}"
    assert second_event["data"]["first_blood"] is False, "later solvers must not get first_blood"


def test_feed_suppresses_private_dojo_activity(random_private_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{random_private_dojo}/join/").status_code == 200

    try:
        start_challenge(random_private_dojo, "test-module", "test-challenge", session=session)
        solve_challenge_offline(random_private_dojo, "test-module", "test-challenge", session=session, user=name)
        wait_for_background_worker()
        time.sleep(2)

        leaked = [e for e in fetch_feed(limit=100)["data"] if e["user_name"] == name or e["user_id"] == user_id]
        assert not leaked, f"a private dojo must not publish feed events, got {leaked}"
    finally:
        remove_workspace_container(name)


def test_feed_emoji_earned_event_and_user_emoji_characters(feed_public_award_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{feed_public_award_dojo}/join/").status_code == 200
    for challenge in ["apple", "banana"]:
        solve_challenge_offline(feed_public_award_dojo, "hello", challenge, session=session, user=name)
    wait_for_background_worker()

    event = poll_feed_event(lambda e: e["type"] == "emoji_earned" and e["user_name"] == name)
    assert event, f"completing an award dojo must publish an emoji_earned event for {name}"

    data = event["data"]
    assert data["emoji"] == "\U0001f9ea", f"unexpected emoji {data['emoji']!r}"
    assert data["dojo_id"] == feed_public_award_dojo
    assert data["dojo_name"], "dojo_name must be populated"
    assert data["emoji_name"], "emoji_name must be populated"
    assert data["reason"].startswith("Awarded for completing"), f"unexpected reason {data['reason']!r}"

    assert isinstance(event["user_emojis"], list)
    assert "\U0001f9ea" in event["user_emojis"], (
        f"user_emojis must carry emoji characters, got {event['user_emojis']}"
    )
    assert "CURRENT" not in event["user_emojis"], "user_emojis must not leak award state keywords"


def test_feed_emoji_earned_suppressed_for_private_award_dojo(feed_private_award_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{feed_private_award_dojo}/join/").status_code == 200
    for challenge in ["apple", "banana"]:
        solve_challenge_offline(feed_private_award_dojo, "hello", challenge, session=session, user=name)
    wait_for_background_worker()
    time.sleep(2)

    category = feed_private_award_dojo.split("~", 1)[1]
    granted = int(db_sql(
        f"SELECT count(*) FROM awards WHERE user_id = {user_id} AND type = 'emoji' AND category = '{category}'"
    ))
    assert granted == 1, "the emoji award must still be granted for a private dojo"

    leaked = [e for e in fetch_feed(limit=100)["data"] if e["user_name"] == name]
    assert not leaked, f"a private award dojo must not publish feed events, got {leaked}"


def test_feed_belt_earned_event(example_dojo, belt_dojos, random_user):
    name, session = random_user
    orange_dojo = belt_dojos["orange"].split("~", 1)[0]
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)

    event = poll_feed_event(lambda e: e["type"] == "belt_earned" and e["user_name"] == name)
    assert event, f"earning a belt must publish a belt_earned event for {name}"
    assert event["data"]["belt"] == "orange", f"unexpected belt {event['data']['belt']!r}"
    assert event["data"]["belt_name"] == "Orange Belt", f"unexpected belt_name {event['data']['belt_name']!r}"
    assert event["data"]["dojo_id"] == orange_dojo
    assert "dojo_name" in event["data"]


def test_feed_suppresses_hidden_user_events(example_dojo, random_user):
    name, session = random_user
    assert session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": True}).status_code == 200
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
        wait_for_background_worker()
        time.sleep(2)

        leaked = [e for e in fetch_feed(limit=100)["data"] if e["user_name"] == name or e["user_id"] == user_id]
        assert not leaked, f"hidden users must not appear in the feed, got {leaked}"
    finally:
        remove_workspace_container(name)


def test_feed_event_carries_highest_belt(feed_public_award_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{feed_public_award_dojo}/join/").status_code == 200

    solve_challenge_offline(feed_public_award_dojo, "hello", "apple", session=session, user=name)
    beltless = poll_feed_event(lambda e: e["type"] == "challenge_solve" and e["user_name"] == name)
    assert beltless, f"no challenge_solve event published for {name}"
    assert beltless["user_belt"] is None, f"a beltless user must report no belt, got {beltless['user_belt']!r}"

    db_sql(
        "INSERT INTO awards (user_id, type, name, description, date, value) VALUES "
        f"({user_id}, 'belt', 'orange', 'Orange Belt', NOW(), 0), "
        f"({user_id}, 'belt', 'green', 'Green Belt', NOW(), 0)"
    )

    solve_challenge_offline(feed_public_award_dojo, "hello", "banana", session=session, user=name)
    belted = poll_feed_event(
        lambda e: e["type"] == "challenge_solve" and e["user_name"] == name and e["data"]["challenge_id"] == "banana"
    )
    assert belted, "no challenge_solve event published for the second solve"
    assert belted["user_belt"] == "green", (
        f"the highest held belt must be reported, got {belted['user_belt']!r}"
    )


def test_feed_event_envelope_shape_and_ordering(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    assert poll_feed_event(
        lambda e: e["user_name"] == name and e["data"].get("challenge_id") == "apple"
    ), "the first solve never reached the feed"
    solve_challenge_offline(example_dojo, "hello", "banana", session=session, user=name)
    assert poll_feed_event(
        lambda e: e["user_name"] == name and e["data"].get("challenge_id") == "banana"
    ), "the second solve never reached the feed"

    events = fetch_feed(limit=50)["data"]
    assert events, "the feed must not be empty after publishing events"

    ids = [event["id"] for event in events]
    assert len(ids) == len(set(ids)), "feed event ids must be unique"

    for event in events:
        assert set(event) == EVENT_KEYS, f"unexpected event envelope keys {sorted(event)}"
        uuid.UUID(event["id"])
        assert event["type"] in FEED_EVENT_TYPES, f"unexpected event type {event['type']!r}"
        timestamp = datetime.fromisoformat(event["timestamp"])
        assert timestamp.tzinfo is not None, f"timestamps must be timezone aware, got {event['timestamp']!r}"
        assert isinstance(event["user_id"], int)
        assert isinstance(event["user_name"], str) and event["user_name"]
        assert event["user_belt"] is None or isinstance(event["user_belt"], str)
        assert isinstance(event["user_emojis"], list)
        assert isinstance(event["data"], dict)

    timestamps = [datetime.fromisoformat(event["timestamp"]) for event in events]
    assert timestamps == sorted(timestamps, reverse=True), "feed events must be ordered newest first"

    mine = [event for event in events if event["user_name"] == name]
    apple_index = next(i for i, e in enumerate(mine) if e["data"].get("challenge_id") == "apple")
    banana_index = next(i for i, e in enumerate(mine) if e["data"].get("challenge_id") == "banana")
    assert banana_index < apple_index, "the newer solve must sort ahead of the older one"


def test_feed_has_no_dojo_update_events(feed_official_dojo, admin_session):
    marker = feed_official_dojo["marker"]
    spec = {
        "id": feed_official_dojo["id"],
        "name": f"{marker} Dojo",
        "description": f"This dojo holds {marker} content for search coverage.",
        "modules": [
            {
                "id": "hello-module",
                "name": f"{marker} Hello Module",
                "description": f"This module holds {marker} content for search coverage.",
                "challenges": [
                    {
                        "id": "apple-challenge",
                        "name": f"{marker} Apple Challenge",
                        "description": f"This challenge holds {marker} content for search coverage.",
                        "import": {"dojo": "example", "module": "hello", "challenge": "apple"},
                    }
                ],
            }
        ],
    }
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{feed_official_dojo['rid']}/update", json=spec
    )
    assert response.status_code == 200, f"dojo update failed: {response.status_code} - {response.text[:300]}"
    assert response.json()["success"] is True
    time.sleep(1)

    updates = [event for event in fetch_feed(limit=100)["data"] if event["type"] == "dojo_update"]
    assert not updates, f"no code path publishes dojo_update events, but the feed carried {updates}"


def test_feed_events_limit_and_offset_handling(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    for challenge in ["apple", "banana"]:
        solve_challenge_offline(example_dojo, "hello", challenge, session=session, user=name)
    assert poll_feed_event(lambda e: e["user_name"] == name), "solves never reached the feed"

    clamped = fetch_feed(limit=500)
    assert clamped["meta"]["limit"] == 100, f"limit must clamp to 100, got {clamped['meta']['limit']}"
    assert clamped["meta"]["offset"] == 0
    assert len(clamped["data"]) <= 100
    assert clamped["meta"]["count"] == len(clamped["data"])

    for params in [{"limit": "abc"}, {"offset": "xyz"}, {"limit": "1.5"}, {"limit": "abc", "offset": "3"}]:
        body = fetch_feed(**params)
        assert body["meta"]["limit"] == 50, f"{params} must fall back to limit 50, got {body['meta']}"
        assert body["meta"]["offset"] == 0, f"{params} must fall back to offset 0, got {body['meta']}"
        assert body["meta"]["count"] == len(body["data"])
        assert len(body["data"]) <= 50

    negative = fetch_feed(limit=5, offset=-10)
    baseline = fetch_feed(limit=5, offset=0)
    assert negative["meta"]["offset"] == 0, "a negative offset must clamp to 0"
    if negative["data"] and baseline["data"] and negative["data"][0]["id"] != baseline["data"][0]["id"]:
        negative = fetch_feed(limit=5, offset=-10)
        baseline = fetch_feed(limit=5, offset=0)
    assert [e["id"] for e in negative["data"]] == [e["id"] for e in baseline["data"]]

    empty = fetch_feed(limit=0)
    assert empty["meta"]["limit"] == 0
    assert empty["data"] == [], f"limit=0 must return no events, got {len(empty['data'])}"
    assert empty["meta"]["count"] == 0

    past_end = fetch_feed(limit=10, offset=100000)
    assert past_end["data"] == [], "an offset past the end must return no events"
    assert past_end["meta"]["count"] == 0
    assert past_end["meta"]["offset"] == 100000


def test_feed_events_pagination_offset(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    for challenge in ["apple", "banana"]:
        solve_challenge_offline(example_dojo, "hello", challenge, session=session, user=name)
    solve_challenge_offline(example_dojo, "world", "earth", session=session, user=name)

    deadline = time.time() + 20
    while len(fetch_feed(limit=100)["data"]) < 3 and time.time() < deadline:
        time.sleep(0.3)

    for _ in range(3):
        page = [e["id"] for e in fetch_feed(limit=2, offset=0)["data"]]
        first = [e["id"] for e in fetch_feed(limit=1, offset=0)["data"]]
        second = [e["id"] for e in fetch_feed(limit=1, offset=1)["data"]]
        if page and first and page[0] == first[0]:
            break
    assert len(page) == 2, f"expected two events on the first page, got {page}"
    assert page == first + second, f"offset paging must partition the feed, got {page} vs {first + second}"


def test_feed_events_readable_anonymously_and_persist(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    event = poll_feed_event(lambda e: e["user_name"] == name)
    assert event, f"no feed event published for {name}"

    anonymous = requests.Session()
    for _ in range(5):
        anonymous_ids = [e["id"] for e in fetch_feed(session=anonymous, limit=20)["data"]]
        authenticated_ids = [e["id"] for e in fetch_feed(session=session, limit=20)["data"]]
        if anonymous_ids == authenticated_ids:
            break
    assert event["id"] in anonymous_ids, "the feed must be readable without authentication"
    assert event["id"] in authenticated_ids
    assert anonymous_ids == authenticated_ids, \
        "authenticated and anonymous readers must see the same events"

    for _ in range(3):
        assert event["id"] in [e["id"] for e in fetch_feed(limit=100)["data"]], \
            "events must not be consumed on read"
        time.sleep(1)


def test_feed_ttl_prunes_expired_events():
    probe_name = f"ttlprobe-{token()}"
    member = json.dumps(synthetic_event(probe_name, 0))
    expired_score = time.time() - 200000
    zadd_events([(expired_score, member)])
    try:
        assert redis_cli("ZSCORE", FEED_KEY, member), "the expired probe event was not stored"

        events = fetch_feed(limit=100)["data"]
        assert not [e for e in events if e["user_name"] == probe_name], \
            "events older than FEED_EVENT_TTL must not be returned"
        assert redis_cli("ZSCORE", FEED_KEY, member) == "", \
            "reading the feed must prune events older than FEED_EVENT_TTL"
    finally:
        redis_cli("ZREM", FEED_KEY, member)


def test_feed_publishing_trims_to_max_events(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    probe_name = f"capprobe-{token()}"
    base = time.time() - 3600
    members = [(base + index * 0.001, json.dumps(synthetic_event(probe_name, index))) for index in range(1010)]

    redis_cli("DEL", FEED_KEY)
    try:
        zadd_events(members)
        assert int(redis_cli("ZCARD", FEED_KEY)) == len(members)

        solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
        deadline = time.time() + 20
        while time.time() < deadline:
            stored = int(redis_cli("ZCARD", FEED_KEY))
            if stored <= FEED_MAX_EVENTS:
                break
            time.sleep(0.3)
        assert stored == FEED_MAX_EVENTS, f"publishing must trim the store to {FEED_MAX_EVENTS}, got {stored}"
        assert redis_cli("ZSCORE", FEED_KEY, members[0][1]) == "", "the oldest events must be dropped first"
        assert redis_cli("ZSCORE", FEED_KEY, members[-1][1]) != "", "the newest events must be kept"
    finally:
        redis_cli("ZREMRANGEBYSCORE", FEED_KEY, f"{base - 1:.6f}", f"{base + 2:.6f}")


def test_feed_events_empty_store(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    for _ in range(5):
        redis_cli("DEL", FEED_KEY)
        body = fetch_feed(limit=50)
        if body["data"] == []:
            break
    assert body["data"] == [], "an empty store must return no events"
    assert body["meta"]["count"] == 0

    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    event = poll_feed_event(lambda e: e["user_name"] == name and e["type"] == "challenge_solve")
    assert event, "the feed must recover after its store is cleared"
    assert event["data"]["dojo_id"] == example_dojo


def test_feed_stream_connected_frame_without_authentication():
    anonymous = requests.Session()
    response = anonymous.get(FEED_STREAM_URL, stream=True, timeout=(10, 30), allow_redirects=False)
    try:
        assert response.status_code == 200, f"the stream must be open to anonymous clients, got {response.status_code}"
        assert response.headers["Content-Type"].startswith("text/event-stream")
        assert response.headers["Cache-Control"] == "no-cache"

        first_line = next(line for line in response.iter_lines(decode_unicode=True) if line)
        assert first_line.startswith("data: "), f"unexpected first SSE line {first_line!r}"
        assert json.loads(first_line[len("data: "):]) == {"type": "connected"}
    finally:
        response.close()


def test_feed_stream_fans_out_live_events_to_every_client(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    clients = [StreamReader(), StreamReader()]
    try:
        for index, client in enumerate(clients):
            assert client.wait_for(lambda payload: payload.get("type") == "connected", 10), \
                f"client {index} never received the connected frame"

        solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)

        deadline = time.time() + 25
        delivered = []
        for index, client in enumerate(clients):
            payload = client.wait_for(
                lambda p: p.get("type") == "challenge_solve" and p.get("user_name") == name,
                max(1, deadline - time.time()),
            )
            assert payload, f"client {index} never received the live event"
            delivered.append(payload)

        assert delivered[0]["id"] == delivered[1]["id"], "every client must receive the same event"
        assert delivered[0]["data"]["dojo_id"] == example_dojo
        assert poll_feed_event(lambda e: e["id"] == delivered[0]["id"]), \
            "a streamed event must also be in the persistent store"
    finally:
        for client in clients:
            client.close()


def test_feed_stream_emits_heartbeats():
    started = time.time()
    client = StreamReader()
    try:
        assert client.wait_for(lambda payload: payload.get("type") == "connected", 10), \
            "never received the connected frame"
        budget = 45 - (time.time() - started)
        assert client.wait_for(lambda payload: payload == {"type": "heartbeat"}, budget), \
            "the stream must emit a heartbeat within ~30s"
    finally:
        client.close()


def test_feed_page_accessible_and_respects_account_visibility(random_user_session):
    assert requests.get(FEED_PAGE_URL, allow_redirects=False).status_code == 200
    assert random_user_session.get(FEED_PAGE_URL).status_code == 200

    try:
        flask_exec("from CTFd.utils import set_config\nset_config('account_visibility', 'private')")
        anonymous = requests.get(FEED_PAGE_URL, allow_redirects=False)
        assert anonymous.status_code == 302, \
            f"private account visibility must redirect anonymous users, got {anonymous.status_code}"
        assert "login" in anonymous.headers.get("Location", ""), \
            f"unexpected redirect target {anonymous.headers.get('Location')!r}"
        assert random_user_session.get(FEED_PAGE_URL).status_code == 200, \
            "authenticated users must still see the feed"
    finally:
        flask_exec("from CTFd.utils import set_config\nset_config('account_visibility', 'public')")

    assert requests.get(FEED_PAGE_URL, allow_redirects=False).status_code == 200


def test_feed_page_bootstraps_the_newest_twenty_events():
    probe_name = f"pageprobe-{token()}"
    base = time.time() - 5
    members = [(base + index * 0.01, json.dumps(synthetic_event(probe_name, index))) for index in range(30)]

    zadd_events(members)
    try:
        for _ in range(5):
            events = fetch_feed(limit=30)["data"]
            response = requests.get(FEED_PAGE_URL)
            assert response.status_code == 200
            page = response.text
            if fetch_feed(limit=1)["data"][0]["id"] == events[0]["id"]:
                break
        assert len(events) >= 25, "not enough events to exercise the page bootstrap limit"

        rendered = [event["id"] for event in events if event["id"] in page]
        assert len(rendered) <= 20, f"the feed page must bootstrap at most 20 events, got {len(rendered)}"
        assert all(event["id"] in page for event in events[:20]), \
            "the feed page must bootstrap the newest 20 events"
        assert all(event["id"] not in page for event in events[20:]), \
            "the feed page must not bootstrap events past the newest 20"
    finally:
        redis_cli("ZREMRANGEBYSCORE", FEED_KEY, f"{base - 1:.6f}", f"{base + 2:.6f}")


def test_activity_zero_solves_user(random_user):
    name, _ = random_user
    user_id = get_user_id(name)

    response = requests.get(f"{ACTIVITY_URL}/{user_id}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert response.json() == {"success": True, "data": {"solve_timestamps": [], "total_solves": 0}}


def test_activity_cache_miss_recomputes_and_repopulates(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    wait_for_background_worker()

    cache_key = f"stats:activity:{user_id}"
    redis_cli("DEL", cache_key, f"{cache_key}:updated")
    assert redis_get(cache_key) is None, "the activity cache was not cleared"

    response = requests.get(f"{ACTIVITY_URL}/{user_id}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_solves"] >= 1, f"expected at least one solve, got {data}"
    assert len(data["solve_timestamps"]) == data["total_solves"]

    for timestamp in data["solve_timestamps"]:
        assert timestamp.endswith("Z"), f"activity timestamps must be Z-suffixed, got {timestamp!r}"
        datetime.fromisoformat(timestamp[:-1])
    newest = max(datetime.fromisoformat(t[:-1]) for t in data["solve_timestamps"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs(now - newest) < timedelta(minutes=5), \
        f"the newest solve timestamp {newest} is not close to now"

    deadline = time.time() + 10
    cached = None
    while time.time() < deadline:
        raw = redis_get(cache_key)
        if raw:
            cached = json.loads(raw)
            break
        time.sleep(0.3)
    assert cached is not None, "a cache miss must write the computed activity back to redis"
    assert cached["total_solves"] == data["total_solves"]


def test_activity_only_counts_the_last_365_days(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    wait_for_background_worker()

    cache_key = f"stats:activity:{user_id}"
    solve_rows = f"user_id = {user_id} AND type = 'correct'"
    db_sql(f"UPDATE submissions SET date = NOW() - INTERVAL '400 days' WHERE {solve_rows}")
    redis_cli("DEL", cache_key, f"{cache_key}:updated")

    aged = requests.get(f"{ACTIVITY_URL}/{user_id}").json()
    assert aged["success"] is True
    assert aged["data"]["total_solves"] == 0, f"solves older than 365 days must be excluded, got {aged['data']}"
    assert aged["data"]["solve_timestamps"] == []

    db_sql(f"UPDATE submissions SET date = NOW() WHERE {solve_rows}")
    redis_cli("DEL", cache_key, f"{cache_key}:updated")

    recent = requests.get(f"{ACTIVITY_URL}/{user_id}").json()
    assert recent["data"]["total_solves"] >= 1, \
        f"recent solves must be counted, got {recent['data']}"


def test_activity_counts_private_dojo_solves(random_private_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{random_private_dojo}/join/").status_code == 200
    solve_challenge_offline(random_private_dojo, "test-module", "test-challenge", session=session, user=name)
    wait_for_background_worker()

    cache_key = f"stats:activity:{user_id}"
    redis_cli("DEL", cache_key, f"{cache_key}:updated")

    response = requests.get(f"{ACTIVITY_URL}/{user_id}")
    assert response.status_code == 200
    data = response.json()["data"]
    expected = recent_solve_count(user_id)
    assert expected >= 1, "the private dojo solve was not recorded"
    assert data["total_solves"] == expected, \
        f"activity must count every solve row, expected {expected}, got {data['total_solves']}"


def test_activity_total_matches_db_after_cache_loss(example_dojo, feed_public_award_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{feed_public_award_dojo}/join/").status_code == 200
    for challenge in ["apple", "banana"]:
        solve_challenge_offline(feed_public_award_dojo, "hello", challenge, session=session, user=name)
    wait_for_background_worker()
    time.sleep(1)

    assert requests.get(f"{ACTIVITY_URL}/{user_id}").json()["data"]["total_solves"] == 2

    cache_key = f"stats:activity:{user_id}"
    redis_cli("DEL", cache_key, f"{cache_key}:updated")

    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    wait_for_background_worker()
    time.sleep(2)

    expected = recent_solve_count(user_id)
    assert expected == 3, f"expected three solve rows, got {expected}"
    cached = json.loads(redis_get(cache_key) or "{}")
    assert cached.get("total_solves") == expected, \
        f"the cached activity total must track the database, expected {expected}, got {cached.get('total_solves')}"


def test_activity_worker_recomputes_on_activity_update_event(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    wait_for_background_worker()

    cache_key = f"stats:activity:{user_id}"
    redis_cli("DEL", cache_key, f"{cache_key}:updated")
    published_at = time.time()
    redis_cli("XADD", "stat:events", "*", "data", json.dumps({
        "type": "activity_update",
        "payload": {"user_id": user_id},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))

    deadline = time.time() + 15
    cached = None
    while time.time() < deadline:
        raw = redis_get(cache_key)
        if raw:
            cached = json.loads(raw)
            break
        time.sleep(0.3)
    assert cached is not None, "the worker must recompute activity for an activity_update event"

    expected = recent_solve_count(user_id)
    assert cached["total_solves"] == expected, \
        f"recomputed activity must match the database, expected {expected}, got {cached['total_solves']}"
    updated_at = float(redis_get(f"{cache_key}:updated"))
    assert updated_at >= published_at - 5, \
        f"the cache updated marker {updated_at} predates the event at {published_at}"


def test_activity_worker_ignores_malformed_events(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    wait_for_background_worker()

    cache_key = f"stats:activity:{user_id}"
    redis_cli("DEL", cache_key, f"{cache_key}:updated")

    missing_user = {"type": "activity_update", "payload": {},
                    "timestamp": datetime.now(timezone.utc).isoformat()}
    unknown_user = {"type": "activity_update", "payload": {"user_id": 9999999},
                    "timestamp": datetime.now(timezone.utc).isoformat()}
    real_user = {"type": "activity_update", "payload": {"user_id": user_id},
                 "timestamp": datetime.now(timezone.utc).isoformat()}
    for event in [missing_user, unknown_user, real_user]:
        redis_cli("XADD", "stat:events", "*", "data", json.dumps(event))

    deadline = time.time() + 15
    recovered = False
    while time.time() < deadline:
        if redis_get(cache_key):
            recovered = True
            break
        time.sleep(0.3)
    assert recovered, "the worker must keep consuming after malformed activity_update events"

    assert redis_cli("EXISTS", "stats:activity:9999999") == "0", \
        "an activity_update for an unknown user must not create a cache entry"
    status = dojo_run("docker", "inspect", "stats-worker", "--format", "{{.State.Status}}").stdout.strip()
    assert status == "running", f"the stats worker must survive malformed events, status is {status}"


def test_activity_worker_skips_stale_events(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    wait_for_background_worker()

    cache_key = f"stats:activity:{user_id}"
    try:
        redis_cli("SET", cache_key, json.dumps({"solve_timestamps": [], "total_solves": 4242}))
        redis_cli("SET", f"{cache_key}:updated", f"{time.time() + 3600:.6f}")

        redis_cli("XADD", "stat:events", "*", "data", json.dumps({
            "type": "activity_update",
            "payload": {"user_id": user_id},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        wait_for_background_worker()
        time.sleep(3)

        cached = json.loads(redis_get(cache_key))
        assert cached["total_solves"] == 4242, \
            f"an event older than the cache marker must be skipped, got {cached}"
    finally:
        redis_cli("DEL", cache_key, f"{cache_key}:updated")


def test_search_rejects_short_queries(admin_session, feed_official_dojo):
    for params in [{}, {"q": ""}, {"q": "   "}, {"q": "a"}]:
        response = admin_session.get(SEARCH_URL, params=params)
        assert response.status_code == 400, f"{params} should be rejected, got {response.status_code}"
        assert response.json() == {"success": False, "error": "Query too short."}

    response = admin_session.get(SEARCH_URL, params={"q": "ap"})
    assert response.status_code == 200, "a two character query must be accepted"
    assert response.json()["success"] is True


def test_search_trims_whitespace_and_ignores_case(feed_official_dojo, admin_session):
    marker = feed_official_dojo["marker"]

    trimmed = search_results(marker, session=admin_session)
    padded = search_results(f"   {marker}   ", session=admin_session)
    assert sorted(c["id"] for c in trimmed["challenges"]) == sorted(c["id"] for c in padded["challenges"])
    assert sorted(d["id"] for d in trimmed["dojos"]) == sorted(d["id"] for d in padded["dojos"])

    lower = search_results(marker.lower(), session=admin_session)
    upper = search_results(marker.upper(), session=admin_session)
    mixed = search_results(marker[:3].upper() + marker[3:], session=admin_session)
    for results in [lower, upper, mixed]:
        assert any(d["id"] == feed_official_dojo["rid"] for d in results["dojos"]), \
            "search matching must be case insensitive"
    assert sorted(d["id"] for d in lower["dojos"]) == sorted(d["id"] for d in upper["dojos"])


def test_search_result_shapes_and_links(feed_official_dojo, admin_session):
    reference_id = feed_official_dojo["rid"]
    marker = feed_official_dojo["marker"]
    results = search_results(marker, session=admin_session)

    dojo = next(d for d in results["dojos"] if d["id"] == reference_id)
    assert set(dojo) == {"id", "name", "link", "description"}, f"unexpected dojo result keys {sorted(dojo)}"
    assert dojo["name"] == f"{marker} Dojo"
    assert dojo["link"] == f"/{reference_id}"
    assert marker in dojo["description"]
    assert admin_session.get(f"{DOJO_URL}{dojo['link']}").status_code == 200, "dojo link must resolve"

    module = next(m for m in results["modules"] if m["dojo"]["id"] == reference_id)
    assert set(module) == {"id", "name", "dojo", "link", "description"}, \
        f"unexpected module result keys {sorted(module)}"
    assert set(module["dojo"]) == {"id", "name", "link"}
    assert module["id"] == "hello-module"
    assert module["name"] == f"{marker} Hello Module"
    assert module["link"] == f"/{reference_id}/hello-module"
    assert module["dojo"]["link"] == f"/{reference_id}"
    assert admin_session.get(f"{DOJO_URL}{module['link']}").status_code == 200, "module link must resolve"

    challenge = next(c for c in results["challenges"] if c["dojo"]["id"] == reference_id)
    assert set(challenge) == {"id", "name", "module", "dojo", "link", "description"}, \
        f"unexpected challenge result keys {sorted(challenge)}"
    assert challenge["id"] == "apple-challenge"
    assert challenge["name"] == f"{marker} Apple Challenge"
    assert challenge["module"] == {
        "id": "hello-module",
        "name": f"{marker} Hello Module",
        "link": f"/{reference_id}/hello-module",
    }
    assert challenge["dojo"] == {
        "id": reference_id,
        "name": f"{marker} Dojo",
        "link": f"/{reference_id}",
    }
    assert challenge["link"] == f"/{reference_id}/hello-module/apple-challenge"
    assert admin_session.get(f"{DOJO_URL}{challenge['link']}").status_code == 200, "challenge link must resolve"


def test_search_hides_private_dojos_until_joined(feed_hidden_dojo, admin_session, random_user):
    name, session = random_user
    reference_id = feed_hidden_dojo["rid"]
    marker = feed_hidden_dojo["marker"]

    admin_results = search_results(marker, session=admin_session)
    assert any(d["id"] == reference_id for d in admin_results["dojos"]), \
        "the dojo admin must be able to find their own private dojo"

    for searcher in [session, requests.Session()]:
        results = search_results(marker, session=searcher)
        assert results["dojos"] == [], f"private dojos must be hidden, got {results['dojos']}"
        assert results["modules"] == [], f"private dojo modules must be hidden, got {results['modules']}"
        assert results["challenges"] == [], f"private dojo challenges must be hidden, got {results['challenges']}"

    assert session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
    joined = search_results(marker, session=session)
    assert any(d["id"] == reference_id for d in joined["dojos"]), "members must find the dojo"
    assert any(m["dojo"]["id"] == reference_id for m in joined["modules"]), "members must find its modules"
    assert any(c["dojo"]["id"] == reference_id for c in joined["challenges"]), "members must find its challenges"


def test_search_hides_password_protected_public_dojo(feed_password_dojo, random_user):
    name, session = random_user
    reference_id = feed_password_dojo["rid"]
    marker = feed_password_dojo["marker"]

    hidden = search_results(marker, session=session)
    assert hidden["dojos"] == [], f"password protected dojos must be hidden, got {hidden['dojos']}"
    assert hidden["modules"] == []
    assert hidden["challenges"] == []

    assert session.get(f"{DOJO_URL}/dojo/{reference_id}/join/feedsearchsecret123").status_code == 200
    joined = search_results(marker, session=session)
    assert any(d["id"] == reference_id for d in joined["dojos"]), \
        "the dojo must be searchable once the password has been used to join"


def test_search_works_anonymously(feed_official_dojo, feed_hidden_dojo):
    anonymous = requests.Session()

    public = search_results(feed_official_dojo["marker"], session=anonymous)
    assert any(d["id"] == feed_official_dojo["rid"] for d in public["dojos"]), \
        "anonymous searchers must see official dojos"

    private = search_results(feed_hidden_dojo["marker"], session=anonymous)
    assert private == {"dojos": [], "modules": [], "challenges": []}, \
        f"anonymous searchers must not see private dojos, got {private}"


def test_search_imported_challenge_appears_once_per_dojo(example_dojo, example_import_dojo, admin_session):
    results = search_results("Apple", session=admin_session)
    entries = [c for c in results["challenges"] if c["dojo"]["id"] in (example_dojo, example_import_dojo)]

    dojos = {entry["dojo"]["id"] for entry in entries}
    assert example_dojo in dojos, "the challenge must be listed under its origin dojo"
    assert example_import_dojo in dojos, "the challenge must be listed again under the importing dojo"

    for entry in entries:
        expected = f"/{entry['dojo']['id']}/{entry['module']['id']}/{entry['id']}"
        assert entry["link"] == expected, f"unexpected link {entry['link']}"
        assert admin_session.get(f"{DOJO_URL}{entry['link']}").status_code == 200, \
            f"challenge link {entry['link']} must resolve"


def test_search_escapes_like_wildcards(feed_official_dojo, admin_session):
    control = search_results(feed_official_dojo["marker"], session=admin_session)
    assert any(d["id"] == feed_official_dojo["rid"] for d in control["dojos"]), "the control query must match"

    for query in ["__", "%%"]:
        results = search_results(query, session=admin_session)
        matches = results["dojos"] + results["modules"] + results["challenges"]
        assert matches == [], f"{query!r} must be matched literally, got {len(matches)} results"


def test_search_respects_challenge_visibility_windows(visibility_test_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{visibility_test_dojo}/join/").status_code == 200

    hidden = search_results("Challenge B", session=session)["challenges"]
    assert not [c for c in hidden if c["dojo"]["id"] == visibility_test_dojo and c["id"] == "challenge-b"], \
        "a challenge whose visibility window has not started must not be searchable"

    shown = search_results("Challenge C", session=session)["challenges"]
    assert [c for c in shown if c["dojo"]["id"] == visibility_test_dojo and c["id"] == "challenge-c"], \
        "an unrestricted challenge in the same dojo must still be searchable"


def test_search_respects_module_visibility_windows(visibility_test_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{visibility_test_dojo}/join/").status_code == 200

    modules = search_results("Module 1", session=session)["modules"]
    assert not [m for m in modules if m["dojo"]["id"] == visibility_test_dojo and m["id"] == "module1"], \
        "a module whose visibility window has not started must not be searchable"

    challenges = search_results("Challenge A", session=session)["challenges"]
    assert not [c for c in challenges if c["dojo"]["id"] == visibility_test_dojo and c["id"] == "challenge-a"], \
        "a challenge inside a not-yet-visible module must not be searchable"


def test_search_hides_challenges_of_hidden_modules(hidden_challenges_dojo, admin_session, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{hidden_challenges_dojo}/join/").status_code == 200
    assert "CHALLENGE" not in session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text, \
        "the module page must hide the challenge for this test to mean anything"

    results = search_results("CHALLENGE", session=session)
    assert not [c for c in results["challenges"] if c["dojo"]["id"] == hidden_challenges_dojo], \
        "challenges in a show_challenges: False module must not be searchable by members"
