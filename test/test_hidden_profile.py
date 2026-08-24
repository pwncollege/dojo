import requests

from utils import (
    DOJO_URL,
    db_sql,
    get_user_id,
    solve_challenge_offline,
    wait_for_background_worker,
)


def test_hidden_user_can_view_own_profile_data(admin_session, random_user, example_dojo):
    username, session = random_user
    user_id = get_user_id(username)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=username)
    wait_for_background_worker()
    activity_url = f"{DOJO_URL}/pwncollege_api/v1/activity/{user_id}"
    assert requests.get(activity_url).status_code == 200

    db_sql(f"""
        INSERT INTO awards (user_id, type, name, description, date, value, icon)
        VALUES
            ({user_id}, 'belt', 'orange', 'Orange Belt', NOW(), 0, NULL),
            ({user_id}, 'emoji', 'CUSTOM', 'Hidden self badge', NOW(), 0, '🧪')
    """)
    response = session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": True})
    assert response.status_code == 200

    profile = session.get(f"{DOJO_URL}/hacker/")
    assert profile.status_code == 200
    assert "/belt/orange.svg" in profile.text
    assert "Hidden self badge" in profile.text
    assert "Time of First Successful Submission" in profile.text

    activity = session.get(activity_url)
    assert activity.status_code == 200
    assert activity.json()["data"]["total_solves"] >= 1
    assert requests.get(activity_url).status_code == 404
    assert admin_session.get(activity_url).status_code == 404

    awards = session.get(f"{DOJO_URL}/api/v1/users/me/awards")
    assert awards.status_code == 200
    assert {award["name"] for award in awards.json()["data"]} >= {"orange", "CUSTOM"}
    assert session.get(f"{DOJO_URL}/hacker/{user_id}").status_code == 404
    assert session.get(f"{DOJO_URL}/hacker/{username}").status_code == 404
    assert session.get(f"{DOJO_URL}/api/v1/users/{user_id}/awards").status_code == 404
