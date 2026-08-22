import random
import shutil
import string
import pytest
import json

import requests
import requests.adapters
from urllib3.util.retry import Retry
from selenium.webdriver.firefox.service import Service as FirefoxService

#pylint:disable=redefined-outer-name,use-dict-literal,missing-timeout,unspecified-encoding,consider-using-with

from utils import TEST_DOJOS_LOCATION, DOJO_URL, login, make_dojo_official, create_dojo, create_dojo_yml, start_challenge, solve_challenge, solve_challenge_offline, remove_workspace_container, remove_workspace_home, wait_for_background_worker, db_sql, dojo_db_id, suppress_award_popup
from selenium.webdriver import Firefox, FirefoxOptions
from tiers import MULTINODE_TEST_FILES, MULTINODE_TESTS, TEST_FILE_TIERS, TEST_TIER_OVERRIDES

TEST_TIERS = ("semantic", "contract", "integration", "unit")

def pytest_collection_modifyitems(items):
    for item in items:
        test_name = getattr(item, "originalname", None) or item.name.split("[", 1)[0]
        test_key = f"{item.path.name}::{test_name}"
        tier = TEST_TIER_OVERRIDES.get(test_key, TEST_FILE_TIERS.get(item.path.name))
        if tier not in TEST_TIERS:
            raise pytest.UsageError(f"Test tier is not configured for {item.nodeid}")
        existing_tiers = {marker.name for marker in item.iter_markers() if marker.name in TEST_TIERS}
        if existing_tiers and existing_tiers != {tier}:
            raise pytest.UsageError(
                f"Test tier for {item.nodeid} conflicts with configured {tier}: {sorted(existing_tiers)}"
            )
        if not existing_tiers:
            item.add_marker(getattr(pytest.mark, tier))
        if item.path.name in MULTINODE_TEST_FILES or test_key in MULTINODE_TESTS:
            item.add_marker(pytest.mark.multinode)

# Nested-docker port publishing drops for a few seconds while user containers
# attach/detach networks; retry connection establishment (never sent requests)
# so local test runs survive the window.
_original_session_init = requests.Session.__init__

def _retrying_session_init(self, *args, **kwargs):
    _original_session_init(self, *args, **kwargs)
    retry = Retry(total=None, connect=6, read=0, redirect=0, status=0, other=0, backoff_factor=0.5)
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    self.mount("http://", adapter)
    self.mount("https://", adapter)

requests.Session.__init__ = _retrying_session_init

@pytest.fixture(scope="session")
def admin_session():
    session = login("admin", "admin")
    yield session

@pytest.fixture(scope="session")
def admin_user():
    session = login("admin", "admin")
    yield "admin", session

@pytest.fixture
def random_user():
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(random_id, random_id, register=True)
    yield random_id, session
    # Workspaces idle for six hours before the watchdog reaps them, which is far
    # longer than a suite run; leaving one behind per test starves the runner.
    user_id = db_sql(f"SELECT id FROM users WHERE name = '{random_id}'").strip()
    if user_id:
        remove_workspace_container(random_id)
        remove_workspace_home(user_id)

@pytest.fixture
def random_user_name(random_user):
    uid, _ = random_user
    yield uid

@pytest.fixture
def random_user_session(random_user):
    _, session = random_user
    yield session


@pytest.fixture
def completionist_user(simple_award_dojo, codepoints_award_dojo):
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(random_id, random_id, register=True)

    for dojo in [simple_award_dojo, codepoints_award_dojo]:
        response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
        assert response.status_code == 200
        for module, challenge in [ ("hello", "apple"), ("hello", "banana") ]:
            solve_challenge_offline(dojo, module, challenge, session=session, user=random_id)

    wait_for_background_worker(timeout=2)

    yield random_id, session


@pytest.fixture(scope="session")
def guest_dojo_admin():
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(random_id, random_id, register=True)
    yield random_id, session

@pytest.fixture(scope="session")
def example_dojo(admin_session):
    try:
        rid = create_dojo("pwncollege/example-dojo", session=admin_session)
    except AssertionError:
        rid = "example"
    return make_dojo_official(rid, admin_session)

# this needs the example_dojo because it imports from it
@pytest.fixture(scope="session")
def belt_dojos(admin_session, example_dojo):
    belt_dojo_rids = {
        color: create_dojo_yml(
            open(TEST_DOJOS_LOCATION / f"fake_{color}.yml").read(), session=admin_session
        ) for color in [ "orange", "yellow", "green", "blue" ]
    }
    return {color: make_dojo_official(rid, admin_session) for color, rid in belt_dojo_rids.items()}

@pytest.fixture(scope="session")
def example_import_dojo(admin_session, example_dojo):
    try:
        rid = create_dojo("pwncollege/example-import-dojo", session=admin_session)
    except AssertionError:
        rid = "example-import"
    return make_dojo_official(rid, admin_session)

@pytest.fixture
def simple_award_dojo(admin_session):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "simple_award_dojo.yml").read(), session=admin_session)

@pytest.fixture
def codepoints_award_dojo(admin_session):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "codepoints_award_dojo.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def no_practice_challenge_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "no_practice_challenge.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def import_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "import.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def import_override_dojo(admin_session, example_dojo):
    # Must not collide with the belt dojos, which claim the same id.
    n = "".join(random.choices(string.ascii_lowercase, k=8))
    rid = create_dojo_yml(
        open(TEST_DOJOS_LOCATION / "import_override.yml").read().replace(
            "id: intro-to-cybersecurity", f"id: import-override-{n}"), session=admin_session)
    return make_dojo_official(rid, admin_session)

@pytest.fixture(scope="session")
def transfer_src_dojo(admin_session):
    n = "".join(random.choices(string.ascii_lowercase, k=8))
    yml = open(TEST_DOJOS_LOCATION / "transfer_src.yml").read().replace("src-dojo", f"src-dojo-{n}")
    rid = create_dojo_yml(yml, session=admin_session)
    return rid

@pytest.fixture(scope="session")
def transfer_dst_dojo(transfer_src_dojo, admin_session):
    n = "".join(random.choices(string.ascii_lowercase, k=8))
    yml = open(
        TEST_DOJOS_LOCATION / "transfer_dst.yml"
    ).read().replace("src-dojo", transfer_src_dojo).replace("dst-dojo", f"dst-dojo-{n}")
    rid = create_dojo_yml(yml, session=admin_session)
    return make_dojo_official(rid, admin_session)

@pytest.fixture(scope="session")
def no_import_challenge_dojo(admin_session, example_dojo):
    n = "".join(random.choices(string.ascii_lowercase, k=8))
    rid = create_dojo_yml(
        open(TEST_DOJOS_LOCATION / "no_import_challenge.yml"
      ).read().replace("no-import-challenge", f"no-import-challenge-{n}"), session=admin_session)
    return make_dojo_official(rid, admin_session)

@pytest.fixture(scope="session")
def no_practice_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "no_practice_dojo.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def lfs_dojo(admin_session):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "lfs_dojo.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def event_dojo(admin_session):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "event_dojo.yml").read(), session=admin_session)
    dojo_id = dojo_db_id(rid)
    data = json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id={dojo_id};"))
    data["permissions"] = ["grant_awards"]
    db_sql(f"UPDATE dojos SET data='{json.dumps(data)}' WHERE dojo_id={dojo_id};")
    return rid

@pytest.fixture(scope="session")
def welcome_dojo(admin_session):
    try:
        rid = create_dojo("pwncollege/welcome-dojo", session=admin_session)
    except AssertionError:
        rid = "welcome"
    return make_dojo_official(rid, admin_session)


@pytest.fixture
def searchable_dojo(admin_session, example_dojo):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "searchable_dojo.yml").read(), session=admin_session)
    return make_dojo_official(rid, admin_session)

@pytest.fixture
def searchable_xss_dojo(admin_session, example_dojo):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "searchable_xss_dojo.yml").read(), session=admin_session)
    return make_dojo_official(rid, admin_session)

@pytest.fixture
def hidden_challenges_dojo(admin_session, example_dojo):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "hidden_challenges.yml").read(), session=admin_session)
    return rid

@pytest.fixture(scope="session")
def progression_locked_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "progression_locked_dojo.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def surveys_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "surveys_dojo.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def privileged_dojo(admin_session, example_dojo):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "privileged_dojo.yml").read(), session=admin_session)
    return make_dojo_official(rid, admin_session)

@pytest.fixture(scope="session")
def visibility_test_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "visibility_test.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def interfaces_dojo(admin_session, example_dojo):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "custom_interfaces.yml").read(), session=admin_session)
    return make_dojo_official(rid, admin_session)

@pytest.fixture
def random_private_dojo(admin_session):
    """Create a private (non-official, non-public) dojo with random ID"""
    n = "".join(random.choices(string.ascii_lowercase, k=8))
    yml = open(TEST_DOJOS_LOCATION / "private_test.yml").read().replace("private-dojo", f"private-dojo-{n}")
    rid = create_dojo_yml(yml, session=admin_session)
    return rid

@pytest.fixture
def browser_fixture():
    options = FirefoxOptions()
    options.add_argument("--headless")
    geckodriver = shutil.which("geckodriver")
    service = FirefoxService(executable_path=geckodriver) if geckodriver else None
    browser = Firefox(options=options, service=service)
    yield browser
    browser.quit()

@pytest.fixture
def random_user_browser(browser_fixture, random_user_name):
    suppress_award_popup(browser_fixture)
    browser_fixture.get(f"{DOJO_URL}/login")
    browser_fixture.find_element("id", "name").send_keys(random_user_name)
    browser_fixture.find_element("id", "password").send_keys(random_user_name)
    browser_fixture.find_element("id", "_submit").click()
    return browser_fixture
