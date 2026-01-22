import time
import logging
import requests
from utils import DOJO_HOST, start_challenge, solve_challenge, wait_for_background_worker
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.by import By

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


def test_feed_shows_all_events(welcome_dojo, simple_award_dojo, random_user_name, random_user_session):
    watcher_options = FirefoxOptions()
    watcher_options.add_argument("--headless")
    watcher = Firefox(options=watcher_options)

    try:
        start_challenge(welcome_dojo, "welcome", "flag", session=random_user_session)
        wait_for_background_worker(timeout=1)

        # make sure past events show up at load timej
        watcher.get(f"http://{DOJO_HOST}/feed")
        events_after_start = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")

        found_start_event = False
        for event in events_after_start:
            event_text = event.text
            if random_user_name in event_text and "started a" in event_text and "container" in event_text:
                found_start_event = True
                assert "Start Here" in event_text, \
                    f"Dojo name 'Start Here' not found in event: {event_text}"
                assert "Using the Dojo" in event_text, \
                    f"Module name 'Using the Dojo' not found in event: {event_text}"
                assert "The Flag File" in event_text, \
                    f"Challenge name 'The Flag File' not found in event: {event_text}"
                assert event_text.count("/") >= 2, \
                    f"Expected at least 2 '/' separators for dojo/module/challenge, found {event_text.count('/')} in: {event_text}"
                break

        assert found_start_event, f"Container start event for {random_user_name} not found"

        solve_challenge(welcome_dojo, "welcome", "flag", session=random_user_session, user=random_user_name)
        wait_for_background_worker(timeout=1)
        # we purposefully don't refresh here, to make sure streaming works
        events_after_solve = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")

        found_solve_event = False
        container_events = 0
        solve_events = 0

        for event in events_after_solve:
            event_text = event.text
            if random_user_name in event_text:
                if "started a" in event_text and "container" in event_text:
                    container_events += 1
                elif "solved" in event_text.lower():
                    solve_events += 1
                    found_solve_event = True
                    assert "Start Here" in event_text, \
                        f"Dojo name 'Start Here' not found in solve event: {event_text}"
                    assert "Using the Dojo" in event_text, \
                        f"Module name 'Using the Dojo' not found in solve event: {event_text}"
                    assert "The Flag File" in event_text, \
                        f"Challenge name 'The Flag File' not found in solve event: {event_text}"
                    assert event_text.count("/") >= 2, \
                        f"Expected at least 2 '/' separators for dojo/module/challenge, found {event_text.count('/')} in solve event: {event_text}"

        assert container_events > 0, f"No container start events found for {random_user_name}"
        assert found_solve_event, f"Challenge solve event for {random_user_name} not found"

        random_user_session.get(f"http://{DOJO_HOST}/dojo/{simple_award_dojo}/join/")
        start_challenge(simple_award_dojo, "hello", "apple", session=random_user_session)
        solve_challenge(simple_award_dojo, "hello", "apple", session=random_user_session, user=random_user_name)
        start_challenge(simple_award_dojo, "hello", "banana", session=random_user_session)
        solve_challenge(simple_award_dojo, "hello", "banana", session=random_user_session, user=random_user_name)
        wait_for_background_worker(timeout=1)
        events_with_emoji = watcher.find_element(By.ID, "events-list").find_elements(By.CLASS_NAME, "event-card")
        
        found_emoji_event = False
        for event in events_with_emoji:
            event_text = event.text
            if random_user_name in event_text and "earned" in event_text.lower() and "🧪" in event_text:
                found_emoji_event = True
                break
        
        assert found_emoji_event, f"Emoji earned event for {random_user_name} not found"

    finally:
        watcher.quit()


def test_private_dojo_events_not_shown(random_private_dojo, random_user_name, random_user_session):
    response = requests.get(f"http://{DOJO_HOST}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    initial_events = response.json()["data"]
    initial_count = len(initial_events)

    start_data = {
        "dojo": random_private_dojo,
        "module": "test-module",
        "challenge": "test-challenge"
    }
    response = random_user_session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/docker", json=start_data)
    assert response.status_code == 200
    wait_for_background_worker(timeout=1)

    response = requests.get(f"http://{DOJO_HOST}/pwncollege_api/v1/feed/events")
    assert response.status_code == 200
    events_after = response.json()["data"]

    found_event = False
    for event in events_after:
        if event.get("user_name") == random_user_name:
            found_event = True
            break

    assert not found_event, "Private dojo events should NOT appear in the feed!"
    assert len(events_after) == initial_count, f"Event count changed! Before: {initial_count}, After: {len(events_after)}"
