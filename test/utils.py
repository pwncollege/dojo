import subprocess
import time
import requests
import pathlib
import shutil
import re
import os

DOJO_URL = os.getenv("DOJO_URL", "http://localhost.pwn.college")
DOJO_CONTAINER = os.getenv("DOJO_CONTAINER", "dojo-test")
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
    return subprocess.run(
        [shutil.which("docker"), "exec", "-i", DOJO_CONTAINER, "dojo", *args],
        check=kwargs.pop("check", True), **kwargs
    )

def workspace_run(cmd, *, user, root=False, **kwargs):
    args = [ "enter" ]
    if root:
        args += [ "-s" ]
    args += [ user ]
    return dojo_run(*args, input=cmd, check=True, **kwargs)
