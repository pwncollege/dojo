import subprocess
import requests
import pathlib
import shutil
import json
import time
import re
import os

def _get_dojo_container():
    if os.getenv("DOJO_CONTAINER"):
        return os.getenv("DOJO_CONTAINER")
    
    if os.path.exists("/.dockerenv"):
        import socket
        hostname = socket.gethostname()
        
        def docker_cmd(args):
            result = subprocess.run(["docker"] + args, capture_output=True, text=True, check=True)
            return result.stdout.strip() if result.returncode == 0 else None
        
        container_name = docker_cmd(["ps", "--filter", f"id={hostname}", "--format", "{{.Names}}"])
        if container_name.endswith("-test"):
            return container_name[:-5]
        
        all_containers = docker_cmd(["ps", "--format", "{{.Names}}"])
        if len(all_containers) == 2:
            return next(c for c in all_containers.split('\n') if c and c != container_name)
    else:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=os.path.dirname(__file__)
        )
        if result.returncode == 0:
            return os.path.basename(result.stdout.strip())

    raise RuntimeError(f"Unable to determine the container the dojo is running in. Please set DOJO_CONTAINER.")

DOJO_CONTAINER = _get_dojo_container()

def _get_container_ip(container_name):
    result = subprocess.run(
        ["docker", "inspect", container_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode == 0:
        try:
            info = json.loads(result.stdout)
            return info[0]["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
    return None

DOJO_IP = _get_container_ip(DOJO_CONTAINER) or os.getenv("DOJO_IP", "localhost")
DOJO_URL = os.getenv("DOJO_URL", f"http://{DOJO_IP}:80/")
DOJO_SSH_HOST = os.getenv("DOJO_SSH_HOST", DOJO_IP)
TEST_DOJOS_LOCATION = pathlib.Path(__file__).parent / "dojos"


def parse_csrf_token(text):
    match = re.search("'csrfNonce': \"(\\w+)\"", text)
    assert match, "Failed to find CSRF token"
    return match.group(1)


def login(name, password, *, success=True, register=False, email=None):
    session = requests.Session()
    endpoint = "login" if not register else "register"
    nonce = parse_csrf_token(session.get(f"{DOJO_URL}/{endpoint}").text)
    data = { "name": name, "password": password, "nonce": nonce }
    if register:
        data["email"] = email or f"{name}@example.com"
    while True:
        response = session.post(f"{DOJO_URL}/{endpoint}", data=data, allow_redirects=False)
        if response.status_code == 429:
            time.sleep(1)
            continue
        break
    if not success:
        assert response.status_code == 200, f"Expected {endpoint} failure (status code 200), but got {response.status_code}"
        return session
    assert response.status_code == 302, f"Expected {endpoint} success (status code 302), but got {response.status_code}"
    session.headers["CSRF-Token"] = parse_csrf_token(session.get(f"{DOJO_URL}/").text)
    return session


def make_dojo_official(dojo_rid, admin_session):
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo_rid}/promote", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"


def _create_dojo_with_retries(create_dojo_json, *, session):
    # Dojo creation fetches external resources (git clone, file downloads);
    # transient network failures are retried, permanent errors are not.
    for _ in range(3):
        response = session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", json=create_dojo_json)
        if response.status_code == 200 or "already exists" in response.text:
            break
        time.sleep(5)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"
    return response.json()["dojo"]


def create_dojo(repository, *, session):
    test_public_key = f"public/{repository}"
    test_private_key = f"private/{repository}"
    create_dojo_json = { "repository": repository, "public_key": test_public_key, "private_key": test_private_key }
    return _create_dojo_with_retries(create_dojo_json, session=session)


def create_dojo_yml(spec, *, session):
    return _create_dojo_with_retries({"spec": spec}, session=session)


def dojo_run(*args, **kwargs):
    kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    container = kwargs.pop("container", DOJO_CONTAINER)
    return subprocess.run(
        [shutil.which("docker"), "exec", "-i", container, *args],
        check=kwargs.pop("check", True), **kwargs
    )


def db_sql(sql):
     db_result = dojo_run("dojo", "db", "-qAt", input=sql)
     return db_result.stdout


def get_user_id(user_name):
    return int(db_sql(f"SELECT id FROM users WHERE name = '{user_name}'"))

def get_outer_container_for(container_name):
    # Check main node first
    result = subprocess.run(
        [shutil.which("docker"), "exec", "-i", DOJO_CONTAINER, "docker", "ps", "--format", "{{.Names}}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode == 0 and container_name in result.stdout.strip().split('\n'):
        return DOJO_CONTAINER
    
    # Check worker nodes if they exist
    result = subprocess.run(
        [shutil.which("docker"), "exec", "-i", DOJO_CONTAINER, "cat", "/data/workspace_nodes.json"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            workspace_nodes = json.loads(result.stdout)
        except json.JSONDecodeError:
            workspace_nodes = {}
        for node_id in workspace_nodes.keys():
            node_container = f"{DOJO_CONTAINER}-node{node_id}"
            result = subprocess.run(
                [shutil.which("docker"), "exec", "-i", node_container, "docker", "ps", "--format", "{{.Names}}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if result.returncode == 0 and container_name in result.stdout.strip().split('\n'):
                return node_container
    
    raise RuntimeError(f"container {container_name} not found on any nodes")

def remove_workspace_container(user):
    container_name = f"user_{get_user_id(user)}"
    try:
        outer_container = get_outer_container_for(container_name)
    except RuntimeError:
        return
    dojo_run("docker", "rm", "-f", container_name, check=False, container=outer_container)


def workspace_run(cmd, *, user, root=False, **kwargs):
    container_name = f"user_{get_user_id(user)}"
    outer_container = get_outer_container_for(container_name)
    user_arg = f"--user=1000" if not root else f"--user=0"
    args = [ "docker", "exec", user_arg, container_name, "bash", "-c", cmd ]
    return dojo_run(*args, stdin=subprocess.DEVNULL, check=True, container=outer_container, **kwargs)


def start_challenge(dojo, module, challenge, practice=False, *, session, as_user=None, wait=0):
    start_challenge_json = dict(dojo=dojo, module=module, challenge=challenge, practice=practice)
    if as_user:
        start_challenge_json["as_user"] = as_user
    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json=start_challenge_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to start challenge: {response.json()['error']}"

    if wait > 0:
        time.sleep(wait)


def solve_challenge(dojo, module, challenge, *, session, flag=None, user=None):
    flag = flag if flag is not None else workspace_run("cat /flag", user=user, root=True).stdout.strip()
    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/solve",
        json={"submission": flag}
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit flag"


def wait_for_background_worker(timeout=5):
    deadline = time.monotonic() + timeout
    idle_observations = 0
    stream_result = None
    outbox_result = None
    stream_length = None
    refresh_count = None
    invalidation_count = None

    while time.monotonic() < deadline:
        stream_result = dojo_run(
            "docker", "exec", "cache", "redis-cli",
            "XLEN", "stat:events", check=False,
        )
        stream_output = stream_result.stdout.strip()
        stream_length = (
            int(stream_output)
            if stream_result.returncode == 0 and stream_output.isdigit()
            else None
        )
        outbox_result = dojo_run(
            "dojo", "db", "-qAt",
            input=(
                "SELECT (SELECT count(*) FROM dojo_cache_refreshes), "
                "(SELECT count(*) FROM dojo_module_cache_invalidations);"
            ),
            check=False,
        )
        outbox_parts = outbox_result.stdout.strip().split("|")
        if (
            outbox_result.returncode == 0
            and len(outbox_parts) == 2
            and all(part.isdigit() for part in outbox_parts)
        ):
            refresh_count, invalidation_count = map(int, outbox_parts)
        else:
            refresh_count = invalidation_count = None

        if stream_length == refresh_count == invalidation_count == 0:
            idle_observations += 1
            if idle_observations == 2:
                return True
        else:
            idle_observations = 0
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))

    worker_state = dojo_run(
        "docker", "inspect", "--format",
        "{{.State.Status}} exit={{.State.ExitCode}} error={{.State.Error}}",
        "stats-worker", check=False,
    )
    worker_logs = dojo_run(
        "docker", "logs", "stats-worker", "--tail", "100", check=False,
    )
    raise AssertionError(
        "Background stats worker did not become idle within "
        f"{timeout}s: stream_length={stream_length}, "
        f"refresh_count={refresh_count}, "
        f"invalidation_count={invalidation_count}\n"
        f"Redis error: {(stream_result.stderr if stream_result else '').strip()}\n"
        f"Database error: {(outbox_result.stderr if outbox_result else '').strip()}\n"
        f"Worker state: {worker_state.stdout.strip()} "
        f"{worker_state.stderr.strip()}\n"
        f"Worker logs:\n{worker_logs.stdout}{worker_logs.stderr}"
    )
