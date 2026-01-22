import random
import string
import pytest

#pylint:disable=redefined-outer-name,use-dict-literal,missing-timeout,unspecified-encoding,consider-using-with

from utils import DOJO_HOST, TEST_DOJOS_LOCATION, login, make_dojo_official, create_dojo, create_dojo_yml, start_challenge, solve_challenge, wait_for_background_worker
from selenium.webdriver import Firefox, FirefoxOptions

@pytest.fixture(scope="session")
def admin_session():
    session = login("admin", "admin")
    yield session


@pytest.fixture(scope="session", autouse=True)
def test_image_setup(admin_session):
    response = admin_session.post(
        f"http://{DOJO_HOST}/pwncollege_api/v1/test_utils/docker_images",
        json={
            "pulls": [
                "pwncollege/challenge-simple",
                "pwncollege/challenge-lecture",
            ],
            "tags": [
                {"source": "pwncollege/challenge-simple", "target": "pwncollege/challenge-legacy"},
            ],
        },
    )
    assert response.status_code == 200, f"Image setup failed: {response.status_code} {response.text}"
    assert response.json().get("success") is True, f"Image setup failed: {response.text}"
    yield

@pytest.fixture(scope="session")
def admin_user():
    session = login("admin", "admin")
    yield "admin", session

@pytest.fixture
def random_user():
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(random_id, random_id, register=True)
    yield random_id, session

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

    response = session.get(f"http://{DOJO_HOST}/dojo/{simple_award_dojo}/join/")
    assert response.status_code == 200
    for module, challenge in [ ("hello", "apple"), ("hello", "banana") ]:
        start_challenge(simple_award_dojo, module, challenge, session=session)
        solve_challenge(simple_award_dojo, module, challenge, session=session, user=random_id)

    response = session.get(f"http://{DOJO_HOST}/dojo/{codepoints_award_dojo}/join/")
    assert response.status_code == 200
    for module, challenge in [ ("hello", "apple"), ("hello", "banana") ]:
        start_challenge(codepoints_award_dojo, module, challenge, session=session)
        solve_challenge(codepoints_award_dojo, module, challenge, session=session, user=random_id)

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
    make_dojo_official(rid, admin_session)
    return rid

# this needs the example_dojo because it imports from it
@pytest.fixture(scope="session")
def belt_dojos(admin_session, example_dojo):
    belt_dojo_rids = {
        color: create_dojo_yml(
            open(TEST_DOJOS_LOCATION / f"fake_{color}.yml").read(), session=admin_session
        ) for color in [ "orange", "yellow", "green", "blue" ]
    }
    for rid in belt_dojo_rids.values():
        make_dojo_official(rid, admin_session)
    return belt_dojo_rids

@pytest.fixture(scope="session")
def example_import_dojo(admin_session, example_dojo):
    try:
        rid = create_dojo("pwncollege/example-import-dojo", session=admin_session)
    except AssertionError:
        rid = "example-import"
    make_dojo_official(rid, admin_session)
    return rid

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
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "import_override.yml").read(), session=admin_session)
    make_dojo_official(rid, admin_session)
    return rid

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
    make_dojo_official(rid, admin_session)
    return rid

@pytest.fixture(scope="session")
def no_import_challenge_dojo(admin_session, example_dojo):
    n = "".join(random.choices(string.ascii_lowercase, k=8))
    rid = create_dojo_yml(
        open(TEST_DOJOS_LOCATION / "no_import_challenge.yml"
      ).read().replace("no-import-challenge", f"no-import-challenge-{n}"), session=admin_session)
    make_dojo_official(rid, admin_session)
    return rid

@pytest.fixture(scope="session")
def no_practice_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "no_practice_dojo.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def lfs_dojo(admin_session):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "lfs_dojo.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def welcome_dojo(admin_session):
    try:
        rid = create_dojo("pwncollege/welcome-dojo", session=admin_session)
    except AssertionError:
        rid = "welcome"
    make_dojo_official(rid, admin_session)
    return rid


@pytest.fixture
def searchable_dojo(admin_session, example_dojo):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "searchable_dojo.yml").read(), session=admin_session)
    make_dojo_official(rid, admin_session)
    return rid

@pytest.fixture
def searchable_xss_dojo(admin_session, example_dojo):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "searchable_xss_dojo.yml").read(), session=admin_session)
    make_dojo_official(rid, admin_session)
    return rid

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
    make_dojo_official(rid, admin_session)
    return rid

@pytest.fixture(scope="session")
def visibility_test_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "visibility_test.yml").read(), session=admin_session)

@pytest.fixture(scope="session")
def interfaces_dojo(admin_session, example_dojo):
    rid = create_dojo_yml(open(TEST_DOJOS_LOCATION / "custom_interfaces.yml").read(), session=admin_session)
    make_dojo_official(rid, admin_session)
    return rid

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
    return Firefox(options=options)

@pytest.fixture
def random_user_browser(browser_fixture, random_user_name):
    browser_fixture.get(f"http://{DOJO_HOST}/login")
    browser_fixture.find_element("id", "name").send_keys(random_user_name)
    browser_fixture.find_element("id", "password").send_keys(random_user_name)
    browser_fixture.find_element("id", "_submit").click()
    return browser_fixture
