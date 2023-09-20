import re
import subprocess

import requests
import pytest


PROTO="http"
HOST="localhost.pwn.college"


def dojo_run(*args, **kwargs):
    kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    container_name = "dojo-test"
    return subprocess.run(["/usr/bin/docker", "exec", "-i", container_name, "dojo", *args], **kwargs)


def login(username, password, *, success=True):
    def parse_csrf_token(text):
        match = re.search("'csrfNonce': \"(\\w+)\"", text)
        assert match, "Failed to find CSRF token"
        return match.group(1)

    session = requests.Session()

    nonce = parse_csrf_token(session.get(f"{PROTO}://{HOST}/login").text)
    login_data = dict(name=username, password=password, nonce=nonce)
    login_response = session.post(f"{PROTO}://{HOST}/login", data=login_data, allow_redirects=False)
    if not success:
        assert login_response.status_code == 200, f"Expected login failure (status code 200), but got {login_response.status_code}"
        return session
    assert login_response.status_code == 302, f"Expected login success (status code 302), but got {login_response.status_code}"

    home_response = session.get(f"{PROTO}://{HOST}/")
    session.headers["CSRF-Token"] = parse_csrf_token(home_response.text)

    return session


@pytest.fixture
def admin_session():
    session = login("admin", "admin")
    yield session


@pytest.mark.parametrize("endpoint", ["/", "/dojos", "/login", "/register"])
def test_unauthenticated_return_200(endpoint):
    response = requests.get(f"{PROTO}://{HOST}{endpoint}")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"


def test_login():
    login("admin", "incorrect_password", success=False)
    login("admin", "admin")


@pytest.mark.dependency()
def test_create_dojo(admin_session):
    create_dojo_json = dict(repository="pwncollege/example-dojo", public_key="", private_key="")
    response = admin_session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/dojo/create", json=create_dojo_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    dojo_reference_id = response.json()["dojo"]

    # TODO: add an official endpoint for making dojos official
    id, dojo_id = dojo_reference_id.split("~", 1)
    dojo_id = int.from_bytes(bytes.fromhex(dojo_id.rjust(8, "0")), "big", signed=True)
    sql = f"UPDATE dojos SET official = 1 WHERE id = '{id}' and dojo_id = {dojo_id}"
    dojo_run("db", input=sql)
    sql = f"SELECT official FROM dojos WHERE id = '{id}' and dojo_id = {dojo_id}"
    db_result = dojo_run("db", input=sql)
    assert db_result.stdout == "official\n1\n", f"Failed to make dojo official: {db_result.stdout}"


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_start_challenge(admin_session):
    start_challenge_json = dict(dojo="example", module="hello", challenge="apple", practice=False)
    response = admin_session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/docker", json=start_challenge_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to start challenge: {response.json()['error']}"


@pytest.mark.dependency(depends=["test_start_challenge"])
@pytest.mark.parametrize("path", ["/flag", "/challenge/apple"])
def test_challenge_container_path_exists(path):
    try:
        dojo_run("enter", "admin", input=f"[ -f '{path}' ]")
    except subprocess.CalledProcessError as e:
        assert False, f"Path does not exist: {path}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_challenge_privilege_escalation():
    try:
        dojo_run("enter", "admin", input="cat /flag")
    except subprocess.CalledProcessError as e:
        assert e.stderr == "cat: /flag: Permission denied\n", f"Expected permission denied, but got: {(e.stdout, e.stderr)}"
    else:
        assert False, f"Expected permission denied, but got no error: {(e.stdout, e.stderr)}"

    result = dojo_run("enter", "admin", input="/challenge/apple")
    match = re.search("pwn.college{(\\S+)}", result.stdout)
    assert match, f"Expected flag, but got: {result.stdout}"
