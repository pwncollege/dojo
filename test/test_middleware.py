import base64
import datetime
import json
import os
import random
import re
import shlex
import socket
import string
import time
import uuid
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pytest
import requests

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    challenge_flag,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    flask_exec,
    get_user_id,
    login,
    parse_csrf_token,
)


FLASK_OUTPUT_MARKER = "--- middleware test output ---"


def flask_run(code):
    """Run python inside CTFd's app context; returns (stdout after marker, stderr)."""
    path = f"/tmp/dojo-test-middleware-{uuid.uuid4().hex}.py"
    script = f"print({FLASK_OUTPUT_MARKER!r}, flush=True)\n{code}"
    dojo_run("docker", "exec", "-i", "ctfd", "sh", "-c", f"cat > {path}", input=script)
    result = dojo_run("docker", "exec", "ctfd", "flask", "shell", "--", path, check=False)
    dojo_run("docker", "exec", "ctfd", "rm", "-f", path, check=False)
    assert FLASK_OUTPUT_MARKER in result.stdout, f"flask shell produced no output: {result.stdout}\n{result.stderr}"
    return result.stdout.split(FLASK_OUTPUT_MARKER, 1)[1].lstrip("\n"), result.stderr


# Scanning a container's whole log gets slower as the suite runs; every scrape is
# bounded to the recent past so it stays independent of how much came before.
LOG_WINDOW = "10m"


def container_logs(container, marker, *, after_context=0, since=LOG_WINDOW):
    command = (f"docker logs --since {since} {container} 2>&1 | "
               f"grep -F -A {after_context} -- {shlex.quote(marker)} || true")
    output = dojo_run("sh", "-c", command, check=False).stdout
    if output:
        return output
    # A loaded deployment can take a while to flush, and the windowed read is only
    # an optimization, so fall back to the whole log before concluding it is absent.
    command = f"docker logs {container} 2>&1 | grep -F -A {after_context} -- {shlex.quote(marker)} || true"
    return dojo_run("sh", "-c", command, check=False).stdout


def wait_for_log(marker, needle, *, container="ctfd", after_context=0, timeout=60):
    deadline = time.time() + timeout
    while True:
        output = container_logs(container, marker, after_context=after_context)
        if needle in output or time.time() > deadline:
            return output
        time.sleep(0.5)


def exception_lines(output):
    return [line for line in output.splitlines()
            if "API_EXCEPTION" in line or "PAGE_EXCEPTION" in line]


_client_ip = None


def client_ip():
    """The source address CTFd/nginx sees for requests issued by this test process."""
    global _client_ip
    if _client_ip is None:
        parsed = urlparse(DOJO_URL)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        sock = socket.create_connection((parsed.hostname, port), timeout=10)
        try:
            _client_ip = sock.getsockname()[0]
        finally:
            sock.close()
    return _client_ip


def ratelimit_key(endpoint):
    return f"flask_cache_rl:{client_ip()}:{endpoint}"


def clear_ratelimit(endpoint):
    dojo_run("docker", "exec", "cache", "redis-cli", "DEL", ratelimit_key(endpoint), check=False)


def redis_ttl(key):
    return int(dojo_run("docker", "exec", "cache", "redis-cli", "TTL", key).stdout.strip())


def stream_entries_added(stream="stat:events"):
    output = dojo_run("docker", "exec", "cache", "redis-cli", "XINFO", "STREAM", stream).stdout.split("\n")
    for index, field in enumerate(output):
        if field.strip() == "entries-added":
            return int(output[index + 1].strip())
    raise AssertionError(f"no entries-added in XINFO STREAM {stream}: {output}")


def cors_origin():
    return dojo_run("docker", "exec", "ctfd", "printenv", "CORS_ORIGINS", check=False).stdout.strip()


def ctfd_env(name):
    return dojo_run("docker", "exec", "ctfd", "printenv", name, check=False).stdout.strip()


def config_rows(sql):
    rows = {}
    for line in db_sql(sql).strip().splitlines():
        key, _, value = line.partition("|")
        rows[key] = value
    return rows


def random_ssh_public_key():
    blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + os.urandom(32)
    return "ssh-ed25519 " + base64.b64encode(blob).decode()


def uncsrfed_session():
    """A logged-in session that does NOT send the CSRF-Token header."""
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(name, name, register=True)
    del session.headers["CSRF-Token"]
    return name, session


@pytest.fixture(scope="module")
def middleware_course_dojo(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = (TEST_DOJOS_LOCATION / "middleware_course.yml").read_text().replace(
        "middleware-course", f"middleware-course-{suffix}"
    )
    reference_id = create_dojo_yml(spec, session=admin_session)
    dojo_id = dojo_db_id(reference_id)
    data = json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id = {dojo_id}"))
    data["course"] = {"student_id": "Student ID"}
    db_sql(f"UPDATE dojos SET data = '{json.dumps(data)}' WHERE dojo_id = {dojo_id}")
    return reference_id


def test_api_exception_cascades_to_page_handler(random_user):
    name, session = random_user
    user_id = get_user_id(name)

    api_marker = uuid.uuid4().hex
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error", params={"marker": api_marker})
    assert response.status_code == 500, f"Expected 500, got {response.status_code}"

    api_logs = wait_for_log(api_marker, "PAGE_EXCEPTION")
    api_lines = exception_lines(api_logs)
    assert any("API_EXCEPTION" in line for line in api_lines), f"no API_EXCEPTION logged: {api_logs}"
    assert any("PAGE_EXCEPTION" in line for line in api_lines), (
        f"API exception was not re-raised into the page handler: {api_logs}")

    page_marker = uuid.uuid4().hex
    response = session.get(f"{DOJO_URL}/test_page_error", params={"marker": page_marker})
    assert response.status_code == 500, f"Expected 500, got {response.status_code}"

    page_logs = wait_for_log(page_marker, "PAGE_EXCEPTION")
    page_lines = exception_lines(page_logs)
    assert any("PAGE_EXCEPTION" in line for line in page_lines), f"no PAGE_EXCEPTION logged: {page_logs}"
    assert not any("API_EXCEPTION" in line for line in page_lines), (
        f"a plain page exception must not be logged as an API exception: {page_logs}")
    assert all(f"user_id={user_id} logger=" in line for line in page_lines), (
        f"exception log must carry the requesting user id {user_id}: {page_logs}")


def test_exception_log_includes_traceback(random_user_session):
    marker = uuid.uuid4().hex
    response = random_user_session.get(f"{DOJO_URL}/test_page_error", params={"marker": marker})
    assert response.status_code == 500, f"Expected 500, got {response.status_code}"

    logs = wait_for_log(marker, "Traceback (most recent call last)", after_context=40)
    assert "Traceback (most recent call last)" in logs, f"no traceback logged alongside the exception: {logs}"
    assert "dojo_plugin/pages/test_error.py" in logs, f"traceback does not point at the failing frame: {logs}"


def test_exception_log_records_request_envelope(random_user_session):
    marker = uuid.uuid4().hex
    body = f"field1={marker}"
    response = random_user_session.post(
        f"{DOJO_URL}/test_page_error",
        params={"q1": marker},
        data={"field1": marker},
        headers={"User-Agent": "TestAgent/1.0", "Referer": "http://example.invalid/ref"},
    )
    assert response.status_code == 500, f"Expected 500, got {response.status_code}"

    logs = wait_for_log(marker, "PAGE_EXCEPTION")
    line = next((line for line in logs.splitlines() if "PAGE_EXCEPTION" in line), None)
    assert line, f"no PAGE_EXCEPTION line for marker {marker}: {logs}"

    assert "method='POST'" in line, line
    assert "endpoint='/test_page_error'" in line, line
    assert f"full_path='/test_page_error?q1={marker}'" in line, line
    assert re.search(r"base_url='https?://[^']*/test_page_error'", line), line
    assert f'query_params=\'{{"q1": "{marker}"}}\'' in line, line
    assert f'form_data=\'{{"field1": "{marker}"}}\'' in line, line
    assert "referrer='http://example.invalid/ref'" in line, line
    assert "content_type='application/x-www-form-urlencoded'" in line, line
    assert f"content_length={len(body)}" in line, line
    assert re.search(r"ip_address='[^']+'", line), line


def test_exception_log_records_user_agent(random_user_session):
    marker = uuid.uuid4().hex
    response = random_user_session.get(
        f"{DOJO_URL}/test_page_error",
        params={"marker": marker},
        headers={"User-Agent": "TestAgent/1.0"},
    )
    assert response.status_code == 500, f"Expected 500, got {response.status_code}"

    logs = wait_for_log(marker, "PAGE_EXCEPTION")
    line = next((line for line in logs.splitlines() if "PAGE_EXCEPTION" in line), None)
    assert line, f"no PAGE_EXCEPTION line for marker {marker}: {logs}"
    assert "user_agent='TestAgent/1.0'" in line, line


def test_exception_log_captures_json_body(random_user_session):
    json_marker = uuid.uuid4().hex
    response = random_user_session.post(f"{DOJO_URL}/test_page_error", json={"k": json_marker})
    assert response.status_code == 500, f"Expected 500, got {response.status_code}"

    logs = wait_for_log(json_marker, "PAGE_EXCEPTION")
    line = next((line for line in logs.splitlines() if "PAGE_EXCEPTION" in line), None)
    assert line, f"no PAGE_EXCEPTION line for marker {json_marker}: {logs}"
    assert f'json_data=\'{{"k": "{json_marker}"}}\'' in line, line
    assert "content_type='application/json'" in line, line

    bad_marker = uuid.uuid4().hex
    response = random_user_session.post(
        f"{DOJO_URL}/test_page_error",
        params={"m": bad_marker},
        data=b"{not json " + bad_marker.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 500, (
        f"a malformed JSON body must still reach the view, got {response.status_code}")

    logs = wait_for_log(bad_marker, "PAGE_EXCEPTION")
    line = next((line for line in logs.splitlines() if "PAGE_EXCEPTION" in line), None)
    assert line, f"no PAGE_EXCEPTION line for marker {bad_marker}: {logs}"
    assert "json_data=None" in line, f"malformed JSON should log json_data=None: {line}"


def test_api_404_is_not_logged_as_an_exception():
    markers = [uuid.uuid4().hex, uuid.uuid4().hex]
    paths = [
        f"{DOJO_URL}/pwncollege_api/v1/nope_{markers[0]}",
        f"{DOJO_URL}/pwncollege_api/v1/dojos/nonexistent_{markers[1]}/awards",
    ]
    for path in paths:
        response = requests.get(path)
        assert response.status_code == 404, f"Expected 404 for {path}, got {response.status_code}"

    for marker in markers:
        logs = wait_for_log(marker, "logger=werkzeug")
        assert not exception_lines(logs), f"an API 404 must not be logged as an exception: {logs}"


def test_test_error_endpoints_require_auth():
    for path in ["/pwncollege_api/v1/test_error", "/test_page_error"]:
        marker = uuid.uuid4().hex
        response = requests.get(f"{DOJO_URL}{path}", params={"marker": marker}, allow_redirects=False)
        assert response.status_code == 302, f"Expected anonymous {path} to redirect, got {response.status_code}"
        location = response.headers["Location"]
        assert "/login" in location, location
        assert "next=" in location, location

        logs = wait_for_log(marker, "logger=werkzeug")
        assert not exception_lines(logs), f"an unauthenticated {path} must not raise: {logs}"


def test_cors_headers_on_api_responses():
    origin = cors_origin()
    if not origin:
        pytest.skip("CORS_ORIGINS is not configured on this deployment")

    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert response.status_code == 200, response.status_code
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert response.headers["Access-Control-Allow-Headers"] == "Content-Type, Authorization"
    assert "OPTIONS" in response.headers["Access-Control-Allow-Methods"]


def test_cors_preflight_short_circuits_dispatch():
    origin = cors_origin()
    if not origin:
        pytest.skip("CORS_ORIGINS is not configured on this deployment")

    response = requests.options(f"{DOJO_URL}/pwncollege_api/v1/docker", allow_redirects=False)
    assert response.status_code == 200, response.status_code
    assert response.content == b"", response.content
    assert response.headers["Access-Control-Max-Age"] == "3600"
    assert response.headers["Access-Control-Allow-Origin"] == origin

    response = requests.options(f"{DOJO_URL}/pwncollege_api/v1/workspace", allow_redirects=False)
    assert response.status_code == 200, (
        f"preflight of an authed-only endpoint must not be redirected to login, got {response.status_code}")


def test_cors_headers_not_applied_outside_api():
    if not cors_origin():
        pytest.skip("CORS_ORIGINS is not configured on this deployment")

    urls = [
        f"{DOJO_URL}/dojos",
        f"{DOJO_URL}/api/v1/users/me",
        f"{DOJO_URL}/pwncollege_api/v1/nope_{uuid.uuid4().hex}",
    ]
    for url in urls:
        headers = requests.get(url).headers
        assert "Access-Control-Allow-Origin" not in headers, f"{url} unexpectedly carries CORS headers"


def test_api_error_response_carries_no_cors_headers(random_user_session):
    if not cors_origin():
        pytest.skip("CORS_ORIGINS is not configured on this deployment")

    ok = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert ok.status_code == 200
    assert "Access-Control-Allow-Origin" in ok.headers

    failed = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error")
    assert failed.status_code == 500
    assert "Access-Control-Allow-Origin" not in failed.headers, (
        "the blueprint after_request does not run for failed requests")


def test_bad_token_authorization_is_unauthorized():
    headers = {"Authorization": f"Token garbage_{uuid.uuid4().hex}", "Content-Type": "application/json"}

    ctfd_response = requests.get(f"{DOJO_URL}/api/v1/users", headers=headers)
    assert ctfd_response.status_code == 401, (
        f"CTFd's own API should reject a bad token with 401, got {ctfd_response.status_code}")

    dojo_response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos", headers=headers)
    assert dojo_response.status_code == 401, (
        f"the dojo API should reject a bad token with 401, got {dojo_response.status_code}")


def test_bearer_bypasses_ctfd_token_auth(admin_session):
    response = admin_session.post(f"{DOJO_URL}/api/v1/tokens", json={"expiration": "2027-01-01"})
    assert response.status_code == 200, f"{response.status_code} - {response.text}"
    token = response.json()["data"]["value"]

    as_token = requests.get(
        f"{DOJO_URL}/api/v1/users/me",
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
    )
    assert as_token.status_code == 200, as_token.status_code
    assert as_token.json()["data"]["id"] == 1

    as_bearer = requests.get(
        f"{DOJO_URL}/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    assert as_bearer.status_code == 403, (
        f"a Bearer credential must not authenticate a CTFd user, got {as_bearer.status_code}")

    anonymous = requests.get(
        f"{DOJO_URL}/pwncollege_api/v1/dojos",
        headers={"Authorization": "Bearer garbage", "Content-Type": "application/json"},
    )
    assert anonymous.status_code == 200, (
        f"a Bearer credential must let the request proceed anonymously, got {anonymous.status_code}")


def test_csrf_protection_on_state_changing_requests():
    _, session = uncsrfed_session()
    url = f"{DOJO_URL}/pwncollege_api/v1/docker"
    payload = {"dojo": "does-not-exist", "module": "y", "challenge": "z"}

    assert session.post(url, json=payload).status_code == 403, "JSON POST without a CSRF token must be rejected"
    assert session.post(url, json=payload, headers={"CSRF-Token": "deadbeef"}).status_code == 403, (
        "JSON POST with a wrong CSRF token must be rejected")

    nonce = parse_csrf_token(session.get(DOJO_URL).text)
    accepted = session.post(url, json=payload, headers={"CSRF-Token": nonce})
    assert accepted.status_code == 200, (
        f"the correct CSRF token must let the request through, got {accepted.status_code}")
    assert accepted.json()["success"] is False, accepted.json()

    assert session.post(url, data={"dojo": "does-not-exist"}).status_code == 403, (
        "form POST without a nonce field must be rejected")
    with_nonce = session.post(url, data={"dojo": "does-not-exist", "nonce": nonce})
    assert with_nonce.status_code != 403, (
        "form POST carrying the session nonce must pass the CSRF check")


def test_csrf_exempts_safe_methods_and_authorization_header():
    _, session = uncsrfed_session()
    url = f"{DOJO_URL}/pwncollege_api/v1/docker"

    assert session.get(url).status_code == 200, "GET is never CSRF checked"
    assert session.options(url).status_code == 200, "OPTIONS is never CSRF checked"

    authorized = session.post(url, json={"dojo": "does-not-exist"}, headers={"Authorization": "Bearer nope"})
    assert authorized.status_code != 403, (
        f"an Authorization header must skip the CSRF check, got {authorized.status_code}")


def test_bypass_csrf_only_applies_to_plain_routes():
    _, session = uncsrfed_session()

    page = session.post(f"{DOJO_URL}/test_page_error", data={"a": "1"})
    assert page.status_code == 500, (
        f"bypass_csrf_protection must be honored for blueprint views, got {page.status_code}")

    resource = session.post(f"{DOJO_URL}/pwncollege_api/v1/test_error", json={"a": 1})
    assert resource.status_code == 403, (
        f"bypass_csrf_protection is not honored for restx resources, got {resource.status_code}")


def test_removed_ctfd_views_return_404(random_user_session, admin_session):
    paths = ["/scoreboard", "/users", "/user", "/profile", "/users/1"]
    anonymous = requests.Session()
    for session in [anonymous, random_user_session, admin_session]:
        for path in paths:
            response = session.get(f"{DOJO_URL}{path}", allow_redirects=False)
            assert response.status_code == 404, f"{path} should be 404, got {response.status_code}"

    assert admin_session.get(f"{DOJO_URL}/api/v1/users/me").status_code == 200, (
        "CTFd's JSON API must be unaffected by the removed HTML views")


def test_challenges_redirects_to_dojos():
    response = requests.get(f"{DOJO_URL}/challenges", allow_redirects=False)
    assert response.status_code == 301, f"Expected a permanent redirect, got {response.status_code}"
    assert response.headers["Location"].endswith("/dojos"), response.headers["Location"]
    assert requests.get(f"{DOJO_URL}/challenges").status_code == 200


def test_index_renders_dojo_listing(welcome_dojo):
    index = requests.get(f"{DOJO_URL}/")
    assert index.status_code == 200, index.status_code
    listing = requests.get(f"{DOJO_URL}/dojos")
    assert listing.status_code == 200, listing.status_code

    assert f"/dojo/{welcome_dojo}" in index.text, (
        "the index route must render the dojo listing, not the empty CTFd index page")
    assert f"/dojo/{welcome_dojo}" in listing.text

    assert requests.get(f"{DOJO_URL}/no_such_page_{uuid.uuid4().hex}").status_code == 404, (
        "other static page routes must still be handled by CTFd")


def test_settings_override_is_authed_only(random_user):
    name, session = random_user

    anonymous = requests.get(f"{DOJO_URL}/settings", allow_redirects=False)
    assert anonymous.status_code == 302, anonymous.status_code
    assert "/login" in anonymous.headers["Location"], anonymous.headers["Location"]

    public_key = random_ssh_public_key()
    stored = session.post(f"{DOJO_URL}/pwncollege_api/v1/ssh_key", json={"ssh_key": public_key})
    assert stored.status_code == 200, f"{stored.status_code} - {stored.text}"
    assert stored.json()["success"], stored.json()

    settings = session.get(f"{DOJO_URL}/settings")
    assert settings.status_code == 200, settings.status_code
    assert public_key.split()[1] in settings.text, "the settings page must surface the user's stored SSH keys"


def test_score_validate_ratelimit():
    endpoint = "pwncollege_api.score_validate_user"
    key = ratelimit_key(endpoint)
    params = {"username": f"nobody_{uuid.uuid4().hex}", "email": "nobody@example.com"}
    url = f"{DOJO_URL}/pwncollege_api/v1/score/validate"
    try:
        clear_ratelimit(endpoint)
        for attempt in range(10):
            response = requests.get(url, params=params)
            assert response.status_code == 200, f"request {attempt} got {response.status_code}"
            assert response.json() == 0, response.json()

        limited = requests.get(url, params=params)
        assert limited.status_code == 429, limited.status_code
        assert limited.json() == {
            "code": 429,
            "message": "Too many requests. Limit is 10 requests in 60 seconds",
        }, limited.json()

        assert requests.Session().get(url, params=params).status_code == 429, (
            "the limiter counts per client IP, so a fresh session is limited too")

        ttl = redis_ttl(key)
        assert 0 < ttl <= 60, f"expected a 60s ttl on {key}, got {ttl}"

        other = requests.get(f"{DOJO_URL}/pwncollege_api/v1/score", params={"username": "nobody"})
        assert other.status_code == 400, (
            f"the limiter is per-endpoint, so /score must stay reachable, got {other.status_code}")
    finally:
        clear_ratelimit(endpoint)


def test_survey_post_ratelimit(surveys_dojo, random_user_session):
    endpoint = "pwncollege_api.dojos_dojo_survey"
    assert random_user_session.get(f"{DOJO_URL}/dojo/{surveys_dojo}/join/").status_code == 200
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{surveys_dojo}/surveys-module-1/challenge-level/surveys"
    try:
        clear_ratelimit(endpoint)
        for attempt in range(15):
            response = random_user_session.get(url)
            assert response.status_code == 200, f"GET {attempt} got {response.status_code}"

        for attempt in range(10):
            response = random_user_session.post(url, json={"response": f"answer-{attempt}"})
            assert response.status_code == 200, f"POST {attempt} got {response.status_code}"

        limited = random_user_session.post(url, json={"response": "one too many"})
        assert limited.status_code == 429, limited.status_code
        assert limited.json()["code"] == 429, limited.json()

        assert random_user_session.get(url).status_code == 200, "GET on the same route is not limited"
    finally:
        clear_ratelimit(endpoint)


def test_course_identity_patch_ratelimit(middleware_course_dojo, random_user_session):
    endpoint = "course.update_identity"
    assert random_user_session.get(f"{DOJO_URL}/dojo/{middleware_course_dojo}/join/").status_code == 200
    url = f"{DOJO_URL}/dojo/{middleware_course_dojo}/course/identity"
    try:
        clear_ratelimit(endpoint)
        for attempt in range(10):
            response = random_user_session.patch(url, json={"identity": f"id-{attempt}"})
            assert response.status_code == 200, f"PATCH {attempt} got {response.status_code}"
            assert response.json()["success"], response.json()

        limited = random_user_session.patch(url, json={"identity": "id-too-many"})
        assert limited.status_code == 429, limited.status_code
        assert limited.json()["code"] == 429, limited.json()

        page = random_user_session.get(f"{DOJO_URL}/dojo/{middleware_course_dojo}/course")
        assert page.status_code == 200, f"the course page itself is not rate limited, got {page.status_code}"
    finally:
        clear_ratelimit(endpoint)


def test_theme_asset_versioning_rules():
    stdout, _ = flask_run(
        "from flask import url_for, current_app\n"
        "with current_app.test_request_context('/'):\n"
        "    print('CSS', url_for('views.themes', path='css/custom.css'))\n"
        "    print('IMAGE', url_for('views.themes', path='img/favicon.png'))\n"
        "    print('FONT', url_for('views.themes', path='font/SpaceMono-Regular.ttf'))\n"
        "    print('OTHER_THEME', url_for('views.themes', theme='admin', path='css/custom.css'))\n"
        "    print('PINNED', url_for('views.themes', path='css/custom.css', v='pinned'))\n"
        "    print('MISSING', url_for('views.themes', path='css/nope-does-not-exist.css'))\n"
        "    print('TRAVERSAL', url_for('views.themes', path='../../../../etc/passwd.css'))\n"
    )
    urls = dict(line.split(" ", 1) for line in stdout.strip().splitlines() if " " in line)

    assert "v=" in urls["CSS"], f"theme css must be versioned: {urls['CSS']}"
    digest = re.search(r"v=([0-9a-f]+)", urls["CSS"]).group(1)

    for name in ["IMAGE", "FONT", "OTHER_THEME", "MISSING", "TRAVERSAL"]:
        assert "v=" not in urls[name], f"{name} must not be versioned: {urls[name]}"

    assert "v=pinned" in urls["PINNED"], urls["PINNED"]
    assert digest not in urls["PINNED"], f"an explicit version must be preserved: {urls['PINNED']}"

    page = requests.get(DOJO_URL)
    assert page.status_code == 200
    favicon = re.search(r'"([^"]*/themes/dojo_theme/static/img/favicon\.png[^"]*)"', page.text)
    assert favicon, "index page does not reference the theme favicon"
    assert "v=" not in favicon.group(1), f"images must not be versioned: {favicon.group(1)}"

    fallback = re.search(r'"([^"]*/themes/dojo_theme/static/css/main\.(?:dev|min)\.css[^"]*)"', page.text)
    assert fallback, "index page does not reference the core theme stylesheet"
    assert "v=" not in fallback.group(1), (
        f"an asset missing from the configured theme must render unversioned: {fallback.group(1)}")

    versioned = re.search(r'"([^"]*/themes/dojo_theme/static/js/dojo/[^"]*\.js[^"]*)"', page.text)
    assert versioned and "v=" in versioned.group(1), "dojo theme javascript should be versioned"

    traversal = requests.get(f"{DOJO_URL}/themes/dojo_theme/static/../../../../etc/passwd.css")
    assert traversal.status_code in (400, 404), traversal.status_code
    assert "root:" not in traversal.text


def test_redirect_dojo_canonical_host():
    stdout, _ = flask_run(
        "from flask import current_app\n"
        "from CTFd.plugins.dojo_plugin import redirect_dojo\n"
        "from CTFd.plugins.dojo_plugin.config import DOJO_HOST\n"
        "print('HOST', DOJO_HOST)\n"
        "with current_app.test_request_context('/dojos?a=b', headers={'X-Forwarded-For': '1.2.3.4', 'Host': '1.2.3.4'}):\n"
        "    r = redirect_dojo()\n"
        "    print('PROXIED', r.status_code, r.headers['Location'])\n"
        "with current_app.test_request_context('/dojos?a=b', headers={'Host': '1.2.3.4'}):\n"
        "    print('DIRECT', redirect_dojo())\n"
        "with current_app.test_request_context('/dojos?a=b', headers={'X-Forwarded-For': '1.2.3.4', 'Host': DOJO_HOST}):\n"
        "    print('CANONICAL', redirect_dojo())\n"
        "with current_app.test_request_context('/dojos?a=b', headers={'X-Forwarded-For': '1.2.3.4', 'Host': '1.2.3.4:8443'}):\n"
        "    r = redirect_dojo()\n"
        "    print('PORT', r.status_code, r.headers['Location'])\n"
    )
    lines = dict(line.split(" ", 1) for line in stdout.strip().splitlines() if " " in line)
    host = lines["HOST"].strip()

    assert lines["PROXIED"] == f"301 http://{host}/dojos?a=b", lines["PROXIED"]
    assert lines["DIRECT"] == "None", f"no redirect without X-Forwarded-For: {lines['DIRECT']}"
    assert lines["CANONICAL"] == "None", f"no redirect when the host already matches: {lines['CANONICAL']}"
    assert lines["PORT"] == f"301 http://{host}:8443/dojos?a=b", lines["PORT"]


def test_api_namespaces_mounted():
    stdout, _ = flask_run(
        "from flask import current_app\n"
        "for rule in current_app.url_map.iter_rules():\n"
        "    if rule.endpoint.startswith('pwncollege_api.'):\n"
        "        print('RULE', rule.rule)\n"
    )
    rules = [line.split(" ", 1)[1] for line in stdout.strip().splitlines() if line.startswith("RULE ")]
    assert rules, stdout

    namespaces = [
        "activity", "auth", "users", "belts", "discord", "docker", "dojos", "feed",
        "score", "scoreboard", "ssh_key", "workspace_tokens", "workspace", "search", "test_error",
    ]
    for namespace in namespaces:
        prefix = f"/pwncollege_api/v1/{namespace}"
        assert any(rule.startswith(prefix) for rule in rules), f"namespace {namespace} is not mounted"

    assert not any(rule.startswith("/api/v1") for rule in rules), (
        "dojo API rules must not collide with CTFd's own /api/v1 prefix")


def test_api_routes_are_strict_about_trailing_slashes():
    assert requests.get(f"{DOJO_URL}/pwncollege_api/v1/belts").status_code == 200
    trailing = requests.get(f"{DOJO_URL}/pwncollege_api/v1/belts/", allow_redirects=False)
    assert trailing.status_code == 404, f"Expected 404, got {trailing.status_code}"


def test_swagger_ui_is_disabled():
    assert requests.get(f"{DOJO_URL}/pwncollege_api/v1/").status_code == 404, (
        "no interactive docs page should be served")


def test_swagger_schema_renders():
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/swagger.json")
    assert response.status_code == 200, f"{response.status_code} - {response.text}"
    assert "paths" in response.json(), response.json()


def test_bootstrap_config_defaults():
    rows = config_rows(
        "SELECT key, value FROM config WHERE key IN "
        "('ctf_name','ctf_description','user_mode','challenge_visibility','registration_visibility',"
        "'score_visibility','account_visibility','ctf_theme','setup')"
    )
    assert rows == {
        "ctf_name": "pwn.college",
        "ctf_description": "pwn.college",
        "user_mode": "users",
        "challenge_visibility": "public",
        "registration_visibility": "public",
        "score_visibility": "public",
        "account_visibility": "public",
        "ctf_theme": "dojo_theme",
        "setup": "true",
    }, rows

    assert requests.get(f"{DOJO_URL}/dojos").status_code == 200, "challenge visibility should be public"
    assert requests.get(f"{DOJO_URL}/register").status_code == 200, "registration should be public"


def test_bootstrap_mail_config_from_env():
    env = {name: ctfd_env(name) for name in ("MAIL_SERVER", "MAIL_PORT", "MAIL_USERNAME", "MAIL_ADDRESS")}
    rows = config_rows("SELECT key, value FROM config WHERE key LIKE 'mail%' OR key = 'mailfrom_addr'")

    assert rows["mail_server"] == env["MAIL_SERVER"], rows
    assert rows["mail_port"] == env["MAIL_PORT"], rows
    assert rows["mailfrom_addr"] == env["MAIL_ADDRESS"], rows
    assert rows["mail_useauth"] == str(bool(env["MAIL_USERNAME"])).lower(), rows
    assert rows["mail_tls"] == str(env["MAIL_PORT"] in ("465", "587")).lower(), rows


def test_bootstrap_admin_and_index_page_are_idempotent():
    def snapshot():
        return (
            db_sql("SELECT name, type, hidden FROM users WHERE id = 1").strip(),
            int(db_sql("SELECT count(*) FROM users WHERE type = 'admin' AND name = 'admin'")),
            int(db_sql("SELECT count(*) FROM pages WHERE route = 'index'")),
            db_sql("SELECT route, coalesce(content, ''), draft FROM pages WHERE route = 'index'").strip(),
        )

    before = snapshot()
    assert before[0] == "admin|admin|t", before[0]
    assert before[1] == 1, before[1]
    assert before[2] == 1, before[2]
    assert before[3] == "index||f", before[3]

    flask_run("from CTFd.plugins.dojo_plugin.config import bootstrap\nbootstrap()\nprint('BOOTSTRAPPED')\n")

    assert snapshot() == before, "re-running bootstrap must not duplicate the admin or the index page"


def test_session_lifetime_is_180_days():
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    login(name, name, register=True)

    session = requests.Session()
    nonce = parse_csrf_token(session.get(f"{DOJO_URL}/login").text)
    response = session.post(
        f"{DOJO_URL}/login",
        data={"name": name, "password": name, "nonce": nonce},
        allow_redirects=False,
    )
    assert response.status_code == 302, response.status_code

    cookies = [value for value in response.raw.headers.getlist("Set-Cookie") if value.startswith("session=")]
    assert cookies, response.raw.headers.getlist("Set-Cookie")
    cookie = cookies[-1]

    expires_match = re.search(r"Expires=([^;]+)", cookie)
    assert expires_match, f"login must set a persistent session cookie: {cookie}"
    remaining = parsedate_to_datetime(expires_match.group(1)) - datetime.datetime.now(datetime.timezone.utc)
    assert 179 <= remaining.days <= 180, f"expected ~180 days of session lifetime, got {remaining}"
    assert "HttpOnly" in cookie, cookie
    assert "SameSite=Lax" in cookie, cookie


def test_trace_id_comes_from_nginx_and_is_not_spoofable():
    for headers in [{}, {"PWN-Trace-ID": "a" * 32}]:
        marker = uuid.uuid4().hex
        response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/belts", params={"m": marker}, headers=headers)
        assert response.status_code == 200, response.status_code

        nginx_logs = wait_for_log(marker, marker, container="nginx")
        entries = [json.loads(line) for line in nginx_logs.splitlines() if line.startswith("{")]
        entries = [entry for entry in entries if marker in entry.get("request", "")]
        assert entries, f"no nginx access log entry for {marker}: {nginx_logs}"
        request_id = entries[-1]["request_id"]

        ctfd_logs = wait_for_log(marker, "logger=werkzeug")
        line = next((line for line in ctfd_logs.splitlines() if "logger=werkzeug" in line), None)
        assert line, f"no ctfd access log line for {marker}: {ctfd_logs}"
        trace_id = re.search(r"trace_id=(\S+)", line).group(1)

        assert trace_id == request_id, f"ctfd trace_id {trace_id} != nginx request_id {request_id}"
        assert re.fullmatch(r"[0-9a-f]{32}", trace_id), trace_id
        assert trace_id != "a" * 32, "a client supplied PWN-Trace-ID must be overwritten by nginx"


def test_trace_id_is_local_for_direct_requests():
    marker = uuid.uuid4().hex
    dojo_run(
        "docker", "exec", "ctfd", "python3", "-c",
        f"import urllib.request; urllib.request.urlopen('http://localhost:8000/healthcheck?m={marker}')",
    )
    logs = wait_for_log(marker, "logger=werkzeug")
    line = next((line for line in logs.splitlines() if "logger=werkzeug" in line), None)
    assert line, f"no log line for the direct request: {logs}"
    assert "trace_id=LOCAL" in line, line
    assert "remote_ip=127.0.0.1" in line, line


LOG_PREFIX = re.compile(
    r'^time="[^"]+" trace_id=\S+ request_reltime=\S+ remote_ip=\S+ user_id=\S+ logger=\S+ (INFO|WARNING|ERROR) '
)


def test_log_lines_use_the_shared_format(random_user_name):
    user_id = get_user_id(random_user_name)
    login(random_user_name, random_user_name)

    registrations = wait_for_log(random_user_name, "logger=registrations")
    registration_lines = [line for line in registrations.splitlines() if "logger=registrations" in line]
    assert registration_lines, f"no registration log line for {random_user_name}: {registrations}"

    logins = wait_for_log(random_user_name, "logger=logins")
    login_lines = [line for line in logins.splitlines() if "logger=logins" in line]
    assert login_lines, f"no login log line for {random_user_name}: {logins}"

    for line in registration_lines + login_lines:
        assert LOG_PREFIX.match(line), f"CTFd log line is not using the shared handler format: {line}"

    for line in registration_lines:
        assert f"user_id={user_id} logger=" in line, line


def test_plugin_logger_names_are_rewritten(random_user_session):
    marker = uuid.uuid4().hex
    assert random_user_session.get(f"{DOJO_URL}/test_page_error", params={"marker": marker}).status_code == 500
    logs = wait_for_log(marker, "PAGE_EXCEPTION")

    assert "logger=dojo_plugin.utils.request_logging" in logs, logs
    assert "logger=CTFd.plugins.dojo_plugin" not in logs, logs

    recent = dojo_run("sh", "-c", f"docker logs --since {LOG_WINDOW} ctfd 2>&1 | tail -n 500").stdout
    assert "logger=CTFd.plugins.dojo_plugin" not in recent, (
        "plugin log records must be renamed to dojo_plugin.*")


def test_log_reltime_tracks_request_duration(random_user_session):
    slow_marker = uuid.uuid4().hex
    slow = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/slow_query", params={"m": slow_marker})
    assert slow.status_code == 200, slow.status_code

    fast_marker = uuid.uuid4().hex
    fast = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/belts", params={"m": fast_marker})
    assert fast.status_code == 200, fast.status_code

    def access_log_reltime(marker):
        logs = wait_for_log(marker, "logger=werkzeug")
        line = next((line for line in logs.splitlines() if "logger=werkzeug" in line), None)
        assert line, f"no access log line for {marker}: {logs}"
        return float(re.search(r"request_reltime=(\S+)", line).group(1))

    assert access_log_reltime(slow_marker) >= 1.0, "a 1s query must be reflected in the request duration"
    assert access_log_reltime(fast_marker) < 1.0, "a trivial request must not report a second of work"


def test_slow_query_logged_with_context(random_user):
    name, session = random_user
    user_id = get_user_id(name)

    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/slow_query")
    assert response.status_code == 200, response.status_code
    assert response.json() == {"status": "ok", "result": 1}, response.json()

    logs = wait_for_log(f"user=<Users {user_id}>", "Slow query")
    line = next((line for line in logs.splitlines() if "Slow query" in line), None)
    assert line, f"no slow query record attributed to user {user_id}: {logs}"
    assert "logger=dojo.query_timer" in line, line
    assert " WARNING " in line, line
    query_time = float(re.search(r"query_time=([0-9.]+)s", line).group(1))
    assert 0.9 <= query_time <= 3.0, line
    assert "traceback_str='dojo_plugin/api/v1/test_error.py:" in line, line
    assert line.rstrip().endswith(":get'"), line


def test_slow_query_outside_dojo_code():
    _, stderr = flask_run(
        "from CTFd.models import db\n"
        "from sqlalchemy import text\n"
        "db.session.execute(text('SELECT pg_sleep(0.7)'))\n"
        "print('SLEPT')\n"
    )
    assert "logger=dojo.query_timer WARNING Slow query:" in stderr, stderr
    assert "user=None" in stderr, "no request context means no user rather than an error"
    assert "traceback_str='no_dojo_frames'" in stderr, stderr


def test_query_timeout_semantics(random_user_session):
    stdout, _ = flask_run(
        "from CTFd.models import db\n"
        "from sqlalchemy import text\n"
        "from sqlalchemy.exc import DBAPIError\n"
        "from CTFd.plugins.dojo_plugin.utils.query_timer import query_timeout\n"
        "try:\n"
        "    query_timeout(lambda: db.session.execute(text('SELECT 1/0')).fetchone(), 5000, 'DEFAULT')\n"
        "    print('DIVISION NO_RAISE')\n"
        "except DBAPIError:\n"
        "    print('DIVISION RAISED')\n"
        "db.session.rollback()\n"
        "print('CAPPED', query_timeout(lambda: db.session.execute(text('SELECT pg_sleep(5)')).fetchone(), 300, 'DEFAULT'))\n"
        "print('SETTING', db.session.execute(text('SHOW statement_timeout')).fetchone()[0])\n"
    )
    lines = dict(line.split(" ", 1) for line in stdout.strip().splitlines() if " " in line)

    assert lines["DIVISION"] == "RAISED", f"a non-timeout DBAPIError must propagate: {stdout}"
    assert lines["CAPPED"] == "DEFAULT", f"a timed-out query must return the default: {stdout}"
    assert lines["SETTING"] == "0", f"statement_timeout must be reset in the finally block: {stdout}"

    for _ in range(2):
        capped = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/capped_query")
        assert capped.status_code == 200, capped.status_code
        assert capped.json()["result"] == "TIMEOUT", capped.json()

    slow = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/slow_query")
    assert slow.status_code == 200, slow.status_code
    assert slow.json() == {"status": "ok", "result": 1}, (
        "a later long query must not be killed by a leftover statement_timeout")


def test_dojo_flag_from_another_user_is_rejected(example_dojo, random_user):
    victim_name = "".join(random.choices(string.ascii_lowercase, k=16))
    login(victim_name, victim_name, register=True)

    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    other_flag = challenge_flag(example_dojo, "hello", "apple", user=victim_name)
    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/hello/apple/solve",
        json={"submission": other_flag},
    )
    assert response.status_code == 400, f"{response.status_code} - {response.text}"
    assert response.json() == {"success": False, "status": "incorrect"}, response.json()

    assert int(db_sql(f"SELECT count(*) FROM submissions WHERE user_id = {user_id} AND type = 'correct'")) == 0
    assert int(db_sql(f"SELECT count(*) FROM submissions WHERE user_id = {user_id} AND type = 'incorrect'")) >= 1


def test_dojo_flag_from_another_challenge_is_rejected(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    apple_flag = challenge_flag(example_dojo, "hello", "apple", user=name)
    banana_flag = challenge_flag(example_dojo, "hello", "banana", user=name)

    wrong = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/hello/banana/solve",
        json={"submission": apple_flag},
    )
    assert wrong.status_code == 400, f"{wrong.status_code} - {wrong.text}"
    assert wrong.json() == {"success": False, "status": "incorrect"}, wrong.json()
    assert int(db_sql(f"SELECT count(*) FROM submissions WHERE user_id = {user_id} AND type = 'correct'")) == 0

    correct = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/hello/banana/solve",
        json={"submission": banana_flag},
    )
    assert correct.status_code == 200, f"{correct.status_code} - {correct.text}"
    assert correct.json() == {"success": True, "status": "solved"}, correct.json()
    assert int(db_sql(f"SELECT count(*) FROM submissions WHERE user_id = {user_id} AND type = 'correct'")) == 1


def test_dojo_flag_garbage_is_rejected_without_raising(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    real_flag = challenge_flag(example_dojo, "hello", "apple", user=name)
    submissions = ["", "pwn.college{not-a-real-flag}", real_flag[:-4] + "xyz}"]

    markers = []
    for submission in submissions:
        marker = uuid.uuid4().hex
        markers.append(marker)
        response = session.post(
            f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/hello/apple/solve",
            params={"m": marker},
            json={"submission": submission},
        )
        assert response.status_code == 400, f"{submission!r} -> {response.status_code} {response.text}"
        assert response.json() == {"success": False, "status": "incorrect"}, response.json()

    assert int(db_sql(f"SELECT count(*) FROM submissions WHERE user_id = {user_id} AND type = 'correct'")) == 0

    for marker in markers:
        logs = wait_for_log(marker, "logger=werkzeug")
        assert not exception_lines(logs), f"a bad signature must be handled, not raised: {logs}"


def test_already_solved_is_idempotent(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    flag = challenge_flag(example_dojo, "hello", "apple", user=name)
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/hello/apple/solve"

    first = session.post(url, json={"submission": flag})
    assert first.status_code == 200, f"{first.status_code} - {first.text}"
    assert first.json() == {"success": True, "status": "solved"}, first.json()
    solves = int(db_sql(f"SELECT count(*) FROM submissions WHERE user_id = {user_id} AND type = 'correct'"))
    assert solves == 1, solves

    second = session.post(url, json={"submission": flag})
    assert second.status_code == 200, f"{second.status_code} - {second.text}"
    assert second.json() == {"success": True, "status": "already_solved"}, second.json()
    assert int(db_sql(f"SELECT count(*) FROM submissions WHERE user_id = {user_id} AND type = 'correct'")) == solves


def test_queued_stat_events_published_after_request(example_dojo, random_user):
    name, session = random_user
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/").status_code == 200

    flag = challenge_flag(example_dojo, "hello", "apple", user=name)
    marker = uuid.uuid4().hex
    before = stream_entries_added()

    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/hello/apple/solve",
        params={"m": marker},
        json={"submission": flag},
    )
    assert response.status_code == 200, f"{response.status_code} - {response.text}"
    assert response.json()["status"] == "solved", response.json()

    after = stream_entries_added()
    assert after > before, "stat events must be on the stream by the time the response returns"

    logs = wait_for_log(marker, "logger=werkzeug")
    line = next((line for line in logs.splitlines() if "logger=werkzeug" in line), None)
    assert line, f"no access log line for the solve: {logs}"
    trace_id = re.search(r"trace_id=(\S+)", line).group(1)

    traced = wait_for_log(f"trace_id={trace_id} ", "queued stat events after request")
    published = [line for line in traced.splitlines() if "queued stat events after request" in line]
    assert published, f"no flush of queued stat events for trace {trace_id}: {traced}"
    assert all("logger=dojo_plugin.utils.events" in line for line in published), published


def test_markdown_filter_registered_and_sanitizing():
    stdout, _ = flask_run(
        "from flask import current_app\n"
        "renderer = current_app.jinja_env.filters['markdown']\n"
        "print('RENDERED', renderer('**bold** <script>alert(1)</script> <img src=x onerror=alert(1)>').replace('\\n', ' '))\n"
        "print('EMPTY', repr(str(renderer(None))))\n"
    )
    lines = dict(line.split(" ", 1) for line in stdout.strip().splitlines() if " " in line)

    rendered = lines["RENDERED"]
    assert "<strong>bold</strong>" in rendered, rendered
    assert "<script>" not in rendered, rendered
    assert "onerror" not in rendered, rendered
    assert lines["EMPTY"] == "''", f"the markdown filter must tolerate None: {lines['EMPTY']}"


def test_shell_context_exposes_models():
    result = dojo_run(
        "dojo", "flask",
        input='print("SHELLOK", Dojos.__tablename__, DojoChallenges.__tablename__, Users.__tablename__)\n',
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "SHELLOK dojos dojo_challenges users" in result.stdout, result.stdout


def assert_admin_menu_target(path, random_user_session, admin_session):
    anonymous = requests.get(f"{DOJO_URL}{path}", allow_redirects=False)
    assert anonymous.status_code == 302, f"anonymous {path} -> {anonymous.status_code}"
    assert "/login" in anonymous.headers["Location"], anonymous.headers["Location"]

    as_user = random_user_session.get(f"{DOJO_URL}{path}", allow_redirects=False)
    assert as_user.status_code in (302, 403), f"non-admin {path} -> {as_user.status_code}"

    as_admin = admin_session.get(f"{DOJO_URL}{path}")
    assert as_admin.status_code == 200, f"admin {path} -> {as_admin.status_code}"


def test_admin_dojos_menu_target_resolves(random_user_session, admin_session):
    assert_admin_menu_target("/admin/dojos", random_user_session, admin_session)


def test_registered_admin_menu_targets_all_resolve(random_user_session, admin_session):
    targets = json.loads(flask_exec(
        "import json\n"
        "from CTFd.plugins import get_admin_plugin_menu_bar\n"
        "print(json.dumps([entry.route for entry in get_admin_plugin_menu_bar()]))\n"
    ))
    assert targets, "the plugin must register at least one admin menu entry"
    for path in targets:
        assert_admin_menu_target(path, random_user_session, admin_session)
