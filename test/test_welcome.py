import contextlib
import time
import string
import random

import pytest
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from utils import DOJO_HOST, workspace_run

@contextlib.contextmanager
def vscode_terminal(browser):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"http://{DOJO_HOST}/workspace/code")

    wait = WebDriverWait(browser, 30)
    workspace_iframe = wait.until(EC.presence_of_element_located((By.ID, "workspace_iframe")))
    browser.switch_to.frame(workspace_iframe)

    def wait_for_selector(*selectors):
        def locate(driver):
            for selector in selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    return elements[0]
            return False
        try:
            return wait.until(locate)
        except Exception as e:
            try:
                print(browser.get_full_page_screenshot_as_base64())
            except Exception:
                pass
            try:
                print(browser.switch_to.active_element.get_attribute("outerHTML"))
            except Exception:
                pass
            raise e

    surface = wait_for_selector(".monaco-workbench", "div.getting-started-step", "button.getting-started-step")
    surface.click()
    ActionChains(browser).key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys("`").key_up(Keys.SHIFT).key_up(Keys.CONTROL).perform()
    wait_for_selector("textarea.xterm-helper-textarea")

    yield browser.switch_to.active_element

    browser.close()
    browser.switch_to.window(module_window)

@contextlib.contextmanager
def desktop_terminal(browser, user_id):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"http://{DOJO_HOST}/workspace/desktop")
    time.sleep(10)
    workspace_run("DISPLAY=:0 xfce4-terminal &", user=user_id)
    wait = WebDriverWait(browser, 30)
    browser.switch_to.frame("workspace")
    def locate_input(driver):
        try:
            return driver.find_element(By.ID, "noVNC_keyboardinput")
        except NoSuchElementException:
            return driver.find_element(By.ID, "keyboardinput")
    e = wait.until(locate_input)
    time.sleep(2)

    yield e

    browser.close()
    browser.switch_to.window(module_window)


@contextlib.contextmanager
def ttyd_terminal(browser):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"http://{DOJO_HOST}/workspace/terminal")

    wait = WebDriverWait(browser, 30)
    workspace_iframe = wait.until(EC.presence_of_element_located((By.ID, "workspace_iframe")))
    browser.switch_to.frame(workspace_iframe)

    # Wait for ttyd to be ready and find the terminal input
    time.sleep(10)
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


def challenge_start(browser, idx, practice=False):
    challenge_expand(browser, idx)
    body = browser.find_element("id", f"challenges-body-{idx}")

    body.find_element("id", "challenge-priv" if practice else "challenge-start").click()
    while "started" not in body.find_element("id", "result-message").text:
        time.sleep(0.5)
    time.sleep(1)


def challenge_submit(browser, idx, flag):
    body = browser.find_element("id", f"challenges-body-{idx}")
    body.find_element("id", "flag-input").send_keys(flag)

    counter = 0
    matches = ["Solved", "completed"]
    while not any(x in body.find_element("id", "workspace-notification-banner").get_attribute("innerHTML") for x in matches) and counter < 20:
        time.sleep(0.5)
        counter = counter + 1
    assert counter != 20

# Gets the accordion entry index
def challenge_idx(browser, name):
    num_challenges = len(browser.find_elements("id", "challenge-start"))
    idx = next(n for n in range(num_challenges) if browser.find_element("id", f"challenges-header-button-{n+1}").text.split("\n")[0] == name)
    return idx+1


def read_flag(user_id):
    for _ in range(10):
        result = workspace_run("test -f /tmp/out && tail -n1 /tmp/out || true", user=user_id)
        parts = result.stdout.split()
        if parts:
            return parts[-1]
        time.sleep(1)
    raise AssertionError("flag not found")


def test_welcome_desktop(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"http://{DOJO_HOST}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "The Flag File")

    challenge_start(random_user_browser, idx)
    with desktop_terminal(random_user_browser, random_user_name) as vs:
        vs.send_keys("/challenge/solve; cat /flag | tee /tmp/out\n")
        time.sleep(5)
        flag = read_flag(random_user_name)
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()


def test_welcome_vscode(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"http://{DOJO_HOST}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "Challenge Programs")

    challenge_start(random_user_browser, idx)
    with vscode_terminal(random_user_browser) as vs:
        vs.send_keys("/challenge/solve | tee /tmp/out\n")
        time.sleep(5)
        flag = read_flag(random_user_name)
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()


def test_welcome_ttyd(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"http://{DOJO_HOST}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "The Flag File")

    challenge_start(random_user_browser, idx)
    with ttyd_terminal(random_user_browser) as terminal:
        terminal.send_keys("/challenge/solve; cat /flag | tee /tmp/out\n")
        time.sleep(5)
        flag = read_flag(random_user_name)
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()


def skip_test_welcome_practice(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"http://{DOJO_HOST}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "Using Practice Mode")

    challenge_start(random_user_browser, idx, practice=True)
    with desktop_terminal(random_user_browser, random_user_name) as vs:
        vs.send_keys("sudo cp /challenge/secret /home/hacker/secret\n")
        time.sleep(1)

    random_user_browser.find_element("id", "workspace-change-privilege").click()
    time.sleep(10)
    with desktop_terminal(random_user_browser, random_user_name) as vs:
        vs.send_keys("/challenge/solve < secret | tee /tmp/out\n")
        time.sleep(2)
        flag = read_flag(random_user_name)
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()

def get_interfaces(browser, idx):
    challenge_expand(browser, idx)
    body = browser.find_element("id", f"challenges-body-{idx}")
    options = Select(body.find_element("id", "workspace-select"))
    return options.options

def match_interfaces(interfaces, expected):
    assert len(interfaces) == len(expected)
    for interface, value in zip(interfaces, expected) :
        assert interface.get_attribute("value") == value

def test_interface_inherit(random_user_browser, random_user_name, interfaces_dojo):
    random_user_browser.get(f"http://{DOJO_HOST}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test1")
    interfaces = get_interfaces(random_user_browser, idx)

    values = ["ssh: ", "terminal: 7681"]
    match_interfaces(interfaces, values)

def test_interface_chal_override(random_user_browser, random_user_name, interfaces_dojo):
    random_user_browser.get(f"http://{DOJO_HOST}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test2")
    interfaces = get_interfaces(random_user_browser, idx)

    values = ["code: 8080", "desktop: 6080"]
    match_interfaces(interfaces, values)

def test_interface_chal_narrow(random_user_browser, random_user_name, interfaces_dojo):
    random_user_browser.get(f"http://{DOJO_HOST}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test3")
    interfaces = get_interfaces(random_user_browser, idx)

    values = ["terminal: 7681"]
    match_interfaces(interfaces, values)


def test_registration_commitment(browser_fixture):
    browser_fixture.get(f"http://{DOJO_HOST}/register")
    wait = WebDriverWait(browser_fixture, 10)

    test_username = "test" + "".join(random.choices(string.ascii_lowercase, k=8))

    browser_fixture.find_element(By.ID, "name").send_keys(test_username)
    browser_fixture.find_element(By.ID, "email").send_keys(f"{test_username}@example.com")
    browser_fixture.find_element(By.ID, "password").send_keys("TestPassword123!")

    submit_button = browser_fixture.find_element(By.ID, "register-submit")
    submit_button.click()

    alert = browser_fixture.switch_to.alert
    assert "Please type the commitment" in alert.text
    alert.accept()

    commitment_input = browser_fixture.find_element(By.ID, "commitment-input")
    commitment_input.send_keys("i have read the ground rules and commit to not publish pwn.college writeups on the internet")

    time.sleep(0.5)

    submit_button.click()

    wait.until(lambda driver: "register" not in driver.current_url.lower())
    assert "register" not in browser_fixture.current_url.lower()

    browser_fixture.close()


def test_welcome_graded_lecture(random_user_browser, random_user_name, example_dojo):
    random_user_browser.get(f"http://{DOJO_HOST}/{example_dojo}/lectures")
    idx = challenge_idx(random_user_browser, "Graded Lecture")

    challenge_expand(random_user_browser, idx)
    body = random_user_browser.find_element("id", f"challenges-body-{idx}")

    body.find_element("id", "challenge-start").click()
    while "started" not in body.find_element("id", "result-message").text:
        time.sleep(0.5)
    time.sleep(1)

    wait = WebDriverWait(random_user_browser, 30)
    lecture_iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, f"#challenges-body-{idx} #workspace-iframe")))
    assert lecture_iframe.is_displayed()
    lecture_iframe_src = lecture_iframe.get_attribute("src")
    assert lecture_iframe_src.rstrip("/").endswith("/80")

    random_user_browser.switch_to.frame(lecture_iframe)
    youtube_iframe_inline = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
    assert youtube_iframe_inline.is_displayed()
    inline_iframe_src = youtube_iframe_inline.get_attribute("src")
    assert "youtube.com" in inline_iframe_src or "youtube-nocookie.com" in inline_iframe_src
    assert "hh4XAU6XYP0" in inline_iframe_src
    random_user_browser.switch_to.default_content()

    challenge_window = random_user_browser.current_window_handle
    random_user_browser.switch_to.new_window("tab")
    random_user_browser.get(f"http://{DOJO_HOST}/workspace/80/")

    time.sleep(2)

    youtube_iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
    assert youtube_iframe.is_displayed()
    iframe_src = youtube_iframe.get_attribute("src")
    if "workspace.localhost" in iframe_src:
        assert iframe_src.rstrip("/").endswith("/80")
        random_user_browser.switch_to.frame(youtube_iframe)
        nested_iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        assert nested_iframe.is_displayed()
        nested_src = nested_iframe.get_attribute("src")
        assert "youtube.com" in nested_src or "youtube-nocookie.com" in nested_src
        assert "hh4XAU6XYP0" in nested_src
        random_user_browser.switch_to.default_content()
    else:
        assert "youtube.com" in iframe_src or "youtube-nocookie.com" in iframe_src
        assert "hh4XAU6XYP0" in iframe_src

    random_user_browser.close()
    random_user_browser.switch_to.window(challenge_window)
    random_user_browser.close()
