import time
from utils import DOJO_URL, start_challenge, solve_challenge
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.by import By


def test_feed_shows_all_events(welcome_dojo, simple_award_dojo, random_user_name, random_user_session):
    watcher_options = FirefoxOptions()
    watcher_options.add_argument("--headless")
    watcher = Firefox(options=watcher_options)

    try:
        # Test container start event
        start_challenge(welcome_dojo, "welcome", "flag", session=random_user_session)
        time.sleep(1)

        watcher.get(f"{DOJO_URL}/feed")
        events = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")
        
        assert any(random_user_name in e.text and "started a" in e.text for e in events), \
            f"Container start event for {random_user_name} not found"

        # Test challenge solve event (streaming without refresh)
        solve_challenge(welcome_dojo, "welcome", "flag", session=random_user_session, user=random_user_name)
        time.sleep(1)
        events = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")
        
        assert any(random_user_name in e.text and "solved" in e.text.lower() for e in events), \
            f"Challenge solve event for {random_user_name} not found"

        # Test emoji earning event
        random_user_session.get(f"{DOJO_URL}/dojo/{simple_award_dojo}/join/")
        for challenge in ["apple", "banana"]:
            start_challenge(simple_award_dojo, "hello", challenge, session=random_user_session)
            solve_challenge(simple_award_dojo, "hello", challenge, session=random_user_session, user=random_user_name)
        
        time.sleep(1)
        events = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")
        
        assert any(random_user_name in e.text and "earned" in e.text.lower() and "🧪" in e.text for e in events), \
            f"Emoji earned event for {random_user_name} not found"

    finally:
        watcher.quit()


def test_private_dojo_events_not_shown(random_private_dojo, random_user_name, random_user_session):
    import requests
    
    # Get initial event count
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    initial_count = len(response.json()["data"])

    # Start challenge in private dojo
    start_data = {
        "dojo": random_private_dojo,
        "module": "test-module",
        "challenge": "test-challenge"
    }
    response = random_user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json=start_data)
    assert response.status_code == 200
    time.sleep(1)

    # Verify no new events appear
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    events_after = response.json()["data"]
    
    assert not any(e.get("user_name") == random_user_name for e in events_after), \
        "Private dojo events should NOT appear in the feed!"
    assert len(events_after) == initial_count, \
        f"Event count changed! Before: {initial_count}, After: {len(events_after)}"