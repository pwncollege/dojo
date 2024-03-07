import json
import random
import re
import string
import subprocess

import requests
import pytest

#pylint:disable=redefined-outer-name,use-dict-literal,missing-timeout,unspecified-encoding,consider-using-with

from utils import PROTO, HOST, login, dojo_run, workspace_run

def get_flag(user):
    return workspace_run("cat /flag", user=user, root=True).stdout

def get_challenge_id(session, dojo, module, challenge):
    response = session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/dojo/{dojo}/{module}/challenges")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    challenges = response.json()['challenges']
    challenge_id = None
    for chall in challenges:
        if chall['id'] == challenge:
            challenge_id = chall['challenge_id']
            break

    assert challenge_id, "Expected to find a challenge ID for this specific challenge"
    return challenge_id


def start_challenge(dojo, module, challenge, practice=False, *, session):
    start_challenge_json = dict(dojo=dojo, module=module, challenge=challenge, practice=practice)
    response = session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/docker", json=start_challenge_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to start challenge: {response.json()['error']}"

def db_sql(sql):
    db_result = dojo_run("db", input=sql)
    return db_result.stdout

def db_sql_one(sql):
    return db_sql(sql).split()[1]

def get_user_id(user_name):
    return int(db_sql_one(f"SELECT id FROM users WHERE name = '{user_name}'"))

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

def start_and_solve(user_name, session, dojo, module, challenge):
    start_challenge(dojo, module, challenge, session=session)
    challenge_id = get_challenge_id(session, dojo, module, challenge)
    flag = get_flag(user_name)
    response = session.post(
        f"{PROTO}://{HOST}/api/v1/challenges/attempt",
        json={"challenge_id": challenge_id, "submission": flag}
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit flag"


@pytest.mark.dependency()
def test_create_dojo(example_dojo, admin_session):
    assert admin_session.get(f"{PROTO}://{HOST}/{example_dojo}/").status_code == 200
    assert admin_session.get(f"{PROTO}://{HOST}/example/").status_code == 200


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_create_import_dojo(example_import_dojo, admin_session):
    assert admin_session.get(f"{PROTO}://{HOST}/{example_import_dojo}/").status_code == 200
    assert admin_session.get(f"{PROTO}://{HOST}/example-import/").status_code == 200


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_start_challenge(admin_session):
    start_challenge("example", "hello", "apple", session=admin_session)

@pytest.mark.dependency(depends=["test_create_dojo"])
def test_join_dojo(admin_session, guest_dojo_admin):
    random_user_name, random_session = guest_dojo_admin
    response = random_session.get(f"{PROTO}://{HOST}/dojo/example/join/")
    assert response.status_code == 200
    response = admin_session.get(f"{PROTO}://{HOST}/dojo/example/admin/")
    assert response.status_code == 200
    assert random_user_name in response.text and response.text.index("Members") < response.text.index(random_user_name)

@pytest.mark.dependency(depends=["test_join_dojo"])
def test_promote_dojo_member(admin_session, guest_dojo_admin):
    random_user_name, _ = guest_dojo_admin
    random_user_id = get_user_id(random_user_name)
    response = admin_session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/dojo/example/promote-admin", json={"user_id": random_user_id})
    assert response.status_code == 200
    response = admin_session.get(f"{PROTO}://{HOST}/dojo/example/admin/")
    assert random_user_name in response.text and response.text.index("Members") > response.text.index(random_user_name)

@pytest.mark.dependency(depends=["test_join_dojo"])
def test_dojo_completion(simple_award_dojo, completionist_user):
    user_name, session = completionist_user
    dojo = simple_award_dojo

    response = session.get(f"{PROTO}://{HOST}/dojo/{dojo}/join/")
    assert response.status_code == 200
    for module, challenge in [
        ("hello", "apple"), ("hello", "banana"),
        #("world", "earth"), ("world", "mars"), ("world", "venus")
    ]:
        start_and_solve(user_name, session, dojo, module, challenge)

    # check for emoji
    scoreboard = session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 2
    assert len(us["badges"]) == 1

@pytest.mark.dependency(depends=["test_join_dojo"])
def test_prune_dojo_awards(simple_award_dojo, admin_session, completionist_user):
    user_name, _ = completionist_user
    db_sql(f"DELETE FROM solves WHERE user_id={get_user_id(user_name)} LIMIT 1")

    # unfortunately, the scoreboard cache makes this test impossible without going through ctfd or `dojo flask`
    #scoreboard = admin_session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/scoreboard/example/_/0/1").json()
    #us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    #assert us["solves"] == 4
    #assert len(us["badges"]) == 1

    response = admin_session.post(f"{PROTO}://{HOST}/pwncollege_api/v1/dojo/{simple_award_dojo}/prune-awards", json={})
    assert response.status_code == 200

    scoreboard = admin_session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/scoreboard/{simple_award_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 1
    assert len(us["badges"]) == 0

@pytest.mark.dependency(depends=["test_dojo_completion"])
def test_belts(belt_dojos, random_user):
    user_name, session = random_user
    for color,dojo in belt_dojos.items():
        start_and_solve(user_name, session, dojo, "test", "test")
        scoreboard = session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        assert color in us["belt"]

@pytest.mark.dependency(depends=["test_belts"])
def test_cumulative_belts(belt_dojos, random_user):
    user_name, session = random_user
    for color,dojo in reversed(belt_dojos.items()):
        start_and_solve(user_name, session, dojo, "test", "test")
        scoreboard = session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        if color == "orange":
            # orange is last, so we should get all belts including blue
            assert "blue" in us["belt"]
        else:
            # until orange, we should be stuck in white
            assert "white" in us["belt"]

@pytest.mark.dependency(depends=["test_start_challenge"])
@pytest.mark.parametrize("path", ["/flag", "/challenge/apple"])
def test_workspace_path_exists(path):
    try:
        workspace_run(f"[ -f '{path}' ]", user="admin")
    except subprocess.CalledProcessError:
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
        s = workspace_run("sudo -v", user="admin")
    except subprocess.CalledProcessError:
        pass
    else:
        assert False, f"Expected sudo to fail, but got no error: {(s.stdout, s.stderr)}"


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

    # if test_workspace_challenge passed correctly, then we should get a valid flag here
    start_challenge(dojo, module, challenge, session=session)
    result = workspace_run("/challenge/apple", user=user)
    flag = result.stdout.strip()
    challenge_id = get_challenge_id(session, dojo, module, challenge)

    # submit the flag
    data = {
        "challenge_id": challenge_id,
        "submission": flag
    }

    response = session.post(f"{PROTO}://{HOST}/api/v1/challenges/attempt", json=data)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit flag"

    # check the scoreboard: is it updated?

    new_standings = get_all_standings(session, dojo, module)
    assert len(prior_standings) != len(new_standings), "Expected to have a new entry in the standings"

    found_me = False
    for standing in new_standings:
        if standing['name'] == user:
            found_me = True
            break
    assert found_me, f"Unable to find new user {user} in new standings after solving a challenge"
