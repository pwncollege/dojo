import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from utils import DOJO_URL, db_sql, get_user_id


SETTINGS_URL = f"{DOJO_URL.rstrip('/')}/settings"


def wait_for_pane(browser, pane, form):
    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, f"#{pane}.active.show #{form}"))
    )


def formatted_token_times(browser):
    times = [element.text for element in browser.find_elements(By.CSS_SELECTOR, "#tokens span[data-time]")]
    return times if times and all(times) else None


def test_settings_profile_form_updates_and_reports_errors(random_user_browser, random_user_name):
    browser = random_user_browser
    user_id = get_user_id(random_user_name)
    browser.get(SETTINGS_URL)

    affiliation = f"affiliation-{uuid.uuid4().hex[:12]}"
    affiliation_field = browser.find_element(By.ID, "affiliation")
    affiliation_field.clear()
    affiliation_field.send_keys(affiliation)
    browser.find_element(By.CSS_SELECTOR, "#user-profile-form #_submit").click()
    WebDriverWait(browser, 10).until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#results .alert-success")))
    assert db_sql(f"SELECT affiliation FROM users WHERE id = {user_id}").strip() == affiliation

    password_hash = db_sql(f"SELECT password FROM users WHERE id = {user_id}").strip()
    browser.find_element(By.ID, "password").send_keys(f"new-{random_user_name}")
    browser.find_element(By.ID, "confirm").send_keys(f"wrong-{random_user_name}")
    browser.find_element(By.CSS_SELECTOR, "#user-profile-form #_submit").click()
    WebDriverWait(browser, 10).until(
        lambda driver: "is-invalid" in driver.find_element(By.ID, "confirm").get_attribute("class").split()
    )
    assert "previous password is incorrect" in browser.find_element(By.CSS_SELECTOR, "#results .alert-danger").text
    assert db_sql(f"SELECT password FROM users WHERE id = {user_id}").strip() == password_hash


def test_settings_token_modal_and_delete(random_user_browser, random_user_name):
    browser = random_user_browser
    user_id = get_user_id(random_user_name)
    browser.get(f"{SETTINGS_URL}#tokens")
    wait_for_pane(browser, "tokens", "user-token-form")

    browser.find_element(By.CSS_SELECTOR, "#user-token-form #_submit").click()
    WebDriverWait(browser, 10).until(EC.visibility_of_element_located((By.ID, "token-modal")))
    token_value = browser.find_element(By.ID, "user-token-result").get_attribute("value")
    assert token_value.startswith("ctfd_"), token_value
    assert db_sql(f"SELECT count(*) FROM tokens WHERE user_id = {user_id}").strip() == "1"

    browser.refresh()
    wait_for_pane(browser, "tokens", "user-token-form")
    formatted_times = WebDriverWait(browser, 10).until(formatted_token_times)
    assert len(formatted_times) == 2, formatted_times
    for formatted_time in formatted_times:
        assert re.fullmatch(r"[A-Z][a-z]+ \d+(st|nd|rd|th), \d+:\d\d:\d\d (AM|PM)", formatted_time), formatted_time

    browser.find_element(By.CSS_SELECTOR, ".delete-token").click()
    WebDriverWait(browser, 5).until(EC.alert_is_present())
    browser.switch_to.alert.accept()
    WebDriverWait(browser, 10).until(lambda driver: driver.find_elements(By.CSS_SELECTOR, ".delete-token") == [])
    assert db_sql(f"SELECT count(*) FROM tokens WHERE user_id = {user_id}").strip() == "0"


def test_settings_add_ssh_key(random_user_browser, random_user_name):
    browser = random_user_browser
    user_id = get_user_id(random_user_name)
    with tempfile.TemporaryDirectory() as key_directory:
        key_path = Path(key_directory) / "key"
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-q"], check=True)
        key_type, key_data, _comment = key_path.with_suffix(".pub").read_text().split()
    public_key = f"{key_type} {key_data} test-comment"

    browser.get(f"{SETTINGS_URL}#ssh-key")
    wait_for_pane(browser, "ssh-key", "ssh-key-form")
    browser.find_element(By.CSS_SELECTOR, "#ssh-key-form input[name=ssh_key]").send_keys(public_key)
    browser.find_element(By.CSS_SELECTOR, "#ssh-key-form #_submit").click()
    WebDriverWait(browser, 10).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, "#ssh-key-results .alert-success"))
    )
    assert db_sql(f"SELECT count(*) FROM ssh_keys WHERE user_id = {user_id}").strip() == "1"
    assert db_sql(f"SELECT value FROM ssh_keys WHERE user_id = {user_id}").strip() == f"{key_type} {key_data}"
