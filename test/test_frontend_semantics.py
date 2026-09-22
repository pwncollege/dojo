import shutil
import uuid
from urllib.parse import urlparse

import pytest
import yaml
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from utils import DOJO_IP, create_dojo_yml, dojo_run, make_dojo_official


@pytest.fixture(scope="module")
def frontend_url():
    host = dojo_run("docker", "exec", "nginx", "printenv", "DOJO_HOST").stdout.strip()
    return f"http://future.{host}"


@pytest.fixture
def frontend_browser():
    options = FirefoxOptions()
    options.add_argument("--headless")
    options.set_preference("network.dns.forceResolve", DOJO_IP)
    driver = shutil.which("geckodriver")
    browser = Firefox(options=options, service=Service(executable_path=driver) if driver else None)
    browser.set_window_size(1440, 1000)
    yield browser
    browser.quit()


@pytest.fixture(scope="module")
def frontend_dojo(admin_session):
    dojo = create_dojo_yml(yaml.safe_dump({
        "id": f"browser-catalog-{uuid.uuid4().hex[:10]}",
        "name": "Browser Catalog",
        "type": "public",
        "image": "pwncollege/challenge-simple",
        "modules": [{
            "id": "reading",
            "name": "Browser Reading Module",
            "resources": [
                {"type": "header", "content": "Reading Section"},
                {"type": "markdown", "name": "Introduction", "content": "Introduction available without expansion.", "expandable": False},
                {"type": "markdown", "name": "Further Reading", "content": "Expanded reading material.", "expandable": True},
            ],
            "challenges": [{"id": "exercise", "name": "Reading Exercise", "description": "Exercise instructions."}],
        }],
    }), session=admin_session)
    return make_dojo_official(dojo, admin_session)


def test_frontend_catalog_opens_modules_and_reading_material(frontend_browser, frontend_url, frontend_dojo):
    browser = frontend_browser
    wait = WebDriverWait(browser, 45)
    browser.get(f"{frontend_url}/dojo/{frontend_dojo}")
    module_link = wait.until(EC.element_to_be_clickable((
        By.CSS_SELECTOR, f'a[href="/dojo/{frontend_dojo}/module/reading"]',
    )))
    module_link.click()
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Introduction available without expansion."))
    assert "Reading Section" in browser.find_element(By.TAG_NAME, "body").text
    assert "Expanded reading material." not in browser.find_element(By.TAG_NAME, "body").text
    wait.until(EC.element_to_be_clickable((By.XPATH, '//*[text()="Further Reading"]'))).click()
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Expanded reading material."))
    assert urlparse(browser.current_url).path == f"/dojo/{frontend_dojo}/module/reading"


def test_frontend_login_survives_reload_and_logout_ends_the_session(frontend_browser, frontend_url, random_user):
    name, _ = random_user
    browser = frontend_browser
    wait = WebDriverWait(browser, 45)
    identity_url = frontend_url.replace("://future.", "://", 1) + "/pwncollege_api/v1/users/me"

    def server_identity():
        return browser.execute_async_script("""
            const done = arguments[arguments.length - 1];
            fetch(arguments[0], {credentials: 'include', headers: {'Content-Type': 'application/json'}})
                .then(async response => done({status: response.status, data: await response.json().catch(() => null)}))
                .catch(error => done({error: String(error)}));
        """, identity_url)

    browser.get(f"{frontend_url}/login")
    wait.until(EC.element_to_be_clickable((By.ID, "name"))).send_keys(name)
    browser.find_element(By.ID, "password").send_keys(name)
    browser.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    wait.until(lambda driver: urlparse(driver.current_url).path == "/")
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "header"), name))

    browser.refresh()
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "header"), name))
    identity = server_identity()
    assert identity["status"] == 200, identity
    assert identity["data"]["name"] == name
    wait.until(EC.element_to_be_clickable((By.XPATH, f'//header//button[contains(., "{name}")]'))).click()
    wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@role="menuitem" and contains(., "Log out")]'))).click()
    wait.until(lambda driver: name not in driver.find_element(By.TAG_NAME, "header").text)
    browser.refresh()
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'header a[href="/login"]')))
    assert name not in browser.find_element(By.TAG_NAME, "header").text
    identity = server_identity()
    assert identity["status"] == 403, identity


def test_frontend_learning_action_sends_anonymous_visitors_to_login(frontend_browser, frontend_url, frontend_dojo):
    browser = frontend_browser
    wait = WebDriverWait(browser, 45)
    browser.get(f"{frontend_url}/dojo/{frontend_dojo}/module/reading")
    wait.until(EC.element_to_be_clickable((By.XPATH, '//*[text()="Further Reading"]'))).click()
    wait.until(EC.element_to_be_clickable((By.XPATH, '//button[contains(., "Start Learning")]'))).click()
    wait.until(lambda driver: urlparse(driver.current_url).path == "/login")
    wait.until(EC.element_to_be_clickable((By.ID, "name")))


@pytest.fixture
def authenticated_frontend_browser(frontend_browser, frontend_url, random_user):
    name, _ = random_user
    browser = frontend_browser
    wait = WebDriverWait(browser, 45)
    browser.get(f"{frontend_url}/login")
    wait.until(EC.element_to_be_clickable((By.ID, "name"))).send_keys(name)
    browser.find_element(By.ID, "password").send_keys(name)
    browser.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    wait.until(lambda driver: urlparse(driver.current_url).path == "/")
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "header"), name))
    return browser


@pytest.fixture(scope="module")
def frontend_search_dojo(admin_session):
    tag = uuid.uuid4().hex[:10]
    module_name = f"Findthislesson{tag}"
    content = f"Search destination reading {tag}"
    dojo = create_dojo_yml(yaml.safe_dump({
        "id": f"browser-search-{tag}",
        "name": f"Search Catalog {tag}",
        "type": "public",
        "modules": [{
            "id": "found",
            "name": module_name,
            "resources": [{"type": "markdown", "name": "Destination", "content": content, "expandable": False}],
        }],
    }), session=admin_session)
    return make_dojo_official(dojo, admin_session), module_name, content


def test_frontend_reading_workspace_preserves_the_selected_resource_on_reload(
    authenticated_frontend_browser, frontend_url, frontend_dojo,
):
    browser = authenticated_frontend_browser
    wait = WebDriverWait(browser, 45)
    browser.get(f"{frontend_url}/dojo/{frontend_dojo}/module/reading")
    wait.until(EC.element_to_be_clickable((By.XPATH, '//*[text()="Further Reading"]'))).click()
    wait.until(EC.element_to_be_clickable((By.XPATH, '//button[contains(., "Start Learning")]'))).click()
    expected_prefix = f"/dojo/{frontend_dojo}/module/reading/workspace/resource/"
    wait.until(lambda driver: urlparse(driver.current_url).path.startswith(expected_prefix))
    workspace_url = browser.current_url
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Reading Material"))
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Expanded reading material."))

    browser.refresh()
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Reading Material"))
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), "Expanded reading material."))
    assert browser.current_url == workspace_url


def test_frontend_search_opens_the_matching_module_from_keyboard_selection(
    frontend_browser, frontend_url, frontend_search_dojo,
):
    dojo, module_name, content = frontend_search_dojo
    browser = frontend_browser
    wait = WebDriverWait(browser, 45)
    browser.get(frontend_url)
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'header a[href="/login"]')))
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[title="Search (Ctrl+K)"]'))).click()
    search = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[placeholder^="Search dojos"]')))
    search.send_keys(module_name)
    wait.until(EC.element_to_be_clickable((By.XPATH, f'//*[@data-search-item and contains(., "{module_name}")]')))
    search.send_keys(Keys.ENTER)

    expected_path = f"/dojo/{dojo}/module/found"
    wait.until(lambda driver: urlparse(driver.current_url).path == expected_path)
    wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), content))
    assert module_name in browser.find_element(By.TAG_NAME, "body").text
