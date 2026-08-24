import subprocess
from urllib.parse import quote, urlencode

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from utils import (
    DOJO_URL,
    create_dojo_yml,
    get_user_id,
    start_challenge,
    suppress_award_popup,
    workspace_run,
)


def test_start_challenge_failure_debug(admin_session, guest_dojo_admin, random_user_session):
    dojo_admin_name, dojo_admin_session = guest_dojo_admin
    dojo = create_dojo_yml(f"""
id: docker-failure-{dojo_admin_name}
type: public
image: pwncollege/challenge-simple
modules:
  - id: test
    challenges:
      - id: test
files:
  - type: text
    path: test/test/.init
    content: |
      #!/bin/sh
      printf '%20000s\\n' x
      echo init-stdout
      echo init-stderr >&2
      exit 1
""", session=admin_session)

    assert dojo_admin_session.get(f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 200
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/admins/promote",
        json={"user_id": get_user_id(dojo_admin_name)},
    )
    assert response.status_code == 200

    start_data = {"dojo": dojo, "module": "test", "challenge": "test", "practice": False}
    response = dojo_admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json=start_data)
    assert response.status_code == 200
    result = response.json()
    assert result["success"] is False
    assert result["error"] == "Docker failed"
    assert result["debug"]["trace_id"]
    assert [attempt["attempt"] for attempt in result["debug"]["attempts"]] == [1, 2, 3]
    for attempt in result["debug"]["attempts"]:
        assert attempt["type"] == "WorkspaceInitializationError"
        assert attempt["message"] == "DOJO_INIT_FAILED: Challenge initialization error."
        assert "init-stdout" in attempt["output"]
        assert "init-stderr" in attempt["output"]
        assert len(attempt["output"].encode()) <= 16 * 1024

    response = random_user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json=start_data)
    assert response.status_code == 200
    assert response.json() == {"success": False, "error": "Docker failed"}


def test_start_challenge_error_renders_as_user_as_text(browser_fixture, example_dojo):
    payload = "<img src=x onerror=window.__challengeStartXss=true>"
    expected_error = f"Invalid user ID ({payload})"

    suppress_award_popup(browser_fixture)
    browser_fixture.get(f"{DOJO_URL}/login")
    browser_fixture.find_element(By.ID, "name").send_keys("admin")
    browser_fixture.find_element(By.ID, "password").send_keys("admin")
    browser_fixture.find_element(By.ID, "_submit").click()
    browser_fixture.get(f"{DOJO_URL}/{example_dojo}/hello?as_user={quote(payload)}")
    browser_fixture.execute_script("window.__challengeStartXss = false")
    browser_fixture.find_element(By.ID, "challenges-header-button-2").click()
    challenge_body = browser_fixture.find_element(By.ID, "challenges-body-2")
    start_button = challenge_body.find_element(By.ID, "challenge-start")
    WebDriverWait(browser_fixture, 10).until(lambda _: start_button.is_displayed() and start_button.is_enabled())
    browser_fixture.execute_script("arguments[0].scrollIntoView({block: 'center'})", start_button)
    WebDriverWait(browser_fixture, 10).until(lambda _: browser_fixture.execute_script(
        "var rect = arguments[0].getBoundingClientRect();"
        "var top = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);"
        "return top === arguments[0] || arguments[0].contains(top);", start_button))
    start_button.click()

    result_message = challenge_body.find_element(By.ID, "result-message")
    WebDriverWait(browser_fixture, 10).until(
        lambda _: result_message.find_element(By.TAG_NAME, "code").text == expected_error
    )
    assert result_message.find_element(By.TAG_NAME, "code").text == expected_error
    assert not result_message.find_elements(By.TAG_NAME, "img")
    assert not browser_fixture.execute_script("return window.__challengeStartXss")


def test_active_module_endpoint(random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "banana", session=random_user_session)
    response = random_user_session.get(f"{DOJO_URL}/active-module")
    assert response.status_code == 200

    current = response.json()["c_current"]
    assert current["challenge_reference_id"] == "banana"
    assert current["dojo_reference_id"] == "example"
    assert current["module_id"] == "hello"
    assert response.json()["c_previous"]["challenge_reference_id"] == "apple"
    assert response.json()["c_next"] == {}

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    response = random_user_session.get(f"{DOJO_URL}/active-module")
    assert response.status_code == 200
    assert response.json()["c_current"]["challenge_reference_id"] == "apple"
    assert response.json()["c_next"]["challenge_reference_id"] == "banana"
    assert response.json()["c_previous"] == {}


def test_workspace_auto_start_without_home_mount(
    random_user_name, random_user_session, random_user_browser, example_dojo
):
    query = urlencode({
        "dojo": example_dojo,
        "module": "hello",
        "challenge": "apple",
        "home": "false",
    })
    random_user_browser.get(f"{DOJO_URL}/workspace/terminal?{query}")

    WebDriverWait(random_user_browser, 60).until(
        lambda browser: browser.current_url.rstrip("/").endswith("/workspace/terminal")
    )
    workspace_iframe = random_user_browser.find_element(By.ID, "workspace-iframe")
    terminal_button = random_user_browser.find_element(
        By.CSS_SELECTOR, '.workspace-service[data-service="terminal: 7681"]'
    )
    WebDriverWait(random_user_browser, 30).until(
        lambda browser: "active" in terminal_button.get_attribute("class")
    )
    WebDriverWait(random_user_browser, 30).until(
        lambda browser: "/7681/" in (workspace_iframe.get_attribute("src") or "")
    )

    workspace_run("test -d /home/hacker", user=random_user_name)
    with pytest.raises(subprocess.CalledProcessError):
        workspace_run("findmnt --mountpoint /home/hacker", user=random_user_name)

    workspace_run("touch /home/hacker/ephemeral", user=random_user_name)
    start_challenge(example_dojo, "hello", "apple", session=random_user_session, home=False)
    workspace_run("test ! -e /home/hacker/ephemeral", user=random_user_name)
