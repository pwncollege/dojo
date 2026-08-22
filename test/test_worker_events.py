import contextlib
import json
import os
import random
import re
import string
import time
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
