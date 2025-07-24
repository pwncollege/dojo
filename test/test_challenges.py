import subprocess

import pytest

from utils import DOJO_URL, workspace_run, start_challenge


def solve_challenge(dojo, module, challenge, *, session, flag=None, user=None):
    flag = flag if flag is not None else workspace_run("cat /flag", user=user, root=True).stdout.strip()
    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/solve",
        json={"submission": flag}
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit flag"


@pytest.mark.dependency(depends=["test_create_dojo"])
def test_start_challenge(admin_session):
    start_challenge("example", "hello", "apple", session=admin_session)


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


def test_hidden_challenges(admin_session, random_user, hidden_challenges_dojo):
    assert "CHALLENGE" in admin_session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text
    assert random_user[1].get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").status_code == 200
    assert "CHALLENGE" not in random_user[1].get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text


def test_progression_locked(progression_locked_dojo, random_user):
    uid, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{progression_locked_dojo}/join/").status_code == 200
    start_challenge(progression_locked_dojo, "progression-locked-module", "unlocked-challenge", session=session)

    with pytest.raises(AssertionError, match="Failed to start challenge: This challenge is locked"):
        start_challenge(progression_locked_dojo, "progression-locked-module", "locked-challenge", session=session)

    solve_challenge(progression_locked_dojo, "progression-locked-module", "unlocked-challenge", session=session, user=uid)
    start_challenge(progression_locked_dojo, "progression-locked-module", "locked-challenge", session=session)