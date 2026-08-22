import subprocess
import pytest
import json
import re
from urllib.parse import quote, urlencode

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from utils import DOJO_URL, create_dojo_yml, dojo_run, workspace_run, start_challenge, solve_challenge, db_sql, get_user_id, suppress_award_popup

def check_mount(path, *, user, fstype=None, check_nosuid=True):
    try:
        result = workspace_run(f"findmnt -J {path}", user=user)
    except subprocess.CalledProcessError as e:
        assert False, f"'{path}' not mounted: {(e.stdout, e.stderr)}"
    assert result, f"'{path}' not mounted: {(e.stdout, e.stderr)}"

    mount_info = json.loads(result.stdout)
    assert len(mount_info.get("filesystems", [])) == 1, f"Expected exactly one filesystem, but got: {mount_info}"

    filesystem = mount_info["filesystems"][0]
    assert filesystem["target"] == path, f"Expected '{path}' to be mounted at '{path}', but got: {filesystem}"
    if fstype:
        assert filesystem["fstype"] == fstype, f"Expected '{path}' to be mounted as '{fstype}', but got: {filesystem}"
    if check_nosuid:
        assert "nosuid" in filesystem["options"], f"Expected '{path}' to be mounted nosuid, but got: {filesystem}"



def test_start_challenge(admin_session, example_dojo):
    start_challenge(example_dojo, "hello", "apple", session=admin_session)


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
    result = response.json()
    assert result == {"success": False, "error": "Docker failed"}


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
    # The accordion is still animating, so scroll the button to the middle of the
    # viewport and wait for nothing to be sitting on top of it before clicking.
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
    assert len(result_message.find_elements(By.TAG_NAME, "br")) == 2
    assert not result_message.find_elements(By.TAG_NAME, "img")
    assert not browser_fixture.execute_script("return window.__challengeStartXss")


def test_active_module_endpoint(random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "banana", session=random_user_session)
    response = random_user_session.get(f"{DOJO_URL}/active-module")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"

    current = response.json()["c_current"]
    assert current["challenge_name"] == "Banana"
    assert current["challenge_reference_id"] == "banana"
    assert current["dojo_reference_id"] == "example"
    assert current["module_id"] == "hello"
    assert current["module_name"] == "Hello"
    assert current["description"] == "<p>This is banana.</p>"

    previous = response.json()["c_previous"]
    assert previous["challenge_name"] == "Apple"
    assert previous["challenge_reference_id"] == "apple"
    assert previous["dojo_reference_id"] == "example"
    assert previous["module_id"] == "hello"
    assert previous["module_name"] == "Hello"
    assert previous["description"] is None

    next_chal = response.json()["c_next"]
    assert next_chal == {}

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    response = random_user_session.get(f"{DOJO_URL}/active-module")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"

    current = response.json()["c_current"]
    assert current["challenge_name"] == "Apple"
    assert current["challenge_reference_id"] == "apple"

    next_chal = response.json()["c_next"]
    assert next_chal["challenge_name"] == "Banana"
    assert next_chal["challenge_reference_id"] == "banana"
    assert next_chal["description"] is None

    previous = response.json()["c_previous"]
    assert previous == {}


def test_progression_locked(progression_locked_dojo, random_user_name, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/dojo/{progression_locked_dojo}/join/").status_code == 200
    start_challenge(progression_locked_dojo, "progression-locked-module", "unlocked-challenge", session=random_user_session)

    with pytest.raises(AssertionError, match="Failed to start challenge: This challenge is locked"):
        start_challenge(progression_locked_dojo, "progression-locked-module", "locked-challenge", session=random_user_session)

    solve_challenge(progression_locked_dojo, "progression-locked-module", "unlocked-challenge", session=random_user_session, user=random_user_name)
    start_challenge(progression_locked_dojo, "progression-locked-module", "locked-challenge", session=random_user_session)


@pytest.mark.parametrize("path", ["/flag", "/challenge/apple"])
def test_workspace_path_exists(path):
    try:
        workspace_run(f"[ -f '{path}' ]", user="admin")
    except subprocess.CalledProcessError:
        assert False, f"Path does not exist: {path}"


def test_workspace_flag_permission():
    try:
        workspace_run("cat /flag", user="admin")
    except subprocess.CalledProcessError as e:
        assert "Permission denied" in e.stderr, f"Expected permission denied, but got: {(e.stdout, e.stderr)}"
    else:
        assert False, f"Expected permission denied, but got no error: {(e.stdout, e.stderr)}"


def test_workspace_challenge():
    result = workspace_run("/challenge/apple", user="admin")
    match = re.search("pwn.college{(\\S+)}", result.stdout)
    assert match, f"Expected flag, but got: {result.stdout}"


def test_workspace_home_mount():
    check_mount("/home/hacker", user="admin")


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

    assert random_user_browser.find_element(By.ID, "workspace-launch-status").text.startswith("Starting challenge")
    WebDriverWait(random_user_browser, 60).until(
        lambda browser: browser.current_url.rstrip("/").endswith("/workspace/terminal")
    )
    workspace_iframe = random_user_browser.find_element(By.ID, "workspace-iframe")
    workspace_controls = random_user_browser.find_element(By.CSS_SELECTOR, ".workspace-controls")
    terminal_button = workspace_controls.find_element(
        By.CSS_SELECTOR, '.workspace-service[data-service="terminal: 7681"]'
    )
    assert workspace_controls.get_attribute("data-popout") == "false"
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


def test_workspace_no_sudo():
    try:
        s = workspace_run("sudo whoami", user="admin")
    except subprocess.CalledProcessError:
        pass
    else:
        assert False, f"Expected sudo to fail, but got no error: {(s.stdout, s.stderr)}"


def test_workspace_practice_challenge(random_user_name, random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "apple", practice=True, session=random_user_session)
    try:
        result = workspace_run("sudo whoami", user=random_user_name)
        assert result.stdout.strip() == "root", f"Expected 'root', but got: ({result.stdout}, {result.stderr})"
    except subprocess.CalledProcessError as e:
        assert False, f"Expected sudo to succeed, but got: {(e.stdout, e.stderr)}"


def test_workspace_home_persistent(random_user_name, random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    workspace_run("touch /home/hacker/test", user=random_user_name)
    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    try:
        workspace_run("[ -f '/home/hacker/test' ]", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected file to exist, but got: {(e.stdout, e.stderr)}"


@pytest.mark.skip(reason="Disabling test temporarily until overlay issue is resolved")
def test_workspace_as_user(admin_user, random_user_name, random_user_session, example_dojo):
    admin_user, admin_session = admin_user
    random_user_id = get_user_id(random_user_name)

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    workspace_run("touch /home/hacker/test", user=random_user_name)

    start_challenge(example_dojo, "hello", "apple", session=admin_session, as_user=random_user_id)
    check_mount("/home/hacker", user=admin_user)
    check_mount("/home/me", user=admin_user)

    try:
        workspace_run("[ -f '/home/hacker/test' ]", user=admin_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected existing file to exist, but got: {(e.stdout, e.stderr)}"

    workspace_run("touch /home/hacker/test2", user=random_user_name)
    try:
        workspace_run("[ -f '/home/hacker/test2' ]", user=admin_user)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected new file to exist, but got: {(e.stdout, e.stderr)}"

    workspace_run("touch /home/hacker/test3", user=admin_user)
    try:
        workspace_run("[ ! -e '/home/hacker/test3' ]", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected overlay file to not exist, but got: {(e.stdout, e.stderr)}"


def test_reset_home_directory(random_user_name, random_user_session, example_dojo):
    # Create a file in the home directory
    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    workspace_run("touch /home/hacker/testfile", user=random_user_name)

    # Reset the home directory
    response = random_user_session.post(f"{DOJO_URL}/pwncollege_api/v1/workspace/reset_home", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], f"Failed to reset home directory: {response.json()['error']}"

    try:
        workspace_run("[ -f '/home/hacker/home-backup.tar.gz' ]", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected zip file to exist, but got: {(e.stdout, e.stderr)}"

    try:
        workspace_run("[ ! -f '/home/hacker/testfile' ]", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected test file to be wiped, but got: {(e.stdout, e.stderr)}"


def test_unprivileged_challenge(random_user_name, random_user_session, example_dojo):
    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    try:
        result = workspace_run("unshare true", user=random_user_name)
        assert False, f"Expected unshare to fail, but it succeeded: {(result.stdout, result.stderr)}"
    except subprocess.CalledProcessError as e:
        assert "unshare: unshare failed: Operation not permitted" in e.stderr, f"Expected unshare to fail, but got: {(e.stdout, e.stderr)}"


def test_privileged_challenge(random_user_name, random_user_session, privileged_dojo):
    start_challenge(privileged_dojo, "test", "test", session=random_user_session)
    try:
        workspace_run("unshare true", user=random_user_name)
    except subprocess.CalledProcessError as e:
        assert False, f"Expected unshare to succeed, but got: {(e.stdout, e.stderr)}"
