import subprocess
import requests
import pathlib
import time
import re
import os

DOJO_HOST = os.getenv("DOJO_HOST", "localhost.pwn.college")
DOJO_URL = os.getenv("DOJO_URL", f"http://{DOJO_HOST}").rstrip("/")
TEST_DOJOS_LOCATION = pathlib.Path(__file__).parent / "dojos"


def parse_csrf_token(text):
    match = re.search("'csrfNonce': \"(\\w+)\"", text)
    assert match, "Failed to find CSRF token"
    return match.group(1)


def login(name, password, *, success=True, register=False, email=None):
    session = requests.Session()
    endpoint = "login" if not register else "register"
    nonce = parse_csrf_token(session.get(f"http://{DOJO_HOST}/{endpoint}").text)
    data = { "name": name, "password": password, "nonce": nonce }
    if register:
        data["email"] = email or f"{name}@example.com"
    while True:
        response = session.post(f"http://{DOJO_HOST}/{endpoint}", data=data, allow_redirects=False)
        if response.status_code == 429:
            time.sleep(1)
            continue
        break
    if not success:
        assert response.status_code == 200, f"Expected {endpoint} failure (status code 200), but got {response.status_code}"
        return session
    assert response.status_code == 302, f"Expected {endpoint} success (status code 302), but got {response.status_code}"
    session.headers["CSRF-Token"] = parse_csrf_token(session.get(f"http://{DOJO_HOST}/").text)
    return session


def make_dojo_official(dojo_rid, admin_session):
    response = admin_session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/dojos/{dojo_rid}/promote", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"


def create_dojo(repository, *, session):
    test_public_key = f"public/{repository}"
    test_private_key = f"private/{repository}"
    create_dojo_json = { "repository": repository, "public_key": test_public_key, "private_key": test_private_key }
    response = session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/dojos/create", json=create_dojo_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"
    dojo_reference_id = response.json()["dojo"]
    return dojo_reference_id


def create_dojo_yml(spec, *, session):
    response = session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/dojos/create", json={"spec": spec})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"
    dojo_reference_id = response.json()["dojo"]
    return dojo_reference_id


def db_sql(sql):
    raise RuntimeError("db_sql is not available over HTTP")


def get_user_id(user_name, *, session=None):
    sess = session or login("admin", "admin")
    response = sess.get(
        f"http://{DOJO_HOST}/pwncollege_api/v1/test_utils/user_id",
        params={"username": user_name},
    )
    assert response.status_code == 200, f"Test API request failed: {response.status_code} {response.text}"
    return int(response.json()["id"])

def workspace_run(cmd, *, user, root=False, session=None, **kwargs):
    sess = session or login("admin", "admin")
    response = sess.post(
        f"http://{DOJO_HOST}/pwncollege_api/v1/test_utils/workspace_exec",
        json={"command": cmd, "user": user, "root": root},
    )
    assert response.status_code == 200, f"Test API request failed: {response.status_code} {response.text}"
    data = response.json()
    completed = subprocess.CompletedProcess(
        args=["workspace_exec", cmd],
        returncode=data["returncode"],
        stdout=data.get("stdout", ""),
        stderr=data.get("stderr", ""),
    )
    if data["returncode"] != 0:
        raise subprocess.CalledProcessError(
            data["returncode"],
            completed.args,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def delete_last_submission(username, *, session, dojo=None):
    payload = {"username": username}
    if dojo:
        payload["dojo"] = dojo
    response = session.post(
        f"http://{DOJO_HOST}/pwncollege_api/v1/test_utils/delete_last_submission",
        json=payload,
    )
    assert response.status_code == 200, f"Test API request failed: {response.status_code} {response.text}"


def clear_dojo_award(dojo_reference_id, *, session):
    response = session.post(
        f"http://{DOJO_HOST}/pwncollege_api/v1/test_utils/clear_dojo_award",
        json={"dojo": dojo_reference_id},
    )
    assert response.status_code == 200, f"Test API request failed: {response.status_code} {response.text}"


def start_challenge(dojo, module, challenge, practice=False, *, session, as_user=None, wait=0):
    start_challenge_json = dict(dojo=dojo, module=module, challenge=challenge, practice=practice)
    if as_user:
        start_challenge_json["as_user"] = as_user
    response = session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/docker", json=start_challenge_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to start challenge: {response.json()['error']}"

    if wait > 0:
        time.sleep(wait)


def solve_challenge(dojo, module, challenge, *, session, flag=None, user=None):
    flag = flag if flag is not None else workspace_run("cat /flag", user=user, root=True).stdout.strip()
    response = session.post(
        f"http://{DOJO_HOST}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/solve",
        json={"submission": flag}
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit flag"


def _redis_command(command, *args):
    response = requests.post(
        f"{DOJO_URL}/pwncollege_api/v1/test_utils/redis",
        json={"command": command, "args": list(args)},
    )
    assert response.status_code == 200, f"Redis test utils request failed: {response.status_code} {response.text}"
    return response.json().get("result")


def wait_for_background_worker(timeout=5):
    """Wait for the background stats worker to finish processing all pending events.

    Polls Redis stream length until it's 0 or timeout is reached.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        stream_length = _redis_command("XLEN", "stat:events")
        if stream_length is not None and int(stream_length) == 0:
            return
        time.sleep(0.1)
