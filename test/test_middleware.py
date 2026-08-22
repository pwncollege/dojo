import json
import random
import re
import shlex
import socket
import string
import time
import uuid
from urllib.parse import urlparse

import pytest
import requests

from utils import (
    DOJO_URL,
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


def cors_origin():
    return dojo_run("docker", "exec", "ctfd", "printenv", "CORS_ORIGINS", check=False).stdout.strip()


def uncsrfed_session():
    """A logged-in session that does NOT send the CSRF-Token header."""
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    session = login(name, name, register=True)
    del session.headers["CSRF-Token"]
    return name, session


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


def test_api_routes_are_strict_about_trailing_slashes():
    assert requests.get(f"{DOJO_URL}/pwncollege_api/v1/belts").status_code == 200
    trailing = requests.get(f"{DOJO_URL}/pwncollege_api/v1/belts/", allow_redirects=False)
    assert trailing.status_code == 404, f"Expected 404, got {trailing.status_code}"


def test_swagger_schema_renders():
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/swagger.json")
    assert response.status_code == 200, f"{response.status_code} - {response.text}"
    assert "paths" in response.json(), response.json()


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


def assert_admin_menu_target(path, random_user_session, admin_session):
    anonymous = requests.get(f"{DOJO_URL}{path}", allow_redirects=False)
    assert anonymous.status_code == 302, f"anonymous {path} -> {anonymous.status_code}"
    assert "/login" in anonymous.headers["Location"], anonymous.headers["Location"]

    as_user = random_user_session.get(f"{DOJO_URL}{path}", allow_redirects=False)
    assert as_user.status_code in (302, 403), f"non-admin {path} -> {as_user.status_code}"

    as_admin = admin_session.get(f"{DOJO_URL}{path}")
    assert as_admin.status_code == 200, f"admin {path} -> {as_admin.status_code}"


def test_registered_admin_menu_targets_all_resolve(random_user_session, admin_session):
    targets = json.loads(flask_exec(
        "import json\n"
        "from CTFd.plugins import get_admin_plugin_menu_bar\n"
        "print(json.dumps([entry.route for entry in get_admin_plugin_menu_bar()]))\n"
    ))
    assert targets, "the plugin must register at least one admin menu entry"
    for path in targets:
        assert_admin_menu_target(path, random_user_session, admin_session)
