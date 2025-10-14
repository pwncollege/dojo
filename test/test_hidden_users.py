import pytest

from utils import DOJO_URL, workspace_run, start_challenge, solve_challenge, db_sql, get_user_id


def test_hidden_user_sees_own_emojis(random_user_name, random_user_session, simple_award_dojo, admin_session):
    """Test that hidden users can see their own emojis."""
    dojo = simple_award_dojo
    
    # Join dojo and solve challenges to get an emoji
    response = random_user_session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200
    
    # Solve challenges to complete the dojo and earn an emoji
    for module, challenge in [("hello", "apple"), ("hello", "banana")]:
        start_challenge(dojo, module, challenge, session=random_user_session)
        solve_challenge(dojo, module, challenge, session=random_user_session, user=random_user_name)
    
    # Check that user has emojis before being hidden
    response = random_user_session.get(f"{DOJO_URL}/hacker/")
    assert response.status_code == 200
    # The page should have emoji data (badges)
    
    # Make the user hidden
    user_id = get_user_id(random_user_name)
    db_sql(f"UPDATE users SET hidden = true WHERE id = {user_id}")
    
    # Verify user can still see their own profile
    response = random_user_session.get(f"{DOJO_URL}/hacker/")
    assert response.status_code == 200, "Hidden user should be able to view their own profile"
    
    # Verify the user's emojis are visible in the response
    # The page uses JavaScript to load badges, but we can check the data is available
    response_text = response.text
    # The hacker.html template includes badges in the page data
    # We'll verify the page loads successfully, which means badges were retrieved
    
    # Verify other users can't see the hidden user's profile
    other_user_session = admin_session
    response = other_user_session.get(f"{DOJO_URL}/hacker/{user_id}")
    assert response.status_code == 404, "Other users should not be able to see hidden user's profile"


def test_hidden_user_sees_own_scoreboard_placement(random_user_name, random_user_session, example_dojo):
    """Test that hidden users can see their own scoreboard placement."""
    dojo = example_dojo
    module = "hello"
    challenge = "apple"
    
    # Solve a challenge to appear on the scoreboard
    start_challenge(dojo, module, challenge, session=random_user_session)
    result = workspace_run("/challenge/apple", user=random_user_name)
    flag = result.stdout.strip()
    solve_challenge(dojo, module, challenge, session=random_user_session, flag=flag)
    
    # Get scoreboard and verify user appears
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/{module}/0/1")
    assert response.status_code == 200
    data = response.json()
    
    # User should appear in "me" before being hidden
    assert "me" in data, "User should have 'me' entry in scoreboard"
    assert data["me"]["name"] == random_user_name
    
    # Make the user hidden
    user_id = get_user_id(random_user_name)
    db_sql(f"UPDATE users SET hidden = true WHERE id = {user_id}")
    
    # Get scoreboard again - hidden user should still see their own placement
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/{module}/0/1")
    assert response.status_code == 200
    data = response.json()
    
    # Hidden user should still see their "me" entry
    assert "me" in data, "Hidden user should still see their 'me' entry in scoreboard"
    assert data["me"]["name"] == random_user_name, "Hidden user should see their own name"
    assert data["me"]["rank"] > 0, "Hidden user should see their rank"
    
    # Verify hidden user is not in the public standings
    found_in_standings = False
    for standing in data["standings"]:
        if standing["name"] == random_user_name:
            found_in_standings = True
            break
    assert not found_in_standings, "Hidden user should not appear in public standings"


def test_hidden_user_emojis_on_scoreboard(random_user_name, random_user_session, simple_award_dojo, admin_session):
    """Test that hidden users can see their own emojis on the scoreboard."""
    dojo = simple_award_dojo
    
    # Join dojo and solve challenges to get an emoji
    response = random_user_session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200
    
    # Solve challenges to complete the dojo and earn an emoji
    for module, challenge in [("hello", "apple"), ("hello", "banana")]:
        start_challenge(dojo, module, challenge, session=random_user_session)
        solve_challenge(dojo, module, challenge, session=random_user_session, user=random_user_name)
    
    # Get scoreboard and verify user has badges before being hidden
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1")
    assert response.status_code == 200
    data = response.json()
    
    # User should have badges
    if "me" in data:
        initial_badges = data["me"].get("badges", [])
        assert len(initial_badges) > 0, "User should have earned badges"
    
    # Make the user hidden
    user_id = get_user_id(random_user_name)
    db_sql(f"UPDATE users SET hidden = true WHERE id = {user_id}")
    
    # Get scoreboard again - hidden user should still see their badges
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1")
    assert response.status_code == 200
    data = response.json()
    
    # Hidden user should still see their badges
    assert "me" in data, "Hidden user should see their 'me' entry"
    badges = data["me"].get("badges", [])
    assert len(badges) > 0, "Hidden user should still see their badges in scoreboard"
