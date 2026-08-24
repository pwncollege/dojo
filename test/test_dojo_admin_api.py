import hashlib
import random
import re
import socket
import string
import time
import urllib.parse

import pytest
import requests
import yaml

from utils import (
    DOJO_URL,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    get_user_id,
    login,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
)

CREATE_ENDPOINT = "pwncollege_api.dojos_create_dojo"
CHALLENGE_IMAGE = "pwncollege/challenge-simple"


def rand(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def spec_id(prefix):
    return f"adminapi-{prefix}-{rand()}"


def post_create(session, payload):
    return session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", json=payload)


def create_spec(session, spec):
    return create_dojo_yml(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), session=session)


def simple_spec(dojo_id, *, type="public", challenges=("a",), **extra):
    return {
        "id": dojo_id,
        "type": type,
        "image": CHALLENGE_IMAGE,
        "modules": [{"id": "m", "resources": [
            {"type": "challenge", "id": challenge, "name": challenge.upper()}
            for challenge in challenges
        ]}],
        **extra,
    }


def dojo_hex(reference_id):
    return reference_id.split("~", 1)[1]


def dojo_row_count(reference_id, table="dojos"):
    return int(db_sql(f"SELECT count(*) FROM {table} WHERE dojo_id = x'{dojo_hex(reference_id)}'::int"))


def dojos_named(dojo_id):
    return int(db_sql(f"SELECT count(*) FROM dojos WHERE id = '{dojo_id}'"))


def dojo_user_type(reference_id, user_id):
    return db_sql(
        f"SELECT type FROM dojo_users WHERE dojo_id = x'{dojo_hex(reference_id)}'::int AND user_id = {user_id}"
    ).strip()


def get_modules(session, reference_id):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/modules")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    return response.json()["modules"]


def module_challenges(session, reference_id):
    return {module["id"]: [challenge["id"] for challenge in module["challenges"]]
            for module in get_modules(session, reference_id)}


def listed_dojo_ids(session):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    return {dojo["id"] for dojo in response.json()["dojos"]}


def client_ip():
    parsed = urllib.parse.urlparse(DOJO_URL)
    connection = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=10)
    try:
        return connection.getsockname()[0]
    finally:
        connection.close()


def clear_create_rate_limit():
    dojo_run("docker", "exec", "cache", "redis-cli", "DEL", f"flask_cache_rl:{client_ip()}:{CREATE_ENDPOINT}")


def solves_code(reference_id):
    private_key = db_sql(f"SELECT private_key FROM dojos WHERE dojo_id = {dojo_db_id(reference_id)}").strip()
    assert private_key, f"{reference_id} has no private key"
    return hashlib.md5(private_key.encode() + b"SOLVES").hexdigest()


def new_user():
    name = rand(16)
    return name, login(name, name, register=True)


@pytest.fixture(scope="module")
def public_dojo(admin_session):
    return create_spec(admin_session, simple_spec(spec_id("public")))


@pytest.fixture(scope="module")
def description_dojo(admin_session):
    return create_spec(admin_session, {
        "id": spec_id("describe"),
        "type": "public",
        "image": CHALLENGE_IMAGE,
        "modules": [{"id": "m", "resources": [
            {"type": "challenge", "id": "a", "name": "A", "description": "Find the **flag**"},
            {"type": "challenge", "id": "future", "name": "Future", "description": "Not yet",
             "visibility": {"start": "2099-01-01T00:00:00Z"}},
        ]}],
    })


def test_create_from_spec_as_site_admin(admin_session):
    dojo_id = spec_id("create")
    response = post_create(admin_session, {"spec": f"id: {dojo_id}\n"})
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"
    assert response.json()["success"] is True

    reference_id = response.json()["dojo"]
    assert reference_id.startswith(f"{dojo_id}~"), f"Unexpected reference id {reference_id}"
    assert re.fullmatch(r"[0-9a-f]{8}", dojo_hex(reference_id)), f"Unexpected reference id {reference_id}"

    assert db_sql(
        f"SELECT official FROM dojos WHERE dojo_id = x'{dojo_hex(reference_id)}'::int").strip() == "f", \
        "a spec-created dojo must not be official"
    assert dojo_user_type(reference_id, get_user_id("admin")) == "admin", \
        "the creating user must become a dojo admin"
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200


def test_create_from_spec_denied_to_non_admin(random_user_session):
    dojo_id = spec_id("nonadmin")
    clear_create_rate_limit()
    response = post_create(random_user_session, {"spec": f"id: {dojo_id}\n"})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert response.json()["success"] is False
    assert "admin" in response.json()["error"], f"Unexpected error: {response.json()['error'][:200]}"
    assert dojos_named(dojo_id) == 0, "the rejected spec must not create a dojo"


def test_create_requires_repository_or_spec(admin_session):
    response = post_create(admin_session, {})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert response.json() == {"success": False, "error": "Repository is required"}


def test_create_repository_validation(admin_session, example_dojo):
    before = int(db_sql("SELECT count(*) FROM dojos WHERE repository = 'pwncollege/example-dojo'"))
    assert before >= 1, "the example dojo's repository must be registered"

    response = post_create(admin_session, {"repository": "not-a-repo", "public_key": "p", "private_key": "k"})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert "Invalid repository" in response.json()["error"], f"Unexpected error: {response.json()['error'][:200]}"

    response = post_create(admin_session, {
        "repository": "https://github.com/pwncollege/example-dojo", "public_key": "p", "private_key": "k"})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert "already exists" in response.json()["error"], \
        f"the github url must normalize to owner/name: {response.json()['error'][:200]}"

    response = post_create(admin_session, {
        "repository": "pwncollege/example-dojo", "public_key": "p", "private_key": "k"})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert "already exists" in response.json()["error"], f"Unexpected error: {response.json()['error'][:200]}"

    after = int(db_sql("SELECT count(*) FROM dojos WHERE repository = 'pwncollege/example-dojo'"))
    assert after == before, "a rejected creation must not add a dojo row"


def test_create_clone_failure_reports_deploy_key(admin_session):
    repository = f"pwncollege/does-not-exist-{rand()}"
    response = post_create(admin_session, {
        "repository": repository, "public_key": "public/x", "private_key": "private/x"})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    error = response.json()["error"]
    assert "Failed to clone" in error, f"Unexpected error: {error[:200]}"
    assert f"github.com/{repository}/settings/keys" in error, \
        f"the error must point at the repository's deploy key page: {error[:200]}"
    assert int(db_sql(f"SELECT count(*) FROM dojos WHERE repository = '{repository}'")) == 0


def test_create_rate_limit_per_ip(admin_session, random_user_session):
    try:
        clear_create_rate_limit()
        for _ in range(2):
            response = post_create(admin_session, {"spec": f"id: {spec_id('bypass')}\n"})
            assert response.status_code == 200, \
                f"site admins bypass the create rate limit, got {response.status_code} - {response.text[:200]}"

        response = post_create(random_user_session, {
            "repository": f"pwncollege/rate-limited-{rand()}", "public_key": "p", "private_key": "k"})
        assert response.status_code == 429, f"Expected 429, got {response.status_code} - {response.text[:300]}"
        assert response.json() == {"success": False, "error": "You can only create 1 dojo per day."}
    finally:
        clear_create_rate_limit()


def test_create_page_issues_fresh_keypair(random_user_session):
    keys = []
    for _ in range(2):
        response = random_user_session.get(f"{DOJO_URL}/dojos/create")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        match = re.search(r"ssh-ed25519 [A-Za-z0-9+/=]+", response.text)
        assert match, "the create page must offer a generated deploy key"
        keys.append(match.group(0))
    assert keys[0] != keys[1], "every visit must generate a fresh keypair"

    response = requests.get(f"{DOJO_URL}/dojos/create", allow_redirects=False)
    assert response.status_code == 302, f"Expected 302, got {response.status_code}"
    assert "/login" in response.headers["Location"], f"Unexpected redirect {response.headers['Location']}"


def test_update_api_replaces_modules_and_challenges(admin_session):
    dojo_id = spec_id("update")
    reference_id = create_spec(admin_session, simple_spec(dojo_id, challenges=("a", "b")))
    assert module_challenges(admin_session, reference_id) == {"m": ["a", "b"]}

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update", json={
        "id": dojo_id,
        "name": "Renamed Dojo",
        "image": CHALLENGE_IMAGE,
        "modules": [
            {"id": "m", "name": "Renamed Module",
             "resources": [{"type": "challenge", "id": "a", "name": "A"}]},
            {"id": "m2", "name": "Second",
             "resources": [{"type": "challenge", "id": "c", "name": "C"}]},
        ],
    })
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"
    assert response.json()["success"] is True

    modules = get_modules(admin_session, reference_id)
    assert [module["id"] for module in modules] == ["m", "m2"]
    assert [module["name"] for module in modules] == ["Renamed Module", "Second"]
    assert [challenge["id"] for challenge in modules[0]["challenges"]] == ["a"], "removed challenges must disappear"
    assert [challenge["id"] for challenge in modules[1]["challenges"]] == ["c"]
    assert db_sql(f"SELECT name FROM dojos WHERE dojo_id = x'{dojo_hex(reference_id)}'::int").strip() == "Renamed Dojo"


def test_update_api_authorization(admin_session, random_user_session, random_user_name):
    dojo_id = spec_id("updauth")
    reference_id = create_spec(admin_session, simple_spec(dojo_id))
    spec = simple_spec(dojo_id)
    hostile_spec = {"id": dojo_id, "image": CHALLENGE_IMAGE,
                    "modules": [{"id": "hacked", "name": "Hacked", "resources": []}]}
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update"

    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
    response = random_user_session.post(url, json=hostile_spec)
    assert response.status_code == 403, f"plain members must not update a dojo, got {response.status_code}"

    response = requests.post(url, json=hostile_spec)
    assert response.status_code == 403, f"anonymous users must not update a dojo, got {response.status_code}"
    assert module_challenges(admin_session, reference_id) == {"m": ["a"]}, "a rejected update must change nothing"

    promote = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/admins/promote",
        json={"user_id": get_user_id(random_user_name)})
    assert promote.status_code == 200, f"Expected 200, got {promote.status_code} - {promote.text[:200]}"
    response = random_user_session.post(url, json=spec)
    assert response.status_code == 200, f"dojo admins may update, got {response.status_code} - {response.text[:200]}"

    db_sql(f"DELETE FROM dojo_users WHERE dojo_id = x'{dojo_hex(reference_id)}'::int "
           f"AND user_id = {get_user_id('admin')}")
    response = admin_session.post(url, json=spec)
    assert response.status_code == 200, \
        f"site admins may update a dojo they do not own, got {response.status_code} - {response.text[:200]}"


def test_update_api_empty_body_rejected(admin_session):
    dojo_id = spec_id("updempty")
    reference_id = create_spec(admin_session, simple_spec(dojo_id))

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update", json={})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert response.json() == {"success": False, "error": "Missing dojo spec."}
    assert module_challenges(admin_session, reference_id) == {"m": ["a"]}


def test_update_api_invalid_spec_rolls_back(admin_session):
    dojo_id = spec_id("updbad")
    reference_id = create_spec(admin_session, simple_spec(dojo_id))

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update", json={
        "id": dojo_id,
        "image": CHALLENGE_IMAGE,
        "modules": [{"id": "m", "resources": [{"type": "challenge"}]}],
    })
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert response.json()["success"] is False

    malformed = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update",
        json=["not-a-dojo-spec"],
    )
    assert malformed.status_code == 400, \
        f"Expected malformed structure to return 400, got {malformed.status_code} - {malformed.text[:300]}"
    assert "has no attribute" not in malformed.json()["error"], malformed.json()

    assert module_challenges(admin_session, reference_id) == {"m": ["a"]}, \
        "a rejected update must leave the previous challenges in place"
    assert dojo_row_count(reference_id, "dojo_challenges") == 1


def test_update_api_renames_dojo_id(admin_session):
    dojo_id = spec_id("renamesrc")
    reference_id = create_spec(admin_session, simple_spec(dojo_id))
    renamed_id = spec_id("renamedst")

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update",
                                  json=simple_spec(renamed_id))
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"

    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 404, \
        "the old reference id must stop resolving after a rename"
    new_reference_id = f"{renamed_id}~{dojo_hex(reference_id)}"
    assert admin_session.get(f"{DOJO_URL}/{new_reference_id}/").status_code == 200
    assert dojos_named(renamed_id) == 1 and dojos_named(dojo_id) == 0


def test_update_api_enqueues_image_pulls(admin_session):
    dojo_id = spec_id("updpull")
    reference_id = create_spec(admin_session, simple_spec(dojo_id))

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update", json={
        "id": dojo_id,
        "type": "public",
        "modules": [{"id": "m", "resources": [
            {"type": "challenge", "id": "a", "name": "A", "image": CHALLENGE_IMAGE},
            {"type": "challenge", "id": "hello-world", "name": "Hello World", "image": "hello-world"},
        ]}],
    })
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"

    deadline = time.monotonic() + 45
    while True:
        try:
            start_challenge(reference_id, "m", "hello-world", session=admin_session)
            break
        except AssertionError:
            assert time.monotonic() < deadline, "the update never pulled the newly referenced image"
            time.sleep(2)
    remove_workspace_container("admin")


def test_update_code_pull_succeeds_unauthenticated(example_dojo):
    code = db_sql(f"SELECT update_code FROM dojos WHERE dojo_id = {dojo_db_id(example_dojo)}").strip()

    response = requests.post(f"{DOJO_URL}/dojo/{example_dojo}/update/{code}")
    assert response.status_code == 200, f"the webhook must bypass CSRF, got {response.status_code}"
    assert response.json() == {"success": True}

    assert requests.get(f"{DOJO_URL}/{example_dojo}/").status_code == 200
    assert [module["id"] for module in get_modules(requests, example_dojo)][:2] == ["hello", "world"]


def test_update_code_wrong_or_missing_forbidden(example_dojo):
    response = requests.post(f"{DOJO_URL}/dojo/{example_dojo}/update/deadbeef")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Forbidden"}

    response = requests.post(f"{DOJO_URL}/dojo/{example_dojo}/update/")
    assert response.status_code in {404, 405}, f"Expected no code-less update route, got {response.status_code}"

    response = requests.post(f"{DOJO_URL}/dojo/no-such-dojo-{rand()}/update/whatever")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Not Found"}


def test_update_code_on_spec_dojo_fails_gracefully(admin_session):
    reference_id = create_spec(admin_session, simple_spec(spec_id("specpull")))
    code = db_sql(f"SELECT update_code FROM dojos WHERE dojo_id = {dojo_db_id(reference_id)}").strip()

    response = requests.post(f"{DOJO_URL}/dojo/{reference_id}/update/{code}")
    assert response.status_code == 400, \
        f"a spec dojo has no repository to pull, expected a clean 400, got {response.status_code}"
    assert response.json()["success"] is False

    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
    assert module_challenges(admin_session, reference_id) == {"m": ["a"]}


def test_delete_removes_dojo_memberships_and_challenges(admin_session, random_user_session):
    reference_id = create_spec(admin_session, simple_spec(spec_id("delete")))
    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
    assert dojo_row_count(reference_id, "dojo_users") == 2, "the creator and the member both have rows"

    response = admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={})
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"
    assert response.json()["success"] is True

    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 404
    for table in ["dojos", "dojo_users", "dojo_modules", "dojo_challenges"]:
        assert dojo_row_count(reference_id, table) == 0, f"{table} rows survived the delete"


def test_delete_denied_to_dojo_admin(admin_session, random_user_session, random_user_name):
    reference_id = create_spec(admin_session, simple_spec(spec_id("delperm")))
    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
    promote = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/admins/promote",
        json={"user_id": get_user_id(random_user_name)})
    assert promote.status_code == 200, f"Expected 200, got {promote.status_code}"

    response = random_user_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={})
    assert response.status_code == 403, f"dojo admins must not delete dojos, got {response.status_code}"
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
    assert dojo_row_count(reference_id) == 1


def test_delete_denied_anonymous_and_unknown_404(admin_session):
    reference_id = create_spec(admin_session, simple_spec(spec_id("delanon")))

    response = requests.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={})
    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    assert dojo_row_count(reference_id) == 1
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200

    response = admin_session.post(f"{DOJO_URL}/dojo/no-such-dojo-{rand()}/delete/", json={})
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Not Found"}


def test_promote_official_effects(admin_session):
    dojo_id = spec_id("promote")
    reference_id = create_spec(admin_session, simple_spec(dojo_id, type="topic"))

    assert not any(listed.startswith(dojo_id) for listed in listed_dojo_ids(requests)), \
        "an unofficial private dojo must not be publicly listed"
    assert requests.get(f"{DOJO_URL}/{dojo_id}/").status_code == 404

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/promote", json={})
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"
    assert response.json() == {"success": True}

    assert db_sql(f"SELECT official FROM dojos WHERE dojo_id = x'{dojo_hex(reference_id)}'::int").strip() == "t"
    listing = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos").json()["dojos"]
    promoted = next((dojo for dojo in listing if dojo["id"] == dojo_id), None)
    assert promoted is not None, "an official dojo is listed by its bare id"
    assert promoted["official"] is True
    assert requests.get(f"{DOJO_URL}/{dojo_id}/").status_code == 200


def test_promote_official_requires_site_admin(admin_session, random_user_session, random_user_name):
    dojo_id = spec_id("promoperm")
    reference_id = create_spec(admin_session, simple_spec(dojo_id, type="topic"))
    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
    promote = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/admins/promote",
        json={"user_id": get_user_id(random_user_name)})
    assert promote.status_code == 200, f"Expected 200, got {promote.status_code}"

    response = random_user_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/promote", json={}, allow_redirects=False)
    assert response.status_code in (302, 403), \
        f"dojo admins must not promote their dojo to official, got {response.status_code}"

    assert db_sql(f"SELECT official FROM dojos WHERE dojo_id = x'{dojo_hex(reference_id)}'::int").strip() == "f"
    assert requests.get(f"{DOJO_URL}/{dojo_id}/").status_code == 404


def test_promote_admin_grants_admin_powers(admin_session, random_user_session, random_user_name):
    dojo_id = spec_id("adminpromo")
    reference_id = create_spec(admin_session, simple_spec(dojo_id))
    user_id = get_user_id(random_user_name)

    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/admin/").status_code == 403
    assert dojo_user_type(reference_id, user_id) == "member"

    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/admins/promote", json={"user_id": user_id})
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"
    assert response.json() == {"success": True}

    assert dojo_user_type(reference_id, user_id) == "admin"
    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/admin/").status_code == 200
    response = random_user_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/update", json=simple_spec(dojo_id))
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:200]}"


def test_promote_admin_validation_errors(admin_session):
    reference_id = create_spec(admin_session, simple_spec(spec_id("promoval")))
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/admins/promote"

    response = admin_session.post(url, json={})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert response.json() == {"success": False, "error": "User not specified."}

    outsider_name, _ = new_user()
    outsider_id = get_user_id(outsider_name)
    response = admin_session.post(url, json={"user_id": outsider_id})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:300]}"
    assert response.json() == {"success": False, "error": "User is not currently a dojo member."}
    assert int(db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id = x'{dojo_hex(reference_id)}'::int "
                      f"AND user_id = {outsider_id}")) == 0, "a failed promotion must not create a membership"


def test_promote_admin_authorization(admin_session):
    reference_id = create_spec(admin_session, simple_spec(spec_id("promoauth")))
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/admins/promote"

    users = {}
    for role in ["a", "b", "c"]:
        name, session = new_user()
        assert session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
        users[role] = (name, session, get_user_id(name))

    assert admin_session.post(url, json={"user_id": users["a"][2]}).status_code == 200

    response = users["a"][1].post(url, json={"user_id": users["b"][2]})
    assert response.status_code == 200, f"dojo admins may promote, got {response.status_code} - {response.text[:200]}"
    assert dojo_user_type(reference_id, users["b"][2]) == "admin"

    response = users["c"][1].post(url, json={"user_id": users["b"][2]})
    assert response.status_code == 403, f"plain members must not promote, got {response.status_code}"
    assert dojo_user_type(reference_id, users["b"][2]) == "admin"
    assert dojo_user_type(reference_id, users["c"][2]) == "member"


def test_join_password_enforced(admin_session, random_user_session, random_user_name):
    reference_id = create_spec(admin_session, simple_spec(
        spec_id("password"), type="public", password="hunter2hunter2"))
    user_id = get_user_id(random_user_name)

    def membership_count():
        return int(db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id = x'{dojo_hex(reference_id)}'::int "
                          f"AND user_id = {user_id}"))

    assert reference_id not in listed_dojo_ids(random_user_session), \
        "a password-protected public dojo is not viewable before joining"

    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 403
    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/wrongpass").status_code == 403
    assert membership_count() == 0, "a refused join must not create a membership"

    assert random_user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/hunter2hunter2").status_code == 200
    assert membership_count() == 1
    assert reference_id in listed_dojo_ids(random_user_session)


def test_join_private_dojo_by_reference_id(random_private_dojo, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/{random_private_dojo}/").status_code == 404
    assert random_user_session.get(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{random_private_dojo}/modules").status_code == 404

    assert random_user_session.get(f"{DOJO_URL}/dojo/{random_private_dojo}/join/").status_code == 200

    assert random_user_session.get(f"{DOJO_URL}/{random_private_dojo}/").status_code == 200
    assert random_user_session.get(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{random_private_dojo}/modules").status_code == 200


def test_join_does_not_demote_existing_admin(admin_session):
    reference_id = create_spec(admin_session, simple_spec(spec_id("joinadmin")))
    admin_id = get_user_id("admin")

    assert admin_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200

    assert dojo_user_type(reference_id, admin_id) == "admin", "joining must not demote a dojo admin"
    assert int(db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id = x'{dojo_hex(reference_id)}'::int "
                      f"AND user_id = {admin_id}")) == 1
    assert admin_session.get(f"{DOJO_URL}/dojo/{reference_id}/admin/").status_code == 200


def test_admin_page_authorization(public_dojo, random_private_dojo, admin_session, random_user_session):
    assert admin_session.get(f"{DOJO_URL}/dojo/{public_dojo}/admin/").status_code == 200

    assert random_user_session.get(f"{DOJO_URL}/dojo/{public_dojo}/join/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/dojo/{public_dojo}/admin/").status_code == 403
    assert requests.get(f"{DOJO_URL}/dojo/{public_dojo}/admin/").status_code == 403

    assert random_user_session.get(f"{DOJO_URL}/dojo/{random_private_dojo}/admin/").status_code == 404, \
        "a non-member must not learn that a private dojo exists"


def test_admin_page_renders_for_spec_dojo(admin_session, public_dojo):
    response = admin_session.get(f"{DOJO_URL}/dojo/{public_dojo}/admin/")
    assert response.status_code == 200, \
        f"the admin page must render for a dojo with no repository, got {response.status_code}"
    assert public_dojo in response.text, "the admin page reports the dojo's reference id"
    assert "Deploy Key" not in response.text, "a spec dojo has no deploy key to show"


def test_admin_page_exposes_deploy_key_only_to_admins(admin_session, random_user_session, example_dojo):
    public_key = db_sql(
        f"SELECT public_key FROM dojos WHERE dojo_id = {dojo_db_id(example_dojo)}").strip()
    assert public_key, "the example dojo has a deploy key"

    response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert response.status_code == 200
    assert "Deploy Key" in response.text and public_key in response.text

    assert random_user_session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
    response = random_user_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    assert public_key not in response.text
    assert public_key not in random_user_session.get(f"{DOJO_URL}/{example_dojo}/").text


def test_activity_page_authorization(public_dojo, random_private_dojo, admin_session, random_user_session):
    assert admin_session.get(f"{DOJO_URL}/dojo/{public_dojo}/admin/activity").status_code == 200

    assert random_user_session.get(f"{DOJO_URL}/dojo/{public_dojo}/join/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/dojo/{public_dojo}/admin/activity").status_code == 403
    assert requests.get(f"{DOJO_URL}/dojo/{public_dojo}/admin/activity").status_code == 403
    assert random_user_session.get(f"{DOJO_URL}/dojo/{random_private_dojo}/admin/activity").status_code == 404


def test_activity_page_reports_running_containers(example_dojo, admin_session, random_user, random_user_name):
    _, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/activity")
    assert response.status_code == 200
    assert random_user_name not in response.text, "a user with no container is not active"

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/activity")
        assert response.status_code == 200
        assert random_user_name in response.text, "the activity page must report users running challenges"
    finally:
        remove_workspace_container(random_user_name)


def test_solves_export_code_required(example_dojo):
    response = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{'0' * 32}/csv")
    assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Forbidden"}
    assert "user_id,module,challenge" not in response.text, "a refused export must not leak solve data"

    response = requests.get(f"{DOJO_URL}/dojo/no-such-dojo-{rand()}/solves/whatever/csv")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Not Found"}


def test_solves_export_spec_dojo_no_500(admin_session, public_dojo):
    for url in [f"{DOJO_URL}/dojo/{public_dojo}/solves/",
                f"{DOJO_URL}/dojo/{public_dojo}/solves/anything/csv"]:
        response = requests.get(url)
        assert response.status_code in (403, 404), \
            f"a dojo with no private key must refuse cleanly, got {response.status_code} for {url}"


def test_solves_export_hidden_user_visibility(example_dojo, admin_session):
    name, session = new_user()
    user_id = get_user_id(name)
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    export_url = f"{DOJO_URL}/dojo/{example_dojo}/solves/{solves_code(example_dojo)}/json"

    def exported_user_ids():
        response = requests.get(export_url)
        assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:200]}"
        return [row["user_id"] for row in response.json()]

    try:
        assert user_id in exported_user_ids(), "a visible solver appears in the export"

        db_sql(f"UPDATE users SET hidden = true WHERE id = {user_id}")
        assert user_id not in exported_user_ids(), "a hidden non-member must be filtered out of the export"

        assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200
        assert user_id in exported_user_ids(), "a hidden dojo member is still exported"
    finally:
        db_sql(f"UPDATE users SET hidden = false WHERE id = {user_id}")

def test_admin_dojos_page_authorization(random_private_dojo, admin_session, random_user_session):
    response = admin_session.get(f"{DOJO_URL}/admin/dojos")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert random_private_dojo in response.text, "the admin listing includes unofficial private dojos"

    for session in [random_user_session, requests]:
        response = session.get(f"{DOJO_URL}/admin/dojos", allow_redirects=False)
        assert response.status_code in (302, 403), f"Expected 302/403, got {response.status_code}"
        if response.status_code == 302:
            assert "/login" in response.headers["Location"], f"Unexpected redirect {response.headers['Location']}"
        assert random_private_dojo not in response.text


def test_challenge_description_api(description_dojo, random_user_session):
    base = f"{DOJO_URL}/pwncollege_api/v1/dojos/{description_dojo}"

    response = random_user_session.get(f"{base}/m/a/description")
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:200]}"
    assert response.json()["success"] is True
    assert "<strong>flag</strong>" in response.json()["description"], \
        f"the description must be rendered markdown: {response.json()['description'][:200]}"

    response = random_user_session.get(f"{base}/m/no-such-challenge/description")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    assert response.json()["error"] == "Invalid challenge id"

    assert random_user_session.get(f"{base}/no-such-module/a/description").status_code == 404


def test_challenge_description_requires_auth(description_dojo):
    response = requests.get(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{description_dojo}/m/a/description", allow_redirects=False)
    assert response.status_code in (302, 403), f"Expected 302/403, got {response.status_code}"
    assert "<strong>flag</strong>" not in response.text, "an unauthenticated caller learns nothing"


def test_per_user_solves_api_user_resolution(example_dojo):
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves"

    response = requests.get(url)
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:200]}"
    assert response.json()["error"] == "User not found"

    response = requests.get(url, params={"username": f"no-such-user-{rand()}"})
    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    assert response.json()["error"] == "User not found"

    name, session = new_user()
    user_id = get_user_id(name)
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    try:
        response = requests.get(url, params={"username": name})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert [solve["challenge_id"] for solve in response.json()["solves"]] == ["apple"]

        db_sql(f"UPDATE users SET hidden = true WHERE id = {user_id}")
        response = requests.get(url, params={"username": name})
        assert response.status_code == 400, f"a hidden user must not be resolvable, got {response.status_code}"
        assert response.json()["error"] == "User not found"
    finally:
        db_sql(f"UPDATE users SET hidden = false WHERE id = {user_id}")
