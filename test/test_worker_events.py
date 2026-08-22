import contextlib
import json
import os
import random
import re
import string
import time
from datetime import datetime, timezone

import pytest
import yaml

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    challenge_db_id,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    get_user_id,
    login,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
)

STAT_STREAM = "stat:events"
STAT_GROUP = "stats-workers"
IMAGE_STREAM = "image:pull:events"
IMAGE_GROUP = "image-pull-workers"

MISSING_DOJO_ID = 2147483647
MISSING_USER_ID = 99999998
MISSING_CHALLENGE_ID = 99999999

BOGUS_IMAGE = "pwncollege/worker-events-nonexistent-image:latest"

FLASK_MARKER = "--- worker events test output ---"


def _redis_py(body):
    script = (
        "import json, redis\n"
        "r = redis.from_url('redis://cache:6379', decode_responses=True)\n"
        f"{body}\n"
    )
    result = dojo_run("docker", "exec", "ctfd", "python3", "-c", script, check=False)
    assert result.returncode == 0, f"redis helper failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout) if result.stdout.strip() else None


def redis_get(key):
    return _redis_py(f"print(json.dumps(r.get({key!r})))")


def redis_json(key):
    value = redis_get(key)
    return json.loads(value) if value is not None else None


def redis_set(key, value):
    _redis_py(f"r.set({key!r}, {value!r})\nprint(json.dumps(True))")


def redis_delete(*keys):
    if keys:
        _redis_py(f"r.delete(*{list(keys)!r})\nprint(json.dumps(True))")


def redis_exists(key):
    return bool(_redis_py(f"print(json.dumps(r.exists({key!r}) == 1))"))


def stream_add(stream, field, value):
    return _redis_py(f"print(json.dumps(r.xadd({stream!r}, {{{field!r}: {value!r}}})))")


def publish_event(event_type, payload, stream=STAT_STREAM):
    data = json.dumps({"type": event_type, "payload": payload, "timestamp": "worker-events-test"})
    return stream_add(stream, "data", data)


def stream_last_id(stream):
    return _redis_py(
        f"entries = r.xrevrange({stream!r}, '+', '-', count=1)\n"
        "print(json.dumps(entries[0][0] if entries else '0-0'))"
    )


def stream_entries(stream, start="-", end="+"):
    raw = _redis_py(
        f"print(json.dumps([[m[0], m[1].get('data')] for m in r.xrange({stream!r}, {start!r}, {end!r})]))"
    )
    entries = []
    for message_id, data in raw:
        try:
            entries.append((message_id, json.loads(data)))
        except (TypeError, ValueError):
            entries.append((message_id, None))
    return entries


def stream_events_after(stream, last_id):
    return [event for _, event in stream_entries(stream, f"({last_id}") if event is not None]


def stream_has_id(stream, message_id):
    return bool(_redis_py(
        f"print(json.dumps(bool(r.xrange({stream!r}, {message_id!r}, {message_id!r}))))"
    ))


def pending_ids(stream, group):
    return _redis_py(
        f"print(json.dumps([e['message_id'] for e in "
        f"r.xpending_range({stream!r}, {group!r}, min='-', max='+', count=100)]))"
    )


def group_names(stream):
    return _redis_py(f"print(json.dumps([g['name'] for g in r.xinfo_groups({stream!r})]))")


def destroy_group(stream, group):
    return _redis_py(f"print(json.dumps(r.xgroup_destroy({stream!r}, {group!r})))")


def ack_and_delete(stream, group, message_id):
    _redis_py(
        f"r.xack({stream!r}, {group!r}, {message_id!r})\n"
        f"r.xdel({stream!r}, {message_id!r})\n"
        "print(json.dumps(True))"
    )


def container_status(name):
    result = dojo_run("docker", "inspect", name, "--format", "{{.State.Status}}", check=False)
    return result.stdout.strip()


def container_logs_since(name, since):
    result = dojo_run("docker", "logs", name, "--since", str(since - 2), check=False)
    return result.stdout + result.stderr


@contextlib.contextmanager
def paused(name):
    dojo_run("docker", "pause", name)
    try:
        yield
    finally:
        dojo_run("docker", "unpause", name, check=False)


def run_in_ctfd(code):
    script = f"print({FLASK_MARKER!r}, flush=True)\n{code}"
    path = f"/tmp/dojo-test-worker-events-{os.getpid()}.py"
    dojo_run("docker", "exec", "-i", "ctfd", "sh", "-c", f"cat > {path}", input=script)
    # The marker is the snippet's first statement, so a missing marker means the app never
    # booted (the shared host occasionally cannot spare the memory) rather than a test failure.
    for attempt in range(3):
        result = dojo_run("docker", "exec", "ctfd", "flask", "shell", "--", path, check=False)
        output = result.stdout + result.stderr
        if FLASK_MARKER in output:
            break
        time.sleep(2)
    assert FLASK_MARKER in output, f"in-app snippet produced no output:\n{output}"
    output = output.split(FLASK_MARKER, 1)[1]
    assert "RESULT:OK" in output, f"in-app assertions failed:\n{output}"
    return output


def worker_barrier(barrier_user_id, timeout=45):
    """Publish a marker event and wait for the worker to process it.

    The worker consumes the stream in order, so once the marker's effect is
    visible every event published before it has already been handled.
    """
    key = f"stats:activity:{barrier_user_id}:updated"
    before = redis_get(key)
    publish_event("activity_update", {"user_id": barrier_user_id})
    deadline = time.time() + timeout
    while time.time() < deadline:
        if redis_get(key) != before:
            return True
        time.sleep(0.3)
    return False


def recalculate_dojo_stats(dojo_id, reference_id, timeout=45):
    key = f"stats:dojo:{reference_id}"
    before = redis_get(f"{key}:updated")
    publish_event("dojo_stats_update", {"dojo_id": dojo_id})
    deadline = time.time() + timeout
    while time.time() < deadline:
        if redis_get(f"{key}:updated") != before:
            return redis_json(key)
        time.sleep(0.3)
    raise AssertionError(f"dojo stats for {reference_id} were not recalculated within {timeout}s")


def join_dojo(session, dojo):
    response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200, f"failed to join {dojo}: {response.status_code}"


@pytest.fixture(scope="module")
def worker_events_dojo(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = open(TEST_DOJOS_LOCATION / "worker_events_dojo.yml").read().replace(
        "id: worker-events", f"id: worker-events-{suffix}"
    )
    return create_dojo_yml(spec, session=admin_session)


@pytest.fixture(scope="module")
def worker_events_import_dojo(admin_session, example_dojo):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = open(TEST_DOJOS_LOCATION / "worker_events_import.yml").read().replace(
        "id: worker-events-import", f"id: worker-events-import-{suffix}"
    )
    return create_dojo_yml(spec, session=admin_session)


@pytest.fixture(scope="module")
def barrier_user():
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    login(name, name, register=True)
    return get_user_id(name)


def test_queued_stat_events_defer_until_after_request():
    run_in_ctfd("""
from flask import current_app
from CTFd.plugins.dojo_plugin.utils.events import queue_stat_event, publish_queued_events
hooks = [func.__name__ for func in current_app.after_request_funcs.get(None, [])]
assert "publish_stat_events_after_request" in hooks, f"queued events are never flushed: {hooks}"
calls = []
with current_app.test_request_context("/"):
    queue_stat_event(lambda: calls.append(1))
    queue_stat_event(lambda: calls.append(2))
    assert calls == [], f"queued events published before the request finished: {calls}"
    publish_queued_events()
    assert calls == [1, 2], f"queued events not published once in FIFO order: {calls}"
    publish_queued_events()
    assert calls == [1, 2], f"second flush re-published already published events: {calls}"
with current_app.test_request_context("/"):
    publish_queued_events()
print("RESULT:OK")
""")


def test_publish_stat_event_swallows_redis_errors():
    run_in_ctfd("""
import redis
from unittest.mock import MagicMock, patch
from CTFd.plugins.dojo_plugin.utils import background_stats as bs
broken = MagicMock()
broken.xadd.side_effect = redis.ConnectionError("down")
with patch.object(bs, "get_redis_client", return_value=broken):
    result = bs.publish_stat_event("dojo_stats_update", {"dojo_id": 1})
assert result is None, f"expected None when redis is unavailable, got {result!r}"
assert broken.xadd.called, "publish_stat_event never attempted to write to the stream"
print("RESULT:OK")
""")


def test_handler_registry_covers_published_event_types():
    run_in_ctfd("""
from CTFd.plugins.dojo_plugin.worker.handlers import EVENT_HANDLERS, handle_stat_event
handle_stat_event("__force_lazy_load__", {}, 0.0)
expected = {
    "challenge_solve", "dojo_stats_update", "scoreboard_update", "scores_update",
    "belts_update", "emojis_update", "activity_update", "container_stats_update",
}
assert set(EVENT_HANDLERS) == expected, f"handler registry mismatch: {sorted(EVENT_HANDLERS)}"
assert all(callable(handler) for handler in EVENT_HANDLERS.values()), "non-callable handler registered"
print("RESULT:OK")
""")


def test_daily_restart_exits_consume_loop():
    run_in_ctfd("""
from unittest.mock import patch
from CTFd.plugins.dojo_plugin.utils import background_stats as bs
handled = []
with patch.object(bs, "should_daily_restart", return_value=True):
    try:
        bs.consume_stat_events(handler=lambda *args: handled.append(args), batch_size=1, block_ms=100)
        raise AssertionError("consume_stat_events returned instead of raising DailyRestartException")
    except bs.DailyRestartException:
        pass
assert handled == [], f"events were consumed before the daily restart check: {handled}"
print("RESULT:OK")
""")


def test_no_op_updates_publish_no_stat_events(random_private_dojo, random_user):
    dojo_id = dojo_db_id(random_private_dojo)
    user_id = get_user_id(random_user[0])
    run_in_ctfd(f"""
from unittest.mock import MagicMock, patch
from flask import current_app
from CTFd.models import Users, db
from CTFd.plugins.dojo_plugin.models import Dojos
from CTFd.plugins.dojo_plugin.utils import events
from CTFd.plugins.dojo_plugin.utils.events import publish_queued_events
with current_app.test_request_context("/"):
    with patch.object(events, "publish_stat_event", MagicMock()) as publish:
        dojo = Dojos.query.get({dojo_id})
        assert dojo is not None, "test dojo is missing"
        original_name = dojo.name
        dojo.name = original_name
        db.session.commit()
        publish_queued_events()
        assert publish.call_count == 0, f"no-op dojo update published {{publish.call_count}} events"
        dojo.name = original_name + " (touched)"
        db.session.commit()
        publish_queued_events()
        types = [call[0][0] for call in publish.call_args_list]
        assert types == ["dojo_stats_update", "scoreboard_update", "scores_update"], \\
            f"unexpected events for a real dojo update: {{types}}"
        for call in publish.call_args_list:
            assert call[0][1].get("dojo_id", call[0][1].get("model_id")) == {dojo_id}, \\
                f"event payload targets the wrong dojo: {{call[0][1]}}"
        publish.reset_mock()
        dojo.name = original_name
        db.session.commit()
        publish_queued_events()
        publish.reset_mock()
        user = Users.query.get({user_id})
        assert user is not None, "test user is missing"
        original_user_name = user.name
        user.name = original_user_name + "x"
        db.session.commit()
        publish_queued_events()
        assert publish.call_count == 0, \\
            f"user update published stat events: {{[c[0][0] for c in publish.call_args_list]}}"
        user.name = original_user_name
        db.session.commit()
        publish_queued_events()
print("RESULT:OK")
""")


def test_cold_start_dojo_stats_failure_is_isolated(worker_events_dojo):
    dojo_id = dojo_db_id(worker_events_dojo)
    redis_delete(f"stats:dojo:{worker_events_dojo}", f"stats:dojo:{worker_events_dojo}:updated")
    run_in_ctfd(f"""
from unittest.mock import MagicMock, patch
from CTFd.plugins.dojo_plugin.models import Dojos
from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat
from CTFd.plugins.dojo_plugin.worker.handlers import dojo_stats as ds
dojo = Dojos.query.get({dojo_id})
assert dojo is not None, "test dojo is missing"
real_calculate = ds.calculate_dojo_stats
attempted = []
def flaky(target):
    attempted.append(target.reference_id)
    if len(attempted) == 1:
        raise RuntimeError("boom")
    return real_calculate(target)
fake_dojos = MagicMock()
fake_dojos.query.all.return_value = [dojo, dojo]
with patch.object(ds, "Dojos", fake_dojos):
    with patch.object(ds, "calculate_dojo_stats", flaky):
        ds.initialize_all_dojo_stats()
assert len(attempted) == 2, f"cold start aborted after the first failure: {{attempted}}"
cached = get_cached_stat("stats:dojo:" + dojo.reference_id)
assert cached is not None, "later dojos were not initialized after an earlier failure"
assert "solves" in cached, f"unexpected cached stats payload: {{cached}}"
print("RESULT:OK")
""")
    assert redis_exists(f"stats:dojo:{worker_events_dojo}"), "stats cache should have been rebuilt"


def test_container_stats_handler_error_preserves_cache():
    run_in_ctfd("""
from unittest.mock import patch
from CTFd.plugins.dojo_plugin.worker.handlers import containers as c
with patch.object(c, "get_all_containers", side_effect=RuntimeError("boom")):
    with patch.object(c, "set_cached_stat") as set_cached:
        c.handle_container_stats_update({}, None)
        assert set_cached.call_count == 0, \\
            f"container cache was overwritten after an enumeration failure: {set_cached.call_args_list}"
print("RESULT:OK")
""")


def test_solve_publishes_single_challenge_solve_event(worker_events_dojo, random_user, barrier_user):
    user_name, session = random_user
    join_dojo(session, worker_events_dojo)
    user_id = get_user_id(user_name)
    challenge_id = challenge_db_id(worker_events_dojo, "hello", "apple")

    with paused("stats-worker"):
        last_id = stream_last_id(STAT_STREAM)
        solve_challenge_offline(worker_events_dojo, "hello", "apple", session=session, user=user_name)
        entries = [
            (message_id, event)
            for message_id, event in stream_entries(STAT_STREAM, f"({last_id}")
            if event and event.get("type") == "challenge_solve"
            and event.get("payload", {}).get("user_id") == user_id
        ]

    assert len(entries) == 1, f"expected exactly one challenge_solve event, got {len(entries)}"
    message_id, event = entries[0]
    payload = event["payload"]
    assert payload["challenge_id"] == challenge_id, \
        f"challenge_solve carried challenge_id={payload['challenge_id']}, expected {challenge_id}"
    solve_date = payload.get("solve_date")
    assert solve_date and solve_date.endswith("Z"), f"solve_date is not ISO-8601 with Z: {solve_date!r}"
    parsed = datetime.fromisoformat(solve_date.rstrip("Z"))
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((now_utc - parsed).total_seconds()) < 300, \
        f"solve_date {solve_date} is not close to the solve time"

    assert worker_barrier(barrier_user), "worker did not drain events queued while it was paused"
    assert not stream_has_id(STAT_STREAM, message_id), \
        "handled event was not removed from the stream (xackdel)"
    assert message_id not in pending_ids(STAT_STREAM, STAT_GROUP), \
        "handled event was left in the consumer group's pending list"

    activity = redis_json(f"stats:activity:{user_id}")
    assert activity is not None, "activity cache should exist after the solve"
    assert solve_date in activity["solve_timestamps"], \
        f"solve was not timestamped with the event's solve_date: {activity['solve_timestamps']}"


def test_dojo_create_promote_and_prune_publish_events(admin_session, barrier_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = open(TEST_DOJOS_LOCATION / "worker_events_dojo.yml").read().replace(
        "id: worker-events", f"id: worker-events-life-{suffix}"
    )

    with paused("stats-worker"):
        last_id = stream_last_id(STAT_STREAM)
        reference_id = create_dojo_yml(spec, session=admin_session)
        dojo_id = dojo_db_id(reference_id)
        created_events = stream_events_after(STAT_STREAM, last_id)

        last_id = stream_last_id(STAT_STREAM)
        response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/promote", json={})
        assert response.status_code == 200, f"promote failed: {response.status_code} {response.text}"
        promoted_events = stream_events_after(STAT_STREAM, last_id)

        official_id = reference_id.split("~", 1)[0]
        last_id = stream_last_id(STAT_STREAM)
        response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{official_id}/awards/prune", json={})
        assert response.status_code == 200, f"prune failed: {response.status_code} {response.text}"
        assert "pruned_awards" in response.json(), f"prune response missing pruned_awards: {response.json()}"
        pruned_events = stream_events_after(STAT_STREAM, last_id)

    def types_for(events):
        return [
            event["type"] for event in events
            if event["payload"].get("dojo_id") == dojo_id or event["payload"].get("model_id") == dojo_id
        ]

    assert set(types_for(created_events)) == {"dojo_stats_update", "scoreboard_update", "scores_update"}, \
        f"dojo creation published {types_for(created_events)}"
    scoreboard_events = [
        event for event in created_events
        if event["type"] == "scoreboard_update" and event["payload"].get("model_id") == dojo_id
    ]
    assert len(scoreboard_events) == 1, f"expected one scoreboard event on create, got {len(scoreboard_events)}"
    assert scoreboard_events[0]["payload"]["model_type"] == "dojo", \
        f"scoreboard event has the wrong model_type: {scoreboard_events[0]['payload']}"

    assert set(types_for(promoted_events)) == {"dojo_stats_update", "scoreboard_update", "scores_update"}, \
        f"dojo promotion published {types_for(promoted_events)}"

    assert sorted(set(types_for(pruned_events))) == ["dojo_stats_update", "scoreboard_update"], \
        f"awards prune published {types_for(pruned_events)}"

    assert worker_barrier(barrier_user), "worker did not drain the events queued while it was paused"
    deadline = time.time() + 30
    while time.time() < deadline and not redis_exists(f"stats:dojo:{official_id}"):
        time.sleep(0.5)
    stats = redis_json(f"stats:dojo:{official_id}")
    assert stats is not None, "promotion should populate stats under the new (official) reference id"
    assert "solves" in stats and "challenges" in stats, f"unexpected stats payload: {stats}"


def test_unknown_and_failing_events_do_not_wedge_worker(barrier_user):
    start = time.time()
    unknown_id = publish_event("totally_unknown_worker_events_type", {"x": 1})
    poison_id = publish_event("challenge_solve", {
        "user_id": barrier_user,
        "challenge_id": MISSING_CHALLENGE_ID,
        "solve_date": "not-a-real-date",
    })

    assert worker_barrier(barrier_user), "worker stopped processing events"

    logs = container_logs_since("stats-worker", start)
    assert "No handler registered for event type: totally_unknown_worker_events_type" in logs, \
        "unknown event type was not logged as unhandled"
    assert "Error handling event challenge_solve" in logs, \
        "handler exception was not caught and logged by handle_stat_event"

    for message_id in (unknown_id, poison_id):
        assert not stream_has_id(STAT_STREAM, message_id), f"event {message_id} was not acked+deleted"
    pending = pending_ids(STAT_STREAM, STAT_GROUP)
    assert unknown_id not in pending and poison_id not in pending, \
        f"unhandled/failed events were left pending: {pending}"
    assert container_status("stats-worker") == "running", "stats-worker died on a bad event"


def test_malformed_stream_entry_stays_pending(barrier_user):
    start = time.time()
    message_id = stream_add(STAT_STREAM, "data", "{this is not json")
    try:
        assert worker_barrier(barrier_user), "worker stopped consuming after a malformed entry"
        logs = container_logs_since("stats-worker", start)
        assert f"Error processing event {message_id}" in logs, "malformed entry was not logged as an error"
        assert stream_has_id(STAT_STREAM, message_id), "malformed entry should not be deleted from the stream"
        assert message_id in pending_ids(STAT_STREAM, STAT_GROUP), \
            "malformed entry should remain in the consumer group's pending list"
        assert container_status("stats-worker") == "running", "stats-worker died on a malformed entry"
    finally:
        ack_and_delete(STAT_STREAM, STAT_GROUP, message_id)
    assert not stream_has_id(STAT_STREAM, message_id)


def test_consumer_group_recreated_after_destroy(barrier_user):
    assert STAT_GROUP in group_names(STAT_STREAM), "stats consumer group missing before the test"
    started_at = dojo_run(
        "docker", "inspect", "stats-worker", "--format", "{{.State.StartedAt}}"
    ).stdout.strip()

    assert destroy_group(STAT_STREAM, STAT_GROUP) == 1, "consumer group was not destroyed"

    assert worker_barrier(barrier_user, timeout=50), \
        "worker did not recover from NOGROUP and resume processing"
    assert STAT_GROUP in group_names(STAT_STREAM), "consumer group was not recreated"
    assert container_status("stats-worker") == "running", "stats-worker died after NOGROUP"
    assert dojo_run(
        "docker", "inspect", "stats-worker", "--format", "{{.State.StartedAt}}"
    ).stdout.strip() == started_at, "stats-worker restarted instead of recreating the group"


def test_challenge_solve_missing_fields_is_noop(barrier_user):
    assert int(db_sql(f"SELECT COUNT(*) FROM users WHERE id = {MISSING_USER_ID}")) == 0
    start = time.time()
    message_ids = [
        publish_event("challenge_solve", {}),
        publish_event("challenge_solve", {"user_id": MISSING_USER_ID}),
        publish_event("challenge_solve", {"challenge_id": MISSING_CHALLENGE_ID}),
    ]

    assert worker_barrier(barrier_user), "worker stopped processing events"

    logs = container_logs_since("stats-worker", start)
    assert logs.count("challenge_solve event missing required fields") >= 3, \
        "incomplete challenge_solve events were not all rejected"
    assert not redis_exists(f"stats:activity:{MISSING_USER_ID}"), \
        "an incomplete challenge_solve created an activity cache"
    for message_id in message_ids:
        assert not stream_has_id(STAT_STREAM, message_id), f"event {message_id} was not acked+deleted"


def test_dojo_stats_update_missing_or_deleted_dojo_is_noop(barrier_user):
    assert int(db_sql(f"SELECT COUNT(*) FROM dojos WHERE dojo_id = {MISSING_DOJO_ID}")) == 0
    start = time.time()
    message_ids = [
        publish_event("dojo_stats_update", {}),
        publish_event("dojo_stats_update", {"dojo_id": MISSING_DOJO_ID}),
    ]

    assert worker_barrier(barrier_user), "worker stopped processing events"

    logs = container_logs_since("stats-worker", start)
    assert "dojo_stats_update event missing dojo_id" in logs, "empty dojo_stats_update was not rejected"
    assert f"Dojo not found for dojo_id={MISSING_DOJO_ID}" in logs, \
        "dojo_stats_update for a deleted dojo was not skipped"
    for message_id in message_ids:
        assert not stream_has_id(STAT_STREAM, message_id), f"event {message_id} was not acked+deleted"
    assert container_status("stats-worker") == "running"


def test_scoreboard_update_invalid_payloads_are_noop(barrier_user):
    start = time.time()
    message_ids = [
        publish_event("scoreboard_update", {}),
        publish_event("scoreboard_update", {"model_type": "galaxy", "model_id": 1}),
        publish_event("scoreboard_update", {"model_type": "dojo", "model_id": MISSING_DOJO_ID}),
        publish_event("scoreboard_update", {
            "model_type": "module", "model_id": {"dojo_id": MISSING_DOJO_ID, "module_index": 0},
        }),
    ]

    assert worker_barrier(barrier_user), "worker stopped processing events"

    logs = container_logs_since("stats-worker", start)
    assert "scoreboard_update event missing model_type or model_id" in logs
    assert "Unknown model_type: galaxy" in logs
    assert f"Dojo not found for dojo_id {MISSING_DOJO_ID}" in logs
    assert "Module not found for id" in logs
    for suffix in ("", ":0"):
        assert not redis_exists(f"stats:scoreboard:dojo:{MISSING_DOJO_ID}{suffix}"), \
            "an invalid scoreboard_update created a scoreboard cache"
    assert not redis_exists(f"stats:scoreboard:module:{MISSING_DOJO_ID}:0:0")
    for message_id in message_ids:
        assert not stream_has_id(STAT_STREAM, message_id), f"event {message_id} was not acked+deleted"
    assert container_status("stats-worker") == "running"


def test_scoreboard_update_accepts_module_composite_id(worker_events_dojo, random_user, barrier_user):
    user_name, session = random_user
    join_dojo(session, worker_events_dojo)
    user_id = get_user_id(user_name)
    dojo_id = dojo_db_id(worker_events_dojo)
    apple_id = challenge_db_id(worker_events_dojo, "hello", "apple")
    bonus_id = challenge_db_id(worker_events_dojo, "hello", "bonus")

    solve_challenge_offline(worker_events_dojo, "hello", "apple", session=session, user=user_name)
    assert worker_barrier(barrier_user), "solve event was not processed"

    keys = [f"stats:scoreboard:module:{dojo_id}:0:{duration}" for duration in (0, 7, 30)]
    keys += [f"stats:crews:module:{dojo_id}:0:0", f"stats:challenge_solves:module:{dojo_id}:0"]
    redis_delete(*(keys + [f"{key}:updated" for key in keys]))
    for key in keys:
        assert not redis_exists(key), f"failed to clear {key}"

    publish_event("scoreboard_update", {
        "model_type": "module", "model_id": {"dojo_id": dojo_id, "module_index": 0},
    })
    assert worker_barrier(barrier_user), "scoreboard_update was not processed"

    for key in keys:
        assert redis_exists(key), f"{key} was not rebuilt from a composite module id"

    scoreboard = redis_json(f"stats:scoreboard:module:{dojo_id}:0:0")
    entry = next((item for item in scoreboard if item["user_id"] == user_id), None)
    assert entry is not None, f"solving user missing from the rebuilt module scoreboard: {scoreboard}"
    assert entry["solves"] >= 1, f"solving user has no solves in the scoreboard: {entry}"
    assert [item["rank"] for item in scoreboard] == list(range(1, len(scoreboard) + 1)), \
        "rebuilt scoreboard ranks are not contiguous"

    challenge_solves = redis_json(f"stats:challenge_solves:module:{dojo_id}:0")
    assert challenge_solves.get(str(apple_id), 0) >= 1, \
        f"challenge_solves missing the solved challenge: {challenge_solves}"
    assert str(bonus_id) not in challenge_solves, \
        f"challenge_solves counted a non-required challenge: {challenge_solves}"


def test_activity_update_recomputes_from_database(worker_events_dojo, random_user, barrier_user):
    user_name, session = random_user
    join_dojo(session, worker_events_dojo)
    user_id = get_user_id(user_name)

    solve_challenge_offline(worker_events_dojo, "hello", "apple", session=session, user=user_name)
    assert worker_barrier(barrier_user), "solve event was not processed"

    solve_count = int(db_sql(
        f"SELECT COUNT(*) FROM submissions WHERE user_id = {user_id} AND type = 'correct'"
    ))
    assert solve_count >= 1, "expected the offline solve to be recorded"

    cache_key = f"stats:activity:{user_id}"
    redis_set(cache_key, json.dumps({"solve_timestamps": [], "total_solves": 999}))

    start = time.time()
    publish_event("activity_update", {"user_id": user_id})
    deadline = time.time() + 45
    activity = None
    while time.time() < deadline:
        activity = redis_json(cache_key)
        if activity and activity["total_solves"] != 999:
            break
        time.sleep(0.3)
    assert activity is not None and activity["total_solves"] == solve_count, \
        f"activity_update did not recompute from the database: {activity}"
    assert len(activity["solve_timestamps"]) == solve_count, \
        f"timestamp count does not match the database: {activity}"

    message_ids = [
        publish_event("activity_update", {}),
        publish_event("activity_update", {"user_id": MISSING_USER_ID}),
    ]
    assert worker_barrier(barrier_user), "worker stopped processing events"
    logs = container_logs_since("stats-worker", start)
    assert "activity_update event missing user_id" in logs
    assert f"User not found for user_id {MISSING_USER_ID}" in logs
    assert not redis_exists(f"stats:activity:{MISSING_USER_ID}"), \
        "activity_update created a cache for a nonexistent user"
    for message_id in message_ids:
        assert not stream_has_id(STAT_STREAM, message_id)


def test_full_recalculation_corrects_incremental_drift(worker_events_dojo, random_user, barrier_user):
    user_name, session = random_user
    join_dojo(session, worker_events_dojo)
    user_id = get_user_id(user_name)
    dojo_id = dojo_db_id(worker_events_dojo)
    challenge_id = challenge_db_id(worker_events_dojo, "hello", "apple")

    solve_challenge_offline(worker_events_dojo, "hello", "apple", session=session, user=user_name)
    assert worker_barrier(barrier_user), "solve event was not processed"

    baseline = recalculate_dojo_stats(dojo_id, worker_events_dojo)["solves"]

    for _ in range(3):
        publish_event("challenge_solve", {"user_id": user_id, "challenge_id": challenge_id})
    assert worker_barrier(barrier_user), "duplicate solve events were not processed"

    drifted = redis_json(f"stats:dojo:{worker_events_dojo}")["solves"]
    assert drifted == baseline + 3, \
        f"incremental solve updates are not additive: {baseline} -> {drifted}"

    corrected = recalculate_dojo_stats(dojo_id, worker_events_dojo)["solves"]
    assert corrected == baseline, \
        f"full recalculation did not restore the authoritative count: {corrected} != {baseline}"


def test_activity_updated_even_when_dojo_updates_skipped(random_user, barrier_user):
    assert int(db_sql(
        f"SELECT COUNT(*) FROM dojo_challenges WHERE challenge_id = {MISSING_CHALLENGE_ID}"
    )) == 0
    user_name, _ = random_user
    user_id = get_user_id(user_name)
    cache_key = f"stats:activity:{user_id}"
    redis_delete(cache_key, f"{cache_key}:updated")

    start = time.time()
    publish_event("challenge_solve", {"user_id": user_id, "challenge_id": MISSING_CHALLENGE_ID})
    assert worker_barrier(barrier_user), "worker stopped processing events"

    logs = container_logs_since("stats-worker", start)
    assert f"Found 0 dojo(s) containing challenge_id={MISSING_CHALLENGE_ID}" in logs, \
        "solve handler did not report an orphan challenge"
    activity = redis_json(cache_key)
    assert activity is not None, "activity should be updated even when no dojo matches the challenge"
    solve_rows = int(db_sql(f"SELECT COUNT(*) FROM solves WHERE user_id = {user_id}").strip())
    assert activity["total_solves"] == solve_rows, \
        f"a rebuilt activity cache must match the database ({solve_rows} solves): {activity}"
    assert len(activity["solve_timestamps"]) == solve_rows, f"unexpected activity payload: {activity}"


def test_stale_event_skips_dojo_stats_write(worker_events_dojo, random_user, barrier_user):
    user_name, session = random_user
    join_dojo(session, worker_events_dojo)
    user_id = get_user_id(user_name)
    dojo_id = dojo_db_id(worker_events_dojo)
    challenge_id = challenge_db_id(worker_events_dojo, "hello", "apple")
    cache_key = f"stats:dojo:{worker_events_dojo}"

    recalculate_dojo_stats(dojo_id, worker_events_dojo)
    sentinel = {
        "users": 0, "challenges": 0, "visible_challenges": 0, "solves": 12345,
        "recent_solves": [], "trends": {},
        "chart_data": {"labels": [], "solves": [], "users": []},
    }
    try:
        redis_set(cache_key, json.dumps(sentinel))
        redis_set(f"{cache_key}:updated", str(time.time() + 300))

        start = time.time()
        publish_event("challenge_solve", {"user_id": user_id, "challenge_id": challenge_id})
        assert worker_barrier(barrier_user), "worker stopped processing events"

        assert redis_json(cache_key)["solves"] == 12345, \
            "a stale challenge_solve event overwrote newer cached dojo stats"
        logs = container_logs_since("stats-worker", start)
        assert f"Skipping stale event for {cache_key}" in logs, "staleness guard did not fire"
    finally:
        redis_delete(cache_key, f"{cache_key}:updated")
        recalculate_dojo_stats(dojo_id, worker_events_dojo)


def test_stale_event_skips_container_stats_write(barrier_user):
    cache_key = "stats:containers"
    sentinel = [{"dojo": "worker-events-sentinel", "module": None, "challenge": None}]
    try:
        redis_set(cache_key, json.dumps(sentinel))
        redis_set(f"{cache_key}:updated", str(time.time() + 300))

        start = time.time()
        publish_event("container_stats_update", {})
        assert worker_barrier(barrier_user), "worker stopped processing events"

        assert redis_json(cache_key) == sentinel, \
            "a stale container_stats_update overwrote the newer cached container list"
        logs = container_logs_since("stats-worker", start)
        assert f"Skipping stale event for {cache_key}" in logs, "staleness guard did not fire"
    finally:
        redis_delete(cache_key, f"{cache_key}:updated")
        publish_event("container_stats_update", {})
        worker_barrier(barrier_user)


def test_incremental_updates_on_empty_caches(worker_events_dojo, random_user, barrier_user):
    user_name, session = random_user
    join_dojo(session, worker_events_dojo)
    user_id = get_user_id(user_name)
    dojo_id = dojo_db_id(worker_events_dojo)

    assert worker_barrier(barrier_user), "worker did not drain earlier events"
    stats_key = f"stats:dojo:{worker_events_dojo}"
    solves_key = f"stats:challenge_solves:module:{dojo_id}:0"
    dojo_scores_key = f"stats:scores:dojo:{dojo_id}"
    module_scores_key = f"stats:scores:module:{dojo_id}:0"
    activity_key = f"stats:activity:{user_id}"
    cleared = [stats_key, solves_key, dojo_scores_key, module_scores_key, activity_key]
    redis_delete(*(cleared + [f"{key}:updated" for key in cleared]))

    start = time.time()
    solve_challenge_offline(worker_events_dojo, "hello", "apple", session=session, user=user_name)
    assert worker_barrier(barrier_user), "solve event was not processed"

    logs = container_logs_since("stats-worker", start)
    assert not redis_exists(stats_key), "incremental solve path fabricated a dojo stats cache"
    assert f"No cached stats for dojo {worker_events_dojo}" in logs, \
        "missing dojo stats cache was not reported as skipped"
    assert not redis_exists(solves_key), "incremental solve path fabricated a challenge_solves cache"
    assert f"No cached challenge_solves for dojo {dojo_id} module 0" in logs, \
        "missing challenge_solves cache was not reported as skipped"

    dojo_scores = redis_json(dojo_scores_key)
    assert dojo_scores is not None, "dojo scores cache should be seeded from empty on a solve"
    assert user_id in dojo_scores["ranks"], f"solver missing from dojo scores: {dojo_scores}"
    assert dojo_scores["solves"][str(user_id)] == 1, f"unexpected dojo scores: {dojo_scores}"

    module_scores = redis_json(module_scores_key)
    assert module_scores is not None, "module scores cache should be seeded from empty on a solve"
    assert module_scores["solves"][str(user_id)] == 1, f"unexpected module scores: {module_scores}"

    activity = redis_json(activity_key)
    assert activity is not None and activity["total_solves"] == 1, f"unexpected activity: {activity}"

    response = session.get(f"{DOJO_URL}/{worker_events_dojo}/hello/")
    assert response.status_code == 200, "module page should fall back to a database count"

    recalculate_dojo_stats(dojo_id, worker_events_dojo)


def test_non_member_solve_skips_dojo_updates(random_private_dojo, random_user, barrier_user):
    user_name, _ = random_user
    user_id = get_user_id(user_name)
    dojo_id = dojo_db_id(random_private_dojo)
    challenge_id = challenge_db_id(random_private_dojo, "test-module", "test-challenge")

    stats_before = recalculate_dojo_stats(dojo_id, random_private_dojo)
    redis_delete(f"stats:activity:{user_id}", f"stats:activity:{user_id}:updated")

    start = time.time()
    publish_event("challenge_solve", {"user_id": user_id, "challenge_id": challenge_id})
    assert worker_barrier(barrier_user), "worker stopped processing events"

    logs = container_logs_since("stats-worker", start)
    assert f"User {user_id} is not a member of dojo {random_private_dojo}" in logs, \
        "non-member solve was not skipped"

    stats_after = redis_json(f"stats:dojo:{random_private_dojo}")
    assert stats_after["solves"] == stats_before["solves"], \
        "non-member solve changed the dojo stats cache"
    scoreboard = redis_json(f"stats:scoreboard:dojo:{dojo_id}:0") or []
    assert not any(entry["user_id"] == user_id for entry in scoreboard), \
        "non-member solve added the user to the dojo scoreboard"
    activity = redis_json(f"stats:activity:{user_id}")
    solve_rows = int(db_sql(f"SELECT COUNT(*) FROM solves WHERE user_id = {user_id}").strip())
    assert activity is not None and activity["total_solves"] == solve_rows, \
        f"activity should still be updated for a non-member solve: {activity}"


def test_private_dojo_solve_skips_scores_cache(random_private_dojo, random_user, barrier_user):
    user_name, session = random_user
    join_dojo(session, random_private_dojo)
    user_id = get_user_id(user_name)
    dojo_id = dojo_db_id(random_private_dojo)

    assert worker_barrier(barrier_user), "worker did not drain the dojo creation events"
    scores_key = f"stats:scores:dojo:{dojo_id}"
    redis_delete(scores_key, f"{scores_key}:updated")

    start = time.time()
    solve_challenge_offline(random_private_dojo, "test-module", "test-challenge",
                            session=session, user=user_name)
    assert worker_barrier(barrier_user), "solve event was not processed"

    logs = container_logs_since("stats-worker", start)
    assert (f"Dojo {random_private_dojo} is not public or official, or challenge Test Challenge is optional; "
            "skipping scores update") in logs, \
        "scores update was not skipped for a private dojo"
    assert not redis_exists(scores_key), "a private dojo solve created a scores cache"

    scoreboard = redis_json(f"stats:scoreboard:dojo:{dojo_id}:0") or []
    entry = next((item for item in scoreboard if item["user_id"] == user_id), None)
    assert entry is not None, f"member solve missing from the private dojo scoreboard: {scoreboard}"
    assert entry["solves"] == 1, f"unexpected scoreboard entry: {entry}"


def test_non_required_challenge_solve_skips_updates(worker_events_dojo, random_user, barrier_user):
    user_name, session = random_user
    join_dojo(session, worker_events_dojo)
    user_id = get_user_id(user_name)
    dojo_id = dojo_db_id(worker_events_dojo)
    bonus_id = challenge_db_id(worker_events_dojo, "hello", "bonus")

    stats_before = recalculate_dojo_stats(dojo_id, worker_events_dojo)
    solves_key = f"stats:challenge_solves:module:{dojo_id}:0"
    activity_key = f"stats:activity:{user_id}"
    redis_delete(activity_key, f"{activity_key}:updated")

    solve_challenge_offline(worker_events_dojo, "hello", "bonus", session=session, user=user_name)
    assert worker_barrier(barrier_user), "solve event was not processed"

    stats_after = redis_json(f"stats:dojo:{worker_events_dojo}")
    assert stats_after["solves"] == stats_before["solves"], \
        "solving a non-required challenge changed the dojo stats cache"
    scoreboard = redis_json(f"stats:scoreboard:dojo:{dojo_id}:0") or []
    assert not any(entry["user_id"] == user_id for entry in scoreboard), \
        "solving a non-required challenge added the user to the dojo scoreboard"
    challenge_solves = redis_json(solves_key) or {}
    assert str(bonus_id) not in challenge_solves, \
        f"non-required challenge counted in challenge_solves: {challenge_solves}"
    activity = redis_json(activity_key)
    assert activity is not None and activity["total_solves"] == 1, \
        f"activity should be updated for a non-required solve: {activity}"


def test_imported_challenge_updates_every_containing_dojo(example_dojo, worker_events_import_dojo,
                                                          random_user, barrier_user):
    import_dojo = worker_events_import_dojo
    user_name, session = random_user
    join_dojo(session, example_dojo)
    join_dojo(session, import_dojo)
    user_id = get_user_id(user_name)
    example_id = dojo_db_id(example_dojo)
    import_id = dojo_db_id(import_dojo)
    assert int(db_sql(
        f"SELECT COUNT(*) FROM dojo_users WHERE dojo_id = {import_id} AND user_id = {user_id}"
    )) == 1, "user did not become a member of the importing dojo"
    challenge_id = challenge_db_id(example_dojo, "hello", "apple")

    example_before = recalculate_dojo_stats(example_id, example_dojo)["solves"]
    import_before = recalculate_dojo_stats(import_id, import_dojo)["solves"]

    start = time.time()
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=user_name)
    assert worker_barrier(barrier_user), "solve event was not processed"

    logs = container_logs_since("stats-worker", start)
    match = re.search(rf"Found (\d+) dojo\(s\) containing challenge_id={challenge_id}", logs)
    assert match, "solve handler did not report the dojos containing the imported challenge"
    assert int(match.group(1)) >= 2, \
        f"imported challenge was only fanned out to {match.group(1)} dojo(s)"

    assert redis_json(f"stats:dojo:{example_dojo}")["solves"] >= example_before + 1, \
        "source dojo stats did not count the solve"
    assert redis_json(f"stats:dojo:{import_dojo}")["solves"] >= import_before + 1, \
        "importing dojo stats did not count the solve"

    for dojo_id, label in ((example_id, example_dojo), (import_id, import_dojo)):
        scoreboard = redis_json(f"stats:scoreboard:dojo:{dojo_id}:0") or []
        entry = next((item for item in scoreboard if item["user_id"] == user_id), None)
        assert entry is not None, f"solver missing from the {label} scoreboard"
        assert entry["solves"] >= 1, f"solver has no solves in the {label} scoreboard: {entry}"


def test_deleted_dojo_events_are_noops_and_cache_is_orphaned(admin_session, barrier_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = open(TEST_DOJOS_LOCATION / "worker_events_dojo.yml").read().replace(
        "id: worker-events", f"id: worker-events-del-{suffix}"
    )
    reference_id = create_dojo_yml(spec, session=admin_session)
    dojo_id = dojo_db_id(reference_id)
    recalculate_dojo_stats(dojo_id, reference_id)
    assert redis_exists(f"stats:dojo:{reference_id}"), "dojo stats cache should exist before deletion"

    response = admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={})
    assert response.status_code == 200, f"delete failed: {response.status_code} {response.text}"
    assert response.json()["success"], f"delete failed: {response.json()}"
    assert int(db_sql(f"SELECT COUNT(*) FROM dojos WHERE dojo_id = {dojo_id}")) == 0, \
        "dojo row was not deleted"

    start = time.time()
    message_ids = [
        publish_event("dojo_stats_update", {"dojo_id": dojo_id}),
        publish_event("scoreboard_update", {"model_type": "dojo", "model_id": dojo_id}),
        publish_event("scores_update", {"dojo_id": dojo_id}),
    ]
    assert worker_barrier(barrier_user), "worker stopped processing events after a dojo deletion"

    logs = container_logs_since("stats-worker", start)
    assert f"Dojo not found for dojo_id={dojo_id}" in logs, "dojo_stats_update did not skip a deleted dojo"
    assert f"Dojo not found for dojo_id {dojo_id}" in logs, "scoreboard_update did not skip a deleted dojo"
    assert f"Dojo {dojo_id} not found, skipping scores update" in logs, \
        "scores_update did not skip a deleted dojo"
    assert container_status("stats-worker") == "running", "stats-worker died on a deleted dojo"
    for message_id in message_ids:
        assert not stream_has_id(STAT_STREAM, message_id), f"event {message_id} was not acked+deleted"
    assert redis_exists(f"stats:dojo:{reference_id}"), \
        "deleting a dojo currently leaves its stats cache behind (no invalidation path)"


def test_dojo_delete_publishes_cache_refresh_events(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = open(TEST_DOJOS_LOCATION / "worker_events_dojo.yml").read().replace(
        "id: worker-events", f"id: worker-events-delev-{suffix}"
    )
    reference_id = create_dojo_yml(spec, session=admin_session)
    dojo_id = dojo_db_id(reference_id)

    with paused("stats-worker"):
        last_id = stream_last_id(STAT_STREAM)
        response = admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={})
        assert response.status_code == 200, f"delete failed: {response.status_code} {response.text}"
        events = stream_events_after(STAT_STREAM, last_id)

    types = {
        event["type"] for event in events
        if event["payload"].get("dojo_id") == dojo_id or event["payload"].get("model_id") == dojo_id
    }
    assert types == {"dojo_stats_update", "scoreboard_update", "scores_update"}, \
        f"dojo deletion published {sorted(types)}"


def test_corrupt_cache_values_fall_back_cleanly(worker_events_dojo, admin_session, barrier_user):
    dojo_id = dojo_db_id(worker_events_dojo)
    stats_key = f"stats:dojo:{worker_events_dojo}"
    scoreboard_key = f"stats:scoreboard:dojo:{dojo_id}:0"
    crews_key = f"stats:crews:dojo:{dojo_id}:0"
    try:
        redis_set(stats_key, "{not json")
        redis_set(scoreboard_key, "###")
        redis_set(crews_key, "###")

        response = admin_session.get(f"{DOJO_URL}/{worker_events_dojo}/")
        assert response.status_code == 200, "dojo page should survive an unparseable stats cache"

        response = admin_session.get(
            f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{worker_events_dojo}/_/0/1"
        )
        assert response.status_code == 200, "scoreboard API should survive an unparseable cache"
        assert response.json()["standings"] == [], \
            f"unparseable scoreboard cache should read as empty: {response.json()['standings']}"
    finally:
        redis_delete(stats_key, f"{stats_key}:updated",
                     scoreboard_key, f"{scoreboard_key}:updated",
                     crews_key, f"{crews_key}:updated")
        publish_event("scoreboard_update", {"model_type": "dojo", "model_id": dojo_id})
        recalculate_dojo_stats(dojo_id, worker_events_dojo)


def test_container_stats_track_challenge_lifecycle(random_private_dojo, random_user):
    user_name, session = random_user
    join_dojo(session, random_private_dojo)
    entry = {"dojo": random_private_dojo, "module": "test-module", "challenge": "test-challenge"}

    def wait_for_entry(present, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            containers = redis_json("stats:containers") or []
            if (entry in containers) == present:
                return containers
            time.sleep(0.5)
        return None

    remove_workspace_container(user_name)
    try:
        # Container starts occasionally hit a transient 502 from the reverse proxy.
        for attempt in range(3):
            try:
                start_challenge(random_private_dojo, "test-module", "test-challenge", session=session)
                break
            except AssertionError:
                if attempt == 2:
                    raise
                time.sleep(3)
        containers = wait_for_entry(True)
        assert containers is not None, \
            "container stats never listed the started private-dojo container"
        assert containers.count(entry) == 1, f"container listed {containers.count(entry)} times"

        response = session.delete(f"{DOJO_URL}/pwncollege_api/v1/docker", json={})
        assert response.status_code == 200, f"stop failed: {response.status_code} {response.text}"
        assert response.json()["success"], f"stop failed: {response.json()}"

        assert wait_for_entry(False) is not None, \
            "container stats still list a stopped container"
    finally:
        remove_workspace_container(user_name)


def test_stats_stream_has_no_autoclaim_recovery():
    run_in_ctfd("""
import json, time
from unittest.mock import patch
from CTFd.plugins.dojo_plugin.utils import background_stats as bs
stream = "test:stat:events:" + str(int(time.time() * 1000))
group = "test-stats-workers"
r = bs.get_redis_client()
r.xgroup_create(stream, group, id="0", mkstream=True)
message_id = r.xadd(stream, {"data": json.dumps({"type": "orphan", "payload": {}, "timestamp": "t"})})
r.xreadgroup(group, "dead-consumer", {stream: ">"}, count=1)
received = []
started = time.time()
with patch.object(bs, "REDIS_STREAM_NAME", stream), patch.object(bs, "CONSUMER_GROUP", group), \\
     patch.object(bs, "should_daily_restart", lambda start_time: time.time() - started > 4):
    try:
        bs.consume_stat_events(handler=lambda *args: received.append(args), batch_size=5, block_ms=200)
        raise AssertionError("consumer loop exited without the restart sentinel")
    except bs.DailyRestartException:
        pass
assert received == [], f"orphaned pending message was unexpectedly reclaimed: {received}"
pending = r.xpending_range(stream, group, min="-", max="+", count=10)
assert len(pending) == 1, f"expected the orphan to stay pending, got {pending}"
assert pending[0]["consumer"] == "dead-consumer", f"unexpected pending owner: {pending}"
assert r.xlen(stream) == 1, "orphaned message should still be in the stream"
r.delete(stream)
print("RESULT:OK")
""")


def test_worker_drains_events_published_while_offline():
    run_in_ctfd("""
import json, time
from unittest.mock import patch
from CTFd.plugins.dojo_plugin.utils import background_stats as bs
stream = "test:stat:drain:" + str(int(time.time() * 1000))
group = "test-stats-workers"
r = bs.get_redis_client()
r.xgroup_create(stream, group, id="0", mkstream=True)
for index in range(3):
    r.xadd(stream, {"data": json.dumps({"type": "activity_update", "payload": {"n": index}, "timestamp": "t"})})
assert r.xlen(stream) == 3, "events published without a consumer should accumulate"
received = []
started = time.time()
with patch.object(bs, "REDIS_STREAM_NAME", stream), patch.object(bs, "CONSUMER_GROUP", group), \\
     patch.object(bs, "should_daily_restart", lambda start_time: time.time() - started > 3):
    try:
        bs.consume_stat_events(handler=lambda *args: received.append(args), batch_size=5, block_ms=200)
        raise AssertionError("consumer loop exited without the restart sentinel")
    except bs.DailyRestartException:
        pass
assert [args[1]["n"] for args in received] == [0, 1, 2], f"backlog not drained in order: {received}"
assert r.xlen(stream) == 0, "handled events should be removed from the stream"
assert r.xpending(stream, group)["pending"] == 0, "handled events should not stay pending"
r.delete(stream)
print("RESULT:OK")
""")


def test_image_pull_worker_container_healthy():
    result = dojo_run("docker", "ps", "--filter", "name=image-pull-worker", "--format", "{{.Names}}")
    assert "image-pull-worker" in result.stdout, "image-pull-worker container is not running"
    status = container_status("image-pull-worker")
    if status == "restarting":
        logs = dojo_run("docker", "logs", "image-pull-worker", "--tail", "50", check=False)
        pytest.fail(f"image-pull-worker is crash-looping:\n{logs.stdout}\n{logs.stderr}")
    assert status == "running", f"image-pull-worker should be running, got {status}"
    assert IMAGE_GROUP in group_names(IMAGE_STREAM), \
        "image pull consumer group was never created"
    logs = dojo_run("docker", "logs", "image-pull-worker", check=False)
    assert "Image pull worker" in (logs.stdout + logs.stderr), \
        "image-pull-worker never announced that it was consuming events"


def test_image_pull_invalid_message_acked_and_deleted():
    start = time.time()
    message_ids = [
        stream_add(IMAGE_STREAM, "notdata", "x"),
        stream_add(IMAGE_STREAM, "data", "{broken"),
    ]
    deadline = time.time() + 45
    while time.time() < deadline:
        if not any(stream_has_id(IMAGE_STREAM, message_id) for message_id in message_ids):
            break
        time.sleep(0.5)

    for message_id in message_ids:
        assert not stream_has_id(IMAGE_STREAM, message_id), \
            f"invalid image pull event {message_id} was not deleted"
    pending = pending_ids(IMAGE_STREAM, IMAGE_GROUP)
    assert not any(message_id in pending for message_id in message_ids), \
        f"invalid image pull events were left pending: {pending}"
    logs = container_logs_since("image-pull-worker", start)
    assert "Invalid image pull event" in logs, "invalid image pull event was not logged"
    assert container_status("image-pull-worker") == "running", \
        "image-pull-worker died on an invalid message"


def test_image_pull_enqueue_dedups_and_filters_images(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = {
        "id": f"worker-events-pull-{suffix}",
        "name": "Worker Events Pull Dojo",
        "type": "topic",
        "modules": [{
            "id": "images",
            "name": "Images",
            "challenges": [
                {"id": "one", "name": "One", "image": BOGUS_IMAGE},
                {"id": "two", "name": "Two", "image": BOGUS_IMAGE},
                {"id": "three", "name": "Three", "image": "pwncollege-local-worker-events"},
                {"id": "four", "name": "Four", "image": "mac:sonoma"},
            ],
        }],
    }
    update_spec = json.loads(json.dumps(spec))
    update_spec["modules"][0]["challenges"][2]["image"] = BOGUS_IMAGE

    with paused("image-pull-worker"):
        last_id = stream_last_id(IMAGE_STREAM)
        reference_id = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
        created = [event for event in stream_events_after(IMAGE_STREAM, last_id)
                   if event.get("dojo_reference_id") == reference_id]

        assert len(created) == 1, f"expected one deduplicated/filtered image pull, got {created}"
        assert created[0]["image"] == BOGUS_IMAGE, f"unexpected image enqueued: {created[0]}"
        assert created[0]["attempt"] == 0, f"unexpected initial attempt: {created[0]}"
        assert created[0]["max_attempts"] == 5, f"unexpected max_attempts: {created[0]}"

        last_id = stream_last_id(IMAGE_STREAM)
        response = admin_session.post(
            f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update", json=update_spec
        )
        assert response.status_code == 200, f"update failed: {response.status_code} {response.text}"
        assert response.json()["success"], f"update failed: {response.json()}"
        updated = [event for event in stream_events_after(IMAGE_STREAM, last_id)
                   if event.get("dojo_reference_id") == reference_id]
        assert updated, "dojo update did not re-enqueue image pulls"
        assert all(event["image"] == BOGUS_IMAGE for event in updated), \
            f"unexpected images enqueued on update: {updated}"


def test_image_pull_handler_skips_without_docker():
    run_in_ctfd("""
from unittest.mock import patch
from CTFd.plugins.dojo_plugin.worker.handlers import image_pulls as h
with patch.object(h, "all_docker_clients", side_effect=AssertionError("docker must not be contacted")):
    assert h.handle_image_pull_event({}) == (True, False), "event without an image should be skipped"
    assert h.handle_image_pull_event({"image": "mac:sonoma"}) == (True, False), "mac images should be skipped"
    assert h.handle_image_pull_event({"image": "pwncollege-local"}) == (True, False), \\
        "locally built images should be skipped"
print("RESULT:OK")
""")


def test_image_pull_retries_with_backoff_then_drops():
    run_in_ctfd("""
import time
from unittest.mock import patch
from CTFd.plugins.dojo_plugin.utils import image_pulls as ip

class StopLoop(Exception):
    pass

class DeadlineClient:
    def __init__(self, client, deadline):
        self._client = client
        self._deadline = deadline
    def __getattr__(self, name):
        return getattr(self._client, name)
    def xreadgroup(self, *args, **kwargs):
        if time.time() > self._deadline:
            raise StopLoop()
        return self._client.xreadgroup(*args, **kwargs)

def drive(stream, handler, seconds):
    real = ip.get_redis_client()
    client = DeadlineClient(real, time.time() + seconds)
    with patch.object(ip, "IMAGE_PULL_STREAM_NAME", stream), \\
         patch.object(ip, "CONSUMER_GROUP", "test-pull-group"), \\
         patch.object(ip, "PENDING_IDLE_MS", 60000), \\
         patch.object(ip, "get_redis_client", return_value=client):
        ip.publish_image_pull("img/x", dojo_reference_id="d", attempt=0, max_attempts=2)
        try:
            ip.consume_image_pull_events(handler=handler, batch_size=5, block_ms=200)
        except StopLoop:
            pass
    return real

import json
r = ip.get_redis_client()
retry_stream = "test:image:pull:retry:" + str(int(time.time() * 1000))
attempts = []
def failing_handler(event):
    attempts.append(event["attempt"])
    return False, True
drive(retry_stream, failing_handler, 12)
assert attempts == [0, 1], f"expected one backoff retry then a drop, got {attempts}"
assert r.xlen(retry_stream) == 0, "dropped image pull left messages in the stream"
r.delete(retry_stream)

drop_stream = "test:image:pull:drop:" + str(int(time.time() * 1000))
seen = []
def fatal_handler(event):
    seen.append(event["attempt"])
    return False, False
drive(drop_stream, fatal_handler, 6)
assert seen == [0], f"non-retryable failure should not be re-published, got {seen}"
assert r.xlen(drop_stream) == 0, "non-retryable failure left messages in the stream"
r.delete(drop_stream)
print("RESULT:OK")
""")


def test_image_pull_autoclaims_orphaned_pending():
    run_in_ctfd("""
import json, time
from unittest.mock import patch
from CTFd.plugins.dojo_plugin.utils import image_pulls as ip

class StopLoop(Exception):
    pass

class DeadlineClient:
    def __init__(self, client, deadline):
        self._client = client
        self._deadline = deadline
    def __getattr__(self, name):
        return getattr(self._client, name)
    def xreadgroup(self, *args, **kwargs):
        if time.time() > self._deadline:
            raise StopLoop()
        return self._client.xreadgroup(*args, **kwargs)

r = ip.get_redis_client()
stream = "test:image:pull:claim:" + str(int(time.time() * 1000))
group = "test-pull-group"
r.xgroup_create(stream, group, id="0", mkstream=True)
r.xadd(stream, {"data": json.dumps({"image": "img/orphan", "attempt": 0, "max_attempts": 5})})
r.xreadgroup(group, "dead-consumer", {stream: ">"}, count=1)
assert r.xpending(stream, group)["pending"] == 1, "failed to orphan the message"
handled = []
client = DeadlineClient(r, time.time() + 4)
with patch.object(ip, "IMAGE_PULL_STREAM_NAME", stream), \\
     patch.object(ip, "CONSUMER_GROUP", group), \\
     patch.object(ip, "PENDING_IDLE_MS", 0), \\
     patch.object(ip, "get_redis_client", return_value=client):
    try:
        ip.consume_image_pull_events(handler=lambda event: handled.append(event["image"]) or True,
                                     batch_size=5, block_ms=200)
    except StopLoop:
        pass
assert handled == ["img/orphan"], f"orphaned image pull was not reclaimed: {handled}"
assert r.xpending(stream, group)["pending"] == 0, "reclaimed message was not acked"
assert r.xlen(stream) == 0, "reclaimed message was not deleted"
r.delete(stream)
print("RESULT:OK")
""")


def kill_stray_workers():
    dojo_run("docker", "exec", "ctfd", "python3", "-c", """
import os, signal
pattern = "dojo_plugin/worker/" + "__main" + "__.py"
me = os.getpid()
for entry in os.listdir("/proc"):
    if not entry.isdigit() or int(entry) == me:
        continue
    try:
        cmdline = open("/proc/" + entry + "/cmdline", "rb").read().decode(errors="replace")
    except OSError:
        continue
    if pattern in cmdline:
        os.kill(int(entry), signal.SIGKILL)
""", check=False)


def test_skip_cold_start_env_skips_initialization():
    # The throwaway worker must never join the live consumer group (it would silently steal and
    # ack events), so it is pointed at an unused redis database. SIGTERM only sets a flag the
    # worker never checks, so it also has to be killed outright.
    kill_stray_workers()
    try:
        result = dojo_run(
            "docker", "exec",
            "-e", "SKIP_COLD_START=1",
            "-e", "REDIS_URL=redis://cache:6379/9",
            "ctfd", "timeout", "-s", "KILL", "15", "flask", "shell",
            "/opt/CTFd/CTFd/plugins/dojo_plugin/worker/__main__.py",
            check=False,
        )
    finally:
        kill_stray_workers()
    output = result.stdout + result.stderr
    assert "SKIP_COLD_START set, skipping cache initialization" in output, output
    assert "Starting event consumption loop" in output, output
    assert "Performing cold start cache initialization" not in output, output
    assert "Cold start complete" not in output, output
