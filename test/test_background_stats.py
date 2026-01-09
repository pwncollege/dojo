import time
import json
import pytest

from utils import DOJO_URL, DOJO_CONTAINER, login, create_dojo_yml, start_challenge, solve_challenge, dojo_run, TEST_DOJOS_LOCATION

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
    all_keys = [k for k in stats_keys if k]
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


def wait_for_cache_timestamp_updated(cache_key_prefix, after_time=None, timeout=10):
    if after_time is None:
        after_time = time.time()

    start_time = time.time()
    timestamp_key = f"{cache_key_prefix}:updated"

    while time.time() - start_time < timeout:
        timestamp_str = redis_get(timestamp_key)
        if timestamp_str:
            try:
                timestamp = float(timestamp_str)
                if timestamp >= after_time:
                    return True
            except ValueError:
                pass
        time.sleep(0.1)
    return False

def wait_for_background_update(dojo_reference_id=None, dojo_id=None, timeout=10):
    before_time = time.time()

    if dojo_id is not None:
        cache_patterns = [
            f"stats:scoreboard:dojo:{dojo_id}:0",
            f"stats:dojo:{dojo_reference_id}" if dojo_reference_id else None
        ]
    elif dojo_reference_id is not None:
        cache_patterns = [f"stats:dojo:{dojo_reference_id}"]
    else:
        raise ValueError("Must provide either dojo_reference_id or dojo_id")

    cache_patterns = [p for p in cache_patterns if p]

    for pattern in cache_patterns:
        if wait_for_cache_timestamp_updated(pattern, after_time=before_time, timeout=timeout):
            return True

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

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    cache_key = f"stats:dojo:{stats_test_dojo}"
    start_time = time.time()
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            stats = json.loads(cached_data)
            if stats.get('solves', 0) >= 1:
                break
        time.sleep(0.5)

    cached_data = redis_get(cache_key)
    assert cached_data is not None, "Event should have been published and processed (cache updated)"
    stats = json.loads(cached_data)
    assert stats.get('solves', 0) >= 1, "Event should have been processed and stats updated"

def test_background_worker_processes_events(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    cache_key = f"stats:dojo:{stats_test_dojo}"

    start_time = time.time()
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            stats = json.loads(cached_data)
            if stats.get('solves', 0) >= 1:
                break
        time.sleep(0.5)

    cached_data = redis_get(cache_key)
    assert cached_data is not None, "Cache entry should exist"

    stats = json.loads(cached_data)
    assert stats['solves'] >= 1, f"Expected at least 1 solve, got {stats['solves']}"
    assert len(stats['recent_solves']) >= 1, "Should have recent solves after incremental update"
    assert stats['recent_solves'][0]['challenge_name'] == 'Apple', "Most recent solve should be Apple"

def test_stats_api_reads_from_cache(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    cache_key = f"stats:dojo:{stats_test_dojo}"

    start_time = time.time()
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            stats = json.loads(cached_data)
            if stats.get('solves', 0) >= 1:
                break
        time.sleep(0.5)

    response = user_session.get(f"{DOJO_URL}/{stats_test_dojo}/")
    assert response.status_code == 200

    cached_data = redis_get(cache_key)
    assert cached_data is not None, "Cache should still exist after page load"

    stats = json.loads(cached_data)
    assert stats['solves'] >= 1, f"Expected at least 1 solve, got {stats['solves']}"

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
    assert "REDIS_URL" in env_vars, "REDIS_URL should be configured"
    assert "DATABASE_URL" in env_vars, "DATABASE_URL should be configured"

def test_fallback_calculation_when_cache_miss(admin_session):
    clear_redis_stats()

    dojo_id = create_dojo_yml(open(TEST_DOJOS_LOCATION / "simple_award_dojo.yml").read(), session=admin_session)

    time.sleep(2)

    cache_key = f"stats:dojo:{dojo_id}"
    redis_delete(cache_key, f"{cache_key}:updated")

    assert redis_get(cache_key) is None, "Cache should be empty after deletion"

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

    cache_key = f"stats:dojo:{stats_test_dojo}"

    start_time = time.time()
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            stats = json.loads(cached_data)
            if stats.get('solves', 0) >= 3:
                break
        time.sleep(0.5)

    stats = json.loads(redis_get(cache_key))
    assert stats['solves'] >= 3, f"Expected at least 3 solves, got {stats['solves']}"
    assert len(stats['recent_solves']) >= 3, "Should have at least 3 recent solves"

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
    for i in range(5):
        event_data = json.dumps({"type": "test", "payload": {}, "timestamp": "2024-01-01"})
        redis_xadd("stat:events", "*", "data", event_data)

    time.sleep(3)

    final_length = get_stream_length()
    assert final_length < 10, f"Stream should be cleaned up after processing (xackdel). Length: {final_length}"

def test_stats_consistency_after_multiple_updates(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    cache_key = f"stats:dojo:{stats_test_dojo}"

    for challenge in ["apple", "banana"]:
        start_challenge(stats_test_dojo, "hello", challenge, session=user_session)
        solve_challenge(stats_test_dojo, "hello", challenge, session=user_session, user=user_name)
        time.sleep(2)

    start_time = time.time()
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            stats = json.loads(cached_data)
            if stats.get('solves', 0) >= 2:
                break
        time.sleep(0.5)

    cached_data = redis_get(cache_key)
    assert cached_data is not None, "Cache should exist"

    stats = json.loads(cached_data)
    assert stats['solves'] >= 2, f"Expected at least 2 solves, got {stats['solves']}"
    assert len(stats['recent_solves']) >= 2, "Should have at least 2 recent solves"
    assert stats['recent_solves'][0]['challenge_name'] == 'Banana', "Most recent solve should be Banana"

def test_scoreboard_cold_start_initialization(example_dojo, random_user):
    user_name, user_session = random_user

    response = user_session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/")
    assert response.status_code == 200

    start_challenge(example_dojo, "hello", "apple", session=user_session)
    solve_challenge(example_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(2)

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{example_dojo}/_/0/1")
    assert response.status_code == 200

    data = response.json()
    assert 'standings' in data
    assert len(data['standings']) >= 1, f"Scoreboard should have at least one entry after solve"

    user_found = any(s['name'] == user_name for s in data['standings'])
    assert user_found, f"User {user_name} should be in scoreboard"

def test_scoreboard_updates_on_solve(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(2)

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{stats_test_dojo}/_/0/1")
    assert response.status_code == 200

    data = response.json()
    assert 'standings' in data
    assert len(data['standings']) >= 1, "Scoreboard should have at least one entry"

    user_entry = next((e for e in data['standings'] if e['name'] == user_name), None)
    assert user_entry is not None, f"User {user_name} should be in scoreboard"
    assert user_entry['solves'] >= 1, "User should have at least 1 solve"

def test_scoreboard_api_reads_from_cache(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(3)

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{stats_test_dojo}/_/0/1")
    assert response.status_code == 200

    data = response.json()
    assert 'standings' in data
    assert len(data['standings']) >= 1

def test_module_scoreboard_updates(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(2)

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{stats_test_dojo}/hello/0/1")
    assert response.status_code == 200

    data = response.json()
    assert 'standings' in data
    assert len(data['standings']) >= 1, "Module scoreboard should have at least one entry"

    user_entry = next((e for e in data['standings'] if e['name'] == user_name), None)
    assert user_entry is not None, f"User {user_name} should be in module scoreboard"

def test_scores_cold_start_initialization():
    dojo_scores_key = "stats:scores:dojos"
    module_scores_key = "stats:scores:modules"

    dojo_scores_data = redis_get(dojo_scores_key)
    module_scores_data = redis_get(module_scores_key)

    if dojo_scores_data is None or module_scores_data is None:
        result = dojo_run("docker", "logs", "stats-worker", "--tail", "100", check=False)
        pytest.fail(f"Cold start should have initialized scores cache. Worker logs:\n{result.stdout}")

    dojo_scores = json.loads(dojo_scores_data)
    assert 'user_ranks' in dojo_scores, "dojo_scores should have user_ranks"
    assert 'user_solves' in dojo_scores, "dojo_scores should have user_solves"
    assert 'dojo_ranks' in dojo_scores, "dojo_scores should have dojo_ranks"

    module_scores = json.loads(module_scores_data)
    assert 'user_ranks' in module_scores, "module_scores should have user_ranks"
    assert 'user_solves' in module_scores, "module_scores should have user_solves"
    assert 'module_ranks' in module_scores, "module_scores should have module_ranks"

    dojo_timestamp = redis_get(f"{dojo_scores_key}:updated")
    module_timestamp = redis_get(f"{module_scores_key}:updated")
    assert dojo_timestamp is not None, "dojo_scores timestamp should exist"
    assert module_timestamp is not None, "module_scores timestamp should exist"

def test_scores_update_on_solve(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    dojo_scores_key = "stats:scores:dojos"
    before_timestamp = redis_get(f"{dojo_scores_key}:updated")
    before_time = float(before_timestamp) if before_timestamp else 0

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    start_time = time.time()
    updated = False
    while time.time() - start_time < 10:
        after_timestamp = redis_get(f"{dojo_scores_key}:updated")
        if after_timestamp and float(after_timestamp) > before_time:
            updated = True
            break
        time.sleep(0.5)

    assert updated, "scores cache should be updated after solve"

    dojo_scores_data = redis_get(dojo_scores_key)
    assert dojo_scores_data is not None, "dojo_scores cache should exist"

    dojo_scores = json.loads(dojo_scores_data)
    assert 'user_ranks' in dojo_scores
    assert 'user_solves' in dojo_scores
    assert 'dojo_ranks' in dojo_scores

def test_hacker_page_uses_scores(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(3)

    response = user_session.get(f"{DOJO_URL}/hacker/")
    assert response.status_code == 200, "Hacker page should load successfully"

def test_scoreboard_page_uses_belts_cache(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(3)

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{stats_test_dojo}/_/0/1")
    assert response.status_code == 200

    data = response.json()
    assert 'standings' in data
    if len(data['standings']) > 0:
        first_entry = data['standings'][0]
        assert 'belt' in first_entry, "Scoreboard entries should have belt info"
        assert 'badges' in first_entry, "Scoreboard entries should have badges info"

def test_belts_page_loads_from_cache(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(3)

    import requests
    response = requests.get(f"{DOJO_URL}/belts")
    assert response.status_code == 200, "Belts page should load successfully"

def test_users_page_loads_with_awards_cache(stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/hacker/")
    assert response.status_code == 200, "Users page should load successfully with awards cache"

def test_emoji_awarded_triggers_cache_update(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    emojis_key = "stats:emojis"
    before_timestamp = redis_get(f"{emojis_key}:updated")
    before_time = float(before_timestamp) if before_timestamp else 0

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    start_challenge(stats_test_dojo, "hello", "banana", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "banana", session=user_session, user=user_name)

    start_time = time.time()
    updated = False
    while time.time() - start_time < 15:
        after_timestamp = redis_get(f"{emojis_key}:updated")
        if after_timestamp and float(after_timestamp) > before_time:
            updated = True
            break
        time.sleep(0.5)

    assert updated, "Emojis cache should be updated after completing a dojo"

def test_belts_cold_start_initialization(example_dojo):
    belts_key = "stats:belts"
    belts_data = redis_get(belts_key)

    if belts_data is None:
        pytest.skip("Belts cache not available (may have been cleared by prior tests)")

    belts = json.loads(belts_data)
    assert 'dates' in belts, "belts should have dates"
    assert 'users' in belts, "belts should have users"
    assert 'ranks' in belts, "belts should have ranks"

    for color in ['orange', 'yellow', 'green', 'purple', 'blue', 'brown', 'red', 'black']:
        assert color in belts['dates'], f"belts dates should have {color}"
        assert color in belts['ranks'], f"belts ranks should have {color}"

    belts_timestamp = redis_get(f"{belts_key}:updated")
    assert belts_timestamp is not None, "belts timestamp should exist"

def test_emojis_cold_start_initialization():
    emojis_key = "stats:emojis"
    emojis_data = redis_get(emojis_key)

    if emojis_data is None:
        result = dojo_run("docker", "logs", "stats-worker", "--tail", "100", check=False)
        pytest.fail(f"Cold start should have initialized emojis cache. Worker logs:\n{result.stdout}")

    emojis = json.loads(emojis_data)
    assert 'emojis' in emojis, "emojis cache should have emojis field"
    assert 'dojos' in emojis, "emojis cache should have dojos field"

    emojis_timestamp = redis_get(f"{emojis_key}:updated")
    assert emojis_timestamp is not None, "emojis timestamp should exist from cold start"

def test_scoreboard_different_durations(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(3)

    for duration in [0, 7, 30]:
        response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{stats_test_dojo}/_/{duration}/1")
        assert response.status_code == 200, f"Scoreboard with duration {duration} should return 200"

        data = response.json()
        assert 'standings' in data, f"Scoreboard duration {duration} should have standings"
        assert 'pages' in data, f"Scoreboard duration {duration} should have pages"

def test_module_scoreboard_cache_structure(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(3)

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{stats_test_dojo}/hello/0/1")
    assert response.status_code == 200

    data = response.json()
    assert 'standings' in data
    assert 'pages' in data

    if len(data['standings']) > 0:
        entry = data['standings'][0]
        assert 'name' in entry, "Scoreboard entry should have name"
        assert 'solves' in entry, "Scoreboard entry should have solves"
        assert 'rank' in entry, "Scoreboard entry should have rank"
        assert 'url' in entry, "Scoreboard entry should have url"
        assert 'symbol' in entry, "Scoreboard entry should have symbol"
        assert 'belt' in entry, "Scoreboard entry should have belt"
        assert 'badges' in entry, "Scoreboard entry should have badges"

def test_belts_cache_structure_after_belt_earned(belt_dojos, random_user):
    user_name, user_session = random_user

    belts_key = "stats:belts"
    before_timestamp = redis_get(f"{belts_key}:updated")
    before_time = float(before_timestamp) if before_timestamp else 0

    orange_dojo = belt_dojos["orange"]
    response = user_session.get(f"{DOJO_URL}/dojo/{orange_dojo}/join/")
    assert response.status_code == 200

    start_challenge(orange_dojo, "test", "test", session=user_session)
    solve_challenge(orange_dojo, "test", "test", session=user_session, user=user_name)

    start_time = time.time()
    updated = False
    while time.time() - start_time < 15:
        after_timestamp = redis_get(f"{belts_key}:updated")
        if after_timestamp and float(after_timestamp) > before_time:
            updated = True
            break
        time.sleep(0.5)

    assert updated, "Belts cache should be updated after earning a belt"

    belts_data = redis_get(belts_key)
    assert belts_data is not None, "Belts cache should exist"

    belts = json.loads(belts_data)

    assert isinstance(belts['dates'], dict), "dates should be a dict"
    assert isinstance(belts['users'], dict), "users should be a dict"
    assert isinstance(belts['ranks'], dict), "ranks should be a dict"

    for color in belts['ranks']:
        assert isinstance(belts['ranks'][color], list), f"ranks[{color}] should be a list"

def test_dojo_stats_includes_visible_challenges(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    assert wait_for_cache_update(stats_test_dojo, timeout=10), "Cache should be updated"

    cache_key = f"stats:dojo:{stats_test_dojo}"
    stats = json.loads(redis_get(cache_key))

    assert 'visible_challenges' in stats, "Stats should include visible_challenges"
    assert stats['visible_challenges'] >= 0, "visible_challenges should be non-negative"
    assert stats['challenges'] >= stats['visible_challenges'], "total challenges should be >= visible challenges"

def test_scoreboard_cache_cold_start_all_durations(example_dojo):
    found_any = False
    for duration in [0, 7, 30]:
        cache_key = f"stats:scoreboard:dojo:*:{duration}"
        keys = redis_keys(cache_key)
        if keys:
            found_any = True

    if not found_any:
        pytest.skip("Scoreboard cache not available (may have been cleared by prior tests)")

def test_emojis_cache_structure_contains_dojo_info():
    emojis_key = "stats:emojis"
    emojis_data = redis_get(emojis_key)

    if emojis_data is None:
        pytest.skip("Emojis cache not initialized")

    emojis = json.loads(emojis_data)

    assert 'dojos' in emojis, "emojis cache should have dojos metadata"
    dojos = emojis['dojos']

    for hex_id, dojo_info in dojos.items():
        assert 'reference_id' in dojo_info, "dojo info should have reference_id"
        assert 'emoji' in dojo_info, "dojo info should have emoji"
        assert 'is_public' in dojo_info, "dojo info should have is_public"
        assert 'is_example' in dojo_info, "dojo info should have is_example"

def test_module_scores_update_on_solve(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    module_scores_key = "stats:scores:modules"
    before_timestamp = redis_get(f"{module_scores_key}:updated")
    before_time = float(before_timestamp) if before_timestamp else 0

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    start_time = time.time()
    updated = False
    while time.time() - start_time < 10:
        after_timestamp = redis_get(f"{module_scores_key}:updated")
        if after_timestamp and float(after_timestamp) > before_time:
            updated = True
            break
        time.sleep(0.5)

    assert updated, "module scores cache should be updated after solve"

    module_scores_data = redis_get(module_scores_key)
    assert module_scores_data is not None, "module_scores cache should exist"

    module_scores = json.loads(module_scores_data)
    assert 'user_ranks' in module_scores
    assert 'user_solves' in module_scores
    assert 'module_ranks' in module_scores

def test_container_stats_cold_start_initialization():
    cache_key = "stats:containers"
    cached_data = redis_get(cache_key)

    if cached_data is None:
        result = dojo_run("docker", "logs", "stats-worker", "--tail", "100", check=False)
        pytest.fail(f"Cold start should have initialized container stats cache. Worker logs:\n{result.stdout}")

    containers = json.loads(cached_data)
    assert isinstance(containers, list), "container stats should be a list"

    timestamp = redis_get(f"{cache_key}:updated")
    assert timestamp is not None, "Container stats timestamp should exist from cold start"

def test_container_stats_update_on_challenge_start(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    cache_key = "stats:containers"
    before_timestamp = redis_get(f"{cache_key}:updated")
    before_time = float(before_timestamp) if before_timestamp else 0

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)

    start_time = time.time()
    updated = False
    while time.time() - start_time < 10:
        after_timestamp = redis_get(f"{cache_key}:updated")
        if after_timestamp and float(after_timestamp) > before_time:
            updated = True
            break
        time.sleep(0.5)

    assert updated, "Container stats cache should be updated after starting a challenge"

    cached_data = redis_get(cache_key)
    assert cached_data is not None, "Container stats cache should exist"

    containers = json.loads(cached_data)
    assert isinstance(containers, list), "Container stats should be a list"
    assert len(containers) >= 1, "Should have at least one container after starting a challenge"

def test_container_stats_update_on_challenge_stop(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)

    time.sleep(2)

    cache_key = "stats:containers"
    before_timestamp = redis_get(f"{cache_key}:updated")
    before_time = float(before_timestamp) if before_timestamp else 0

    response = user_session.delete(f"{DOJO_URL}/pwncollege_api/v1/docker", json={})
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    start_time = time.time()
    updated = False
    while time.time() - start_time < 10:
        after_timestamp = redis_get(f"{cache_key}:updated")
        if after_timestamp and float(after_timestamp) > before_time:
            updated = True
            break
        time.sleep(0.5)

    assert updated, "Container stats cache should be updated after stopping a challenge"

def test_container_stats_cache_structure(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)

    cache_key = "stats:containers"

    start_time = time.time()
    found_container = False
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            containers = json.loads(cached_data)
            if len(containers) >= 1:
                found_container = True
                break
        time.sleep(0.5)

    assert found_container, "Should have container in cache after starting challenge"

    containers = json.loads(redis_get(cache_key))

    for container in containers:
        assert 'dojo' in container, "Container should have dojo field"
        assert 'module' in container, "Container should have module field"
        assert 'challenge' in container, "Container should have challenge field"

def test_container_stats_fallback_on_cache_miss(admin_session):
    clear_redis_stats()

    cache_key = "stats:containers"
    redis_delete(cache_key, f"{cache_key}:updated")

    assert redis_get(cache_key) is None, "Cache should be empty after deletion"

    response = admin_session.get(f"{DOJO_URL}/dojos")
    assert response.status_code == 200, "Dojos page should load even without container cache"

def test_activity_update_on_solve(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert response.status_code == 200
    user_id = response.json()["id"]

    cache_key = f"stats:activity:{user_id}"
    redis_delete(cache_key, f"{cache_key}:updated")

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    start_time = time.time()
    updated = False
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            updated = True
            break
        time.sleep(0.5)

    assert updated, "Activity cache should be updated after solve"

    activity = json.loads(cached_data)
    assert 'daily_solves' in activity, "Activity should have daily_solves"
    assert 'total_solves' in activity, "Activity should have total_solves"
    assert activity['total_solves'] >= 1, f"Expected at least 1 solve, got {activity['total_solves']}"

def test_activity_api_returns_cached_data(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert response.status_code == 200
    user_id = response.json()["id"]

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    cache_key = f"stats:activity:{user_id}"

    start_time = time.time()
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            break
        time.sleep(0.5)

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/activity/{user_id}")
    assert response.status_code == 200

    data = response.json()
    assert data['success'] is True, "API should return success"
    assert 'data' in data, "API should return data"
    assert 'daily_solves' in data['data'], "API data should have daily_solves"
    assert 'total_solves' in data['data'], "API data should have total_solves"

def test_activity_cache_structure(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert response.status_code == 200
    user_id = response.json()["id"]

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    cache_key = f"stats:activity:{user_id}"

    start_time = time.time()
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            break
        time.sleep(0.5)

    assert cached_data is not None, "Activity cache should exist"

    activity = json.loads(cached_data)

    assert isinstance(activity['daily_solves'], dict), "daily_solves should be a dict"
    assert isinstance(activity['total_solves'], int), "total_solves should be an int"

    today = time.strftime('%Y-%m-%d')
    assert today in activity['daily_solves'], f"Today's date ({today}) should be in daily_solves"
    assert activity['daily_solves'][today] >= 1, "Today should have at least 1 solve"

def test_activity_multiple_solves_same_day(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert response.status_code == 200
    user_id = response.json()["id"]

    cache_key = f"stats:activity:{user_id}"
    redis_delete(cache_key, f"{cache_key}:updated")

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(2)

    start_challenge(stats_test_dojo, "hello", "banana", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "banana", session=user_session, user=user_name)

    start_time = time.time()
    while time.time() - start_time < 10:
        cached_data = redis_get(cache_key)
        if cached_data:
            activity = json.loads(cached_data)
            if activity.get('total_solves', 0) >= 2:
                break
        time.sleep(0.5)

    activity = json.loads(redis_get(cache_key))
    today = time.strftime('%Y-%m-%d')

    assert activity['total_solves'] >= 2, f"Expected at least 2 total solves, got {activity['total_solves']}"
    assert activity['daily_solves'].get(today, 0) >= 2, f"Expected at least 2 solves today, got {activity['daily_solves'].get(today, 0)}"

def test_activity_fallback_on_cache_miss(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert response.status_code == 200
    user_id = response.json()["id"]

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(2)

    cache_key = f"stats:activity:{user_id}"
    redis_delete(cache_key, f"{cache_key}:updated")

    assert redis_get(cache_key) is None, "Cache should be empty after deletion"

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/activity/{user_id}")
    assert response.status_code == 200, "API should return 200 even without cache"

    data = response.json()
    assert data['success'] is True, "API should return success on fallback"
    assert 'daily_solves' in data['data'], "Fallback should compute daily_solves"
    assert data['data']['total_solves'] >= 1, "Fallback should find existing solves"

def test_activity_api_user_not_found(stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/activity/999999")
    assert response.status_code == 404, "API should return 404 for non-existent user"

def test_hacker_page_loads_with_activity(stats_test_dojo, stats_test_user):
    user_name, user_session = stats_test_user

    response = user_session.get(f"{DOJO_URL}/dojo/{stats_test_dojo}/join/")
    assert response.status_code == 200

    start_challenge(stats_test_dojo, "hello", "apple", session=user_session)
    solve_challenge(stats_test_dojo, "hello", "apple", session=user_session, user=user_name)

    time.sleep(2)

    response = user_session.get(f"{DOJO_URL}/hacker/")
    assert response.status_code == 200, "Hacker page should load successfully with activity"
    assert 'activity-tracker' in response.text, "Hacker page should contain activity tracker"
