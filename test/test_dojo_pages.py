import random
import string

import pytest
import requests

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    challenge_db_id,
    challenge_flag,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    get_user_id,
    login,
    solve_challenge_offline,
)


def random_id(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def official_reference_id(dojo):
    """An official dojo's reference id drops the ~hex suffix it had while unofficial."""
    return dojo.split("~", 1)[0]


def solve_count(dojo, module, challenge, user_name):
    return int(db_sql(
        f"SELECT count(*) FROM submissions WHERE type = 'correct' AND user_id = {get_user_id(user_name)} "
        f"AND challenge_id = {challenge_db_id(dojo, module, challenge)}"
    ))


@pytest.fixture(scope="module")
def pages_dojo(admin_session):
    spec = (TEST_DOJOS_LOCATION / "dojo_pages.yml").read_text().replace("dojo-pages", f"dojo-pages-{random_id()}")
    return create_dojo_yml(spec, session=admin_session)


@pytest.fixture(scope="module")
def pages_password_dojo(admin_session):
    spec = (TEST_DOJOS_LOCATION / "dojo_pages_password.yml").read_text().replace(
        "pages-password", f"pages-password-{random_id()}")
    return create_dojo_yml(spec, session=admin_session)


@pytest.fixture(scope="module")
def solves_code(example_dojo):
    code = db_sql(f"SELECT md5(private_key || 'SOLVES') FROM dojos WHERE dojo_id = {dojo_db_id(example_dojo)}").strip()
    assert code, f"{example_dojo} has no private key, so no solves code can be derived"
    return code


@pytest.fixture(scope="module")
def export_solvers(example_dojo):
    solvers = []
    for _ in range(2):
        name = random_id(16)
        session = login(name, name, register=True)
        solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
        solvers.append(name)
    return solvers


def test_solves_export_csv(example_dojo, solves_code, export_solvers):
    response = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{solves_code}/csv")
    assert response.status_code == 200, f"Expected the csv export to be public, got {response.status_code}"
    assert response.headers["Content-Type"].startswith("text/csv"), response.headers["Content-Type"]
    assert "attachment; filename=data.csv" in response.headers["Content-Disposition"], response.headers

    lines = response.text.splitlines()
    assert lines[0] == "user_id,module,challenge,time", f"Unexpected csv header: {lines[0]}"
    for name in export_solvers:
        prefix = f"{get_user_id(name)},hello,apple,"
        matching = [line for line in lines[1:] if line.startswith(prefix)]
        assert len(matching) == 1, f"Expected exactly one '{prefix}' row, got {matching}"
        assert matching[0].endswith("+00:00"), f"Expected a UTC timestamp, got {matching[0]}"


def test_solves_export_json_and_username_filter(example_dojo, solves_code, export_solvers):
    response = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{solves_code}/json")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    rows = response.json()
    assert isinstance(rows, list), f"Expected a list of solves, got {type(rows)}"
    assert rows, "Expected the example dojo to have solves"
    expected_keys = {"user_id", "user_name", "module", "challenge", "time"}
    assert all(set(row) == expected_keys for row in rows), f"Unexpected keys: {set(rows[0])}"

    names = {row["user_name"] for row in rows}
    for name in export_solvers:
        assert name in names, f"{name} is missing from the json export"

    target = export_solvers[0]
    response = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{solves_code}/json",
                            params={"user_name": target})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    filtered = response.json()
    assert filtered, f"Expected {target}'s solves to survive the user_name filter"
    assert all(row["user_name"] == target for row in filtered), f"Filter leaked other users: {filtered}"
    assert ("hello", "apple") in {(row["module"], row["challenge"]) for row in filtered}
    assert all(row["user_id"] == get_user_id(target) for row in filtered)

    response = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{solves_code}/json",
                            params={"user_name": f"nobody-{random_id()}"})
    assert response.status_code == 200
    assert response.json() == [], "Filtering on an unknown user should return no rows"


def test_solves_export_rejects_bad_format_code_and_dojo(example_dojo, solves_code):
    response = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{solves_code}/xml")
    assert response.status_code == 400, f"Expected status code 400, but got {response.status_code}"
    assert response.json() == {"success": False, "error": "Invalid format"}, response.json()

    response = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{'0' * 32}/csv")
    assert response.status_code == 403, f"Expected a wrong solves code to be forbidden, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Forbidden"}, response.json()

    response = requests.get(f"{DOJO_URL}/dojo/nonexistent-{random_id()}/solves/{solves_code}/csv")
    assert response.status_code == 404, f"Expected status code 404, but got {response.status_code}"
    assert response.json() == {"success": False, "error": "Not Found"}, response.json()


def test_modules_api_required_flag_and_unified_order(pages_dojo, admin_session):
    response = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{pages_dojo}/modules")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    modules = response.json()["modules"]
    assert [module["id"] for module in modules] == ["pages-module"], modules

    module = modules[0]
    assert module["name"] == "Pages Module"
    assert [challenge["id"] for challenge in module["challenges"]] == ["a", "b", "c"]
    required = {challenge["id"]: challenge["required"] for challenge in module["challenges"]}
    assert required == {"a": True, "b": False, "c": True}, required

    unified = module["unified_items"]
    assert [item["item_type"] for item in unified] == [
        "resource", "challenge", "resource", "challenge", "challenge"
    ], [item["item_type"] for item in unified]
    assert [item["id"] for item in unified] == ["resource-0", "a", "resource-2", "b", "c"]
    assert [item["required"] for item in unified] == [None, True, None, False, True]

    header, markdown = unified[0], unified[2]
    assert header["type"] == "header" and header["content"] == "Pages Section", header
    assert markdown["type"] == "markdown" and markdown["name"] == "Pages Notes", markdown
    assert "Notes between challenges." in markdown["content"], markdown["content"]

    assert [resource["id"] for resource in module["resources"]] == ["resource-0", "resource-2"]


def test_dojo_listing_api_counts_required_challenges(pages_dojo, admin_session):
    response = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    data = response.json()
    assert data["success"]

    entry = next((dojo for dojo in data["dojos"] if dojo["id"] == pages_dojo), None)
    assert entry is not None, f"{pages_dojo} missing from {[dojo['id'] for dojo in data['dojos']]}"
    assert entry["modules_count"] == 1, entry
    assert entry["challenges_count"] == 2, f"challenges_count should count only required challenges: {entry}"
    assert entry["official"] is False and entry["type"] == "public", entry
    assert entry["name"] == "Dojo Pages Test"

    total = int(db_sql(f"SELECT count(*) FROM dojo_challenges WHERE dojo_id = {dojo_db_id(pages_dojo)}"))
    assert total == 3, f"Expected 3 challenge rows in the database, got {total}"


def test_dojo_listing_api_orders_official_first(pages_dojo, example_dojo, admin_session):
    response = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    dojos = response.json()["dojos"]

    official_flags = [dojo["official"] for dojo in dojos]
    assert official_flags == sorted(official_flags, reverse=True), (
        f"Official dojos must precede unofficial ones: {[(d['id'], d['official']) for d in dojos]}"
    )

    ids = [dojo["id"] for dojo in dojos]
    assert ids.index(official_reference_id(example_dojo)) < ids.index(pages_dojo)


def test_challenges_url_redirects_to_dojos(example_dojo):
    response = requests.get(f"{DOJO_URL}/challenges", allow_redirects=False)
    assert response.status_code == 301, f"Expected a permanent redirect, got {response.status_code}"
    assert response.headers["Location"].rstrip("/").endswith("/dojos"), response.headers["Location"]

    response = requests.get(f"{DOJO_URL}/dojo/{example_dojo}", allow_redirects=False)
    assert response.status_code == 302, f"Expected a redirect to the dojo page, got {response.status_code}"
    assert response.headers["Location"].rstrip("/").endswith(f"/{official_reference_id(example_dojo)}"), (
        response.headers["Location"]
    )


def test_dojo_and_module_pages(example_dojo, pages_dojo, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/{example_dojo}/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/{example_dojo}/hello/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/{example_dojo}/hello/apple/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/{example_dojo}/hello/nonexistent/").status_code == 404
    assert random_user_session.get(f"{DOJO_URL}/{example_dojo}/nonexistent/").status_code == 404
    assert random_user_session.get(f"{DOJO_URL}/nonexistent-{random_id()}/").status_code == 404

    response = random_user_session.get(f"{DOJO_URL}/{pages_dojo}/pages-module/")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    for name in ["Challenge A", "Challenge B", "Challenge C"]:
        assert name in response.text, f"{name} missing from the module page"


def test_join_dojo_membership(example_dojo, pages_password_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)

    anonymous = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/join/", allow_redirects=False)
    assert anonymous.status_code == 302, f"Expected anonymous joins to redirect to login, got {anonymous.status_code}"
    assert "login" in anonymous.headers["Location"], anonymous.headers["Location"]

    def membership(dojo):
        return db_sql(
            f"SELECT type FROM dojo_users WHERE dojo_id = {dojo_db_id(dojo)} AND user_id = {user_id}"
        ).split()

    response = session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/", allow_redirects=False)
    assert response.status_code == 302, f"Expected status code 302, but got {response.status_code}"
    assert response.headers["Location"].rstrip("/").endswith(f"/{official_reference_id(example_dojo)}")
    assert membership(example_dojo) == ["member"], membership(example_dojo)

    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/", allow_redirects=False).status_code == 302
    assert membership(example_dojo) == ["member"], "Joining twice must not duplicate the membership"

    assert session.get(f"{DOJO_URL}/dojo/{pages_password_dojo}/join/").status_code == 403
    assert session.get(f"{DOJO_URL}/dojo/{pages_password_dojo}/join/wrongpassword").status_code == 403
    assert membership(pages_password_dojo) == [], "A rejected join must not create a membership"

    response = session.get(f"{DOJO_URL}/dojo/{pages_password_dojo}/join/hunter2hunter2", allow_redirects=False)
    assert response.status_code == 302, f"Expected status code 302, but got {response.status_code}"
    assert membership(pages_password_dojo) == ["member"], membership(pages_password_dojo)


def test_per_user_solves_api_filters(example_dojo, random_user):
    name, session = random_user
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    solve_challenge_offline(example_dojo, "hello", "banana", session=session, user=name)

    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    solves = response.json()["solves"]
    assert [solve["challenge_id"] for solve in solves] == ["apple", "banana"], solves
    assert all(solve["module_id"] == "hello" for solve in solves), solves
    timestamps = [solve["timestamp"] for solve in solves]
    assert timestamps == sorted(timestamps), f"Solves must be ordered by ascending timestamp: {timestamps}"

    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves",
                           params={"after": timestamps[0]})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert [solve["challenge_id"] for solve in response.json()["solves"]] == ["banana"], response.json()

    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves",
                           params={"after": timestamps[-1]})
    assert response.status_code == 200
    assert response.json()["solves"] == [], "Nothing was solved after the last solve"

    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves",
                           params={"after": "not-a-date"})
    assert response.status_code == 400, f"Expected status code 400, but got {response.status_code}"
    assert response.json()["error"] == "Invalid after date format", response.json()


def test_solve_endpoint_incorrect_and_duplicate(example_dojo, random_user):
    name, session = random_user
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/hello/apple/solve"

    response = session.post(url, json={"submission": "pwn.college{not-a-flag}"})
    assert response.status_code == 400, f"Expected status code 400, but got {response.status_code}"
    assert response.json()["success"] is False and response.json()["status"] == "incorrect", response.json()
    assert solve_count(example_dojo, "hello", "apple", name) == 0, "An incorrect flag must not register a solve"

    response = session.post(url, json={})
    assert response.status_code == 400, f"Expected status code 400, but got {response.status_code}"
    assert response.json()["error"] == "Must supply a submission.", response.json()

    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/hello/nonexistent/solve",
                            json={"submission": "pwn.college{whatever}"})
    assert response.status_code == 404, f"Expected status code 404, but got {response.status_code}"

    flag = challenge_flag(example_dojo, "hello", "apple", user=name)
    response = session.post(url, json={"submission": flag})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json() == {"success": True, "status": "solved"}, response.json()
    assert solve_count(example_dojo, "hello", "apple", name) == 1

    response = session.post(url, json={"submission": flag})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json() == {"success": True, "status": "already_solved"}, response.json()
    assert solve_count(example_dojo, "hello", "apple", name) == 1, "Resubmitting must not duplicate the solve"
