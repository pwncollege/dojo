import json
import random
import re
import string
import subprocess
import shutil

import requests
import pytest


PROTO="http"
HOST="localhost.pwn.college"


def dojo_run(*args, **kwargs):
    kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    container_name = "dojo-test"
    return subprocess.run([shutil.which("docker"), "exec", "-i", container_name, "dojo", *args], **kwargs)


def workspace_run(cmd, *, user):
    return dojo_run("enter", user, input=cmd)


def parse_csrf_token(text):
    match = re.search("'csrfNonce': \"(\\w+)\"", text)
    assert match, "Failed to find CSRF token"
    return match.group(1)


def login(name, password, *, success=True, register=False, email=None):
    session = requests.Session()
    endpoint = "login" if not register else "register"
    nonce = parse_csrf_token(session.get(f"{PROTO}://{HOST}/{endpoint}").text)
    data = dict(name=name, password=password, nonce=nonce)
    if register:
        data["email"] = email or f"{name}@example.com"
    response = session.post(f"{PROTO}://{HOST}/{endpoint}", data=data, allow_redirects=False)
    if not success:
        assert response.status_code == 200, f"Expected {endpoint} failure (status code 200), but got {response.status_code}"
        return session
    assert response.status_code == 302, f"Expected {endpoint} success (status code 302), but got {response.status_code}"
    session.headers["CSRF-Token"] = parse_csrf_token(session.get(f"{PROTO}://{HOST}/").text)
    return session


def start_challenge(dojo, module, challenge, practice=False, *, session):
    start_challenge_json = dict(dojo=dojo, module=module, challenge=challenge, practice=practice)
    response = session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/docker", json=start_challenge_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to start challenge: {response.json()['error']}"


@pytest.fixture
def admin_session():
    session = login("admin", "admin")
    yield session


@pytest.fixture
def random_user():
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(random_id, random_id, register=True)
    yield random_id, session


@pytest.mark.parametrize("endpoint", ["/", "/dojos", "/login", "/register"])
def test_unauthenticated_return_200(endpoint):
    response = requests.get(f"{PROTO}://{HOST}{endpoint}")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"


def test_login():
    login("admin", "incorrect_password", success=False)
    login("admin", "admin")


def test_register():
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    login(random_id, random_id, register=True)


def create_dojo(repository, *, official=True, session):
    test_public_key = f"public/{repository}"
    test_private_key = f"private/{repository}"
    create_dojo_json = dict(repository=repository, public_key=test_public_key, private_key=test_private_key)
    response = session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/dojo/create", json=create_dojo_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"
    dojo_reference_id = response.json()["dojo"]

    if official:
        # TODO: add an official endpoint for making dojos official
        id, dojo_id = dojo_reference_id.split("~", 1)
        dojo_id = int.from_bytes(bytes.fromhex(dojo_id.rjust(8, "0")), "big", signed=True)
        sql = f"UPDATE dojos SET official = 1 WHERE id = '{id}' and dojo_id = {dojo_id}"
        dojo_run("db", input=sql)
        sql = f"SELECT official FROM dojos WHERE id = '{id}' and dojo_id = {dojo_id}"
        db_result = dojo_run("db", input=sql)
        assert db_result.stdout == "official\n1\n", f"Failed to make dojo official: {db_result.stdout}"

    return dojo_reference_id


@pytest.mark.dependency()
def test_create_dojo(admin_session):
    create_dojo("pwncollege/example-dojo", session=admin_session)


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_create_import_dojo(admin_session):
    create_dojo("pwncollege/example-import-dojo", session=admin_session)


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_start_challenge(admin_session):
    start_challenge("example", "hello", "apple", session=admin_session)


@pytest.mark.dependency(depends=["test_start_challenge"])
@pytest.mark.parametrize("path", ["/flag", "/challenge/apple"])
def test_workspace_path_exists(path):
    try:
        workspace_run(f"[ -f '{path}' ]", user="admin")
    except subprocess.CalledProcessError as e:
        assert False, f"Path does not exist: {path}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_flag_permission():
    try:
        workspace_run("cat /flag", user="admin")
    except subprocess.CalledProcessError as e:
        assert "Permission denied" in e.stderr, f"Expected permission denied, but got: {(e.stdout, e.stderr)}"
    else:
        assert False, f"Expected permission denied, but got no error: {(e.stdout, e.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_challenge():
    result = workspace_run("/challenge/apple", user="admin")
    match = re.search("pwn.college{(\\S+)}", result.stdout)
    assert match, f"Expected flag, but got: {result.stdout}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_home_mount():
    try:
        result = workspace_run("findmnt -J /home/hacker", user="admin")
    except subprocess.CalledProcessError as e:
        assert False, f"Home not mounted: {(e.stdout, e.stderr)}"
    assert result, f"Home not mounted: {(e.stdout, e.stderr)}"

    mount_info = json.loads(result.stdout)
    assert len(mount_info.get("filesystems", [])) == 1, f"Expected exactly one filesystem, but got: {mount_info}"

    filesystem = mount_info["filesystems"][0]
    assert filesystem["target"] == "/home/hacker", f"Expected home to be mounted at /home/hacker, but got: {filesystem}"
    assert "nosuid" in filesystem["options"], f"Expected home to be mounted nosuid, but got: {filesystem}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_no_sudo():
    try:
        workspace_run("sudo -v", user="admin")
    except subprocess.CalledProcessError as e:
        pass
    else:
        assert False, f"Expected sudo to fail, but got no error: {(e.stdout, e.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_home_persistent(random_user):
    user, session = random_user
    start_challenge("example", "hello", "apple", session=session)
    workspace_run("touch /home/hacker/test", user=user)
    start_challenge("example", "hello", "apple", session=session)
    try:
        workspace_run("[ -f '/home/hacker/test' ]", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected file to exist, but got: {(e.stdout, e.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_practice_challenge(random_user):
    user, session = random_user
    start_challenge("example", "hello", "apple", practice=True, session=session)
    try:
        workspace_run("sudo -v", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected sudo to succeed, but got: {(e.stdout, e.stderr)}"


def get_all_standings(session, dojo, module=None):
    """
    Return a big list of all the standings, going through all the available pages.
    """
    to_return = []

    page_number = 1
    done = False

    if module is None:
        module = "_"

    while not done:
        response = session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/scoreboard/{dojo}/{module}/0/{page_number}")
        assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
        response = response.json()

        to_return.extend(response["standings"])

        next_page = page_number + 1

        if next_page in response["pages"]:
            page_number += 1
        else:
            done = True

    return to_return


@pytest.mark.dependency(depends=["test_workspace_challenge"])
def test_scoreboard(random_user):
    user, session = random_user

    dojo = "example"
    module = "hello"
    challenge = "apple"

    prior_standings = get_all_standings(session, dojo, module)

    # get the challenge_id from the dojo API so we can submit the flag
    response = session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/dojo/{dojo}/{module}/challenges")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    challenges = response.json()['challenges']
    challenge_id = None
    for chall in challenges:
        if chall['id'] == challenge:
            challenge_id = chall['challenge_id']
            break

    assert challenge_id, f"Expected to find a challenge ID for this specific challenge"

    # if test_workspace_challenge passed correctly, then we should get a valid flag here
    start_challenge(dojo, module, challenge, session=session)
    result = workspace_run("/challenge/apple", user=user)
    flag = result.stdout.strip()

    # submit the flag
    data = {"challenge_id": challenge_id,
            "submission": flag}

    response = session.post(f"{PROTO}://{HOST}/api/v1/challenges/attempt",
                            json=data)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Expected to successfully submit flag"

    # check the scoreboard: is it updated?

    new_standings = get_all_standings(session, dojo, module)
    assert len(prior_standings) != len(new_standings), "Expected to have a new entry in the standings"

    found_me = False
    for standing in new_standings:
        if standing['name'] == user:
            found_me = True
            break
    assert found_me, f"Unable to find new user {user} in new standings after solving a challenge"
