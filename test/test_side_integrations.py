import json
import random
import string
import textwrap

import pytest
import requests

from utils import (
    DOJO_URL,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    flask_exec,
    get_user_id,
    login,
    make_dojo_official,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
)


DISCORD_API = f"{DOJO_URL}/pwncollege_api/v1/discord"


DOJO_FILES_SPEC = """
files:
  - type: text
    path: lessons/first/src
    content: |
      #!/opt/pwn.college/bash
      cat /flag
"""


def random_name(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def register_side_user(discord_id_base):
    name = random_name(16)
    session = login(name, name, register=True)
    user_id = get_user_id(name)
    return name, session, user_id, discord_id_base + user_id


def config_env_value(key):
    for line in dojo_run("cat", "/data/config.env", check=False).stdout.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def link_discord(user_id, discord_id):
    db_sql(f"INSERT INTO discord_users (user_id, discord_id) VALUES ({user_id}, {discord_id})")


def unlink_discord(user_id):
    db_sql(f"DELETE FROM discord_users WHERE user_id = {user_id}")


def set_course(dojo_reference_id, course):
    dojo_id = dojo_db_id(dojo_reference_id)
    data = json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id = {dojo_id}"))
    data["course"] = course
    db_sql(f"UPDATE dojos SET data = '{json.dumps(data)}' WHERE dojo_id = {dojo_id}")


def dojo_challenge_ids(dojo_reference_id):
    rows = db_sql(
        "SELECT dm.id, dc.id FROM dojo_challenges dc "
        "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = {dojo_db_id(dojo_reference_id)} "
        "ORDER BY dc.module_index, dc.challenge_index"
    )
    return [tuple(line.split("|")) for line in rows.strip().splitlines() if line]


def index_next_section(text):
    start = text.index("YOUR Journey")
    end = text.index("Side Quests")
    assert start < end, "index page did not render the next-steps section"
    return text[start:end]


def site_direct(url, session=None, method=None):
    """Talk to the site container behind nginx's back, so the headers nginx consumes stay visible."""
    args = ["docker", "exec", "nginx", "curl", "-s", "-i"]
    if session is not None:
        cookie = "; ".join(f"{name}={value}" for name, value in session.cookies.get_dict().items())
        args += ["-H", f"Cookie: {cookie}"]
    if method:
        args += ["-X", method]
    raw = dojo_run(*args, url).stdout.replace("\r\n", "\n")
    head, _, body = raw.partition("\n\n")
    lines = head.split("\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return status, headers, body


@pytest.fixture(scope="module")
def side_user():
    return register_side_user(60_000_000_000)


@pytest.fixture(scope="module")
def side_other_user():
    return register_side_user(61_000_000_000)


@pytest.fixture
def linked_discord_user(side_user):
    _, _, user_id, discord_id = side_user
    unlink_discord(user_id)
    link_discord(user_id, discord_id)
    try:
        yield side_user
    finally:
        unlink_discord(user_id)


@pytest.fixture(scope="module")
def side_official_course_dojo(admin_session):
    spec = f"""
id: si-official-course-{random_name()}
name: Side Integrations Official Course Dojo
type: course
modules:
  - id: lessons
    name: Lessons
    challenges:
      - id: first
        name: First
{DOJO_FILES_SPEC}"""
    rid = create_dojo_yml(spec, session=admin_session)
    make_dojo_official(rid, admin_session)
    return rid


def test_unlink_discord_deletes_only_the_callers_row_and_is_idempotent(linked_discord_user, side_other_user):
    _, session, user_id, _ = linked_discord_user
    _, _, other_user_id, other_discord_id = side_other_user
    unlink_discord(other_user_id)
    link_discord(other_user_id, other_discord_id)
    try:
        response = session.delete(f"{DOJO_URL}/pwncollege_api/v1/discord", json={})
        assert response.status_code == 200, f"expected 200, got {response.status_code}"
        assert response.json() == {"success": True}, response.json()
        assert int(db_sql(f"SELECT count(*) FROM discord_users WHERE user_id = {user_id}")) == 0
        assert int(db_sql(f"SELECT count(*) FROM discord_users WHERE user_id = {other_user_id}")) == 1, \
            "unlinking must not touch another user's discord link"

        response = session.delete(f"{DOJO_URL}/pwncollege_api/v1/discord", json={})
        assert response.status_code == 200, f"unlinking twice returned {response.status_code}"
        assert response.json() == {"success": True}, response.json()
    finally:
        unlink_discord(other_user_id)


def test_unlink_discord_requires_auth_and_csrf(linked_discord_user):
    _, session, user_id, _ = linked_discord_user

    response = requests.delete(f"{DOJO_URL}/pwncollege_api/v1/discord", json={})
    assert response.status_code in (302, 403), f"anonymous unlink returned {response.status_code}"
    assert int(db_sql(f"SELECT count(*) FROM discord_users WHERE user_id = {user_id}")) == 1

    response = session.delete(f"{DOJO_URL}/pwncollege_api/v1/discord")
    assert response.status_code == 403, f"a non-JSON unlink must fail CSRF, got {response.status_code}"
    assert int(db_sql(f"SELECT count(*) FROM discord_users WHERE user_id = {user_id}")) == 1


def test_discord_connect_requires_login():
    for path in ["/discord/connect", "/discord/redirect"]:
        response = requests.get(f"{DOJO_URL}{path}", allow_redirects=False)
        assert response.status_code == 302, f"{path} returned {response.status_code}"
        location = response.headers["Location"]
        assert location.startswith("/login?next="), location
        assert path in location, location


def test_discord_connect_unconfigured_returns_501(side_other_user):
    if config_env_value("DISCORD_CLIENT_ID"):
        pytest.skip("deployment has a DISCORD_CLIENT_ID configured")
    _, session, _, _ = side_other_user
    for path in ["/discord/connect", "/discord/redirect"]:
        response = session.get(f"{DOJO_URL}{path}", allow_redirects=False)
        assert response.status_code == 501, f"{path} returned {response.status_code}, expected 501"


def discord_oauth_case(user, code):
    name, session = user
    setup = (
        "import importlib\n"
        "from urllib.parse import parse_qs, urlsplit\n"
        "from unittest.mock import patch\n"
        "from flask import current_app\n"
        "from dojo.models import db\n"
        "from dojo.models import DiscordUsers\n"
        "discord_pages = importlib.import_module('dojo.pages.discord')\n"
        "app = current_app._get_current_object()\n"
        "client = app.test_client()\n"
        f"client.set_cookie(app.config['SESSION_COOKIE_NAME'], {session.cookies.get('session')!r})\n"
        f"user_id = {get_user_id(name)}\n"
    )
    output = flask_exec(setup + textwrap.dedent(code) + "\nprint('DISCORD-OAUTH-PASSED')\n")
    assert "DISCORD-OAUTH-PASSED" in output.splitlines(), output


def test_discord_stats_endpoints_are_retired(side_user):
    _, session, _, discord_id = side_user
    paths = [
        f"/activity/{discord_id}",
        f"/memes/user/{discord_id}", f"/thanks/user/{discord_id}",
        "/thanks/leaderboard",
        "/course/test/memes", "/course/test/thanks",
    ]
    for path in paths:
        response = session.get(f"{DISCORD_API}{path}")
        assert response.status_code == 404, f"retired endpoint {path} returned {response.status_code}"
    for path in [f"/memes/user/{discord_id}", f"/thanks/user/{discord_id}"]:
        response = session.post(f"{DISCORD_API}{path}", json={})
        assert response.status_code == 404, f"retired endpoint {path} returned {response.status_code}"


def test_discord_oauth_link_relink_and_provider_recovery(random_user):
    discord_oauth_case(random_user, """
        from dojo.utils import awards as award_utils

        accounts = {"first": 80_000_000_000 + user_id, "second": 81_000_000_000 + user_id}
        granted_roles = set()
        member = lambda discord_id: {"roles": []} if discord_id == accounts["second"] else None
        with patch.object(discord_pages, "DISCORD_CLIENT_ID", "test-client"), \
             patch.object(discord_pages, "get_discord_member", side_effect=member), \
             patch.object(discord_pages, "add_role", side_effect=lambda discord_id, role: granted_roles.add((discord_id, role))), \
             patch.object(award_utils, "get_discord_member", return_value=None), \
             patch.object(award_utils, "get_discord_roles", return_value={}):
            try:
                connect = client.get("/discord/connect")
                assert connect.status_code == 302
                authorize = parse_qs(urlsplit(connect.location).query)
                assert authorize["scope"] == ["identify"]
                state = authorize["state"][0]

                with patch.object(discord_pages, "get_discord_id", side_effect=RuntimeError("provider unavailable")):
                    failed = client.get("/discord/redirect", query_string={"state": state, "code": "first"})
                assert failed.status_code == 400, failed.get_data(as_text=True)
                assert DiscordUsers.query.filter_by(user_id=user_id).first() is None

                with patch.object(discord_pages, "get_discord_id", side_effect=accounts.__getitem__):
                    for code in ["first", "second"]:
                        connected = client.get("/discord/connect")
                        state = parse_qs(urlsplit(connected.location).query)["state"][0]
                        linked = client.get("/discord/redirect", query_string={"state": state, "code": code})
                        assert linked.status_code == 302, linked.get_data(as_text=True)
                        assert urlsplit(linked.location).path == "/settings"
                        assert DiscordUsers.query.filter_by(user_id=user_id).one().discord_id == accounts[code]
                assert granted_roles == {(accounts["second"], "White Belt")}
            finally:
                DiscordUsers.query.filter_by(user_id=user_id).delete()
                db.session.commit()
    """)


def test_discord_oauth_account_conflict_preserves_both_links(random_user):
    _, _, other_id, other_discord_id = register_side_user(82_000_000_000)
    discord_oauth_case(random_user, f"""
        original_discord_id = 83_000_000_000 + user_id
        db.session.add_all([
            DiscordUsers(user_id=user_id, discord_id=original_discord_id),
            DiscordUsers(user_id={other_id}, discord_id={other_discord_id}),
        ])
        db.session.commit()
        try:
            with patch.object(discord_pages, "DISCORD_CLIENT_ID", "test-client"), \\
                 patch.object(discord_pages, "get_discord_member", return_value=None), \\
                 patch.object(discord_pages, "get_discord_id", return_value={other_discord_id}):
                connected = client.get("/discord/connect")
                state = parse_qs(urlsplit(connected.location).query)["state"][0]
                response = client.get("/discord/redirect", query_string={{"state": state, "code": "other-account"}})
                assert response.status_code == 400, response.get_data(as_text=True)
                assert response.get_json()["success"] is False
                assert DiscordUsers.query.filter_by(user_id=user_id).one().discord_id == original_discord_id
                assert DiscordUsers.query.filter_by(user_id={other_id}).one().discord_id == {other_discord_id}
        finally:
            DiscordUsers.query.filter(DiscordUsers.user_id.in_([user_id, {other_id}])).delete(synchronize_session=False)
            db.session.commit()
    """)


def test_settings_renders_with_unreachable_discord(side_user):
    _, session, user_id, discord_id = side_user
    unlink_discord(user_id)
    link_discord(user_id, discord_id)
    try:
        response = session.get(f"{DOJO_URL}/settings")
        assert response.status_code == 200, f"/settings broke for a linked user: {response.status_code}"
        if not config_env_value("DISCORD_CLIENT_ID"):
            assert "/discord/connect" not in response.text, \
                "an unconfigured deployment must not offer the Discord link flow"
    finally:
        unlink_discord(user_id)

    response = session.get(f"{DOJO_URL}/settings")
    assert response.status_code == 200, f"/settings broke for an unlinked user: {response.status_code}"


def test_course_page_setup_incomplete_without_reachable_discord(side_official_course_dojo, side_user):
    _, session, user_id, discord_id = side_user
    unlink_discord(user_id)
    set_course(side_official_course_dojo, {"start_date": "2026-01-01T00:00:00", "discord_role": "Test Role"})

    response = session.get(f"{DOJO_URL}/dojo/{side_official_course_dojo}/course")
    assert response.status_code == 200, f"course page returned {response.status_code}"
    assert "Setup incomplete." in response.text, "an unlinked student should see incomplete setup"

    link_discord(user_id, discord_id)
    try:
        response = session.get(f"{DOJO_URL}/dojo/{side_official_course_dojo}/course")
        assert response.status_code == 200, f"course page returned {response.status_code}"
        assert "Setup incomplete." in response.text, \
            "join_discord cannot complete while the Discord bot is unconfigured"
    finally:
        unlink_discord(user_id)


def test_sensai_requires_login():
    response = requests.get(f"{DOJO_URL}/sensai", allow_redirects=False)
    assert response.status_code == 302, f"/sensai returned {response.status_code}"
    assert response.headers["Location"].startswith("/login?next="), response.headers["Location"]
    assert "/sensai" in response.headers["Location"], response.headers["Location"]

    response = requests.get(f"{DOJO_URL}/sensai/chat", allow_redirects=False)
    assert response.status_code == 302, f"/sensai/chat returned {response.status_code}"
    assert "x-accel-redirect" not in {key.lower() for key in response.headers}, \
        "an anonymous request must not be forwarded upstream"

    response = requests.post(f"{DOJO_URL}/sensai/chat", json={"a": 1}, allow_redirects=False)
    assert response.status_code == 403, f"anonymous json POST returned {response.status_code}"

    response = requests.post(f"{DOJO_URL}/sensai/chat", data="x", allow_redirects=False)
    assert response.status_code == 302, f"anonymous form POST returned {response.status_code}"


def test_sensai_view_tracks_active_challenge(side_other_user, example_dojo):
    name, session, _, _ = side_other_user
    remove_workspace_container(name)

    response = session.get(f"{DOJO_URL}/sensai")
    assert response.status_code == 200, f"/sensai returned {response.status_code}"
    assert "No active challenge session" in response.text, \
        "a user without a container should be told to start a challenge"

    start_challenge(example_dojo, "hello", "apple", session=session, wait=2)
    try:
        response = session.get(f"{DOJO_URL}/sensai")
        assert response.status_code == 200, f"/sensai returned {response.status_code}"
        assert "No active challenge session" not in response.text, \
            "a running container should activate the sensai view"
        assert "/sensai/" in response.text, "the active sensai view should point at the proxy"
    finally:
        remove_workspace_container(name)


def test_sensai_proxy_emits_accel_redirect_with_identity(side_other_user, admin_session):
    _, session, user_id, _ = side_other_user

    status, headers, body = site_direct("http://site:8000/sensai/foo?bar=1", session=session)
    assert status == 200, f"expected 200, got {status}"
    assert headers["x-accel-redirect"] == "@sensai", headers
    assert headers["x-forwarded-prefix"] == "/sensai", headers
    assert headers["redirect_uri"] == "http://sensai/sensai/foo?bar=1", headers
    assert headers["redirect_auth"] == f"User {user_id}", headers
    assert headers["content-length"] == "0", headers
    assert body.strip() == "", f"expected an empty body, got {body[:100]!r}"

    status, headers, _ = site_direct("http://site:8000/sensai/foo", session=admin_session)
    assert status == 200, f"expected 200, got {status}"
    assert headers["redirect_auth"] == f"Admin {get_user_id('admin')}", headers


def test_sensai_proxy_post_bypasses_csrf_and_rejects_other_methods(side_other_user):
    _, session, _, _ = side_other_user

    status, headers, _ = site_direct("http://site:8000/sensai/chat", session=session, method="POST")
    assert status == 200, f"POST without a CSRF nonce returned {status}"
    assert headers.get("x-accel-redirect") == "@sensai", headers

    status, headers, _ = site_direct("http://site:8000/sensai/chat", session=session, method="PUT")
    assert status == 404, f"PUT should not be routed, got {status}"
    assert "x-accel-redirect" not in headers, headers


def test_sensai_proxy_without_upstream_is_a_gateway_error(side_other_user):
    if "sensai" in dojo_run("dojo", "compose", "ps", "--services", check=False).stdout.split():
        pytest.skip("this deployment runs a sensai upstream")
    _, session, _, _ = side_other_user

    for path in ["/sensai/", "/sensai/anything"]:
        response = session.get(f"{DOJO_URL}{path}", allow_redirects=False)
        assert response.status_code == 502, f"{path} returned {response.status_code}, expected 502"

    response = session.get(f"{DOJO_URL}/sensai")
    assert response.status_code == 200, "the sensai landing page must not depend on the upstream"


def test_research_page_is_public(side_other_user):
    _, session, _, _ = side_other_user

    response = requests.get(f"{DOJO_URL}/research")
    assert response.status_code == 200, f"anonymous /research returned {response.status_code}"

    response = session.get(f"{DOJO_URL}/research")
    assert response.status_code == 200, f"authenticated /research returned {response.status_code}"


def test_index_next_step_recommends_welcome_dojo(welcome_dojo, random_user_session):
    anonymous = index_next_section(requests.get(f"{DOJO_URL}/").text)
    assert f'"/dojo/{welcome_dojo}"' in anonymous, \
        f"anonymous visitors should be pointed at {welcome_dojo}: {anonymous}"

    fresh = index_next_section(random_user_session.get(f"{DOJO_URL}/").text)
    assert f'"/dojo/{welcome_dojo}"' in fresh, \
        f"a user with no solves should be pointed at {welcome_dojo}: {fresh}"


def test_index_next_step_advances_after_completion(welcome_dojo, random_user):
    name, session = random_user
    response = session.get(f"{DOJO_URL}/dojo/{welcome_dojo}/join/")
    assert response.status_code == 200, f"joining {welcome_dojo} returned {response.status_code}"

    for module, challenge in dojo_challenge_ids(welcome_dojo):
        solve_challenge_offline(welcome_dojo, module, challenge, session=session, user=name)

    section = index_next_section(session.get(f"{DOJO_URL}/").text)
    assert f'"/dojo/{welcome_dojo}"' not in section, \
        f"a completed dojo must not stay in the next-steps section: {section}"
    assert "/dojo/" in section, f"next steps should advance to another dojo: {section}"


def test_belt_granted_with_linked_but_unreachable_discord(belt_dojos, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    orange_dojo_id = int(db_sql("SELECT dojo_id FROM dojos WHERE official AND id = 'intro-to-cybersecurity' LIMIT 1"))
    orange = f"intro-to-cybersecurity~{orange_dojo_id & 0xFFFFFFFF:08x}"

    link_discord(user_id, 65_000_000_000 + user_id)
    try:
        response = session.get(f"{DOJO_URL}/dojo/{orange}/join/")
        assert response.status_code == 200, f"joining {orange} returned {response.status_code}"
        for module, challenge in dojo_challenge_ids(orange):
            solve_challenge_offline(orange, module, challenge, session=session, user=name)

        belts = db_sql(f"SELECT name FROM awards WHERE user_id = {user_id} AND type = 'belt'").split()
        assert "orange" in belts, f"a linked but unreachable Discord account blocked belt awarding: {belts}"
    finally:
        unlink_discord(user_id)
