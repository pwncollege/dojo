import contextlib
import selenium.webdriver
import pytest
import time
import os

#pylint:disable=unused-argument,redefined-outer-name

from utils import PROTO, HOST, workspace_run
from selenium.webdriver.common.keys import Keys

def webdriver():
    # workaround for ubuntu
    gd = "/snap/bin/geckodriver"
    if os.path.exists(gd):
        ds = selenium.webdriver.FirefoxService(executable_path=gd)
        wd = selenium.webdriver.Firefox(service=ds)
    else:
        wd = selenium.webdriver.Firefox()
    return wd

@pytest.fixture
def random_user_webdriver(random_user):
    random_id,random_session = random_user
    wd = webdriver()
    wd.get(f"{PROTO}://{HOST}/login")
    wd.find_element("id", "name").send_keys(random_id)
    wd.find_element("id", "password").send_keys(random_id)
    wd.find_element("id", "_submit").click()
    return random_id,random_session,wd

@contextlib.contextmanager
def vscode_terminal(wd):
    module_window = wd.current_window_handle

    wd.switch_to.new_window("tab")
    wd.get(f"{PROTO}://{HOST}/workspace/code")
    time.sleep(3)
    wd.switch_to.active_element.send_keys(Keys.CONTROL + Keys.SHIFT + "`")
    time.sleep(2)

    yield wd.switch_to.active_element

    wd.close()
    wd.switch_to.window(module_window)

@contextlib.contextmanager
def desktop_terminal(wd, user_id):
    module_window = wd.current_window_handle

    wd.switch_to.new_window("tab")
    wd.get(f"{PROTO}://{HOST}/workspace/desktop")
    time.sleep(2)
    workspace_run("DISPLAY=:0 xfce4-terminal &", user=user_id)
    wd.switch_to.frame("workspace")
    e = wd.find_element("id", "noVNC_keyboardinput")
    time.sleep(2)

    yield e

    wd.close()
    wd.switch_to.window(module_window)


# Expands the accordion entry of the challenge
def challenge_expand(wd, idx):
    wd.refresh()
    wd.find_element("id", f"challenges-header-button-{idx}").click()
    time.sleep(0.5)

def challenge_start(wd, idx, practice=False):
    challenge_expand(wd, idx)
    body = wd.find_element("id", f"challenges-body-{idx}")
    body.find_element("id", "challenge-practice" if practice else "challenge-start").click()
    while "started" not in body.find_element("id", "result-message").text:
        time.sleep(0.5)
    time.sleep(1)

def challenge_submit(wd, idx, flag):
    challenge_expand(wd, idx)
    body = wd.find_element("id", f"challenges-body-{idx}")
    body.find_element("id", "challenge-input").send_keys(flag)
    body.find_element("id", "challenge-submit").click()
    while "Correct" not in body.find_element("id", "result-message").text:
        time.sleep(0.5)

# Gets the accordion entry index
def challenge_idx(wd, name):
    num_challenges = len(wd.find_elements("id", "challenge-start"))
    idx = next(n for n in range(num_challenges) if wd.find_element("id", f"challenges-header-button-{n+1}").text.split("\n")[0] == name)
    return idx+1

def test_welcome_desktop(random_user_webdriver, welcome_dojo):
    random_id, _, wd = random_user_webdriver
    wd.get(f"{PROTO}://{HOST}/welcome/welcome")
    idx = challenge_idx(wd, "The Flag File")

    challenge_start(wd, idx)
    with desktop_terminal(wd, random_id) as vs:
        vs.send_keys("/challenge/solve; cat /flag | tee /tmp/out\n")
        time.sleep(5)

    flag = workspace_run("tail -n1 /tmp/out", user=random_id).stdout.split()[-1]
    challenge_submit(wd, idx, flag)
    wd.close()

def test_welcome_vscode(random_user_webdriver, welcome_dojo):
    random_id, _, wd = random_user_webdriver
    wd.get(f"{PROTO}://{HOST}/welcome/welcome")
    idx = challenge_idx(wd, "Challenge Programs")

    challenge_start(wd, idx)
    with vscode_terminal(wd) as vs:
        vs.send_keys("/challenge/solve | tee /tmp/out\n")
        time.sleep(5)

    flag = workspace_run("tail -n1 /tmp/out", user=random_id).stdout.split()[-1]
    challenge_submit(wd, idx, flag)
    wd.close()

def test_welcome_practice(random_user_webdriver, welcome_dojo):
    random_id, _, wd = random_user_webdriver
    wd.get(f"{PROTO}://{HOST}/welcome/welcome")
    idx = challenge_idx(wd, "Using Practice Mode")

    challenge_start(wd, idx, practice=True)
    with vscode_terminal(wd) as vs:
        vs.send_keys("sudo chmod 644 /challenge/secret\n")
        vs.send_keys("cp /challenge/secret /home/hacker/\n")
        time.sleep(1)

    challenge_start(wd, idx, practice=False)
    with vscode_terminal(wd) as vs:
        vs.send_keys("/challenge/solve < secret | tee /tmp/out\n")
        time.sleep(5)

    flag = workspace_run("tail -n1 /tmp/out", user=random_id).stdout.split()[-1]
    challenge_submit(wd, idx, flag)
    wd.close()
