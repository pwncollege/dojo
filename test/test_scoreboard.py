import random
import string

import pytest

from utils import DOJO_URL, login, create_dojo_yml, workspace_run, start_challenge, solve_challenge, wait_for_background_worker, get_user_id, remove_workspace_container


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


def test_scoreboard(random_user_name, random_user_session, example_dojo):
    dojo = example_dojo
    module = "hello"
    challenge = "apple"

    prior_standings = get_all_standings(random_user_session, dojo, module)

    start_challenge(dojo, module, challenge, session=random_user_session)
    result = workspace_run("/challenge/apple", user=random_user_name)
    flag = result.stdout.strip()
    solve_challenge(dojo, module, challenge, session=random_user_session, flag=flag)

    wait_for_background_worker(timeout=2)

    new_standings = get_all_standings(random_user_session, dojo, module)
    assert len(prior_standings) != len(new_standings), "Expected to have a new entry in the standings"

    found_me = False
    for standing in new_standings:
        if standing['name'] == random_user_name:
            found_me = True
            break
    assert found_me, f"Unable to find new user {random_user_name} in new standings after solving a challenge"


def bracket_name_solver(example_dojo, tag):
    user_id = "".join(random.choices(string.ascii_lowercase, k=12))
    name = f"{user_id} [{tag}]"
    session = login(name, user_id, register=True, email=f"{user_id}@example.com")
    start_challenge(example_dojo, "hello", "apple", session=session)
    result = workspace_run("/challenge/apple", user=name)
    solve_challenge(example_dojo, "hello", "apple", session=session, flag=result.stdout.strip())
    remove_workspace_container(name)
    wait_for_background_worker(timeout=30)
    return name, session


@pytest.mark.timeout(180)
def test_scoreboard_bracket_name_passthrough(example_dojo):
    name, session = bracket_name_solver(example_dojo, "CrewTag")
    standings = get_all_standings(session, example_dojo)
    assert any(standing["name"] == name for standing in standings), \
        f"user {name!r} not found verbatim in standings"


@pytest.mark.timeout(180)
def test_scoreboard_hostile_tag_passthrough(example_dojo):
    name, session = bracket_name_solver(example_dojo, '<b x="y">&amp;')
    standings = get_all_standings(session, example_dojo)
    assert any(standing["name"] == name for standing in standings), \
        f"user {name!r} not found verbatim in standings"


def test_scoreboard_empty_module_contract(admin_session, example_dojo):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = f"""
id: empty-board-{suffix}
name: Empty Board
modules:
  - id: hello
    name: Hello
    challenges:
      - id: apple
        import:
          dojo: example
          module: hello
          challenge: apple
"""
    dojo = create_dojo_yml(spec, session=admin_session)
    response = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/hello/0/1")
    assert response.status_code == 200
    result = response.json()
    assert result["standings"] == []
    assert result["pages"] == []


def test_folder_awards(admin_session, event_dojo, random_user, example_dojo):
    grant_award = f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant"
    random_user_name, random_user_session = random_user
    uid = get_user_id(random_user_name)
    assert admin_session.post(grant_award, json={"user_id": uid, "emoji": "🥈", "description": "Test emoji 1"}).status_code == 200
    assert admin_session.post(grant_award, json={"user_id": uid, "emoji": "🥈", "description": "Test emoji 2"}).status_code == 200

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    result = workspace_run("/challenge/apple", user=random_user_name)
    flag = result.stdout.strip()
    solve_challenge(example_dojo, "hello", "apple", session=random_user_session, flag=flag)

    wait_for_background_worker()

    scoreboard = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{example_dojo}/hello/0/1").json()
    assert scoreboard.get("me",None), f"Unable to find entry for {random_user_name}."
    for emoji in scoreboard["me"]["badges"]:
        if emoji["emoji"] == "🥈" and emoji["count"] == 2:
            return
    assert False, f"Failed to find second place award with count 2. Emojis: {scoreboard["me"]["badges"]}"

