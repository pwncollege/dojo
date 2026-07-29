import subprocess
import requests
import pathlib
import shutil
import json
import time
import re
import os
import uuid

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
    """Promote a dojo and return the reference id it answers to afterwards.

    An official dojo drops the hex differentiator, and that shorter form is what
    every API then reports, so tests must compare against it.
    """
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo_rid}/promote", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"
    return dojo_rid.split("~")[0]


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
    db_result = dojo_run(
        "dojo", "db", "-v", "ON_ERROR_STOP=1", "-qAt", input=sql,
        check=False,
    )
    assert db_result.returncode == 0, db_result.stderr
    return db_result.stdout


def get_user_id(user_name):
    return int(db_sql(f"SELECT id FROM users WHERE name = '{user_name}'"))


FLASK_EXEC_MARKER = "--- dojo test output ---"

def flask_exec(code):
    """Run python inside CTFd's application context and return everything it printed."""
    path = f"/tmp/dojo-test-exec-{uuid.uuid4().hex}.py"
    script = f"print({FLASK_EXEC_MARKER!r}, flush=True)\n{code}"
    dojo_run("docker", "exec", "-i", "ctfd", "sh", "-c", f"cat > {path}", input=script)
    result = dojo_run("docker", "exec", "ctfd", "flask", "shell", "--", path, check=False)
    dojo_run("docker", "exec", "ctfd", "rm", "-f", path, check=False)
    assert FLASK_EXEC_MARKER in result.stdout, f"flask exec produced no output: {result.stdout}\n{result.stderr}"
    return result.stdout.split(FLASK_EXEC_MARKER, 1)[1].lstrip("\n")


def dojo_db_id(dojo_reference_id):
    if "~" in dojo_reference_id:
        _, hex_id = dojo_reference_id.split("~", 1)
        return int.from_bytes(bytes.fromhex(hex_id.rjust(8, "0")), "big", signed=True)
    return int(db_sql(f"SELECT dojo_id FROM dojos WHERE id = '{dojo_reference_id}' AND official"))


_challenge_ids = {}

def challenge_db_id(dojo, module, challenge):
    key = (dojo, module, challenge)
    if key not in _challenge_ids:
        _challenge_ids[key] = int(db_sql(
            "SELECT dc.challenge_id FROM dojo_challenges dc "
            "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
            f"WHERE dc.dojo_id = {dojo_db_id(dojo)} AND dm.id = '{module}' AND dc.id = '{challenge}'"
        ))
    return _challenge_ids[key]


_flags = {}

def challenge_flag(dojo, module, challenge, *, user):
    """Derive a challenge's flag the way the workspace does, without starting a container.

    The derivation runs inside the ctfd container so it always uses the same
    serializer implementation and secret key that flag submission validates against.
    """
    key = (user, dojo, module, challenge)
    if key not in _flags:
        _flags[key] = dojo_run(
            "docker", "exec", "ctfd", "python3", "-c",
            "import sys, os\n"
            "from itsdangerous.url_safe import URLSafeSerializer\n"
            "data = [int(sys.argv[1]), int(sys.argv[2])]\n"
            "print('pwn.college{' + URLSafeSerializer(os.environ['SECRET_KEY']).dumps(data)[::-1] + '}')",
            str(get_user_id(user)), str(challenge_db_id(dojo, module, challenge)),
        ).stdout.strip()
    return _flags[key]

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
    user_id = db_sql(f"SELECT id FROM users WHERE name = '{user}'").strip()
    if not user_id:
        # A test may have renamed or deleted the user it started a workspace for.
        return
    container_name = f"user_{user_id}"
    try:
        outer_container = get_outer_container_for(container_name)
    except RuntimeError:
        return
    dojo_run("docker", "rm", "-f", container_name, check=False, container=outer_container)


def remove_workspace_home(user_id):
    """Drop a test user's home storage.

    Homes outlive their container by design, so a suite that registers a
    thousand users would otherwise leave a thousand subvolumes behind.
    """
    dojo_run(
        "sh", "-c",
        f"for subvolume in /data/homes/{user_id}/snapshots/* /data/homes/{user_id}/overlays/* "
        f"/data/homes/{user_id}/snapshots /data/homes/{user_id}/overlays /data/homes/{user_id}/active "
        f"/data/homes/{user_id}; do btrfs subvolume delete \"$subvolume\" 2>/dev/null; done; true",
        check=False,
    )


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


def solve_challenge_offline(dojo, module, challenge, *, session, user):
    """Register a solve without paying for a workspace container start."""
    solve_challenge(dojo, module, challenge, session=session,
                    flag=challenge_flag(dojo, module, challenge, user=user))


def suppress_award_popup(browser):
    """Keep the award popup from covering the page a browser test is driving.

    The popup renders for any award earned in the last two days, so on a
    deployment where tests have been granting awards it can appear over
    whatever the test is about to click.
    """
    browser.get(f"{DOJO_URL}/")
    browser.execute_script(
        "window.localStorage.setItem('lastPopup', new Date(Date.now() + 86400000).toISOString())"
    )


def wait_for_background_worker(timeout=5):
    """Wait for the background stats worker to finish processing all pending events.

    Polls Redis stream length until it's 0 or timeout is reached.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        result = dojo_run("docker", "exec", "cache", "redis-cli", "XLEN", "stat:events", check=False)
        if result.returncode == 0 and int(result.stdout.strip()) == 0:
            return
        time.sleep(0.1)
