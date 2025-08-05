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
def random_user_browser(random_user_name):
    options = FirefoxOptions()
    options.add_argument("--headless")
    browser = Firefox(options=options)

    browser.get(f"{DOJO_URL}/login")
    browser.find_element("id", "name").send_keys(random_user_name)
    browser.find_element("id", "password").send_keys(random_user_name)
    browser.find_element("id", "_submit").click()
    return browser


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
    time.sleep(10)
    workspace_run("DISPLAY=:0 xfce4-terminal &", user=user_id)
    browser.switch_to.frame("workspace")
    e = browser.find_element("id", "noVNC_keyboardinput")
    time.sleep(2)

    yield e

    browser.close()
    browser.switch_to.window(module_window)


@contextlib.contextmanager
def ttyd_terminal(browser):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"{DOJO_URL}/workspace/terminal")

    wait = WebDriverWait(browser, 30)
    workspace_iframe = wait.until(EC.presence_of_element_located((By.ID, "workspace_iframe")))
    browser.switch_to.frame(workspace_iframe)

    # Wait for ttyd to be ready and find the terminal input
    time.sleep(3)
    # ttyd uses body as the input element
    body = browser.find_element("tag name", "body")
    body.click()  # Focus the terminal
    time.sleep(1)

    yield body

    browser.close()
    browser.switch_to.window(module_window)


# Expands the accordion entry of the challenge
def challenge_expand(browser, idx):
    browser.refresh()
    browser.find_element("id", f"challenges-header-button-{idx}").click()
    time.sleep(0.5)


def challenge_start(browser, idx, practice=False, first=True):
    if first:
        challenge_expand(browser, idx)

    body = browser.find_element("id", f"challenges-body-{idx}")
    restore = browser.current_window_handle

    if first:
        body.find_element("id", "challenge-start").click()
        while "started" not in body.find_element("id", "result-message").text:
            time.sleep(0.5)
        time.sleep(1)

    browser.switch_to.frame(body.find_element("id", "workspace-iframe"))

    if practice:
        browser.find_element("id", "start-privileged").click()
        while "disabled" in browser.find_element("id", "start-privileged").get_attribute("class"):
            time.sleep(0.5)
    elif not first:
        browser.find_element("id", "start-unprivileged").click()
        while "disabled" in browser.find_element("id", "start-unprivileged").get_attribute("class"):
            time.sleep(0.5)

    time.sleep(1)

    browser.switch_to.window(restore)


def challenge_submit(browser, idx, flag):
    body = browser.find_element("id", f"challenges-body-{idx}")
    restore = browser.current_window_handle

    browser.switch_to.frame(body.find_element("id", "workspace-iframe"))
    browser.find_element("id", "flag-input").send_keys(flag)

    counter = 0
    while not "orrect" in browser.find_element("id", "flag-input").get_attribute("placeholder") and counter < 20:
        time.sleep(0.5)
        counter = counter + 1
    assert counter != 20
    browser.switch_to.window(restore)

# Gets the accordion entry index
def challenge_idx(browser, name):
    num_challenges = len(browser.find_elements("id", "challenge-start"))
    idx = next(n for n in range(num_challenges) if browser.find_element("id", f"challenges-header-button-{n+1}").text.split("\n")[0] == name)
    return idx+1


def test_welcome_desktop(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "The Flag File")

    challenge_start(random_user_browser, idx)
    with desktop_terminal(random_user_browser, random_user_name) as vs:
        vs.send_keys("/challenge/solve; cat /flag | tee /tmp/out\n")
        time.sleep(5)
        flag = workspace_run("tail -n1 /tmp/out", user=random_user_name).stdout.split()[-1]
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()


def test_welcome_vscode(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "Challenge Programs")

    challenge_start(random_user_browser, idx)
    with vscode_terminal(random_user_browser) as vs:
        vs.send_keys("/challenge/solve | tee /tmp/out\n")
        time.sleep(5)
        flag = workspace_run("tail -n1 /tmp/out", user=random_user_name).stdout.split()[-1]
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()


def test_welcome_ttyd(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "The Flag File")

    challenge_start(random_user_browser, idx)
    with ttyd_terminal(random_user_browser) as terminal:
        terminal.send_keys("/challenge/solve; cat /flag | tee /tmp/out\n")
        time.sleep(5)
        flag = workspace_run("tail -n1 /tmp/out", user=random_user_name).stdout.split()[-1]
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()


def skip_test_welcome_practice(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "Using Practice Mode")

    challenge_start(random_user_browser, idx, practice=True)
    with desktop_terminal(random_user_browser, random_user_name) as vs:
        vs.send_keys("sudo cat /challenge/secret >/home/hacker/secret 2>&1\n")
        time.sleep(1)

    challenge_start(random_user_browser, idx, practice=False, first=False)
    with desktop_terminal(random_user_browser, random_user_name) as vs:
        vs.send_keys("/challenge/solve < secret | tee /tmp/out\n")
        time.sleep(2)
        flag = workspace_run("tail -n1 /tmp/out 2>&1", user=random_user_name).stdout.split()[-1]
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()
