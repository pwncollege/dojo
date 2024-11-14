import contextlib
import time

import pytest
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

from utils import DOJO_URL, workspace_run


@pytest.fixture
def random_user_browser(random_user):
    random_id, random_session = random_user

    options = FirefoxOptions()
    options.add_argument("--headless")
    browser = Firefox(options=options)

    browser.get(f"{DOJO_URL}/login")
    browser.find_element("id", "name").send_keys(random_id)
    browser.find_element("id", "password").send_keys(random_id)
    browser.find_element("id", "_submit").click()
    return random_id, random_session, browser


@contextlib.contextmanager
def vscode_terminal(browser):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"{DOJO_URL}/workspace/code")

    wait = WebDriverWait(browser, 30)
    workspace_iframe = wait.until(EC.presence_of_element_located((By.ID, "workspace_iframe")))
    browser.switch_to.frame(workspace_iframe)

    def wait_for_selector(selector):
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        except Exception as e:
            print(browser.get_full_page_screenshot_as_base64())
            print(browser.switch_to.active_element.get_attribute("outerHTML"))
            raise e

    wait_for_selector("button.getting-started-step")
    browser.switch_to.active_element.send_keys(Keys.CONTROL, Keys.SHIFT, "`")  # Shortcut to open terminal
    wait_for_selector("textarea.xterm-helper-textarea")

    yield browser.switch_to.active_element

    browser.close()
    browser.switch_to.window(module_window)


@contextlib.contextmanager
def desktop_terminal(browser, user_id):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"{DOJO_URL}/workspace/desktop")
    time.sleep(2)
    workspace_run("DISPLAY=:0 xfce4-terminal &", user=user_id)
    browser.switch_to.frame("workspace")
    e = browser.find_element("id", "noVNC_keyboardinput")
    time.sleep(2)

    yield e

    browser.close()
    browser.switch_to.window(module_window)


# Expands the accordion entry of the challenge
def challenge_expand(browser, idx):
    browser.refresh()
    browser.find_element("id", f"challenges-header-button-{idx}").click()
    time.sleep(0.5)


def challenge_start(browser, idx, practice=False):
    challenge_expand(browser, idx)
    body = browser.find_element("id", f"challenges-body-{idx}")
    body.find_element("id", "challenge-practice" if practice else "challenge-start").click()
    while "started" not in body.find_element("id", "result-message").text:
        time.sleep(0.5)
    time.sleep(1)


def challenge_submit(browser, idx, flag):
    challenge_expand(browser, idx)
    body = browser.find_element("id", f"challenges-body-{idx}")
    body.find_element("id", "challenge-input").send_keys(flag)
    body.find_element("id", "challenge-submit").click()
    while "Correct" not in body.find_element("id", "result-message").text:
        time.sleep(0.5)

# Gets the accordion entry index
def challenge_idx(browser, name):
    num_challenges = len(browser.find_elements("id", "challenge-start"))
    idx = next(n for n in range(num_challenges) if browser.find_element("id", f"challenges-header-button-{n+1}").text.split("\n")[0] == name)
    return idx+1


def test_welcome_desktop(random_user_browser, welcome_dojo):
    random_id, _, browser = random_user_browser
    browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(browser, "The Flag File")

    challenge_start(browser, idx)
    with desktop_terminal(browser, random_id) as vs:
        vs.send_keys("/challenge/solve; cat /flag | tee /tmp/out\n")
        time.sleep(5)
        flag = workspace_run("tail -n1 /tmp/out", user=random_id).stdout.split()[-1]
    challenge_submit(browser, idx, flag)
    browser.close()


def test_welcome_vscode(random_user_browser, welcome_dojo):
    random_id, _, browser = random_user_browser
    browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(browser, "Challenge Programs")

    challenge_start(browser, idx)
    with vscode_terminal(browser) as vs:
        vs.send_keys("/challenge/solve | tee /tmp/out\n")
        time.sleep(5)
        flag = workspace_run("tail -n1 /tmp/out", user=random_id).stdout.split()[-1]
    challenge_submit(browser, idx, flag)
    browser.close()


def test_welcome_practice(random_user_browser, welcome_dojo):
    random_id, _, browser = random_user_browser
    browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(browser, "Using Practice Mode")

    challenge_start(browser, idx, practice=True)
    with vscode_terminal(browser) as vs:
        vs.send_keys("sudo chmod 644 /challenge/secret\n")
        vs.send_keys("cp /challenge/secret /home/hacker/\n")
        time.sleep(1)

    challenge_start(browser, idx, practice=False)
    with vscode_terminal(browser) as vs:
        vs.send_keys("/challenge/solve < secret | tee /tmp/out\n")
        time.sleep(5)
        flag = workspace_run("tail -n1 /tmp/out", user=random_id).stdout.split()[-1]
    challenge_submit(browser, idx, flag)
    browser.close()
