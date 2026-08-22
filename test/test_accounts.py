import base64
import contextlib
import datetime
import json
import os
import random
import re
import string
import subprocess
import tempfile
import time
import pytest
import requests

from utils import (
    DOJO_URL,
    db_sql,
    dojo_run,
    get_user_id,
    login,
    parse_csrf_token,
    remove_workspace_container,
    start_challenge,
    workspace_run,
)


def rand_name(prefix="acct"):
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def anon_session():
    session = requests.Session()
    session.headers["CSRF-Token"] = parse_csrf_token(session.get(f"{DOJO_URL}/login").text)
    return session


def _post_retrying_throttle(session, path, payload):
    while True:
        response = session.post(f"{DOJO_URL}{path}", json=payload)
        if response.status_code != 429:
            return response
        time.sleep(1)


def api_register(session, **payload):
    return _post_retrying_throttle(session, "/pwncollege_api/v1/auth/register", payload)


def api_login(session, **payload):
    return _post_retrying_throttle(session, "/pwncollege_api/v1/auth/login", payload)


def api_login_raw(session, **payload):
    return session.post(f"{DOJO_URL}/pwncollege_api/v1/auth/login", json=payload)


def registration_payload(name, **overrides):
    payload = dict(name=name, email=f"{name}@example.com", password=name)
    payload.update(overrides)
    return payload


def count_users(name):
    return int(db_sql(f"SELECT count(*) FROM users WHERE name = '{name}'").strip())


def flask_shell_result(code):
    encoded = base64.b64encode(code.encode()).decode()
    result = dojo_run("dojo", "flask", input=f'import base64; exec(base64.b64decode("{encoded}").decode())\n')
    match = re.search(r"RESULT:(.*)", result.stdout)
    assert match, f"flask shell produced no RESULT line: {result.stdout}\n{result.stderr}"
    return json.loads(match.group(1))


@contextlib.contextmanager
def server_config(**overrides):
    """Flip a CTFd config value for the duration of a test.

    set_config from a separate process updates the row but not the running
    server's memoized copy, and the two converge at an unpredictable moment, so a
    test that cannot see its own change must skip rather than leave the
    deployment holding a setting the rest of the suite does not expect.
    """
    read = ("import json\n"
            "from CTFd.utils import get_config\n"
            f"print('RESULT:' + json.dumps({{key: get_config(key) for key in {list(overrides)!r}}}))\n")
    write = ("import json\n"
             "from CTFd.utils import set_config\n"
             "for key, value in {values!r}.items():\n"
             "    set_config(key, value)\n"
             "print('RESULT:' + json.dumps(True))\n")

    original = flask_shell_result(read)
    flask_shell_result(write.format(values=overrides))
    if flask_shell_result(read) != overrides:
        flask_shell_result(write.format(values=original))
        pytest.skip("this deployment does not propagate config changes made outside the server")
    try:
        yield
    finally:
        flask_shell_result(write.format(values=original))


def mint_signed_token(payload, *, age=0):
    """Mint a CTFd-compatible URLSafeTimedSerializer token, optionally backdated by `age` seconds."""
    return dojo_run(
        "docker", "exec", "ctfd", "python3", "-c",
        "import os, sys, time\n"
        "from itsdangerous.url_safe import URLSafeTimedSerializer\n"
        "from itsdangerous.timed import TimestampSigner\n"
        "age = int(sys.argv[2])\n"
        "class Backdated(TimestampSigner):\n"
        "    def get_timestamp(self):\n"
        "        return int(time.time()) - age\n"
        "print(URLSafeTimedSerializer(os.environ['SECRET_KEY'], signer=Backdated).dumps(sys.argv[1]))\n",
        payload, str(age),
    ).stdout.strip()


def mint_ssh_service_token(user_id):
    token = dojo_run(
        "docker", "exec", "ctfd", "python3", "-c",
        "import os, sys\n"
        "from itsdangerous.url_safe import URLSafeTimedSerializer\n"
        "print(URLSafeTimedSerializer(os.environ['DOJO_SSH_SERVICE_KEY']).dumps([int(sys.argv[1]), 'ssh-tui']))\n",
        str(user_id),
    ).stdout.strip()
    return f"sk-ssh-service-{token}"


def password_hash(name):
    return db_sql(f"SELECT password FROM users WHERE name = '{name}'").strip()


@pytest.fixture(scope="module")
def ssh_keypairs():
    with tempfile.TemporaryDirectory() as tmpdir:
        keys = []
        for index in range(6):
            path = os.path.join(tmpdir, f"key{index}")
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-f", path, "-N", "", "-q"],
                check=True, capture_output=True,
            )
            with open(f"{path}.pub") as key_file:
                keys.append(key_file.read().strip())
        yield keys


@pytest.fixture
def second_user():
    name = rand_name("second")
    yield name, login(name, name, register=True)


def test_api_register_creates_user_and_session():
    name = rand_name()
    session = anon_session()

    response = api_register(session, **registration_payload(name))
    assert response.status_code == 200, f"registration failed: {response.status_code} {response.text}"
    body = response.json()
    assert body["success"] is True, body
    assert body["data"]["username"] == name, body
    assert body["data"]["email"] == f"{name}@example.com", body
    assert body["data"]["verified"] is True, f"no mail server configured, so registration must auto-verify: {body}"
    assert isinstance(body["data"]["user_id"], int), body

    assert count_users(name) == 1, "registration must create exactly one user row"

    me = session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert me.status_code == 200, f"registration must authenticate the session: {me.status_code}"
    assert me.json()["name"] == name, me.json()
    assert me.json()["id"] == body["data"]["user_id"], me.json()


def test_api_register_blocked_when_registration_not_public():
    name = rand_name()
    session = anon_session()

    with server_config(registration_visibility="private"):
        response = api_register(session, **registration_payload(name))
        assert response.status_code == 403, response.text
        assert response.json()["errors"] == ["Registration is currently disabled"], response.json()
        assert requests.get(f"{DOJO_URL}/register").status_code == 404, "the HTML register form must be unreachable"

    assert count_users(name) == 0, "registration must not create a user while disabled"
    assert requests.get(f"{DOJO_URL}/register").status_code == 200, "registration must be restored"


def test_api_register_user_limit():
    limit = int(db_sql("SELECT count(*) FROM users WHERE banned = false AND hidden = false").strip())
    name = rand_name()
    session = anon_session()

    with server_config(num_users=limit):
        response = api_register(session, **registration_payload(name))
        assert response.status_code == 403, response.text
        assert response.json()["errors"] == [f"Reached maximum users ({limit})"], response.json()

    assert count_users(name) == 0, "registration must not create a user past the limit"


def test_api_register_registration_code():
    session = anon_session()

    with server_config(registration_code="SeCrEt"):
        missing_name = rand_name()
        missing = api_register(session, **registration_payload(missing_name))
        assert missing.status_code == 400, missing.text
        assert "Invalid registration code" in missing.json()["errors"], missing.json()

        wrong_name = rand_name()
        wrong = api_register(session, **registration_payload(wrong_name, registration_code="wrong"))
        assert wrong.status_code == 400, wrong.text
        assert "Invalid registration code" in wrong.json()["errors"], wrong.json()

        accepted_name = rand_name()
        accepted = api_register(session, **registration_payload(accepted_name, registration_code="secret"))
        assert accepted.status_code == 200, f"registration code comparison must be case-insensitive: {accepted.text}"

    assert count_users(missing_name) == 0, "missing registration code must not create a user"
    assert count_users(wrong_name) == 0, "wrong registration code must not create a user"
    assert count_users(accepted_name) == 1, "correct registration code must create a user"


def test_api_login_success_returns_identity():
    name = rand_name()
    assert api_register(anon_session(), **registration_payload(name)).status_code == 200

    session = anon_session()
    response = api_login(session, name=name, password=name)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["username"] == name, data
    assert data["email"] == f"{name}@example.com", data
    assert data["type"] == "user", data
    assert data["verified"] is True, data
    assert data["team_id"] is None, data

    me = session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert me.status_code == 200, me.status_code
    assert me.json()["id"] == data["user_id"], me.json()

    admin_response = api_login(anon_session(), name="admin", password="admin")
    assert admin_response.status_code == 200, admin_response.text
    assert admin_response.json()["data"]["type"] == "admin", admin_response.json()


def test_api_login_invalid_credentials_uniform_error(random_user_name):
    wrong_password_session = anon_session()
    wrong_password = api_login(wrong_password_session, name=random_user_name, password="wrong")
    assert wrong_password.status_code == 401, wrong_password.text

    unknown_session = anon_session()
    unknown = api_login(unknown_session, name=rand_name("nosuchuser"), password="wrong")
    assert unknown.status_code == 401, unknown.text

    assert wrong_password.json() == {"success": False, "errors": ["Invalid credentials"]}, wrong_password.json()
    assert wrong_password.json() == unknown.json(), "failed login must not enumerate accounts"

    for session in [wrong_password_session, unknown_session]:
        redirected = session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", allow_redirects=False)
        assert redirected.status_code == 302, "failed login must not establish a session"
        assert session.get(
            f"{DOJO_URL}/pwncollege_api/v1/users/me", headers={"Content-Type": "application/json"}
        ).status_code == 403


def test_api_login_rate_limited(random_user_name):
    session = anon_session()
    statuses = []
    for _ in range(20):
        status = api_login_raw(session, name=random_user_name, password="wrong").status_code
        statuses.append(status)
        if status == 429:
            break

    assert 429 in statuses, (
        f"the JSON login API must be throttled like the login form, but got: {statuses}"
    )
    assert set(statuses) == {401, 429}, statuses
    time.sleep(6)


def test_api_logout_clears_session():
    name = rand_name()
    session = login(name, name, register=True)
    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").status_code == 200

    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/auth/logout", json={})
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True, response.json()

    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", allow_redirects=False).status_code == 302
    hacker = session.get(f"{DOJO_URL}/hacker/", allow_redirects=False)
    assert hacker.status_code == 302 and "/login" in hacker.headers["Location"], hacker.headers
    assert session.post(f"{DOJO_URL}/pwncollege_api/v1/ssh_key", json={"ssh_key": ""}).status_code == 403


def test_api_verify_email_token_lifecycle(random_user_name):
    verify_url = f"{DOJO_URL}/pwncollege_api/v1/auth/verify"

    invalid = requests.get(f"{verify_url}/not-a-token")
    assert invalid.status_code == 400, invalid.text
    assert invalid.json()["errors"] == ["Your confirmation token is invalid"], invalid.json()

    expired = requests.get(f"{verify_url}/{mint_signed_token('someone@example.com', age=10000)}")
    assert expired.status_code == 400, expired.text
    assert expired.json()["errors"] == ["Your confirmation link has expired"], expired.json()

    unknown = requests.get(f"{verify_url}/{mint_signed_token(f'{rand_name()}@example.com')}")
    assert unknown.status_code == 404, unknown.text
    assert unknown.json()["errors"] == ["User not found"], unknown.json()

    db_sql(f"UPDATE users SET verified = false WHERE name = '{random_user_name}'")
    token = mint_signed_token(f"{random_user_name}@example.com")

    verified = requests.get(f"{verify_url}/{token}")
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["message"] == "Email successfully verified", verified.json()
    assert db_sql(f"SELECT verified FROM users WHERE name = '{random_user_name}'").strip() == "t"

    replayed = requests.get(f"{verify_url}/{token}")
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["data"]["message"] == "Email already verified", replayed.json()


def test_api_forgot_password_without_mail(random_user_name):
    session = anon_session()
    for email in [f"{random_user_name}@example.com", f"{rand_name()}@example.com"]:
        response = session.post(f"{DOJO_URL}/pwncollege_api/v1/auth/forgot-password", json={"email": email})
        assert response.status_code == 400, response.text
        assert response.json()["errors"] == ["Email functionality is not configured"], response.json()


def test_api_reset_password_changes_credentials():
    name = rand_name()
    login(name, name, register=True)
    before = password_hash(name)

    token = mint_signed_token(f"{name}@example.com")
    response = anon_session().post(
        f"{DOJO_URL}/pwncollege_api/v1/auth/reset-password/{token}", json={"password": "newpass123"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["message"] == "Password successfully reset", response.json()

    assert password_hash(name) != before, "the stored password hash must change"
    login(name, "newpass123")
    login(name, name, success=False)


def test_api_reset_password_validation():
    name = rand_name()
    login(name, name, register=True)
    before = password_hash(name)
    reset_url = f"{DOJO_URL}/pwncollege_api/v1/auth/reset-password"
    valid_token = mint_signed_token(f"{name}@example.com")
    session = anon_session()

    attempts = [
        (f"{reset_url}/{valid_token}", {"password": ""}, 400, ["Please provide a password"]),
        (f"{reset_url}/{valid_token}", {"password": "x" * 129}, 400, ["Password is too long"]),
        (f"{reset_url}/garbage", {"password": "abc"}, 400, ["Your reset token is invalid"]),
        (f"{reset_url}/{mint_signed_token(f'{name}@example.com', age=10000)}", {"password": "abc"},
         400, ["Your reset link has expired"]),
        (f"{reset_url}/{mint_signed_token(f'{rand_name()}@example.com')}", {"password": "abc"},
         404, ["User not found"]),
    ]
    for url, payload, expected_status, expected_errors in attempts:
        response = session.post(url, json=payload)
        assert response.status_code == expected_status, f"{url} {payload} -> {response.status_code} {response.text}"
        assert response.json()["errors"] == expected_errors, response.json()

    assert password_hash(name) == before, "a rejected reset must leave the password untouched"
    login(name, name)


def test_api_reset_password_evicts_existing_sessions():
    name = rand_name()
    session = login(name, name, register=True)
    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").status_code == 200

    token = mint_signed_token(f"{name}@example.com")
    reset = anon_session().post(
        f"{DOJO_URL}/pwncollege_api/v1/auth/reset-password/{token}", json={"password": "newpass123"}
    )
    assert reset.status_code == 200, reset.text

    evicted = session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", allow_redirects=False)
    assert evicted.status_code == 302, "a password reset must evict sessions established with the old password"
    assert "/login" in evicted.headers["Location"], evicted.headers

    reauthenticated = login(name, "newpass123")
    assert reauthenticated.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["name"] == name


def test_users_me_session_payload(admin_session):
    name = rand_name()
    session = anon_session()
    assert api_register(session, **registration_payload(name)).status_code == 200

    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {
        "id", "name", "email", "website", "affiliation", "country",
        "bracket", "hidden", "banned", "verified", "admin",
    }, payload
    assert payload["name"] == name, payload
    assert payload["email"] == f"{name}@example.com", payload
    assert payload["id"] == get_user_id(name), payload
    assert payload["admin"] is False, payload
    assert payload["banned"] is False, payload
    assert payload["hidden"] is False, payload
    assert payload["verified"] is True, payload

    admin_payload = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()
    assert admin_payload["admin"] is True, admin_payload
    assert admin_payload["hidden"] == (db_sql("SELECT hidden FROM users WHERE name = 'admin'").strip() == "t")


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/pwncollege_api/v1/users/me", None),
    ("post", "/pwncollege_api/v1/ssh_key", {"ssh_key": ""}),
    ("get", "/pwncollege_api/v1/workspace_tokens", None),
])
def test_authed_only_endpoints_reject_anonymous(method, path, payload):
    session = anon_session()
    request_kwargs = {"json": payload} if payload is not None else {}

    json_request = getattr(session, method)(
        f"{DOJO_URL}{path}", headers={"Content-Type": "application/json"}, **request_kwargs
    )
    assert json_request.status_code == 403, f"{method} {path} -> {json_request.status_code}"

    if method == "get":
        redirected = session.get(f"{DOJO_URL}{path}", allow_redirects=False)
        assert redirected.status_code == 302, f"{path} -> {redirected.status_code}"
        assert "/login" in redirected.headers["Location"], redirected.headers


def test_cli_token_invalid_signature():
    for token in ["sk-workspace-local-deadbeef", "sk-workspace-local-" + "A" * 60]:
        response = requests.get(
            f"{DOJO_URL}/pwncollege_api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401, f"{token} -> {response.status_code} {response.text}"
        assert response.json()["error"] == "Failed to authenticate container token.", response.json()


def test_cli_token_authenticates_and_is_request_scoped(random_user, example_dojo):
    name, session = random_user
    start_challenge(example_dojo, "hello", "apple", session=session)
    try:
        token = workspace_run("cat /run/dojo/var/auth_token", user=name, root=True).stdout.strip()
        headers = {"Authorization": f"Bearer {token}"}

        me = requests.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", headers=headers)
        assert me.status_code == 200, f"{me.status_code} {me.text}"
        assert me.json()["name"] == name, me.json()

        current = requests.get(f"{DOJO_URL}/pwncollege_api/v1/docker", headers=headers)
        assert current.status_code == 200, current.text
        assert current.json()["dojo"] == example_dojo, current.json()
        assert current.json()["module"] == "hello", current.json()
        assert current.json()["challenge"] == "apple", current.json()

        cookie_jar = requests.Session()
        assert cookie_jar.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", headers=headers).status_code == 200
        leaked = cookie_jar.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", allow_redirects=False)
        assert leaked.status_code == 302, "bearer auth must not persist into the cookie session"
        assert "/login" in leaked.headers["Location"], leaked.headers
    finally:
        remove_workspace_container(name)

    stale = requests.get(f"{DOJO_URL}/pwncollege_api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert stale.status_code == 403, f"{stale.status_code} {stale.text}"
    assert stale.json()["error"] == "No active challenge container.", stale.json()


def test_cli_token_rejected_after_challenge_switch(random_user, example_dojo):
    name, session = random_user
    start_challenge(example_dojo, "hello", "apple", session=session)
    try:
        token = workspace_run("cat /run/dojo/var/auth_token", user=name, root=True).stdout.strip()
        start_challenge(example_dojo, "hello", "banana", session=session)

        response = requests.get(
            f"{DOJO_URL}/pwncollege_api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403, f"{response.status_code} {response.text}"
        assert response.json()["error"] == "Token failed to authenticate active challenge container.", response.json()
    finally:
        remove_workspace_container(name)


def test_ssh_service_token_auth(random_user):
    name, session = random_user
    token = mint_ssh_service_token(get_user_id(name))

    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, f"{response.status_code} {response.text}"
    assert response.json() == session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos").json(), \
        "the ssh service token must resolve to the same view as the user's own session"

    bad_signature = requests.get(
        f"{DOJO_URL}/pwncollege_api/v1/dojos", headers={"Authorization": "Bearer sk-ssh-service-garbage"}
    )
    assert bad_signature.status_code == 401, bad_signature.text
    assert bad_signature.json()["error"] == "Failed to authenticate ssh service token.", bad_signature.json()

    unknown_user = requests.get(
        f"{DOJO_URL}/pwncollege_api/v1/dojos",
        headers={"Authorization": f"Bearer {mint_ssh_service_token(999999)}"},
    )
    assert unknown_user.status_code == 404, unknown_user.text
    assert unknown_user.json()["error"] == "User not found.", unknown_user.json()

    cookie_jar = requests.Session()
    assert cookie_jar.get(
        f"{DOJO_URL}/pwncollege_api/v1/dojos", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200
    leaked = cookie_jar.get(f"{DOJO_URL}/hacker/", allow_redirects=False)
    assert leaked.status_code == 302, "ssh service auth must not persist into the cookie session"
    assert "/login" in leaked.headers["Location"], leaked.headers

    without_csrf = requests.post(
        f"{DOJO_URL}/pwncollege_api/v1/docker",
        json={"dojo": "definitely-not-a-dojo", "module": "hello", "challenge": "apple"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert without_csrf.status_code == 200, \
        f"an Authorization header must short-circuit the CSRF check: {without_csrf.status_code}"
    assert without_csrf.json() == {"success": False, "error": "Invalid dojo"}, without_csrf.json()


def test_bearer_bypasses_ctfd_token_handler():
    docker_url = f"{DOJO_URL}/pwncollege_api/v1/docker"
    body = {"dojo": "x", "module": "y", "challenge": "z"}

    bearer = requests.post(docker_url, json=body, headers={"Authorization": "Bearer totally-bogus"})
    assert bearer.status_code == 403, (
        f"an unrecognised Bearer token must fall through to normal auth, not CTFd's token handler: "
        f"{bearer.status_code} {bearer.text[:200]}"
    )

    ctfd_token = requests.post(docker_url, json=body, headers={"Authorization": "Token totally-bogus"})
    assert ctfd_token.status_code == 401, f"{ctfd_token.status_code} {ctfd_token.text[:200]}"


def test_ctfd_access_token_auth():
    name = rand_name()
    session = login(name, name, register=True)

    created = session.post(f"{DOJO_URL}/api/v1/tokens", json={})
    assert created.status_code == 200, created.text
    value = created.json()["data"]["value"]

    authorized = requests.get(
        f"{DOJO_URL}/api/v1/users/me",
        headers={"Authorization": f"Token {value}", "Content-Type": "application/json"},
    )
    assert authorized.status_code == 200, authorized.text
    assert authorized.json()["data"]["name"] == name, authorized.json()

    bogus = requests.get(
        f"{DOJO_URL}/api/v1/users/me",
        headers={"Authorization": "Token bogus", "Content-Type": "application/json"},
    )
    assert bogus.status_code == 401, bogus.text

    db_sql(f"UPDATE tokens SET expiration = NOW() - interval '1 day' WHERE value = '{value}'")
    expired = requests.get(
        f"{DOJO_URL}/api/v1/users/me",
        headers={"Authorization": f"Token {value}", "Content-Type": "application/json"},
    )
    assert expired.status_code == 401, expired.text
    assert "expired" in expired.text.lower(), expired.text

    assert session.get(f"{DOJO_URL}/settings").status_code == 200


def test_workspace_token_create_and_scope(random_user, second_user):
    owner_name, owner_session = random_user
    other_name, other_session = second_user
    url = f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens"

    created = owner_session.post(url, json={})
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["value"].startswith("workspace_"), data
    assert set(data) == {"id", "expiration", "value"}, data

    expiration = datetime.datetime.strptime(data["expiration"][:19], "%Y-%m-%dT%H:%M:%S")
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    expiration_days = (expiration - now).total_seconds() / 86400
    assert 29 < expiration_days < 31, f"expected a ~30 day default expiration, got {expiration_days} days"

    assert db_sql(
        f"SELECT user_id FROM workspace_tokens WHERE value = '{data['value']}'"
    ).strip() == str(get_user_id(owner_name))

    listed = owner_session.get(url)
    assert listed.status_code == 200, listed.text
    assert [entry["id"] for entry in listed.json()["data"]] == [data["id"]], listed.json()
    assert "value" not in listed.json()["data"][0], "listing must not disclose token values"

    other_created = other_session.post(url, json={})
    assert other_created.status_code == 200, other_created.text
    other_listed = other_session.get(url).json()["data"]
    assert [entry["id"] for entry in other_listed] == [other_created.json()["data"]["id"]], other_listed
    assert data["id"] not in [entry["id"] for entry in other_listed], "listing must be scoped to the caller"


def test_workspace_token_explicit_expiration(random_user_session):
    response = random_user_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens", json={"expiration": "2035-01-01"}
    )
    assert response.status_code == 200, f"{response.status_code} {response.text[:200]}"
    assert response.json()["data"]["expiration"].startswith("2035-01-01"), response.json()


def test_workspace_token_header_rejected_when_invalid(random_user, second_user):
    name, session = random_user
    other_name, other_session = second_user
    docker_url = f"{DOJO_URL}/pwncollege_api/v1/docker"
    body = {"dojo": "definitely-not-a-dojo", "module": "hello", "challenge": "apple"}

    unknown = session.post(docker_url, json=body, headers={"X-Workspace-Token": "workspace_deadbeef"})
    assert unknown.status_code == 401, f"{unknown.status_code} {unknown.text[:200]}"
    assert "Invalid workspace token" in unknown.text, unknown.text[:400]

    other_token = other_session.post(f"{DOJO_URL}/pwncollege_api/v1/workspace_tokens", json={}).json()["data"]["value"]
    db_sql(f"UPDATE workspace_tokens SET expiration = NOW() - interval '1 day' WHERE value = '{other_token}'")
    expired = session.post(docker_url, json=body, headers={"X-Workspace-Token": other_token})
    assert expired.status_code == 401, f"{expired.status_code} {expired.text[:200]}"
    assert "This workspace token has expired" in expired.text, expired.text[:400]

    without_header = session.post(docker_url, json=body)
    assert without_header.status_code == 200, without_header.text
    assert without_header.json() == {"success": False, "error": "Invalid dojo"}, without_header.json()


def test_hidden_flag_round_trip(random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)

    public = requests.get(f"{DOJO_URL}/api/v1/users/{user_id}")
    assert public.status_code == 200, public.text
    assert "hidden" not in public.json()["data"], "the hidden flag must not leak into the public view"
    assert "hidden" in session.get(f"{DOJO_URL}/api/v1/users/me").json()["data"]

    assert session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": True}).status_code == 200
    assert requests.get(f"{DOJO_URL}/hacker/{user_id}").status_code == 404
    assert requests.get(f"{DOJO_URL}/api/v1/users/{user_id}").status_code == 404
    assert admin_session.get(f"{DOJO_URL}/api/v1/users/{user_id}").status_code == 200
    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["hidden"] is True

    assert session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": False}).status_code == 200
    assert requests.get(f"{DOJO_URL}/hacker/{user_id}").status_code == 200
    assert db_sql(f"SELECT hidden FROM users WHERE id = {user_id}").strip() == "f"
    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["hidden"] is False


def test_self_patch_cannot_escalate_privileges(random_user):
    name, session = random_user

    response = session.patch(
        f"{DOJO_URL}/api/v1/users/me",
        json={"type": "admin", "verified": True, "banned": False, "secret": "x"},
    )
    assert response.status_code in (200, 400), f"{response.status_code} {response.text}"

    assert db_sql(f"SELECT type FROM users WHERE name = '{name}'").strip() == "user"
    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["admin"] is False
    assert session.get(f"{DOJO_URL}/admin/dojos", allow_redirects=False).status_code in (302, 403)


def test_banned_user_locked_out(random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)

    banned = admin_session.patch(f"{DOJO_URL}/api/v1/users/{user_id}", json={"banned": True})
    assert banned.status_code == 200, banned.text
    try:
        assert session.get(f"{DOJO_URL}/dojos").status_code == 403
        assert session.get(
            f"{DOJO_URL}/pwncollege_api/v1/users/me", headers={"Content-Type": "application/json"}
        ).status_code == 403

        relogged = login(name, name)
        assert relogged.get(f"{DOJO_URL}/dojos").status_code == 403, \
            "a ban must lock out even a freshly established session"
    finally:
        unbanned = admin_session.patch(f"{DOJO_URL}/api/v1/users/{user_id}", json={"banned": False})
        assert unbanned.status_code == 200, unbanned.text

    assert login(name, name).get(f"{DOJO_URL}/dojos").status_code == 200


def test_settings_page_requires_auth_and_reflects_account_state(random_user, second_user, ssh_keypairs):
    owner_name, owner_session = random_user
    other_name, other_session = second_user

    anonymous = requests.get(f"{DOJO_URL}/settings", allow_redirects=False)
    assert anonymous.status_code == 302, anonymous.status_code
    assert "/login" in anonymous.headers["Location"] and "next" in anonymous.headers["Location"], anonymous.headers

    owner_key, other_key = ssh_keypairs[0], ssh_keypairs[1]
    assert owner_session.post(f"{DOJO_URL}/pwncollege_api/v1/ssh_key", json={"ssh_key": owner_key}).status_code == 200
    assert other_session.post(f"{DOJO_URL}/pwncollege_api/v1/ssh_key", json={"ssh_key": other_key}).status_code == 200

    owner_key_body = owner_key.split()[1]
    other_key_body = other_key.split()[1]

    owner_settings = owner_session.get(f"{DOJO_URL}/settings")
    assert owner_settings.status_code == 200, owner_settings.status_code
    assert owner_key_body in owner_settings.text, "the settings page must list the caller's own key"
    assert other_key_body not in owner_settings.text, "the settings page must not list another user's key"

    other_settings = other_session.get(f"{DOJO_URL}/settings")
    assert other_settings.status_code == 200, other_settings.status_code
    assert other_key_body in other_settings.text
    assert owner_key_body not in other_settings.text

    assert owner_session.post(f"{DOJO_URL}/api/v1/tokens", json={}).status_code == 200
    assert "Active Tokens" in owner_session.get(f"{DOJO_URL}/settings").text, \
        "the settings page must list the caller's own access tokens"
    assert "Active Tokens" not in other_session.get(f"{DOJO_URL}/settings").text, \
        "the settings page must not list another user's access tokens"
