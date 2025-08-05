import subprocess
import requests
import pytest
import random
import string

from utils import TEST_DOJOS_LOCATION, DOJO_URL, dojo_run, create_dojo_yml, start_challenge, solve_challenge, workspace_run, login, db_sql, get_user_id


def get_dojo_modules(dojo):
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/modules")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    return response.json()["modules"]


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


def test_import(import_dojo, admin_session):
    assert admin_session.get(f"{DOJO_URL}/{import_dojo}/hello").status_code == 200

# this exists despite test_import because it doesn't re-run on re-test, but we still want to make sure our public example-import dojo passes
def test_create_import_dojo(example_import_dojo, admin_session):
    assert admin_session.get(f"{DOJO_URL}/{example_import_dojo}/").status_code == 200
    assert admin_session.get(f"{DOJO_URL}/example-import/").status_code == 200

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
    db_sql(f"DELETE FROM solves WHERE id IN (SELECT id FROM solves WHERE user_id={get_user_id(user_name)} ORDER BY id DESC LIMIT 1)")

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{simple_award_dojo}/awards/prune", json={})
    assert response.status_code == 200

    scoreboard = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{simple_award_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 1
    assert len(us["badges"]) == 0


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


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_hidden_challenges(admin_session, random_user, hidden_challenges_dojo):
    assert "CHALLENGE" in admin_session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text
    assert random_user[1].get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").status_code == 200
    assert "CHALLENGE" not in random_user[1].get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text


@pytest.mark.dependency(depends=["test/test_challenges.py::test_start_challenge"], scope="session")
def test_dojo_solves_api(example_dojo, random_user):
    user_name, session = random_user
    dojo = example_dojo

    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    other_session = login(random_id, random_id, register=True)

    start_challenge(dojo, "hello", "apple", session=session)
    solve_challenge(dojo, "hello", "apple", session=session, user=user_name)

    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/solves")
    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    assert len(data["solves"]) == 1
    assert data["solves"][0]["challenge_id"] == "apple"

    response = other_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/solves", params={"username": user_name})
    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    assert len(data["solves"]) == 1
    assert data["solves"][0]["challenge_id"] == "apple"
