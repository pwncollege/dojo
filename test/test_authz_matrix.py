import datetime
import json
import random
import re
import string

import pytest
import requests

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    challenge_db_id,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    get_outer_container_for,
    get_user_id,
    login,
    parse_csrf_token,
    remove_workspace_container,
    start_challenge,
)

#pylint:disable=redefined-outer-name

BAD_JSON = dict(data="", headers={"Content-Type": "application/json"})
NO_CSRF = {"CSRF-Token": None}


def clear_ratelimit(endpoint_fragment):
    """The whole suite shares one client IP, so a neighbouring test file can exhaust an endpoint's ratelimit."""
    scan = dojo_run("docker", "exec", "cache", "redis-cli", "--scan", "--pattern", "flask_cache_rl:*", check=False)
    keys = [key for key in scan.stdout.split() if endpoint_fragment in key]
    if keys:
        dojo_run("docker", "exec", "cache", "redis-cli", "DEL", *keys, check=False)


def anonymous_session(*, with_csrf=False):
    session = requests.Session()
    if with_csrf:
        session.headers["CSRF-Token"] = parse_csrf_token(session.get(f"{DOJO_URL}/login").text)
    return session


def make_dojo(admin_session, yml_name, dojo_id):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = (TEST_DOJOS_LOCATION / yml_name).read_text().replace(f"id: {dojo_id}\n", f"id: {dojo_id}-{suffix}\n", 1)
    return create_dojo_yml(spec, session=admin_session)


def count_rows(table, where):
    return int(db_sql(f"SELECT count(*) FROM {table} WHERE {where}"))


@pytest.fixture(scope="module")
def authz_dojo(admin_session):
    reference_id = make_dojo(admin_session, "authz_matrix.yml", "authz-matrix")
    db_id = dojo_db_id(reference_id)
    data = json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id = {db_id}"))
    data["permissions"] = ["grant_awards"]
    db_sql(f"UPDATE dojos SET data = '{json.dumps(data)}' WHERE dojo_id = {db_id}")
    return reference_id


@pytest.fixture(scope="module")
def authz_private_dojo(admin_session):
    return make_dojo(admin_session, "authz_matrix_private.yml", "authz-matrix-private")


@pytest.fixture(scope="module")
def container_user(example_dojo):
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(name, name, register=True)
    start_challenge(example_dojo, "hello", "apple", session=session)
    yield name, session
    remove_workspace_container(name)


def survey_url(dojo, module, challenge):
    return f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/surveys"


def survey_response_count(dojo, module, challenge, user_name=None):
    where = f"challenge_id = {challenge_db_id(dojo, module, challenge)}"
    if user_name:
        where += f" AND user_id = {get_user_id(user_name)}"
    return count_rows("survey_responses", where)


def join(session, dojo):
    response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200, f"Expected to join {dojo}, but got {response.status_code}"


def test_survey_post_requires_auth(authz_dojo):
    clear_ratelimit("dojo_survey")
    url = survey_url(authz_dojo, "surveyed", "surveyed-challenge")
    before = survey_response_count(authz_dojo, "surveyed", "surveyed-challenge")

    no_csrf = anonymous_session()
    with_csrf = anonymous_session(with_csrf=True)

    for label, response in [
        ("json without csrf", no_csrf.post(url, json={"response": "x"}, allow_redirects=False)),
        ("json with csrf", with_csrf.post(url, json={"response": "x"}, allow_redirects=False)),
        ("bodyless", with_csrf.post(url, data="", allow_redirects=False)),
        ("form encoded", with_csrf.post(url, data={"response": "x"}, allow_redirects=False)),
    ]:
        assert response.status_code == 403, \
            f"Anonymous survey POST ({label}) should be 403, but got {response.status_code}"

    assert survey_response_count(authz_dojo, "surveyed", "surveyed-challenge") == before, \
        "Anonymous survey POSTs must not store a survey response"


def test_survey_post_missing_response(authz_dojo, random_user):
    clear_ratelimit("dojo_survey")
    name, session = random_user
    join(session, authz_dojo)
    url = survey_url(authz_dojo, "surveyed", "surveyed-challenge")

    for body in [{}, {"answer": "x"}]:
        response = session.post(url, json=body)
        assert response.status_code == 400, f"Expected 400 for body {body}, but got {response.status_code}"
        assert response.json() == {"success": False, "error": "Missing response"}, \
            f"Unexpected error payload for body {body}: {response.json()}"

    assert survey_response_count(authz_dojo, "surveyed", "surveyed-challenge", name) == 0, \
        "A survey POST without a 'response' key must not store anything"


def test_survey_post_missing_survey_and_success(authz_dojo, random_user):
    clear_ratelimit("dojo_survey")
    name, session = random_user
    join(session, authz_dojo)

    response = session.post(survey_url(authz_dojo, "plain", "plain-challenge"), json={"response": "x"})
    assert response.status_code == 404, \
        f"Expected 404 for a challenge with no survey, but got {response.status_code}"
    assert response.json() == {"success": False, "error": "Survey not found"}, \
        f"Unexpected error payload: {response.json()}"

    response = session.post(survey_url(authz_dojo, "surveyed", "surveyed-challenge"), json={"response": "x"})
    assert response.status_code == 200, f"Expected 200 for a survey-bearing challenge, but got {response.status_code}"
    assert response.json()["success"], f"Expected a successful survey submission: {response.json()}"

    assert survey_response_count(authz_dojo, "plain", "plain-challenge", name) == 0, \
        "The survey-less challenge must have stored nothing"
    assert survey_response_count(authz_dojo, "surveyed", "surveyed-challenge", name) == 1, \
        "The survey-bearing challenge must have stored exactly one response"


def test_survey_post_unknown_or_invisible_challenge(authz_dojo, random_user, admin_session):
    clear_ratelimit("dojo_survey")
    name, session = random_user
    join(session, authz_dojo)

    for label, url in [
        ("nonexistent challenge", survey_url(authz_dojo, "surveyed", "no-such-challenge")),
        ("not-yet-visible challenge", survey_url(authz_dojo, "surveyed", "hidden-challenge")),
    ]:
        response = session.post(url, json={"response": "x"})
        assert response.status_code == 404, f"Expected 404 for {label}, but got {response.status_code}"
        assert response.json() == {"success": False, "error": "Challenge not found"}, \
            f"Unexpected error payload for {label}: {response.json()}"

    admin_response = admin_session.post(survey_url(authz_dojo, "surveyed", "hidden-challenge"), json={"response": "x"})
    assert admin_response.status_code == 404, \
        f"Survey visibility has no admin bypass, expected 404 but got {admin_response.status_code}"

    assert survey_response_count(authz_dojo, "surveyed", "hidden-challenge") == 0, \
        "An invisible challenge must never accumulate survey responses"


def test_survey_post_malformed_body(authz_dojo, random_user):
    clear_ratelimit("dojo_survey")
    name, session = random_user
    join(session, authz_dojo)
    url = survey_url(authz_dojo, "surveyed", "surveyed-challenge")

    undecodable = session.post(url, **BAD_JSON)
    assert 400 <= undecodable.status_code < 500, \
        f"An undecodable JSON body must be a client error, but got {undecodable.status_code}"

    form_encoded = session.post(url, data="response=x")
    assert 400 <= form_encoded.status_code < 500, \
        f"A form-encoded body must be a client error, but got {form_encoded.status_code}"

    assert survey_response_count(authz_dojo, "surveyed", "surveyed-challenge", name) == 0, \
        "A malformed survey POST must not store a survey response"


def test_promote_admin_rejects_anonymous_and_nonmember(authz_dojo, authz_private_dojo, random_user):
    name, session = random_user
    join(session, authz_dojo)
    join(session, authz_private_dojo)
    user_id = get_user_id(name)
    anonymous = anonymous_session(with_csrf=True)

    public_anon = anonymous.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/admins/promote", json={"user_id": user_id}
    )
    assert public_anon.status_code == 403, \
        f"Anonymous promote on a viewable dojo should be 403, but got {public_anon.status_code}"

    private_anon = anonymous.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_private_dojo}/admins/promote", json={"user_id": user_id}
    )
    assert private_anon.status_code == 404, \
        f"Anonymous promote on a private dojo must not disclose it, expected 404 but got {private_anon.status_code}"

    nonmember_name = "".join(random.choices(string.ascii_lowercase, k=16))
    nonmember_session = login(nonmember_name, nonmember_name, register=True)
    private_nonmember = nonmember_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_private_dojo}/admins/promote", json={"user_id": user_id}
    )
    assert private_nonmember.status_code == 404, \
        f"Non-member promote on a private dojo should be 404, but got {private_nonmember.status_code}"
    assert authz_private_dojo.split("~")[0] not in private_nonmember.text, \
        "The 404 body must not disclose the private dojo"

    for dojo in [authz_dojo, authz_private_dojo]:
        types = db_sql(f"SELECT type FROM dojo_users WHERE dojo_id = {dojo_db_id(dojo)} AND user_id = {user_id}").split()
        assert types == ["member"], f"Expected {name} to still be a member of {dojo}, but got {types}"


def test_promote_admin_rejects_malformed_input(authz_dojo, random_user, admin_session):
    name, session = random_user
    join(session, authz_dojo)
    user_id = get_user_id(name)
    db_id = dojo_db_id(authz_dojo)
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/admins/promote"
    admins_before = count_rows("dojo_users", f"dojo_id = {db_id} AND type = 'admin'")

    non_integer = admin_session.post(url, json={"user_id": "notanint"})
    assert 400 <= non_integer.status_code < 500, \
        f"A non-integer user_id must be a client error, but got {non_integer.status_code}"
    assert not non_integer.json()["success"], f"Unexpected success payload: {non_integer.json()}"

    undecodable = admin_session.post(url, **BAD_JSON)
    assert 400 <= undecodable.status_code < 500, \
        f"An undecodable JSON body must be a client error, but got {undecodable.status_code}"

    assert count_rows("dojo_users", f"dojo_id = {db_id} AND type = 'admin'") == admins_before, \
        "Malformed promote requests must not change the dojo's admin set"
    assert db_sql(f"SELECT type FROM dojo_users WHERE dojo_id = {db_id} AND user_id = {user_id}").split() == ["member"], \
        "Malformed promote requests must not promote the target user"

    valid = admin_session.post(url, json={"user_id": user_id})
    assert valid.status_code == 200, f"Expected the following valid promote to succeed, but got {valid.status_code}"
    assert db_sql(f"SELECT type FROM dojo_users WHERE dojo_id = {db_id} AND user_id = {user_id}").split() == ["admin"], \
        "A valid promote after a malformed one must still take effect"


def test_grant_award_non_integer_user_id_is_client_error(authz_dojo, admin_session):
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/award/grant",
        json={"user_id": "notanint", "emoji": "\U0001f600", "description": "authz-matrix-bad"},
    )
    assert 400 <= response.status_code < 500, \
        f"A non-integer user_id must be a client error, but got {response.status_code}"


def test_grant_award_malformed_user_id_grants_nothing(authz_dojo, random_user, admin_session):
    name, session = random_user
    join(session, authz_dojo)
    user_id = get_user_id(name)
    category = authz_dojo.split("~")[1]
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/award/grant"
    awards_before = count_rows("awards", f"category = '{category}'")

    admin_session.post(url, json={"user_id": "notanint", "emoji": "\U0001f600", "description": "authz-matrix-bad"})
    assert count_rows("awards", f"category = '{category}'") == awards_before, \
        "A malformed grant must not create an award"

    valid = admin_session.post(
        url, json={"user_id": user_id, "emoji": "\U0001f600", "description": "authz-matrix-good"}
    )
    assert valid.status_code == 200, f"Expected the following valid grant to succeed, but got {valid.status_code}"
    assert count_rows("awards", f"category = '{category}' AND user_id = {user_id}") == 1, \
        "A valid grant after a malformed one must still create exactly one award"


def test_promote_official_requires_site_admin(authz_dojo, random_user, admin_session):
    _, session = random_user

    unknown = session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/definitely-not-a-dojo/promote", json={})
    real = session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/promote", json={})
    assert unknown.status_code == 403, f"Expected 403 for a non-admin promote, but got {unknown.status_code}"
    assert real.status_code == 403, f"Expected 403 for a non-admin promote, but got {real.status_code}"
    assert unknown.text == real.text, "A non-admin must not be able to tell a real dojo from a nonexistent one"

    admin_unknown = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/definitely-not-a-dojo/promote", json={})
    assert admin_unknown.status_code == 404, \
        f"Expected 404 when a site admin promotes an unknown dojo, but got {admin_unknown.status_code}"

    official = db_sql(f"SELECT official FROM dojos WHERE dojo_id = {dojo_db_id(authz_dojo)}").strip()
    assert official == "f", f"The rejected promote must leave the dojo unofficial, but official is {official!r}"


def test_create_dojo_malformed_body(admin_session):
    marker = "authz-matrix-form-" + "".join(random.choices(string.ascii_lowercase, k=8))

    undecodable = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", **BAD_JSON)
    assert 400 <= undecodable.status_code < 500, \
        f"An undecodable JSON body must be a client error, but got {undecodable.status_code}"
    assert not undecodable.json()["success"], f"Unexpected payload: {undecodable.json()}"

    form_encoded = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/create",
        data={"nonce": admin_session.headers["CSRF-Token"], "spec": f"id: {marker}\n"},
    )
    assert 400 <= form_encoded.status_code < 500, \
        f"A form-encoded body must be a client error, but got {form_encoded.status_code}"

    assert count_rows("dojos", f"id = '{marker}'") == 0, \
        "A malformed create request must not create a dojo"


def test_update_api_malformed_body(authz_dojo, admin_session):
    modules_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/modules"
    before = admin_session.get(modules_url).json()

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/update", **BAD_JSON)
    assert 400 <= response.status_code < 500, \
        f"An undecodable JSON body must be a client error, but got {response.status_code}"

    assert admin_session.get(modules_url).json() == before, \
        "A rejected update must leave the dojo's modules and challenges untouched"


def test_workspace_tokens_require_auth():
    url = f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens"
    anonymous = anonymous_session(with_csrf=True)

    json_get = anonymous.get(url, headers={"Content-Type": "application/json"}, allow_redirects=False)
    assert json_get.status_code == 403, f"Expected 403 for an anonymous JSON GET, but got {json_get.status_code}"
    assert not re.search(r"workspace_[0-9a-f]{64}", json_get.text), "The rejection must not disclose any token value"

    plain_get = anonymous.get(url, allow_redirects=False)
    assert plain_get.status_code == 302, f"Expected a login redirect, but got {plain_get.status_code}"
    assert "/login" in plain_get.headers["Location"], f"Expected a /login redirect, got {plain_get.headers['Location']}"

    post = anonymous.post(url, json={}, allow_redirects=False)
    assert post.status_code == 403, f"Expected 403 for an anonymous POST, but got {post.status_code}"

    assert count_rows("workspace_tokens", "user_id IS NULL") == 0, \
        "Anonymous workspace token requests must not mint an ownerless token"


def test_workspace_token_malformed_expiration(random_user):
    name, session = random_user
    url = f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens"
    user_id = get_user_id(name)

    for expiration in ["garbage", "2026-13-45"]:
        response = session.post(url, json={"expiration": expiration})
        assert 400 <= response.status_code < 500, \
            f"Expiration {expiration!r} must be a client error, but got {response.status_code}"
        assert not response.json()["success"], f"Unexpected success payload: {response.json()}"

    assert count_rows("workspace_tokens", f"user_id = {user_id}") == 0, \
        "A rejected expiration must not mint a token"
    assert session.get(url).json()["data"] == [], "A rejected expiration must not appear in the token listing"

    valid = session.post(url, json={"expiration": "2030-01-01"})
    assert valid.status_code == 200, f"Expected the valid expiration to succeed, but got {valid.status_code}"
    assert valid.json()["data"]["expiration"].startswith("2030-01-01"), \
        f"Expected an expiration on 2030-01-01, got {valid.json()['data']['expiration']}"
    assert count_rows("workspace_tokens", f"user_id = {user_id}") == 1, \
        "The valid request must mint exactly one token"


def test_workspace_token_create_malformed_body(random_user):
    name, session = random_user
    url = f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens"
    user_id = get_user_id(name)

    response = session.post(url, **BAD_JSON)
    assert response.status_code < 500, \
        f"An undecodable JSON body must not crash the server, but got {response.status_code}"

    tokens = session.get(url).json()["data"]
    assert count_rows("workspace_tokens", f"user_id = {user_id}") == len(tokens), \
        "The token listing must match the tokens actually stored for the user"
    for token in tokens:
        datetime.datetime.fromisoformat(token["expiration"])


def test_workspace_api_non_numeric_user_param(random_user, admin_session):
    _, session = random_user

    as_user = session.get(f"{DOJO_URL}/pwncollege_api/v1/workspace?user=abc&password=x")
    assert 400 <= as_user.status_code < 500, \
        f"A non-numeric user param must be a client error, but got {as_user.status_code}"
    assert "iframe_src" not in as_user.text, "A rejected workspace request must not return an iframe_src"

    as_admin = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/workspace?user=abc")
    assert 400 <= as_admin.status_code < 500, \
        f"A non-numeric user param must be a client error for admins too, but got {as_admin.status_code}"


def test_workspace_api_unknown_user_is_not_an_oracle(random_user, admin_session, admin_user):
    _, session = random_user
    admin_name, _ = admin_user
    url = f"{DOJO_URL}/pwncollege_api/v1/workspace"

    admin_unknown = admin_session.get(f"{url}?user=999999999")
    assert admin_unknown.status_code == 404, \
        f"A site admin asking for a nonexistent user should get 404, but got {admin_unknown.status_code}"

    user_unknown = session.get(f"{url}?user=999999999")
    user_existing = session.get(f"{url}?user={get_user_id(admin_name)}")
    assert user_unknown.status_code == 403, \
        f"A non-admin must be rejected before the lookup, expected 403 but got {user_unknown.status_code}"
    assert user_existing.status_code == 403, \
        f"A non-admin must be rejected before the lookup, expected 403 but got {user_existing.status_code}"
    assert user_unknown.text == user_existing.text, \
        "A non-admin must not be able to tell an existing user id from a nonexistent one"


def test_workspace_api_port_param(container_user):
    _, session = container_user
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/workspace?port=8080")
    assert response.status_code == 200, f"Expected 200 for a valid port, but got {response.status_code}"
    assert response.json()["iframe_src"].endswith("/8080/"), \
        f"Expected the proxy url to end in the requested port, got {response.json()['iframe_src']}"


@pytest.mark.parametrize("port", ["../../etc", "8080/../../x"])
def test_workspace_api_port_param_rejects_traversal(container_user, port):
    _, session = container_user
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/workspace", params={"port": port})
    if response.status_code == 200:
        assert ".." not in response.json().get("iframe_src", ""), \
            f"The proxy url must not contain path traversal: {response.json().get('iframe_src')}"
    assert 400 <= response.status_code < 500, \
        f"A non-integer port must be a client error, but got {response.status_code}"


def test_active_module_requires_auth(container_user):
    name, session = container_user
    anonymous = anonymous_session()

    redirected = anonymous.get(f"{DOJO_URL}/active-module", allow_redirects=False)
    assert redirected.status_code == 302, f"Expected a login redirect, but got {redirected.status_code}"
    assert "/login" in redirected.headers["Location"], \
        f"Expected a /login redirect, got {redirected.headers['Location']}"
    assert "challenge_name" not in redirected.text, "The redirect must not leak any challenge data"

    as_json = anonymous.get(f"{DOJO_URL}/active-module", headers={"Content-Type": "application/json"})
    assert as_json.status_code == 403, f"Expected 403 for an anonymous JSON request, but got {as_json.status_code}"
    assert "challenge_name" not in as_json.text, "The rejection must not leak any challenge data"

    owner = session.get(f"{DOJO_URL}/active-module")
    assert owner.status_code == 200, f"Expected the container owner to get 200, but got {owner.status_code}"
    assert owner.json()["c_current"]["challenge_reference_id"] == "apple", \
        f"Expected the owner's active challenge, got {owner.json()['c_current']}"


def test_docker_get_delete_next_require_auth(container_user):
    name, session = container_user
    url = f"{DOJO_URL}/pwncollege_api/v1/docker"
    anonymous = anonymous_session(with_csrf=True)

    for label, response in [
        ("GET", anonymous.get(url, headers={"Content-Type": "application/json"})),
        ("GET next", anonymous.get(f"{url}/next", headers={"Content-Type": "application/json"})),
        ("DELETE", anonymous.delete(url, headers={"Content-Type": "application/json"})),
    ]:
        assert response.status_code == 403, f"Expected 403 for an anonymous {label}, but got {response.status_code}"
        assert "apple" not in response.text, f"The anonymous {label} rejection must not leak the running challenge"

    plain = anonymous.get(url, allow_redirects=False)
    assert plain.status_code == 302, f"Expected a login redirect, but got {plain.status_code}"
    assert "/login" in plain.headers["Location"], f"Expected a /login redirect, got {plain.headers['Location']}"

    get_outer_container_for(f"user_{get_user_id(name)}")

    owner = session.get(url)
    assert owner.status_code == 200, f"Expected the container owner to get 200, but got {owner.status_code}"
    assert owner.json()["challenge"] == "apple", f"Expected the owner's running challenge, got {owner.json()}"


def test_docker_post_malformed_body(random_user):
    name, session = random_user
    url = f"{DOJO_URL}/pwncollege_api/v1/docker"

    response = session.post(url, data="notjson", headers={"Content-Type": "application/json"})
    assert 400 <= response.status_code < 500, \
        f"An undecodable JSON body must be a client error, but got {response.status_code}"

    assert session.get(url).json() == {"success": False, "error": "No active challenge"}, \
        "A rejected docker POST must not leave an active challenge"
    with pytest.raises(RuntimeError):
        get_outer_container_for(f"user_{get_user_id(name)}")


def test_solve_missing_submission_field(authz_dojo, random_user):
    name, session = random_user
    join(session, authz_dojo)
    user_id = get_user_id(name)
    challenge_id = challenge_db_id(authz_dojo, "surveyed", "surveyed-challenge")
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/surveyed/surveyed-challenge/solve"

    for body in [{}, {"flag": "x"}]:
        response = session.post(url, json=body)
        assert 400 <= response.status_code < 500, \
            f"Expected a client error for body {body}, but got {response.status_code}"
        assert not response.json()["success"], f"Unexpected success payload for body {body}: {response.json()}"

    assert count_rows("submissions", f"user_id = {user_id} AND challenge_id = {challenge_id}") == 0, \
        "A solve without a submission must not record a submission of any type"

    incorrect = session.post(url, json={"submission": "wrong"})
    assert incorrect.status_code == 400, f"Expected 400 for a wrong flag, but got {incorrect.status_code}"
    assert incorrect.json()["status"] == "incorrect", f"Expected an incorrect status, got {incorrect.json()}"
    assert count_rows("submissions", f"user_id = {user_id} AND challenge_id = {challenge_id} AND type = 'incorrect'") == 1, \
        "The endpoint must still record real submissions after rejecting malformed ones"


def test_dojo_scoped_routes_hide_private_dojo(authz_private_dojo, random_user):
    name, session = random_user
    anonymous = anonymous_session()
    routes = [
        f"/pwncollege_api/v1/scoreboard/{authz_private_dojo}/_/0/1",
        f"/pwncollege_api/v1/scoreboard/{authz_private_dojo}/_/crews/0/1",
        f"/pwncollege_api/v1/dojos/{authz_private_dojo}/modules",
        f"/pwncollege_api/v1/dojos/{authz_private_dojo}/solves",
        f"/pwncollege_api/v1/dojos/{authz_private_dojo}/course",
        f"/pwncollege_api/v1/dojos/{authz_private_dojo}/secret-module/secret-challenge/surveys",
        f"/{authz_private_dojo}",
    ]

    for route in routes:
        for label, response in [("anonymous", anonymous.get(DOJO_URL + route)),
                                ("non-member", session.get(DOJO_URL + route))]:
            assert response.status_code == 404, \
                f"Expected 404 for a {label} on {route}, but got {response.status_code}"
            assert "Secret Module" not in response.text and "Secret Challenge" not in response.text, \
                f"The {label} 404 for {route} must not disclose the dojo's contents"

    description = f"/pwncollege_api/v1/dojos/{authz_private_dojo}/secret-module/secret-challenge/description"
    anonymous_description = anonymous.get(DOJO_URL + description, allow_redirects=False)
    assert anonymous_description.status_code == 302, \
        f"Expected an authentication redirect on the description route, but got {anonymous_description.status_code}"
    assert session.get(DOJO_URL + description).status_code == 404, \
        "A logged-in non-member must get 404 from the description route"

    join(session, authz_private_dojo)

    for route in routes:
        response = session.get(DOJO_URL + route)
        if route.endswith("/course"):
            assert response.status_code == 404 and response.json()["error"] == "This dojo is not a course", \
                f"Expected the not-a-course error once joined, but got {response.status_code} {response.text[:100]}"
            continue
        assert response.status_code == 200, \
            f"Expected 200 for a member on {route}, but got {response.status_code}"
    assert session.get(DOJO_URL + description).status_code == 200, \
        "A member must be able to read the challenge description"


def test_csrf_required_on_mutating_dojo_endpoints(authz_dojo, random_user, admin_session):
    name, session = random_user
    join(session, authz_dojo)
    user_id = get_user_id(name)
    db_id = dojo_db_id(authz_dojo)
    api = f"{DOJO_URL}/pwncollege_api/v1"
    create_marker = "authz-matrix-csrf-" + "".join(random.choices(string.ascii_lowercase, k=8))
    admins_before = count_rows("dojo_users", f"dojo_id = {db_id} AND type = 'admin'")
    awards_before = count_rows("awards", f"category = '{authz_dojo.split('~')[1]}'")

    user_requests = [
        ("POST docker", session.post(f"{api}/docker", json={"dojo": authz_dojo, "module": "surveyed", "challenge": "surveyed-challenge"}, headers=NO_CSRF)),
        ("POST survey", session.post(survey_url(authz_dojo, "surveyed", "surveyed-challenge"), json={"response": "x"}, headers=NO_CSRF)),
        ("POST solve", session.post(f"{api}/dojos/{authz_dojo}/surveyed/surveyed-challenge/solve", json={"submission": "x"}, headers=NO_CSRF)),
        ("POST ssh_key", session.post(f"{api}/ssh_key", json={"ssh_key": "ssh-rsa AAAA"}, headers=NO_CSRF)),
        ("DELETE ssh_key", session.delete(f"{api}/ssh_key", json={"ssh_key": "ssh-rsa AAAA"}, headers=NO_CSRF)),
        ("POST workspace_tokens", session.post(f"{api}/workspace_tokens", json={}, headers=NO_CSRF)),
        ("POST reset_home", session.post(f"{api}/workspace/reset_home", json={}, headers=NO_CSRF)),
        ("DELETE discord", session.delete(f"{api}/discord", json={}, headers=NO_CSRF)),
        ("PATCH course identity", session.patch(f"{DOJO_URL}/dojo/{authz_dojo}/course/identity", json={"identity": "x"}, headers=NO_CSRF)),
    ]
    admin_requests = [
        ("POST dojos/create", admin_session.post(f"{api}/dojos/create", json={"spec": f"id: {create_marker}\n"}, headers=NO_CSRF)),
        ("POST dojo update", admin_session.post(f"{api}/dojos/{authz_dojo}/update", json={"id": "nope"}, headers=NO_CSRF)),
        ("POST award/grant", admin_session.post(f"{api}/dojos/{authz_dojo}/award/grant", json={"user_id": user_id, "emoji": "\U0001f600", "description": "csrf"}, headers=NO_CSRF)),
        ("POST admins/promote", admin_session.post(f"{api}/dojos/{authz_dojo}/admins/promote", json={"user_id": user_id}, headers=NO_CSRF)),
        ("POST awards/prune", admin_session.post(f"{api}/dojos/{authz_dojo}/awards/prune", json={}, headers=NO_CSRF)),
    ]

    for label, response in user_requests + admin_requests:
        assert response.status_code == 403, \
            f"{label} without a CSRF token should be 403, but got {response.status_code}"

    assert count_rows("ssh_keys", f"user_id = {user_id}") == 0, "No SSH key may be registered without a CSRF token"
    assert count_rows("workspace_tokens", f"user_id = {user_id}") == 0, "No token may be minted without a CSRF token"
    assert count_rows("survey_responses", f"user_id = {user_id}") == 0, "No survey may be stored without a CSRF token"
    assert count_rows("submissions", f"user_id = {user_id}") == 0, "No submission may be recorded without a CSRF token"
    assert db_sql(f"SELECT type FROM dojo_users WHERE dojo_id = {db_id} AND user_id = {user_id}").split() == ["member"], \
        "No membership may change without a CSRF token"
    assert count_rows("dojos", f"id = '{create_marker}'") == 0, "No dojo may be created without a CSRF token"
    assert count_rows("dojo_users", f"dojo_id = {db_id} AND type = 'admin'") == admins_before, \
        "No dojo admin may be added without a CSRF token"
    assert count_rows("awards", f"category = '{authz_dojo.split('~')[1]}'") == awards_before, \
        "No award may be granted without a CSRF token"
    with pytest.raises(RuntimeError):
        get_outer_container_for(f"user_{user_id}")

    reattached = session.post(f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens", json={})
    assert reattached.status_code == 200, \
        f"The same request with a CSRF token must succeed, but got {reattached.status_code}"
    assert count_rows("workspace_tokens", f"user_id = {user_id}") == 1, \
        "The CSRF-bearing request must be the one that mints the token"


def test_update_code_null_rejects_anonymous_update(authz_private_dojo):
    db_id = dojo_db_id(authz_private_dojo)
    update_code = db_sql(f"SELECT update_code FROM dojos WHERE dojo_id = {db_id}").strip()
    db_sql(f"UPDATE dojos SET update_code = NULL WHERE dojo_id = {db_id}")
    anonymous = anonymous_session()
    try:
        wrong_code = anonymous.get(f"{DOJO_URL}/dojo/{authz_private_dojo}/update/anything")
        assert wrong_code.status_code == 403, \
            f"A wrong update code must be 403, but got {wrong_code.status_code}"
        assert wrong_code.json() == {"success": False, "error": "Forbidden"}, \
            f"Unexpected payload for a wrong update code: {wrong_code.json()}"

        no_code = anonymous.get(f"{DOJO_URL}/dojo/{authz_private_dojo}/update/")
        assert no_code.status_code == 403, \
            f"An anonymous update of a NULL-update_code dojo must be 403, but got {no_code.status_code}"
        assert no_code.json() == {"success": False, "error": "Forbidden"}, \
            f"Unexpected payload for an anonymous update: {no_code.json()}"
    finally:
        db_sql(f"UPDATE dojos SET update_code = '{update_code}' WHERE dojo_id = {db_id}")


def test_dojo_page_directory_renders_default(authz_dojo, random_user_session):
    response = random_user_session.get(f"{DOJO_URL}/{authz_dojo}/authz-notes")
    assert response.status_code == 200, f"Expected the page directory to render, but got {response.status_code}"
    assert "AUTHZ_MATRIX_DEFAULT_PAGE" in response.text, "Expected the page directory's default.md content"


def test_dojo_page_directory_anonymous(authz_dojo):
    response = anonymous_session().get(f"{DOJO_URL}/{authz_dojo}/authz-notes")
    assert response.status_code == 200, \
        f"An anonymous page-directory request must not crash, but got {response.status_code}"
    assert "AUTHZ_MATRIX_DEFAULT_PAGE" in response.text, "Expected the page directory's default.md content"


def test_course_page_user_param_requires_dojo_admin(authz_dojo, random_user):
    _, session = random_user
    join(session, authz_dojo)

    response = session.get(f"{DOJO_URL}/dojo/{authz_dojo}/course?user=abc", allow_redirects=False)
    assert response.status_code == 403, \
        f"A non-admin must be rejected before the user lookup, expected 403 but got {response.status_code}"


def test_course_page_non_numeric_user_param(authz_dojo, admin_session):
    response = admin_session.get(f"{DOJO_URL}/dojo/{authz_dojo}/course?user=abc", allow_redirects=False)
    assert response.status_code == 404, \
        f"A non-numeric user param must be a client error, but got {response.status_code}"


def test_course_identity_malformed_body(authz_dojo, random_user):
    clear_ratelimit("update_identity")
    name, session = random_user
    join(session, authz_dojo)
    user_id = get_user_id(name)
    db_id = dojo_db_id(authz_dojo)
    url = f"{DOJO_URL}/dojo/{authz_dojo}/course/identity"

    undecodable = session.patch(url, **BAD_JSON)
    assert undecodable.status_code < 500, \
        f"An undecodable JSON body must not crash the server, but got {undecodable.status_code}"
    rows = db_sql(f"SELECT type, token FROM dojo_users WHERE dojo_id = {db_id} AND user_id = {user_id}").split()
    assert rows in (["member|"], ["student|"]), \
        f"An undecodable body must not store a garbage identity, but the row is {rows}"

    form_encoded = session.patch(url, data="identity=formvalue")
    assert 400 <= form_encoded.status_code < 500, \
        f"A form-encoded body must be a client error, but got {form_encoded.status_code}"
    assert count_rows("dojo_users", f"dojo_id = {db_id} AND user_id = {user_id} AND token = 'formvalue'") == 0, \
        "A rejected identity request must not store the identity"

    valid = session.patch(url, json={"identity": "authz-matrix-student"})
    assert valid.status_code == 200, f"Expected the valid identity to be accepted, but got {valid.status_code}"
    assert valid.json()["success"], f"Unexpected payload: {valid.json()}"
    assert db_sql(
        f"SELECT type, token FROM dojo_users WHERE dojo_id = {db_id} AND user_id = {user_id}"
    ).split() == ["student|authz-matrix-student"], \
        "The endpoint must still be usable after rejecting malformed bodies"
