import json
import random
import re
import string
import subprocess

import requests
import pytest

from utils import TEST_DOJOS_LOCATION, DOJO_URL, login, dojo_run, workspace_run, create_dojo_yml


def get_dojo_modules(dojo):
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/modules")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    return response.json()["modules"]


def start_challenge(dojo, module, challenge, practice=False, *, session, as_user=None):
    start_challenge_json = dict(dojo=dojo, module=module, challenge=challenge, practice=practice)
    if as_user:
        start_challenge_json["as_user"] = as_user
    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json=start_challenge_json)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to start challenge: {response.json()['error']}"


def solve_challenge(dojo, module, challenge, *, session, flag=None, user=None):
    flag = flag if flag is not None else workspace_run("cat /flag", user=user, root=True).stdout.strip()
    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/solve",
        json={"submission": flag}
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit flag"

def get_challenge_survey(dojo, module, challenge, session):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/surveys")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to recieve valid survey"
    return response.json()

def post_survey_response(dojo, module, challenge, survey_response, session):
    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/surveys",
        json={"response": survey_response}
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit survey"

def db_sql(sql):
    db_result = dojo_run("db", input=sql)
    return db_result.stdout


def db_sql_one(sql):
    return db_sql(sql).split()[1]


def get_user_id(user_name):
    return int(db_sql_one(f"SELECT id FROM users WHERE name = '{user_name}'"))


@pytest.mark.parametrize("endpoint", ["/", "/dojos", "/login", "/register"])
def test_unauthenticated_return_200(endpoint):
    response = requests.get(f"{DOJO_URL}{endpoint}")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"


def test_login():
    login("admin", "incorrect_password", success=False)
    login("admin", "admin")


def test_register():
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    login(random_id, random_id, register=True)


@pytest.mark.dependency()
def test_create_dojo(example_dojo, admin_session):
    assert admin_session.get(f"{DOJO_URL}/{example_dojo}/").status_code == 200
    assert admin_session.get(f"{DOJO_URL}/example/").status_code == 200


@pytest.mark.dependency()
def test_get_dojo_modules(example_dojo):
    modules = get_dojo_modules(example_dojo)

    hello_module = modules[0]
    assert hello_module['id'] == "hello", f"Expected module id to be 'hello' but got {hello_module['id']}"
    assert hello_module['name'] == "Hello", f"Expected module name to be 'Hello' but got {hello_module['name']}"

    world_module = modules[1]
    assert world_module['id'] == "world", f"Expected module id to be 'world' but got {world_module['id']}"
    assert world_module['name'] == "World", f"Expected module name to be 'World' but got {world_module['name']}"


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_delete_dojo(admin_session):
    reference_id = create_dojo_yml("""id: delete-test""", session=admin_session)
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
    assert admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={"dojo": reference_id}).status_code == 200
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 404


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_create_import_dojo(example_import_dojo, admin_session):
    assert admin_session.get(f"{DOJO_URL}/{example_import_dojo}/").status_code == 200
    assert admin_session.get(f"{DOJO_URL}/example-import/").status_code == 200


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_start_challenge(admin_session):
    start_challenge("example", "hello", "apple", session=admin_session)


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_join_dojo(admin_session, guest_dojo_admin):
    random_user_name, random_session = guest_dojo_admin
    response = random_session.get(f"{DOJO_URL}/dojo/example/join/")
    assert response.status_code == 200
    response = admin_session.get(f"{DOJO_URL}/dojo/example/admin/")
    assert response.status_code == 200
    assert random_user_name in response.text and response.text.index("Members") < response.text.index(random_user_name)


@pytest.mark.dependency(depends=["test_join_dojo"])
def test_promote_dojo_member(admin_session, guest_dojo_admin):
    random_user_name, _ = guest_dojo_admin
    random_user_id = get_user_id(random_user_name)
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/example/admins/promote", json={"user_id": random_user_id})
    assert response.status_code == 200
    response = admin_session.get(f"{DOJO_URL}/dojo/example/admin/")
    assert random_user_name in response.text and response.text.index("Members") > response.text.index(random_user_name)


@pytest.mark.dependency(depends=["test_join_dojo"])
def test_dojo_completion(simple_award_dojo, completionist_user):
    user_name, session = completionist_user
    dojo = simple_award_dojo

    response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200
    for module, challenge in [
        ("hello", "apple"), ("hello", "banana"),
        #("world", "earth"), ("world", "mars"), ("world", "venus")
    ]:
        start_challenge(dojo, module, challenge, session=session)
        solve_challenge(dojo, module, challenge, session=session, user=user_name)

    # check for emoji
    scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 2
    assert len(us["badges"]) == 1


@pytest.mark.dependency(depends=["test_join_dojo"])
def test_no_practice(no_practice_challenge_dojo, no_practice_dojo, random_user):
    _, session = random_user
    for dojo in [ no_practice_challenge_dojo, no_practice_dojo ]:
        response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
        assert response.status_code == 200
        response = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
            "dojo": dojo,
            "module": "test",
            "challenge": "test",
            "practice": True
        })
        assert response.status_code == 200
        assert not response.json()["success"]
        assert "practice" in response.json()["error"]


@pytest.mark.dependency(depends=["test_join_dojo"])
def test_lfs(lfs_dojo, random_user):
    uid, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{lfs_dojo}/join/").status_code == 200
    start_challenge(lfs_dojo, "test", "test", session=session)
    try:
        workspace_run("[ -f '/challenge/dojo.txt' ]", user=uid)
    except subprocess.CalledProcessError:
        assert False, "LFS didn't create dojo.txt"


@pytest.mark.dependency(depends=["test_join_dojo"])
def test_import_override(import_override_dojo, random_user):
    uid, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{import_override_dojo}/join/").status_code == 200
    start_challenge(import_override_dojo, "test", "test", session=session)
    try:
        workspace_run("[ -f '/challenge/boom' ]", user=uid)
        workspace_run("[ ! -f '/challenge/apple' ]", user=uid)
    except subprocess.CalledProcessError:
        assert False, "dojo_initialize_files didn't create /challenge/boom"


@pytest.mark.dependency(depends=["test_join_dojo"])
def test_challenge_transfer(transfer_src_dojo, transfer_dst_dojo, random_user):
    user_name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{transfer_src_dojo}/join/").status_code == 200
    assert session.get(f"{DOJO_URL}/dojo/{transfer_dst_dojo}/join/").status_code == 200
    start_challenge(transfer_dst_dojo, "dst-module", "dst-challenge", session=session)
    solve_challenge(transfer_dst_dojo, "dst-module", "dst-challenge", session=session, user=user_name)
    scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{transfer_src_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 1


@pytest.mark.dependency(depends=["test_join_dojo"])
def test_no_import(no_import_challenge_dojo, admin_session):
    try:
        create_dojo_yml(open(TEST_DOJOS_LOCATION / "forbidden_import.yml").read(), session=admin_session)
    except AssertionError as e:
        assert "Import disallowed" in str(e)
    else:
        raise AssertionError("forbidden-import dojo creation should have failed, but it succeeded")


@pytest.mark.dependency(depends=["test_join_dojo"])
def test_prune_dojo_awards(simple_award_dojo, admin_session, completionist_user):
    user_name, _ = completionist_user
    db_sql(f"DELETE FROM solves WHERE user_id={get_user_id(user_name)} LIMIT 1")

    # unfortunately, the scoreboard cache makes this test impossible without going through ctfd or `dojo flask`
    #scoreboard = admin_session.get(f"{PROTO}://{HOST}/pwncollege_api/v1/scoreboard/example/_/0/1").json()
    #us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    #assert us["solves"] == 4
    #assert len(us["badges"]) == 1

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{simple_award_dojo}/awards/prune", json={})
    assert response.status_code == 200

    scoreboard = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{simple_award_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 1
    assert len(us["badges"]) == 0


@pytest.mark.dependency(depends=["test_dojo_completion"])
def test_belts(belt_dojos, random_user):
    user_name, session = random_user
    for color,dojo in belt_dojos.items():
        start_challenge(dojo, "test", "test", session=session)
        solve_challenge(dojo, "test", "test", session=session, user=user_name)
        scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        assert color in us["belt"]


@pytest.mark.dependency(depends=["test_belts"])
def test_cumulative_belts(belt_dojos, random_user):
    user_name, session = random_user
    for color,dojo in reversed(belt_dojos.items()):
        start_challenge(dojo, "test", "test", session=session)
        solve_challenge(dojo, "test", "test", session=session, user=user_name)
        scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()
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


def check_mount(path, *, user, fstype=None, check_nosuid=True):
    try:
        result = workspace_run(f"findmnt -J {path}", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"'{path}' not mounted: {(e.stdout, e.stderr)}"
    assert result, f"'{path}' not mounted: {(e.stdout, e.stderr)}"

    mount_info = json.loads(result.stdout)
    assert len(mount_info.get("filesystems", [])) == 1, f"Expected exactly one filesystem, but got: {mount_info}"

    filesystem = mount_info["filesystems"][0]
    assert filesystem["target"] == path, f"Expected '{path}' to be mounted at '{path}', but got: {filesystem}"
    if fstype:
        assert filesystem["fstype"] == fstype, f"Expected '{path}' to be mounted as '{fstype}', but got: {filesystem}"
    if check_nosuid:
        assert "nosuid" in filesystem["options"], f"Expected '{path}' to be mounted nosuid, but got: {filesystem}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_home_mount():
    check_mount("/home/hacker", user="admin")


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_no_sudo():
    try:
        s = workspace_run("sudo whoami", user="admin")
    except subprocess.CalledProcessError:
        pass
    else:
        assert False, f"Expected sudo to fail, but got no error: {(s.stdout, s.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_workspace_practice_challenge(random_user):
    user, session = random_user
    start_challenge("example", "hello", "apple", practice=True, session=session)
    try:
        result = workspace_run("sudo whoami", user=user)
        assert result.stdout.strip() == "root", f"Expected 'root', but got: ({result.stdout}, {result.stderr})"
    except subprocess.CalledProcessError as e:
        assert False, f"Expected sudo to succeed, but got: {(e.stdout, e.stderr)}"


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
def test_active_module_endpoint(random_user):
    user, session = random_user
    start_challenge("example", "hello", "banana", session=session)
    response = session.get(f"{DOJO_URL}/active-module")
    challenges = {
        "apple": {
            "challenge_id": 1,
            "challenge_name": "Apple",
            "challenge_reference_id": "apple",
            "dojo_name": "Example Dojo",
            "dojo_reference_id": "example",
            "module_id": "hello",
            "module_name": "Hello",
            "description": "<p>This is apple.</p>",
        },
        "banana": {
            "challenge_id": 2,
            "challenge_name": "Banana",
            "challenge_reference_id": "banana",
            "dojo_name": "Example Dojo",
            "dojo_reference_id": "example",
            "module_id": "hello",
            "module_name": "Hello",
            "description": "<p>This is banana.</p>",
        },
        "empty": {}
    }
    apple_description = challenges["apple"].pop("description")
    challenges["apple"]["description"] = None
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["c_current"] == challenges["banana"], f"Expected challenge 'Banana'\n{challenges['banana']}\n, but got {response.json()['c_current']}"
    assert response.json()["c_next"] == challenges["empty"], f"Expected empty {challenges['empty']} challenge, but got {response.json()['c_next']}"
    assert response.json()["c_previous"] == challenges["apple"], f"Expected challenge 'Apple'\n{challenges['apple']}\n, but got {response.json()['c_previous']}"
    challenges["apple"]["description"] = apple_description

    start_challenge("example", "hello", "apple", session=session)
    response = session.get(f"{DOJO_URL}/active-module")
    banana_description = challenges["banana"].pop("description")
    challenges["banana"]["description"] = None
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["c_current"] == challenges["apple"], f"Expected challenge 'Apple'\n{challenges['apple']}\n, but got {response.json()['c_current']}"
    assert response.json()["c_next"] == challenges["banana"], f"Expected challenge 'Banana'\n{challenges['banana']}\n, but got {response.json()['c_next']}"
    assert response.json()["c_previous"] == challenges["empty"], f"Expected empty {challenges['empty']} challenge, but got {response.json()['c_previous']}"
    challenges["banana"]["description"] = banana_description


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
        response = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/{module}/0/{page_number}")
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

    start_challenge(dojo, module, challenge, session=session)
    result = workspace_run("/challenge/apple", user=user)
    flag = result.stdout.strip()
    solve_challenge(dojo, module, challenge, session=session, flag=flag)

    new_standings = get_all_standings(session, dojo, module)
    assert len(prior_standings) != len(new_standings), "Expected to have a new entry in the standings"

    found_me = False
    for standing in new_standings:
        if standing['name'] == user:
            found_me = True
            break
    assert found_me, f"Unable to find new user {user} in new standings after solving a challenge"


@pytest.mark.skip(reason="Disabling test temporarily until overlay issue is resolved")
@pytest.mark.dependency(depends=["test_workspace_home_persistent"])
def test_workspace_as_user(admin_user, random_user):
    admin_user, admin_session = admin_user
    random_user, random_session = random_user
    random_user_id = get_user_id(random_user)

    start_challenge("example", "hello", "apple", session=random_session)
    workspace_run("touch /home/hacker/test", user=random_user)

    start_challenge("example", "hello", "apple", session=admin_session, as_user=random_user_id)
    check_mount("/home/hacker", user=admin_user)
    check_mount("/home/me", user=admin_user)

    try:
        workspace_run("[ -f '/home/hacker/test' ]", user=admin_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected existing file to exist, but got: {(e.stdout, e.stderr)}"

    workspace_run("touch /home/hacker/test2", user=random_user)
    try:
        workspace_run("[ -f '/home/hacker/test2' ]", user=admin_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected new file to exist, but got: {(e.stdout, e.stderr)}"

    workspace_run("touch /home/hacker/test3", user=admin_user)
    try:
        workspace_run("[ ! -e '/home/hacker/test3' ]", user=random_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected overlay file to not exist, but got: {(e.stdout, e.stderr)}"


@pytest.mark.dependency(depends=["test_start_challenge"])
def test_reset_home_directory(random_user):
    user, session = random_user

    # Create a file in the home directory
    start_challenge("example", "hello", "apple", session=session)
    workspace_run("touch /home/hacker/testfile", user=user)

    # Reset the home directory
    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/workspace/reset_home", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to reset home directory: {response.json()['error']}"

    try:
        workspace_run("[ -f '/home/hacker/home-backup.tar.gz' ]", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected zip file to exist, but got: {(e.stdout, e.stderr)}"

    try:
        workspace_run("[ ! -f '/home/hacker/testfile' ]", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected test file to be wiped, but got: {(e.stdout, e.stderr)}"


@pytest.mark.dependency()
def test_searchable_content(searchable_dojo, admin_session):
    search_url = f"{DOJO_URL}/pwncollege_api/v1/search"

    cases = [
        # Matches in name only — verify name field
        ("searchable", lambda r: any("searchable dojo" in d["name"].lower() for d in r["dojos"])),
        ("hello", lambda r: any("hello module" in m["name"].lower() for m in r["modules"])),
        ("Apple Challenge", lambda r: any("apple challenge" in c["name"].lower() for c in r["challenges"])),

        # Matches in description — verify `match` exists and contains the query
        ("search test content", lambda r: any("search test content" in (d.get("match") or "").lower() for d in r["dojos"])),
        ("search testing", lambda r: any("search testing" in (m.get("match") or "").lower() for m in r["modules"])),
        ("about apples", lambda r: any("about apples" in (c.get("match") or "").lower() for c in r["challenges"])),
    ]

    for query, validate in cases:
        response = admin_session.get(search_url, params={"q": query})
        assert response.status_code == 200, f"Request failed for query: {query}"
        data = response.json()
        assert data["success"]
        assert validate(data["results"]), f"No expected match found for query: {query}"

def test_search_no_results(admin_session):
    search_url = f"{DOJO_URL}/pwncollege_api/v1/search"
    query = "qwertyuiopasdfgh"  # something unlikely to match anything

    response = admin_session.get(search_url, params={"q": query})
    assert response.status_code == 200
    data = response.json()

    assert data["success"]
    assert not data["results"]["dojos"], "Expected no dojo matches"
    assert not data["results"]["modules"], "Expected no module matches"
    assert not data["results"]["challenges"], "Expected no challenge matches"

def test_progression_locked(progression_locked_dojo, random_user):
    uid, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{progression_locked_dojo}/join/").status_code == 200
    start_challenge(progression_locked_dojo, "progression-locked-module", "unlocked-challenge", session=session)

    with pytest.raises(AssertionError, match="Failed to start challenge: This challenge is locked"):
        start_challenge(progression_locked_dojo, "progression-locked-module", "locked-challenge", session=session)

    solve_challenge(progression_locked_dojo, "progression-locked-module", "unlocked-challenge", session=session, user=uid)
    start_challenge(progression_locked_dojo, "progression-locked-module", "locked-challenge", session=session)

def test_surveys(surveys_dojo, random_user):
    uid, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{surveys_dojo}/join/").status_code == 200

    challenge_level_survey = get_challenge_survey(surveys_dojo, "surveys-module-1", "challenge-level", session=session)
    module_level_survey = get_challenge_survey(surveys_dojo, "surveys-module-1", "module-level", session=session)
    dojo_level_survey = get_challenge_survey(surveys_dojo, "surveys-module-2", "dojo-level", session=session)

    assert challenge_level_survey["prompt"] == "Challenge-level prompt", "Challenge-level survey is wrong/missing"
    assert module_level_survey["prompt"] == "Module-level prompt", "Module-level survey is wrong/missing"
    assert dojo_level_survey["prompt"] == "Dojo-level prompt", "Dojo-level survey is wrong/missing"

    assert len(dojo_level_survey["options"]) == 3, "Survey options are wrong/missing"

    post_survey_response(surveys_dojo, "surveys-module-1", "challenge-level", "Test response", session=session)
    post_survey_response(surveys_dojo, "surveys-module-1", "module-level", "up", session=session)
    post_survey_response(surveys_dojo, "surveys-module-2", "dojo-level", 1, session=session)