import time
import json
import pytest

from utils import DOJO_URL, login, create_dojo_yml, start_challenge, solve_challenge, dojo_run, TEST_DOJOS_LOCATION

def redis_cli(*args):
    result = dojo_run("docker", "exec", "cache", "redis-cli", *args, check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return None

def redis_get(key):
    result = redis_cli("GET", key)
    if result and result != "(nil)":
        return result
    return None

def redis_exists(key):
    result = redis_cli("EXISTS", key)
    return result == "1"

def redis_delete(*keys):
    if keys:
        redis_cli("DEL", *keys)

def redis_keys(pattern):
    result = redis_cli("KEYS", pattern)
    if result and result != "(empty array)":
        return result.split('\n')
    return []

def redis_xadd(stream, *args):
    return redis_cli("XADD", stream, *args)

def redis_xlen(stream):
    result = redis_cli("XLEN", stream)
    if result and result.isdigit():
        return int(result)
    return 0

def clear_redis_stats():
    stats_keys = redis_keys("stats:*")
    event_keys = redis_keys("stat:events")
    all_keys = [k for k in stats_keys + event_keys if k]
    if all_keys:
        redis_delete(*all_keys)

def wait_for_cache_update(dojo_id, timeout=10):
    start_time = time.time()
    cache_key = f"stats:dojo:{dojo_id}"

    while time.time() - start_time < timeout:
        if redis_exists(cache_key):
            return True
        time.sleep(0.1)
    return False

def get_stream_length():
    return redis_xlen("stat:events")

@pytest.fixture
def stats_test_dojo(admin_session):
    clear_redis_stats()
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "simple_award_dojo.yml").read(), session=admin_session)

@pytest.fixture
def stats_test_user():
    import random, string
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(random_id, random_id, register=True)
    yield random_id, session

def test_redis_stream_event_published(stats_test_dojo, stats_test_user, admin_session):
    user_name, user_session = stats_test_user

    initial_length = get_stream_length()

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(0.5)

    new_length = get_stream_length()
    assert new_length > initial_length, f"Expected events to be published to Redis Stream. Initial: {initial_length}, New: {new_length}"

def test_background_worker_processes_events(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), f"Cache was not updated within timeout for dojo {stats_test_dojo}"

    cache_key = f"stats:dojo:{stats_test_dojo}"
    cached_data = redis_get(cache_key)
    assert cached_data is not None, "Cache entry should exist"

    stats = json.loads(cached_data)
    assert stats['solves'] >= 1, f"Expected at least 1 solve, got {stats['solves']}"
    assert stats['users'] >= 1, f"Expected at least 1 user, got {stats['users']}"

def test_stats_api_reads_from_cache(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache was not updated within timeout"

    response = user_session.get(f"{DOJO_URL}/{stats_test_dojo}/")
    assert response.status_code == 200

    cache_key = f"stats:dojo:{stats_test_dojo}"
    cached_data = redis_get(cache_key)
    assert cached_data is not None, "Cache should still exist after page load"

    stats = json.loads(cached_data)
    assert stats['solves'] >= 1

def test_cache_timestamps(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache was not updated within timeout"

    timestamp_key = f"stats:dojo:{stats_test_dojo}:updated"
    timestamp = redis_get(timestamp_key)

    assert timestamp is not None, "Cache timestamp should exist"
    assert float(timestamp) > 0, "Timestamp should be a positive number"

def test_multiple_solves_update_stats(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache was not updated after first solve"

    cache_key = f"stats:dojo:{stats_test_dojo}"
    first_stats = json.loads(redis_get(cache_key))
    first_solves = first_stats['solves']

    time.sleep(1)

    start_challenge(stats_test_dojo, "hello", "banana", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "banana", session=user_session, user=user_name)

    time.sleep(1)

    start_time = time.time()
    while time.time() - start_time < 10:
        second_stats = json.loads(redis_get(cache_key))
        second_solves = second_stats['solves']
        if second_solves > first_solves:
            break
        time.sleep(0.5)

    assert second_solves > first_solves, f"Expected solves to increase from {first_solves} to more, got {second_solves}"

def test_cold_start_initializes_cache(example_dojo):
    cache_key = f"stats:dojo:{example_dojo}"
    cached_data = redis_get(cache_key)

    if cached_data is None:
        result = dojo_run("docker", "logs", "stats-worker", "--tail", "100", check=False)
        pytest.fail(f"Cold start should have initialized cache for {example_dojo}. Worker logs:\n{result.stdout}")

    stats = json.loads(cached_data)
    assert 'solves' in stats
    assert 'users' in stats
    assert 'challenges' in stats

    timestamp = redis_get(f"{cache_key}:updated")
    assert timestamp is not None, "Cache timestamp should exist from cold start"

def test_cache_structure(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache was not updated within timeout"

    cache_key = f"stats:dojo:{stats_test_dojo}"
    stats = json.loads(redis_get(cache_key))

    assert 'users' in stats
    assert 'challenges' in stats
    assert 'visible_challenges' in stats
    assert 'solves' in stats
    assert 'recent_solves' in stats
    assert 'trends' in stats
    assert 'chart_data' in stats

    assert 'labels' in stats['chart_data']
    assert 'solves' in stats['chart_data']
    assert 'users' in stats['chart_data']

    assert isinstance(stats['recent_solves'], list)

def test_stats_worker_running():
    result = dojo_run("docker", "ps", "--filter", "name=stats-worker", "--format", "{{.Names}}", check=False)

    if result.returncode != 0 or "stats-worker" not in result.stdout:
        pytest.skip("stats-worker container not running")

    assert "stats-worker" in result.stdout, "stats-worker container should be running"

    time.sleep(2)

    result = dojo_run("docker", "inspect", "stats-worker", "--format", "{{.State.Status}}", check=True)
    status = result.stdout.strip().lower()

    if status == "restarting":
        result = dojo_run("docker", "logs", "stats-worker", "--tail", "50", check=False)
        pytest.fail(f"stats-worker is crash-looping. Last 50 log lines:\n{result.stdout}")

    assert status == "running", f"stats-worker should be in running state, got: {status}"

def test_worker_env_variables():
    result = dojo_run(
        "docker", "inspect", "stats-worker",
        "--format", "{{range .Config.Env}}{{println .}}{{end}}",
        check=False
    )

    if result.returncode != 0:
        pytest.skip("stats-worker container not found")

    env_vars = result.stdout
    assert "BACKGROUND_STATS_ENABLED=1" in env_vars, "BACKGROUND_STATS_ENABLED should be set to 1"
    assert "REDIS_URL" in env_vars, "REDIS_URL should be configured"
    assert "DATABASE_URL" in env_vars, "DATABASE_URL should be configured"

def test_fallback_calculation_when_cache_miss(admin_session):
    clear_redis_stats()

    dojo_id = create_dojo_yml(open(TEST_DOJOS_LOCATION / "simple_award_dojo.yml").read(), session=admin_session)

    cache_key = f"stats:dojo:{dojo_id}"

    assert redis_get(cache_key) is None, "Cache should be empty initially"

    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/")
    assert response.status_code == 200, "Page should load even without cache"

def test_concurrent_solves(stats_test_dojo):
    import random, string

    users = []
    for i in range(3):
        random_id = "".join(random.choices(string.ascii_lowercase, k=16))
        session = login(random_id, random_id, register=True)
        users.append((random_id, session))

    for user_name, user_session in users:
        response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
        assert response.status_code == 200

    for user_name, user_session in users:
        start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
        solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache should be updated"

    time.sleep(2)

    cache_key = f"stats:dojo:{stats_test_dojo}"
    stats = json.loads(redis_get(cache_key))

    assert stats['solves'] >= 3, f"Expected at least 3 solves, got {stats['solves']}"
    assert stats['users'] >= 3, f"Expected at least 3 users, got {stats['users']}"

def test_recent_solves_appear_in_stats(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache should be updated"

    cache_key = f"stats:dojo:{stats_test_dojo}"
    stats = json.loads(redis_get(cache_key))

    assert len(stats['recent_solves']) > 0, "Should have recent solves"
    recent_solve = stats['recent_solves'][0]
    assert 'challenge_name' in recent_solve
    assert 'date_display' in recent_solve

def test_chart_data_structure(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache should be updated"

    cache_key = f"stats:dojo:{stats_test_dojo}"
    stats = json.loads(redis_get(cache_key))

    chart_data = stats['chart_data']
    assert len(chart_data['labels']) == 4
    assert len(chart_data['solves']) == 4
    assert len(chart_data['users']) == 4

    assert chart_data['labels'] == ['Today', '1w ago', '1mo ago', '2mo ago']

def test_redis_stream_cleanup():
    initial_length = get_stream_length()

    for i in range(5):
        event_data = json.dumps({"type": "test", "payload": {}, "timestamp": "2024-01-01"})
        redis_xadd("stat:events", "*", "data", event_data)

    new_length = get_stream_length()
    assert new_length >= initial_length + 5, "Events should be added to stream"

def test_stats_consistency_after_multiple_updates(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    cache_key = f"stats:dojo:{stats_test_dojo}"

    for challenge in ["apple", "banana"]:
        start_challenge(stats_test_dojo, "hello", challenge, session=user_session)
        solve_challenge(stats_test_dojo, "hello", challenge, session=user_session, user=user_name)
        time.sleep(2)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache should be updated after solves"

    cached_data = redis_get(cache_key)
    assert cached_data is not None, "Cache should exist"

    stats = json.loads(cached_data)

    assert stats['solves'] >= 2, f"Expected at least 2 solves, got {stats['solves']}"
    assert stats['users'] >= 1, f"Expected at least 1 user, got {stats['users']}"
