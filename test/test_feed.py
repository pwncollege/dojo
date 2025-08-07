import time
import random
import string
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from utils import DOJO_URL, login


def test_feed_api_endpoint():
    username = "apitest" + "".join(random.choices(string.ascii_lowercase, k=8))
    session = login(username, username, register=True)
    
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    
    data = response.json()
    assert "success" in data
    assert data["success"] is True
    assert "data" in data
    assert isinstance(data["data"], list)
    print(f"✓ Feed API endpoint works")


def challenge_expand(browser, idx):
    browser.refresh()
    browser.find_element("id", f"challenges-header-button-{idx}").click()
    time.sleep(0.5)


def challenge_start(browser, idx):
    challenge_expand(browser, idx)
    body = browser.find_element("id", f"challenges-body-{idx}")
    body.find_element("id", "challenge-start").click()
    
    counter = 0
    while counter < 20:
        message = body.find_element("id", "result-message").text
        if "started" in message.lower():
            break
        time.sleep(0.5)
        counter += 1
    
    assert counter < 20, "Challenge failed to start"
    time.sleep(1)


def test_feed_shows_all_events(welcome_dojo):
    from utils import workspace_run
    
    user_name = "feeduser" + "".join(random.choices(string.ascii_lowercase, k=8))
    user_session = login(user_name, user_name, register=True)
    
    watcher_options = FirefoxOptions()
    watcher_options.add_argument("--headless")
    watcher = Firefox(options=watcher_options)
    
    user_options = FirefoxOptions()
    user_options.add_argument("--headless")
    user_browser = Firefox(options=user_options)
    
    try:
        watcher.get(f"{DOJO_URL}/feed")
        initial_events = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")
        initial_count = len(initial_events)
        print(f"Initial events on feed: {initial_count}")
        
        user_browser.get(f"{DOJO_URL}/login")
        user_browser.find_element("id", "name").send_keys(user_name)
        user_browser.find_element("id", "password").send_keys(user_name)
        user_browser.find_element("id", "_submit").click()
        
        user_browser.get(f"{DOJO_URL}/welcome/welcome")
        time.sleep(1)
        
        num_challenges = len(user_browser.find_elements("id", "challenge-start"))
        challenge_idx = None
        for n in range(num_challenges):
            header_text = user_browser.find_element("id", f"challenges-header-button-{n+1}").text
            if "The Flag File" in header_text:
                challenge_idx = n + 1
                break
        
        assert challenge_idx is not None, "Could not find 'The Flag File' challenge"
        
        print(f"Starting challenge at index {challenge_idx}")
        challenge_start(user_browser, challenge_idx)
        print("✓ Challenge started")
        
        time.sleep(2)
        
        watcher.refresh()
        time.sleep(1)
        
        events_after_start = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")
        print(f"Events after container start: {len(events_after_start)}")
        
        found_start_event = False
        for event in events_after_start:
            event_text = event.text
            if user_name in event_text and "started a" in event_text and "container" in event_text:
                found_start_event = True
                print(f"✓ Found container start event: {event_text[:100]}...")
                break
        
        assert found_start_event, f"Container start event for {user_name} not found"
        
        print("Solving challenge...")
        time.sleep(2)
        workspace_run("/challenge/solve > /tmp/solve_output 2>&1", user=user_name)
        time.sleep(1)
        flag_output = workspace_run("cat /flag", user=user_name).stdout.strip()
        print(f"Got flag: {flag_output}")
        
        body = user_browser.find_element("id", f"challenges-body-{challenge_idx}")
        user_browser.switch_to.frame(body.find_element("id", "workspace-iframe"))
        
        flag_input = user_browser.find_element("id", "flag-input")
        flag_input.clear()
        flag_input.send_keys(flag_output)
        
        counter = 0
        while counter < 20:
            placeholder = flag_input.get_attribute("placeholder")
            if "orrect" in placeholder:
                print("✓ Flag accepted")
                break
            time.sleep(0.5)
            counter += 1
        
        user_browser.switch_to.default_content()
        
        time.sleep(2)
        
        watcher.refresh()
        time.sleep(1)
        
        events_after_solve = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")
        print(f"Events after solve: {len(events_after_solve)}")
        
        found_solve_event = False
        container_events = 0
        solve_events = 0
        
        for event in events_after_solve:
            event_text = event.text
            if user_name in event_text:
                if "started a" in event_text and "container" in event_text:
                    container_events += 1
                    print(f"✓ Container start event: {event_text[:100]}...")
                elif "solved" in event_text.lower():
                    solve_events += 1
                    found_solve_event = True
                    print(f"✓ Challenge solve event: {event_text}")
        
        assert container_events > 0, f"No container start events found for {user_name}"
        assert found_solve_event, f"Challenge solve event for {user_name} not found"

    finally:
        watcher.quit()
        user_browser.quit()


def test_private_dojo_events_not_shown(random_private_dojo, random_user_name, random_user_session):
    import requests
    
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    initial_events = response.json()["data"]
    initial_count = len(initial_events)
    print(f"Initial events on feed: {initial_count}")
    
    start_data = {
        "dojo": random_private_dojo,
        "module": "test-module",
        "challenge": "test-challenge"
    }
    response = random_user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json=start_data)
    if response.status_code == 200:
        print(f"✓ Started container in private dojo '{random_private_dojo}'")
    else:
        print(f"Warning: Could not start container: {response.json()}")
    
    time.sleep(1)
    
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    events_after = response.json()["data"]
    print(f"Events after private dojo action: {len(events_after)}")
    
    found_event = False
    for event in events_after:
        if event.get("user_name") == random_user_name:
            found_event = True
            print(f"✗ FAILED: Found private dojo event in feed: {event}")
            break
    
    assert not found_event, f"Private dojo events should NOT appear in the feed!"
    assert len(events_after) == initial_count, f"Event count changed! Before: {initial_count}, After: {len(events_after)}"
    print(f"✓ Private dojo events correctly filtered from feed")


