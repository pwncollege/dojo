import pytest

from utils import DOJO_URL, workspace_run, start_challenge, solve_challenge, wait_for_background_worker, get_user_id


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


def test_folder_awards(admin_session, event_dojo, random_user, example_dojo):
    grant_award = f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant"
    random_user_name, random_user_session = random_user
    uid = get_user_id(random_user_name)
    assert admin_session.post(grant_award, json={"user_id": uid, "event_name": "Test Event 1", "event_place": 2}).status_code == 200
    assert admin_session.post(grant_award, json={"user_id": uid, "event_name": "Test Event 2", "event_place": 2}).status_code == 200

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

