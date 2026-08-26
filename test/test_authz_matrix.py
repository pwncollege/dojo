import json
import random
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
    get_outer_container_for,
    get_user_id,
    login,
    parse_csrf_token,
    redis_cli,
    remove_workspace_container,
    start_challenge,
)

#pylint:disable=redefined-outer-name

BAD_JSON = dict(data="", headers={"Content-Type": "application/json"})
NO_CSRF = {"CSRF-Token": None}


def clear_ratelimit(endpoint_fragment):
    """The whole suite shares one client IP, so a neighbouring test file can exhaust an endpoint's ratelimit."""
    scan = redis_cli("--scan", "--pattern", "flask_cache_rl:*", check=False)
    keys = [key for key in scan.stdout.split() if endpoint_fragment in key]
    if keys:
        redis_cli("DEL", *keys, check=False)


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


def test_survey_post_malformed_body(authz_dojo, random_user):
    clear_ratelimit("dojo_survey")
    name, session = random_user
    join(session, authz_dojo)
    url = survey_url(authz_dojo, "surveyed", "surveyed-challenge")

    undecodable = session.post(url, **BAD_JSON)
    assert 400 <= undecodable.status_code < 500, \
        f"An undecodable JSON body must be a client error, but got {undecodable.status_code}"

    non_object = session.post(url, json=["response", "x"])
    assert 400 <= non_object.status_code < 500, \
        f"A non-object JSON body must be a client error, but got {non_object.status_code}"

    assert survey_response_count(authz_dojo, "surveyed", "surveyed-challenge", name) == 0, \
        "A malformed survey POST must not store a survey response"


def test_grant_award_non_integer_user_id_is_client_error(authz_dojo, admin_session):
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/award/grant"
    before = count_rows("awards", "description = 'authz-matrix-bad'")
    for user_id in ["notanint", True, 1.9, 0, 2**31]:
        response = admin_session.post(
            url,
            json={"user_id": user_id, "emoji": "\U0001f600", "description": "authz-matrix-bad"},
        )
        assert 400 <= response.status_code < 500, \
            f"The invalid user_id {user_id!r} must be a client error, but got {response.status_code}"
    assert count_rows("awards", "description = 'authz-matrix-bad'") == before, \
        "Rejected user ids must not grant an award"

    for payload in [[], {"user_id": 1, "emoji": 1, "description": "authz-matrix-bad"}]:
        response = admin_session.post(url, json=payload)
        assert 400 <= response.status_code < 500, \
            f"Malformed award data must be rejected, but got {response.status_code}"
    assert count_rows("awards", "description = 'authz-matrix-bad'") == before


def test_admin_promotion_requires_an_exact_user_id(authz_dojo, admin_session, random_user):
    name, session = random_user
    join(session, authz_dojo)
    user_id = get_user_id(name)
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/admins/promote"

    for invalid_user_id in [True, user_id + 0.5, 0, 2**31, "9" * 5000]:
        response = admin_session.post(url, json={"user_id": invalid_user_id})
        assert 400 <= response.status_code < 500, \
            f"The invalid user id {invalid_user_id!r} must be rejected, but got {response.status_code}"

    row = db_sql(
        f"SELECT type FROM dojo_users WHERE dojo_id = {dojo_db_id(authz_dojo)} AND user_id = {user_id}"
    ).strip()
    assert row == "member", f"An invalid promotion changed the user's role to {row!r}"


def test_create_dojo_malformed_body(admin_session):
    marker = "authz-matrix-form-" + "".join(random.choices(string.ascii_lowercase, k=8))

    undecodable = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", **BAD_JSON)
    assert 400 <= undecodable.status_code < 500, \
        f"An undecodable JSON body must be a client error, but got {undecodable.status_code}"
    assert not undecodable.json()["success"], f"Unexpected payload: {undecodable.json()}"

    non_object = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", json=[])
    assert 400 <= non_object.status_code < 500, \
        f"A non-object JSON body must be rejected, but got {non_object.status_code}"

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


def test_workspace_token_malformed_expiration(random_user):
    name, session = random_user
    url = f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens"
    user_id = get_user_id(name)

    for expiration in ["garbage", "2026-13-45", False]:
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
    assert 400 <= response.status_code < 500, \
        f"An undecodable JSON body must be rejected, but got {response.status_code}"

    tokens = session.get(url).json()["data"]
    assert tokens == [], f"A malformed body minted a workspace token: {tokens}"
    assert count_rows("workspace_tokens", f"user_id = {user_id}") == 0, \
        "A malformed body must not mint a workspace token"


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


@pytest.mark.parametrize("port", ["../../etc", "8080/../../x"])
def test_workspace_api_port_param_rejects_traversal(container_user, port):
    _, session = container_user
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/workspace", params={"port": port})
    if response.status_code == 200:
        assert ".." not in response.json().get("iframe_src", ""), \
            f"The proxy url must not contain path traversal: {response.json().get('iframe_src')}"
    assert 400 <= response.status_code < 500, \
        f"A non-integer port must be a client error, but got {response.status_code}"


def test_workspace_api_numeric_params_require_valid_ranges(container_user, admin_session):
    _, session = container_user
    url = f"{DOJO_URL}/pwncollege_api/v1/workspace"
    for port in ["0", "-1", "65536"]:
        response = session.get(url, params={"port": port})
        assert response.status_code == 404, \
            f"Out-of-range port {port} must be rejected, but got {response.status_code}"

    for user_id in ["0", "-1", str(2**31)]:
        response = admin_session.get(url, params={"user": user_id})
        assert response.status_code == 404, \
            f"Invalid user id {user_id} must be rejected, but got {response.status_code}"


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

    non_object = session.post(url, json=[])
    assert 400 <= non_object.status_code < 500, \
        f"A non-object JSON body must be rejected, but got {non_object.status_code}"


def test_solve_post_rejects_non_object_json(authz_dojo, random_user):
    name, session = random_user
    join(session, authz_dojo)
    challenge_id = challenge_db_id(authz_dojo, "surveyed", "surveyed-challenge")
    before = count_rows("submissions", f"user_id = {get_user_id(name)} AND challenge_id = {challenge_id}")

    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{authz_dojo}/surveyed/surveyed-challenge/solve",
        json=[],
    )
    assert 400 <= response.status_code < 500, \
        f"A non-object solve body must be rejected, but got {response.status_code}"
    assert count_rows("submissions", f"user_id = {get_user_id(name)} AND challenge_id = {challenge_id}") == before, \
        "A rejected solve request must not create a submission"


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
        wrong_code = anonymous.post(f"{DOJO_URL}/dojo/{authz_private_dojo}/update/anything")
        assert wrong_code.status_code == 403, \
            f"A wrong update code must be 403, but got {wrong_code.status_code}"
        assert wrong_code.json() == {"success": False, "error": "Forbidden"}, \
            f"Unexpected payload for a wrong update code: {wrong_code.json()}"

        no_code = anonymous.post(f"{DOJO_URL}/dojo/{authz_private_dojo}/update/")
        assert no_code.status_code in {404, 405}, \
            f"A code-less update route must be unavailable, but got {no_code.status_code}"
    finally:
        db_sql(f"UPDATE dojos SET update_code = '{update_code}' WHERE dojo_id = {db_id}")


def test_course_page_invalid_user_param(authz_dojo, admin_session):
    for user_id in ["abc", "0", "-1", str(2**31)]:
        response = admin_session.get(
            f"{DOJO_URL}/dojo/{authz_dojo}/course", params={"user": user_id}, allow_redirects=False
        )
        assert response.status_code == 404, \
            f"Invalid user id {user_id} must be a client error, but got {response.status_code}"


def test_course_identity_malformed_body(authz_dojo, random_user):
    clear_ratelimit("update_identity")
    name, session = random_user
    join(session, authz_dojo)
    user_id = get_user_id(name)
    db_id = dojo_db_id(authz_dojo)
    url = f"{DOJO_URL}/dojo/{authz_dojo}/course/identity"

    undecodable = session.patch(url, **BAD_JSON)
    assert 400 <= undecodable.status_code < 500, \
        f"An undecodable JSON body must be rejected, but got {undecodable.status_code}"
    rows = db_sql(f"SELECT type, token FROM dojo_users WHERE dojo_id = {db_id} AND user_id = {user_id}").split()
    assert rows == ["member|"], \
        f"An undecodable body changed the user's membership: {rows}"

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
