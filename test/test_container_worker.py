import time
import json

from utils import (
    DOJO_URL,
    DOJO_CONTAINER,
    dojo_run,
    login,
    start_challenge,
)


def test_container_worker_running():
    result = dojo_run("dojo", "compose", "ps", "--format", "json", "container-worker", check=False)
    assert result.returncode == 0, f"Failed to check container-worker status: {result.stderr}"
    data = json.loads(result.stdout)
    if isinstance(data, list):
        assert len(data) > 0, "container-worker service not found"
        assert data[0]["State"] == "running", f"container-worker is not running: {data[0]['State']}"
    else:
        assert data["State"] == "running", f"container-worker is not running: {data['State']}"


def test_async_start_challenge(admin_session, example_dojo):
    user_name = f"async_test_{int(time.time())}"
    session = login(user_name, "password", register=True)
    start_challenge(example_dojo, "hello", "hello", session=session)


def test_async_start_status_progression(admin_session, example_dojo):
    user_name = f"status_test_{int(time.time())}"
    session = login(user_name, "password", register=True)

    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
        "dojo": example_dojo,
        "module": "hello",
        "challenge": "hello",
        "practice": False,
    })
    assert response.status_code == 200
    result = response.json()
    assert result["success"]
    start_id = result["start_id"]

    seen_statuses = set()
    start_time = time.time()
    while time.time() - start_time < 120:
        status_response = session.get(f"{DOJO_URL}/pwncollege_api/v1/docker/status?id={start_id}")
        assert status_response.status_code == 200
        status = status_response.json()
        assert status["success"]
        seen_statuses.add(status["status"])
        if status["status"] in ("ready", "failed"):
            break
        time.sleep(1)

    assert status["status"] == "ready", f"Expected ready, got {status['status']}: {status.get('error')}"
    assert "queued" in seen_statuses or "starting" in seen_statuses, (
        f"Expected to see queued or starting status, only saw: {seen_statuses}"
    )


def test_concurrent_start_same_user(admin_session, example_dojo):
    user_name = f"concurrent_test_{int(time.time())}"
    session = login(user_name, "password", register=True)

    response1 = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
        "dojo": example_dojo,
        "module": "hello",
        "challenge": "hello",
        "practice": False,
    })
    assert response1.status_code == 200
    result1 = response1.json()
    assert result1["success"]

    response2 = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
        "dojo": example_dojo,
        "module": "hello",
        "challenge": "hello",
        "practice": False,
    })
    assert response2.status_code == 200
    result2 = response2.json()
    assert not result2["success"], "Expected second concurrent start to fail due to lock"
    assert "already starting" in result2["error"].lower() or "please wait" in result2["error"].lower()


def test_status_unknown_id(admin_session):
    user_name = f"unknown_id_test_{int(time.time())}"
    session = login(user_name, "password", register=True)

    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/docker/status?id=nonexistent-id")
    assert response.status_code == 200
    result = response.json()
    assert not result["success"]
    assert "unknown" in result["error"].lower() or "missing" in result["error"].lower()
