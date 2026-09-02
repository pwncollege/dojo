import contextlib
import re
import time
import string
import random

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from utils import DOJO_URL, workspace_run

@contextlib.contextmanager
def vscode_terminal(browser):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"{DOJO_URL}/workspace/code")

    wait = WebDriverWait(browser, 30)
    workspace_iframe = wait.until(
        lambda driver: next(
            (
                iframe
                for iframe in driver.find_elements(By.ID, "workspace-iframe")
                if "/8080/" in (iframe.get_attribute("src") or "")
            ),
            False,
        )
    )
    browser.switch_to.frame(workspace_iframe)

    def wait_for_selector(*selectors):
        def locate(driver):
            for selector in selectors:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    return elements[-1]
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
    def send_terminal_shortcut():
        browser.execute_script("if (document.activeElement) document.activeElement.blur();")
        ActionChains(browser).key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys("`").key_up(Keys.SHIFT).key_up(Keys.CONTROL).perform()

    send_terminal_shortcut()
    terminal = None
    for _ in range(5):
        try:
            terminal = WebDriverWait(browser, 10).until(
                lambda driver: (driver.find_elements(By.CSS_SELECTOR, "textarea.xterm-helper-textarea") or [None])[-1])
            break
        except TimeoutException:
            # The Getting Started webview steals focus into a cross-origin iframe, swallowing keybindings;
            # only resend the shortcut if focus is still trapped there, lest we spawn a second terminal.
            if not browser.execute_script("return document.activeElement !== null && document.activeElement.tagName === 'IFRAME';"):
                break
            send_terminal_shortcut()
    if terminal is None:
        terminal = wait_for_selector("textarea.xterm-helper-textarea")
    time.sleep(2)
    browser.execute_script("arguments[0].focus();", terminal)

    yield terminal

    browser.close()
    browser.switch_to.window(module_window)

@contextlib.contextmanager
def desktop_workspace(browser):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"{DOJO_URL}/workspace/desktop")
    wait = WebDriverWait(browser, 30)
    wait.until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "workspace")))
    wait.until(
        lambda driver: driver.execute_script(
            "return typeof client !== 'undefined' && client.connected;"
        )
    )
    desktop = wait.until(
        lambda driver: max(
            [
                canvas
                for canvas in driver.find_elements(By.CSS_SELECTOR, "canvas")
                if canvas.is_displayed()
                and canvas.size["width"] >= 640
                and canvas.size["height"] >= 480
            ],
            key=lambda canvas: canvas.size["width"] * canvas.size["height"],
            default=False,
        )
    )

    yield desktop

    browser.close()
    browser.switch_to.window(module_window)


@contextlib.contextmanager
def ttyd_terminal(browser):
    module_window = browser.current_window_handle

    browser.switch_to.new_window("tab")
    browser.get(f"{DOJO_URL}/workspace/terminal")

    wait = WebDriverWait(browser, 30)
    workspace_iframe = wait.until(
        lambda driver: next(
            (
                iframe
                for iframe in driver.find_elements(By.ID, "workspace-iframe")
                if "/7681/" in (iframe.get_attribute("src") or "")
            ),
            False,
        )
    )
    browser.switch_to.frame(workspace_iframe)

    terminal = wait.until(
        lambda driver: (driver.find_elements(By.CSS_SELECTOR, "textarea.xterm-helper-textarea") or [None])[-1]
    )
    terminal.click()

    yield terminal

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
        match = re.search(r"pwn\.college\{[^}\n]+\}", result.stdout)
        if match:
            return match.group(0)
        time.sleep(1)
    raise AssertionError("flag not found")


def test_welcome_desktop(random_user_browser, welcome_dojo):
    random_user_browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "The Flag File")

    challenge_start(random_user_browser, idx)
    with desktop_workspace(random_user_browser):
        pass
    random_user_browser.close()


def test_welcome_vscode(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "Challenge Programs")

    challenge_start(random_user_browser, idx)
    with vscode_terminal(random_user_browser) as vs:
        vs.send_keys("/challenge/solve | tee /tmp/out\n")
        flag = read_flag(random_user_name)
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()


def test_welcome_ttyd(random_user_browser, random_user_name, welcome_dojo):
    random_user_browser.get(f"{DOJO_URL}/welcome/welcome")
    idx = challenge_idx(random_user_browser, "The Flag File")

    challenge_start(random_user_browser, idx)
    with ttyd_terminal(random_user_browser) as terminal:
        terminal.send_keys("/challenge/solve; cat /flag | tee /tmp/out\n")
        flag = read_flag(random_user_name)
    challenge_submit(random_user_browser, idx, flag)
    random_user_browser.close()


def get_interface_names(root):
    return [element.text for element in root.find_elements(By.CSS_SELECTOR, ".workspace-service-name")]


def service_button(root, name):
    return next(
        button for button in root.find_elements(By.CSS_SELECTOR, ".workspace-service")
        if button.find_element(By.CSS_SELECTOR, ".workspace-service-name").text == name
    )


def test_configured_interfaces_drive_workspace(random_user_browser, interfaces_dojo):
    random_user_browser.get(f"{DOJO_URL}/testing-interfaces/test")
    scenarios = [
        ("test1", ["SSH", "Terminal"], "/7681/"),
        ("test2", ["Code", "Desktop"], "/8080/"),
        ("test3", ["Terminal"], "/7681/"),
    ]
    for challenge_name, interface_names, workspace_path in scenarios:
        idx = challenge_idx(random_user_browser, challenge_name)
        challenge_start(random_user_browser, idx)
        body = random_user_browser.find_element("id", f"challenges-body-{idx}")
        WebDriverWait(random_user_browser, 30).until(
            lambda driver: get_interface_names(body) == interface_names
        )
        WebDriverWait(random_user_browser, 30).until(
            lambda driver: workspace_path in (
                body.find_element(By.ID, "workspace-iframe").get_attribute("src") or ""
            )
        )
    random_user_browser.close()

def test_actionbar_service_buttons(random_user_browser, interfaces_dojo):
    random_user_browser.get(f"{DOJO_URL}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test1")
    challenge_start(random_user_browser, idx)
    body = random_user_browser.find_element("id", f"challenges-body-{idx}")
    module_handle = random_user_browser.current_window_handle
    handles = set(random_user_browser.window_handles)
    wait = WebDriverWait(random_user_browser, 30)

    service_button(body, "Terminal").click()
    wait.until(lambda driver: len(driver.window_handles) == len(handles) + 1)
    popout_handle = (set(random_user_browser.window_handles) - handles).pop()
    random_user_browser.switch_to.window(popout_handle)
    wait.until(lambda driver: driver.current_url.rstrip("/").endswith("/workspace/terminal"))
    popout_controls = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".workspace-controls")))

    description_button = popout_controls.find_element(
        By.CSS_SELECTOR, ".workspace-description-control"
    )
    description_button.click()
    description = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".workspace-description")))
    assert "Interface test challenge description." in description.text

    service_button(popout_controls, "SSH").click()
    wait.until(lambda driver: driver.current_url.rstrip("/").endswith("/workspace/ssh"))
    wait.until(lambda driver: driver.find_element(By.CSS_SELECTOR, ".workspace-ssh").is_displayed())

    service_button(popout_controls, "Terminal").click()
    wait.until(lambda driver: driver.current_url.rstrip("/").endswith("/workspace/terminal"))

    random_user_browser.switch_to.window(module_handle)
    service_button(random_user_browser.find_element("id", f"challenges-body-{idx}"), "Terminal").click()
    time.sleep(2)
    assert len(random_user_browser.window_handles) == len(handles) + 1
    random_user_browser.switch_to.window(popout_handle)
    assert random_user_browser.current_url.rstrip("/").endswith("/workspace/terminal")
    random_user_browser.close()
    random_user_browser.switch_to.window(module_handle)
    random_user_browser.close()

def test_actionbar_ssh_only_challenge(random_user_browser, interfaces_dojo):
    random_user_browser.get(f"{DOJO_URL}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test5")
    challenge_start(random_user_browser, idx)
    body = random_user_browser.find_element("id", f"challenges-body-{idx}")
    buttons = body.find_elements(By.CSS_SELECTOR, ".workspace-service-name")
    assert [button.text for button in buttons] == ["SSH"]

    wait = WebDriverWait(random_user_browser, 30)
    ssh_box = body.find_element(By.CSS_SELECTOR, ".workspace-ssh")
    wait.until(lambda driver: ssh_box.is_displayed())

    handles = len(random_user_browser.window_handles)
    service_button(body, "SSH").click()
    time.sleep(1)
    assert len(random_user_browser.window_handles) == handles
    assert ssh_box.is_displayed()
    random_user_browser.close()

def test_actionbar_ssh_toggle(random_user_browser, interfaces_dojo):
    random_user_browser.get(f"{DOJO_URL}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test1")
    challenge_start(random_user_browser, idx)
    body = random_user_browser.find_element("id", f"challenges-body-{idx}")
    wait = WebDriverWait(random_user_browser, 30)
    iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, f"#challenges-body-{idx} #workspace-iframe")))
    wait.until(lambda driver: "/7681/" in (iframe.get_attribute("src") or ""))

    ssh_box = body.find_element(By.CSS_SELECTOR, ".workspace-ssh")
    assert not ssh_box.is_displayed()

    service_button(body, "SSH").click()
    wait.until(lambda driver: ssh_box.is_displayed())

    restart_button = body.find_element(By.CSS_SELECTOR, "#challenge-restart")
    restart_button.click()
    wait.until(lambda driver: restart_button.get_attribute("disabled") is None)
    time.sleep(1)
    assert ssh_box.is_displayed()

    service_button(body, "SSH").click()
    wait.until(lambda driver: not ssh_box.is_displayed())
    wait.until(lambda driver: "/7681/" in (iframe.get_attribute("src") or ""))
    random_user_browser.close()

def test_actionbar_sudo_checkbox(random_user_browser, random_user_name, interfaces_dojo):
    random_user_browser.get(f"{DOJO_URL}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test1")
    challenge_start(random_user_browser, idx)
    body = random_user_browser.find_element("id", f"challenges-body-{idx}")
    wait = WebDriverWait(random_user_browser, 30)

    control = body.find_element(By.CSS_SELECTOR, "#workspace-change-privilege")
    checkbox = control.find_element(By.CSS_SELECTOR, "input")
    assert not checkbox.is_selected()

    checkbox.click()
    wait.until(EC.alert_is_present())
    random_user_browser.switch_to.alert.accept()
    wait.until(lambda driver: checkbox.is_enabled())
    assert checkbox.is_selected()

    def workspace_output(cmd):
        last_exception = None
        for _ in range(30):
            try:
                output = workspace_run(cmd, user=random_user_name).stdout
            except Exception as e:
                last_exception = e
                output = None
            if output:
                return output
            time.sleep(1)
        raise AssertionError(f"no output from workspace: {cmd} (last exception: {last_exception!r})") from last_exception

    assert workspace_output("sudo id -u || echo nosudo").strip() == "0"

    checkbox.click()
    wait.until(EC.alert_is_present())
    random_user_browser.switch_to.alert.accept()
    wait.until(lambda driver: checkbox.is_enabled())
    assert not checkbox.is_selected()

    assert "nosudo" in workspace_output("sudo id -u || echo nosudo")
    random_user_browser.close()

def test_actionbar_popout_reload(random_user_browser, interfaces_dojo):
    random_user_browser.get(f"{DOJO_URL}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test1")
    challenge_start(random_user_browser, idx)
    body = random_user_browser.find_element("id", f"challenges-body-{idx}")
    module_handle = random_user_browser.current_window_handle
    handles = set(random_user_browser.window_handles)
    wait = WebDriverWait(random_user_browser, 30)

    service_button(body, "Terminal").click()
    wait.until(lambda driver: len(driver.window_handles) == len(handles) + 1)
    popout_handle = (set(random_user_browser.window_handles) - handles).pop()
    random_user_browser.switch_to.window(popout_handle)
    wait.until(lambda driver: driver.current_url.rstrip("/").endswith("/workspace/terminal"))
    popout_page = random_user_browser.find_element(By.TAG_NAME, "body")

    random_user_browser.switch_to.window(module_handle)
    restart_button = body.find_element(By.CSS_SELECTOR, "#challenge-restart")
    restart_button.click()
    wait.until(lambda driver: restart_button.get_attribute("disabled") is None)

    random_user_browser.switch_to.window(popout_handle)
    wait.until(EC.staleness_of(popout_page))
    assert random_user_browser.current_url.rstrip("/").endswith("/workspace/terminal")
    random_user_browser.close()
    random_user_browser.switch_to.window(module_handle)
    random_user_browser.close()

def test_actionbar_banner_treats_challenge_name_as_text(random_user_browser, interfaces_dojo):
    random_user_browser.get(f"{DOJO_URL}/testing-interfaces/test")
    controls = random_user_browser.find_element(By.CSS_SELECTOR, ".workspace-controls")
    payload = '<img id="actionbar-html-probe" src=x onerror="window.actionbarHtmlExecuted=true">'
    expected = f"🎉 Successfully completed {payload}! 🎉"

    random_user_browser.execute_script("""
        window.actionbarHtmlExecuted = false;
        const controls = arguments[0];
        const input = controls.querySelector("#flag-input");
        controls.querySelector("#current-challenge-id").setAttribute("data-challenge-name", arguments[1]);
        CTFd.api.post_challenge_attempt = () => Promise.resolve({data: {status: "correct"}});
        input.value = "test";
        actionSubmitFlag({target: input});
    """, controls, payload)

    banner = controls.find_element(By.ID, "workspace-notification-banner")
    WebDriverWait(random_user_browser, 10).until(
        lambda driver: banner.get_attribute("textContent") == expected)
    assert not banner.find_elements(By.ID, "actionbar-html-probe")
    assert not random_user_browser.execute_script("return window.actionbarHtmlExecuted;")
    random_user_browser.close()

def test_actionbar_popup_blocked(random_user_browser, interfaces_dojo):
    random_user_browser.get(f"{DOJO_URL}/testing-interfaces/test")
    idx = challenge_idx(random_user_browser, "test1")
    challenge_start(random_user_browser, idx)
    body = random_user_browser.find_element("id", f"challenges-body-{idx}")
    handles = len(random_user_browser.window_handles)
    random_user_browser.execute_script("window.open = function() { return null; };")

    service_button(body, "Terminal").click()
    banner = body.find_element(By.ID, "workspace-notification-banner")
    WebDriverWait(random_user_browser, 30).until(lambda driver: banner.is_displayed() and banner.text)
    assert len(random_user_browser.window_handles) == handles
    random_user_browser.close()


def test_registration_commitment(browser_fixture):
    browser_fixture.get(f"{DOJO_URL}/register")
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


def test_welcome_graded_lecture(random_user_browser, example_dojo):
    random_user_browser.get(f"{DOJO_URL}/{example_dojo}/lectures")
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
    random_user_browser.close()
