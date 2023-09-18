import re
import subprocess

import requests
import pytest


PROTO="http"
HOST="localhost.pwn.college"
UNAUTHENTICATED_URLS = ["/", "/dojos", "/login", "/register"]


def login(username, password, *, success=True):
    def parse_csrf_token(text):
        match = re.search("'csrfNonce': \"(\w+)\"", text)
        assert match, "Failed to find CSRF token"
        return match.group(1)

    session = requests.Session()

    nonce = parse_csrf_token(session.get(f"{PROTO}://{HOST}/login").text)
    login_data = dict(name=username, password=password, nonce=nonce)
    login_response = session.post(f"{PROTO}://{HOST}/login", data=login_data, follow_redirects=False)
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


@pytest.mark.parametrize("endpoint", UNAUTHENTICATED_URLS)
def test_unauthenticated_return_200(endpoint):
    response = requests.get(f"{PROTO}://{HOST}{endpoint}")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"


def test_login():
    login("admin", "incorrect_password", success=False)
    login("admin", "admin")


def test_create_dojo(admin_session):
    create_dojo_json = dict(repository="pwncollege/example-dojo", public_key="", private_key="")
    response = admin_session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/dojo/create", json=create_dojo_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    dojo_reference_id = response.json()["dojo"]

    # TODO: add an official endpoint for making dojos official
    id, dojo_id = dojo_reference_id.split("~", 1)
    dojo_id = int.from_bytes(bytes.fromhex(dojo_id.rjust(8, "0")), "big", signed=True)
    sql = f"UPDATE dojos SET official = TRUE WHERE id = '{id}' and dojo_id = {dojo_id}"
    subprocess.run(["/usr/bin/dojo", "db"], input=sql, text=True, check=True)


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_start_challenge(admin_session):
    start_challenge_json = dict(dojo="example-dojo", module="hello", challenge="apple", practice=False)
    response = admin_session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/dojo/start", json=start_challenge_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to start challenge: {response.json()['error']}"
