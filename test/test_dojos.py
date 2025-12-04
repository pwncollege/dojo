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


def test_create_dojo(example_dojo, admin_session):
    assert admin_session.get(f"{DOJO_URL}/{example_dojo}/").status_code == 200
    assert admin_session.get(f"{DOJO_URL}/{example_dojo}/").status_code == 200


def test_get_dojo_modules(example_dojo):
    modules = get_dojo_modules(example_dojo)

    hello_module = modules[0]
    assert hello_module['id'] == "hello", f"Expected module id to be 'hello' but got {hello_module['id']}"
    assert hello_module['name'] == "Hello", f"Expected module name to be 'Hello' but got {hello_module['name']}"

    world_module = modules[1]
    assert world_module['id'] == "world", f"Expected module id to be 'world' but got {world_module['id']}"
    assert world_module['name'] == "World", f"Expected module name to be 'World' but got {world_module['name']}"


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
    assert admin_session.get(f"{DOJO_URL}/{example_import_dojo}/").status_code == 200

def test_join_dojo(admin_session, guest_dojo_admin, example_dojo):
    random_user_name, random_session = guest_dojo_admin
    response = random_session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/")
    assert response.status_code == 200
    response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert response.status_code == 200
    assert random_user_name in response.text and response.text.index("Members") < response.text.index(random_user_name)


def test_promote_dojo_member(admin_session, guest_dojo_admin, example_dojo):
    random_user_name, _ = guest_dojo_admin
    random_user_id = get_user_id(random_user_name)
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/admins/promote", json={"user_id": random_user_id})
    assert response.status_code == 200
    response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert random_user_name in response.text and response.text.index("Members") > response.text.index(random_user_name)


def test_dojo_completion_emoji(simple_award_dojo, advanced_award_dojo, completionist_user):
    user_name, session = completionist_user

    award_dojos = [simple_award_dojo, advanced_award_dojo]
    for award_dojo in award_dojos:
        scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{award_dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        assert us["solves"] == 2
        assert len(us["badges"]) == 2

def test_no_practice(no_practice_challenge_dojo, no_practice_dojo, random_user_session):
    for dojo in [ no_practice_challenge_dojo, no_practice_dojo ]:
        response = random_user_session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
        assert response.status_code == 200
        response = random_user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
            "dojo": dojo,
            "module": "test",
            "challenge": "test",
            "practice": True
        })
        assert response.status_code == 200
        assert not response.json()["success"]
        assert "practice" in response.json()["error"]


def test_no_import(no_import_challenge_dojo, admin_session):
    try:
        create_dojo_yml(open(
            TEST_DOJOS_LOCATION / "forbidden_import.yml"
        ).read().replace("no-import-challenge", no_import_challenge_dojo), session=admin_session)
    except AssertionError as e:
        assert "Import disallowed" in str(e)
    else:
        raise AssertionError("forbidden-import dojo creation should have failed, but it succeeded")


def test_prune_dojo_emoji(simple_award_dojo, advanced_award_dojo, admin_session, completionist_user):
    user_name, _ = completionist_user
    db_sql(f"DELETE FROM submissions WHERE id IN (SELECT id FROM submissions WHERE user_id={get_user_id(user_name)} ORDER BY id DESC LIMIT 1)")

    award_dojos = [simple_award_dojo, advanced_award_dojo]
    for award_dojo in award_dojos:
        response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{award_dojo}/awards/prune", json={})
        assert response.status_code == 200
    
        scoreboard = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{award_dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        assert us["solves"] == 1
        assert len(us["badges"]) == 1
        assert us["badges"][0]["stale"] == True


def test_dojo_removes_emoji(simple_award_dojo, advanced_award_dojo, admin_session, completionist_user):
    user_name, _ = completionist_user

    award_dojos = [simple_award_dojo, advanced_award_dojo]
    for award_dojo in award_dojos:
        scoreboard = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{award_dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        assert us["solves"] == 2
        assert len(us["badges"]) == 1
        assert us["badges"][0]["stale"] == False
    
        dojo_id = award_dojo.split("~")[1]
        db_sql(f"UPDATE dojos SET data = data - 'award' || jsonb_build_object('award', jsonb_build_object('belt', 'orange')) WHERE dojo_id = x'{dojo_id}'::int")
    
        scoreboard = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{award_dojo}/_/0/1").json()
        us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
        assert us["solves"] == 2
        assert len(us["badges"]) == 0


def test_lfs(lfs_dojo, random_user_name, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/dojo/{lfs_dojo}/join/").status_code == 200
    start_challenge(lfs_dojo, "test", "test", session=random_user_session)
    try:
        workspace_run("[ -f '/challenge/dojo.txt' ]", user=random_user_name)
    except subprocess.CalledProcessError:
        assert False, "LFS didn't create dojo.txt"


def test_import_override(import_override_dojo, random_user_name, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/dojo/{import_override_dojo}/join/").status_code == 200
    start_challenge(import_override_dojo, "test", "test", session=random_user_session)
    try:
        workspace_run("[ -f '/challenge/boom' ]", user=random_user_name)
        workspace_run("[ ! -f '/challenge/apple' ]", user=random_user_name)
    except subprocess.CalledProcessError:
        assert False, "dojo_initialize_files didn't create /challenge/boom"


def test_challenge_transfer(transfer_src_dojo, transfer_dst_dojo, random_user_name, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/dojo/{transfer_src_dojo}/join/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/dojo/{transfer_dst_dojo}/join/").status_code == 200
    start_challenge(transfer_dst_dojo, "dst-module", "dst-challenge", session=random_user_session)
    solve_challenge(transfer_dst_dojo, "dst-module", "dst-challenge", session=random_user_session, user=random_user_name)
    scoreboard = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{transfer_src_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == random_user_name)
    assert us["solves"] == 1


def test_hidden_challenges(admin_session, random_user_session, hidden_challenges_dojo):
    assert "CHALLENGE" in admin_session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text
    assert random_user_session.get(f"{DOJO_URL}/dojo/{hidden_challenges_dojo}/join/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").status_code == 200
    assert "CHALLENGE" not in random_user_session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text


def test_dojo_solves_api(example_dojo, random_user_name, random_user_session):
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    other_session = login(random_id, random_id, register=True)

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    solve_challenge(example_dojo, "hello", "apple", session=random_user_session, user=random_user_name)

    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves")
    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    assert len(data["solves"]) == 1
    assert data["solves"][0]["challenge_id"] == "apple"

    response = other_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves", params={"username": random_user_name})
    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    assert len(data["solves"]) == 1
    assert data["solves"][0]["challenge_id"] == "apple"
