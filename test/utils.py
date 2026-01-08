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


def create_dojo(repository, *, session):
    test_public_key = f"public/{repository}"
    test_private_key = f"private/{repository}"
    create_dojo_json = { "repository": repository, "public_key": test_public_key, "private_key": test_private_key }
    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", json=create_dojo_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"
    dojo_reference_id = response.json()["dojo"]
    return dojo_reference_id


def create_dojo_yml(spec, *, session):
    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", json={"spec": spec})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"
    dojo_reference_id = response.json()["dojo"]
    return dojo_reference_id


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
    """Wait for the background stats worker to finish processing all pending events.

    Polls Redis stream length until it's 0 or timeout is reached.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        result = dojo_run("docker", "exec", "cache", "redis-cli", "XLEN", "stat:events", check=False)
        if result.returncode == 0 and int(result.stdout.strip()) == 0:
            return
        time.sleep(0.1)
