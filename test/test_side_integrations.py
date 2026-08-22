import datetime
import json
import random
import string

import pytest
import requests

from utils import (
    DOJO_URL,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    get_user_id,
    login,
    make_dojo_official,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
)


DISCORD_API = f"{DOJO_URL}/pwncollege_api/v1/discord"
ACTIVITY_COLUMNS = "(user_id, source_user_id, type, guild_id, channel_id, message_id, message_timestamp)"

# Everything the count/window tests seed lives in the distant past so that it can
# never perturb the leaderboard, whose default window is the current year.
PAST = "2001"

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


def activity_count():
    return int(db_sql("SELECT count(*) FROM discord_user_activity"))


def insert_activity(discord_id, activity_type, rows):
    values = ", ".join(
        f"({discord_id}, {source_user_id}, '{activity_type}', 1, 1, {message_id}, '{timestamp}')"
        for message_id, source_user_id, timestamp in rows
    )
    db_sql(f"INSERT INTO discord_user_activity {ACTIVITY_COLUMNS} VALUES {values}")


def delete_activity(*discord_ids):
    ids = ", ".join(str(discord_id) for discord_id in discord_ids)
    db_sql(f"DELETE FROM discord_user_activity WHERE user_id IN ({ids})")


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


def leaderboard_entry(leaderboard, discord_id):
    return next((entry for entry in leaderboard if entry["discord_id"] == discord_id), None)


def index_next_section(text):
    start = text.index("YOUR Journey")
    end = text.index("Side Quests")
    assert start < end, "index page did not render the next-steps section"
    return text[start:end]


def ctfd_direct(url, session=None, method=None):
    """Talk to CTFd behind nginx's back, so the headers nginx consumes stay visible."""
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
def bot_auth():
    secret = config_env_value("DISCORD_CLIENT_SECRET")
    if secret:
        return {"Authorization": f"Bearer {secret}"}
    # With no configured secret the only way to satisfy auth_check is the empty-token
    # bypass that test_discord_bot_auth_empty_secret_bypass_closed reports as a defect.
    headers = {"Authorization": "Bearer  x"}
    probe = requests.get(f"{DISCORD_API}/memes/user/1", headers=headers)
    if probe.status_code != 200:
        pytest.skip("no DISCORD_CLIENT_SECRET configured and the empty-secret bypass is closed")
    return headers


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
    delete_activity(discord_id)
    link_discord(user_id, discord_id)
    try:
        yield side_user
    finally:
        delete_activity(discord_id)
        unlink_discord(user_id)


@pytest.fixture(scope="module")
def side_course_dojo(admin_session):
    spec = f"""
id: si-course-{random_name()}
name: Side Integrations Course Dojo
type: public
modules:
  - id: lessons
    name: Lessons
    challenges:
      - id: first
        name: First
{DOJO_FILES_SPEC}"""
    return create_dojo_yml(spec, session=admin_session)


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


def test_discord_bot_auth_rejects_missing_or_wrong_bearer():
    endpoints = [
        f"{DISCORD_API}/activity/1234",
        f"{DISCORD_API}/memes/user/1234",
        f"{DISCORD_API}/thanks/user/1234",
    ]
    header_sets = [
        None,
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer wrongsecret"},
        {"Authorization": "Bearer"},
    ]
    before = activity_count()
    for endpoint in endpoints:
        for headers in header_sets:
            response = requests.get(endpoint, headers=headers)
            assert response.status_code == 401, f"{endpoint} with {headers} returned {response.status_code}"
            assert response.json() == {"success": False, "error": "Unauthorized"}, \
                f"{endpoint} with {headers} returned {response.json()}"
    assert activity_count() == before, "rejected bot requests must not touch discord_user_activity"


def test_discord_bot_auth_empty_secret_bypass_closed():
    if config_env_value("DISCORD_CLIENT_SECRET"):
        pytest.skip("deployment has a DISCORD_CLIENT_SECRET configured")
    headers = {"Authorization": "Bearer  x"}
    before = activity_count()

    response = requests.get(f"{DISCORD_API}/memes/user/1234", headers=headers)
    assert response.status_code == 401, \
        f"an unconfigured deployment accepted an empty bot token: {response.status_code} {response.text[:200]}"

    body = {"source_user_id": 1, "guild_id": 2, "channel_id": 3, "message_id": 1,
            "message_timestamp": f"{PAST}-01-01T00:00:00"}
    response = requests.post(f"{DISCORD_API}/memes/user/1234", json=body, headers=headers)
    assert response.status_code == 401, f"anonymous bot write accepted: {response.status_code}"
    assert activity_count() == before, "an unauthorized POST inserted a discord_user_activity row"


def test_discord_bot_post_authorization_bypasses_csrf(side_other_user, bot_auth):
    _, session, _, _ = side_other_user

    response = requests.post(f"{DISCORD_API}/memes/user/1234", json={})
    assert response.status_code == 403, \
        f"expected CSRF rejection without an Authorization header, got {response.status_code}"

    response = requests.post(f"{DISCORD_API}/memes/user/1234", json={}, headers=bot_auth)
    assert response.status_code == 400, f"expected the handler to be reached, got {response.status_code}"
    assert "source_user_id" in response.json()["error"], response.json()

    response = session.post(f"{DISCORD_API}/memes/user/1234", json={})
    assert response.status_code == 401, \
        f"a session-authenticated POST must still fail bot auth, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Unauthorized"}


def test_discord_activity_unknown_discord_id_404(bot_auth):
    assert int(db_sql("SELECT count(*) FROM discord_users WHERE discord_id = 999999999")) == 0
    response = requests.get(f"{DISCORD_API}/activity/999999999", headers=bot_auth)
    assert response.status_code == 404, f"expected 404, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Discord user not found"}


def test_discord_activity_linked_user_without_container(linked_discord_user, bot_auth):
    name, _, _, discord_id = linked_discord_user
    remove_workspace_container(name)
    response = requests.get(f"{DISCORD_API}/activity/{discord_id}", headers=bot_auth)
    assert response.status_code == 200, f"expected 200, got {response.status_code}"
    assert response.json() == {"success": True, "activity": None}, response.json()


def test_discord_activity_reports_running_challenge(linked_discord_user, example_dojo, bot_auth):
    name, session, _, discord_id = linked_discord_user
    start_challenge(example_dojo, "hello", "apple", session=session, wait=2)
    try:
        response = requests.get(f"{DISCORD_API}/activity/{discord_id}", headers=bot_auth)
        assert response.status_code == 200, f"expected 200, got {response.status_code}"
        activity = response.json()["activity"]
        assert activity is not None, "a running container must produce activity"
        challenge = activity["challenge"]
        assert challenge["reference_id"] == f"{example_dojo}/hello/apple", challenge
        assert challenge["challenge"], f"expected a challenge name, got {challenge}"
        assert challenge["module"], f"expected a module name, got {challenge}"
        assert challenge["dojo"], f"expected a dojo name, got {challenge}"
        assert "description" in challenge, challenge
    finally:
        remove_workspace_container(name)


def test_discord_activity_nonnumeric_discord_id(bot_auth):
    for endpoint in [f"{DISCORD_API}/activity/abc", f"{DISCORD_API}/memes/user/abc"]:
        response = requests.get(endpoint, headers=bot_auth)
        assert response.status_code in (400, 404), \
            f"{endpoint} returned {response.status_code}, expected a 4xx for a non-numeric id"


def test_discord_counts_for_unlinked_discord_id_are_zero(bot_auth):
    discord_id = 91000000
    insert_activity(discord_id, "memes", [(1, 1, f"{PAST}-01-01T00:00:00")])
    insert_activity(discord_id, "thanks", [(2, 1, f"{PAST}-01-01T00:00:00")])
    try:
        response = requests.get(f"{DISCORD_API}/memes/user/{discord_id}", headers=bot_auth)
        assert response.status_code == 200, response.status_code
        assert response.json() == {"success": True, "memes": 0}, response.json()

        response = requests.get(f"{DISCORD_API}/thanks/user/{discord_id}", headers=bot_auth)
        assert response.status_code == 200, response.status_code
        assert response.json() == {"success": True, "thanks": 0}, response.json()
    finally:
        delete_activity(discord_id)


def test_discord_memes_count_is_not_deduplicated(linked_discord_user, bot_auth):
    _, _, _, discord_id = linked_discord_user
    insert_activity(discord_id, "memes", [
        (1, 1, f"{PAST}-01-01T00:00:00"),
        (2, 1, f"{PAST}-01-02T00:00:00"),
        (2, 1, f"{PAST}-01-02T00:00:00"),
    ])
    response = requests.get(f"{DISCORD_API}/memes/user/{discord_id}", headers=bot_auth)
    assert response.status_code == 200, response.status_code
    assert response.json() == {"success": True, "memes": 3}, response.json()


def test_discord_thanks_count_is_deduplicated_by_message_and_source(linked_discord_user, bot_auth):
    _, _, _, discord_id = linked_discord_user
    insert_activity(discord_id, "thanks", [
        (200, 5, f"{PAST}-01-01T00:00:00"),
        (200, 5, f"{PAST}-01-01T00:00:00"),
        (200, 6, f"{PAST}-01-01T00:00:00"),
    ])
    response = requests.get(f"{DISCORD_API}/thanks/user/{discord_id}", headers=bot_auth)
    assert response.status_code == 200, response.status_code
    assert response.json() == {"success": True, "thanks": 2}, response.json()


def test_discord_memes_and_thanks_are_isolated_by_type(linked_discord_user, bot_auth):
    _, _, _, discord_id = linked_discord_user
    insert_activity(discord_id, "memes", [(300, 9, f"{PAST}-01-01T00:00:00")])
    insert_activity(discord_id, "thanks", [(300, 9, f"{PAST}-01-01T00:00:00")])

    response = requests.get(f"{DISCORD_API}/memes/user/{discord_id}", headers=bot_auth)
    assert response.json() == {"success": True, "memes": 1}, response.json()

    response = requests.get(f"{DISCORD_API}/thanks/user/{discord_id}", headers=bot_auth)
    assert response.json() == {"success": True, "thanks": 1}, response.json()


def test_discord_activity_start_filter(linked_discord_user, bot_auth):
    _, _, _, discord_id = linked_discord_user
    insert_activity(discord_id, "thanks", [
        (1, 1, f"{PAST}-01-15T00:00:00"),
        (2, 1, f"{PAST}-03-15T00:00:00"),
    ])
    url = f"{DISCORD_API}/thanks/user/{discord_id}"

    assert requests.get(url, headers=bot_auth).json()["thanks"] == 2
    assert requests.get(f"{url}?start={PAST}-02-01", headers=bot_auth).json()["thanks"] == 1
    assert requests.get(f"{url}?start={int(PAST) + 1}-01-01", headers=bot_auth).json()["thanks"] == 0


def test_discord_activity_invalid_start_400(bot_auth):
    response = requests.get(f"{DISCORD_API}/memes/user/1234?start=notadate", headers=bot_auth)
    assert response.status_code == 400, f"expected 400, got {response.status_code}"
    assert response.json() == {"success": False, "error": "invalid start format"}, response.json()


def test_discord_activity_end_filter(linked_discord_user, bot_auth):
    _, _, _, discord_id = linked_discord_user
    insert_activity(discord_id, "memes", [
        (1, 1, f"{PAST}-01-10T00:00:00"),
        (2, 1, f"{PAST}-02-10T00:00:00"),
        (3, 1, f"{PAST}-03-10T00:00:00"),
    ])
    url = f"{DISCORD_API}/memes/user/{discord_id}"

    response = requests.get(f"{url}?end={PAST}-12-31", headers=bot_auth)
    assert response.status_code == 200, f"a lone ?end= was rejected: {response.status_code} {response.text[:200]}"
    assert response.json()["memes"] == 3, response.json()

    response = requests.get(f"{url}?start={PAST}-01-01&end={PAST}-02-28", headers=bot_auth)
    assert response.status_code == 200, response.status_code
    assert response.json()["memes"] == 2, response.json()


def test_discord_post_activity_requires_every_field(bot_auth):
    fields = {
        "source_user_id": 1,
        "guild_id": 2,
        "channel_id": 3,
        "message_id": 4,
        "message_timestamp": f"{PAST}-01-01T00:00:00",
    }
    before = activity_count()
    for missing in fields:
        body = {key: value for key, value in fields.items() if key != missing}
        response = requests.post(f"{DISCORD_API}/memes/user/1234", json=body, headers=bot_auth)
        assert response.status_code == 400, f"omitting {missing} returned {response.status_code}"
        assert response.json() == {"success": False, "error": f"Invalid JSON data - {missing} not found!"}, \
            response.json()

    response = requests.post(f"{DISCORD_API}/thanks/user/1234", json={}, headers=bot_auth)
    assert response.status_code == 400, response.status_code
    assert response.json()["error"] == "Invalid JSON data - source_user_id not found!", response.json()

    assert activity_count() == before, "a rejected POST inserted a discord_user_activity row"


def test_discord_post_activity_creates_row_and_returns_count(linked_discord_user, bot_auth):
    _, _, _, discord_id = linked_discord_user
    body = {"source_user_id": 1, "guild_id": 2, "channel_id": 3, "message_id": 10,
            "message_timestamp": f"{PAST}-01-05T00:00:00"}

    response = requests.post(f"{DISCORD_API}/memes/user/{discord_id}", json=body, headers=bot_auth)
    assert response.status_code == 200, f"{response.status_code} {response.text[:200]}"
    assert response.json() == {"success": True, "memes": 1}, response.json()

    response = requests.post(f"{DISCORD_API}/memes/user/{discord_id}", json={**body, "message_id": 11},
                             headers=bot_auth)
    assert response.status_code == 200, response.status_code
    assert response.json() == {"success": True, "memes": 2}, response.json()

    rows = db_sql(
        f"SELECT type, message_id FROM discord_user_activity WHERE user_id = {discord_id} ORDER BY message_id"
    ).strip().splitlines()
    assert rows == ["memes|10", "memes|11"], rows


def test_discord_post_activity_for_unlinked_id_inserts_but_counts_zero(bot_auth):
    discord_id = 92000000
    year = datetime.date.today().year
    body = {"source_user_id": 7, "guild_id": 2, "channel_id": 3, "message_id": 1,
            "message_timestamp": f"{year}-06-01T00:00:00"}
    try:
        response = requests.post(f"{DISCORD_API}/thanks/user/{discord_id}", json=body, headers=bot_auth)
        assert response.status_code == 200, f"{response.status_code} {response.text[:200]}"
        assert response.json() == {"success": True, "thanks": 0}, response.json()

        stored = int(db_sql(f"SELECT count(*) FROM discord_user_activity WHERE user_id = {discord_id}"))
        assert stored == 1, f"expected the row to be stored anyway, found {stored}"

        leaderboard = requests.get(f"{DISCORD_API}/thanks/leaderboard").json()["leaderboard"]
        entry = leaderboard_entry(leaderboard, discord_id)
        assert entry is not None, f"unlinked activity is missing from the public leaderboard: {leaderboard}"
        assert entry["score"] == 1, entry
    finally:
        delete_activity(discord_id)


def test_discord_post_activity_bad_timestamp(bot_auth):
    before = activity_count()
    body = {"source_user_id": 1, "guild_id": 2, "channel_id": 3, "message_id": 1,
            "message_timestamp": "notatime"}
    response = requests.post(f"{DISCORD_API}/memes/user/1234", json=body, headers=bot_auth)
    assert response.status_code == 400, f"expected 400, got {response.status_code} {response.text[:200]}"
    assert response.json()["success"] is False, response.json()
    assert activity_count() == before, "a malformed POST inserted a discord_user_activity row"


def test_discord_thanks_leaderboard_is_public_and_defaults_to_current_year():
    discord_id = 94000000
    year = datetime.date.today().year
    insert_activity(discord_id, "thanks", [
        (1, 1, f"{year - 1}-06-01T00:00:00"),
        (2, 1, f"{year}-06-01T00:00:00"),
    ])
    try:
        response = requests.get(f"{DISCORD_API}/thanks/leaderboard")
        assert response.status_code == 200, f"leaderboard is not anonymously readable: {response.status_code}"
        assert response.json()["success"] is True, response.json()
        entry = leaderboard_entry(response.json()["leaderboard"], discord_id)
        assert entry is not None, f"seeded id missing from leaderboard: {response.json()['leaderboard']}"
        assert entry["score"] == 1, f"the default window must be the current year only, got {entry}"

        response = requests.get(f"{DISCORD_API}/thanks/leaderboard?start={year - 1}-01-01")
        entry = leaderboard_entry(response.json()["leaderboard"], discord_id)
        assert entry is not None and entry["score"] == 2, entry
    finally:
        delete_activity(discord_id)


def test_discord_thanks_leaderboard_invalid_start_400():
    response = requests.get(f"{DISCORD_API}/thanks/leaderboard?start=garbage")
    assert response.status_code == 400, f"expected 400, got {response.status_code}"
    assert response.json() == {"success": False, "error": "Invalid start format"}, response.json()


def test_discord_thanks_leaderboard_dedups_and_ignores_memes():
    discord_id = 95000000
    year = datetime.date.today().year
    stamp = f"{year}-06-01T00:00:00"
    insert_activity(discord_id, "thanks", [(1, 1, stamp), (1, 1, stamp), (1, 2, stamp)])
    insert_activity(discord_id, "memes", [(1, 1, stamp), (2, 1, stamp), (3, 1, stamp)])
    try:
        leaderboard = requests.get(f"{DISCORD_API}/thanks/leaderboard").json()["leaderboard"]
        entry = leaderboard_entry(leaderboard, discord_id)
        assert entry is not None, f"seeded id missing from leaderboard: {leaderboard}"
        assert entry["score"] == 2, f"expected distinct (message, source) thanks only, got {entry}"
    finally:
        delete_activity(discord_id)


def test_discord_thanks_leaderboard_ordering_and_limit():
    year = datetime.date.today().year
    base = 96000000
    ids = list(range(base, base + 22))
    db_sql(
        f"INSERT INTO discord_user_activity {ACTIVITY_COLUMNS} "
        f"SELECT {base} + i, 1, 'thanks', 1, 1, m, '{year}-06-01T00:00:00' "
        "FROM generate_series(0, 21) AS i, generate_series(1, 71) AS m WHERE m <= 50 + i"
    )
    try:
        leaderboard = requests.get(f"{DISCORD_API}/thanks/leaderboard").json()["leaderboard"]
        assert len(leaderboard) == 20, f"leaderboard must be truncated to 20 entries, got {len(leaderboard)}"
        scores = [entry["score"] for entry in leaderboard]
        assert scores == sorted(scores, reverse=True), f"leaderboard is not sorted by score: {scores}"
        top = leaderboard_entry(leaderboard, base + 21)
        assert top is not None and top["score"] == 71, top
        for excluded in (base, base + 1):
            assert leaderboard_entry(leaderboard, excluded) is None, \
                f"lowest-scoring id {excluded} should have been truncated away"
    finally:
        delete_activity(*ids)


def test_course_discord_endpoints_require_login(side_course_dojo):
    for resource in ["memes", "thanks"]:
        url = f"{DISCORD_API}/course/{side_course_dojo}/{resource}"
        response = requests.get(url, allow_redirects=False)
        assert response.status_code == 302, f"{url} returned {response.status_code}"
        assert response.headers["Location"].startswith("/login?next="), response.headers["Location"]

        response = requests.get(url, headers={"Content-Type": "application/json"}, allow_redirects=False)
        assert response.status_code == 403, f"{url} (json) returned {response.status_code}"


def test_course_discord_endpoints_unknown_or_inaccessible_dojo_404(side_other_user, random_private_dojo):
    _, session, _, _ = side_other_user
    for dojo in ["nonexistent-dojo-xyz", random_private_dojo]:
        for resource in ["memes", "thanks"]:
            response = session.get(f"{DISCORD_API}/course/{dojo}/{resource}")
            assert response.status_code == 404, \
                f"/course/{dojo}/{resource} returned {response.status_code}, expected 404"


def test_course_discord_endpoints_without_discord_link(side_other_user, side_course_dojo):
    _, session, user_id, _ = side_other_user
    unlink_discord(user_id)
    set_course(side_course_dojo, {"start_date": "2026-01-01T00:00:00"})
    for resource in ["memes", "thanks"]:
        response = session.get(f"{DISCORD_API}/course/{side_course_dojo}/{resource}")
        assert response.status_code == 200, f"{resource} returned {response.status_code}"
        assert response.json() == {"success": False, "error": "Discord not linked"}, response.json()


def test_course_discord_endpoints_without_course_start(linked_discord_user, side_course_dojo):
    _, session, _, _ = linked_discord_user
    set_course(side_course_dojo, {})
    for resource in ["memes", "thanks"]:
        response = session.get(f"{DISCORD_API}/course/{side_course_dojo}/{resource}")
        assert response.status_code == 200, f"{resource} returned {response.status_code}"
        assert response.json() == {"success": False, "error": "No course start"}, response.json()


def test_course_memes_counts_weekly_buckets(linked_discord_user, side_course_dojo):
    _, session, _, discord_id = linked_discord_user
    set_course(side_course_dojo, {"start_date": "2026-01-01T00:00:00"})
    url = f"{DISCORD_API}/course/{side_course_dojo}/memes"

    insert_activity(discord_id, "memes", [
        (1, 1, "2026-01-01T12:00:00"),
        (2, 1, "2026-01-02T12:00:00"),
        (3, 1, "2026-01-08T12:00:00"),
        (4, 1, "2026-03-01T00:00:00"),
    ])
    response = session.get(url)
    assert response.status_code == 200, response.status_code
    assert response.json() == {"success": True, "memes": 3}, response.json()

    insert_activity(discord_id, "memes", [(5, 1, "2026-01-09T00:00:00")])
    response = session.get(url)
    assert response.json() == {"success": True, "memes": 3}, \
        f"a second meme in an already-counted week must not add a bucket: {response.json()}"


def test_course_memes_are_limited_to_a_17_week_window(linked_discord_user, side_course_dojo):
    _, session, _, discord_id = linked_discord_user
    set_course(side_course_dojo, {"start_date": "2026-01-01T00:00:00"})
    insert_activity(discord_id, "memes", [
        (1, 1, "2025-12-01T00:00:00"),
        (2, 1, "2026-02-01T00:00:00"),
        (3, 1, "2026-06-01T00:00:00"),
    ])
    response = session.get(f"{DISCORD_API}/course/{side_course_dojo}/memes")
    assert response.status_code == 200, response.status_code
    assert response.json() == {"success": True, "memes": 1}, response.json()


def test_course_thanks_counts_everything_since_course_start(linked_discord_user, side_course_dojo):
    _, session, _, discord_id = linked_discord_user
    set_course(side_course_dojo, {"start_date": "2026-01-01T00:00:00"})
    insert_activity(discord_id, "thanks", [
        (1, 1, "2025-12-31T00:00:00"),
        (2, 1, "2026-05-01T00:00:00"),
        (2, 1, "2026-05-01T00:00:00"),
        (3, 1, "2027-01-01T00:00:00"),
    ])
    response = session.get(f"{DISCORD_API}/course/{side_course_dojo}/thanks")
    assert response.status_code == 200, response.status_code
    assert response.json() == {"success": True, "thanks": 2}, response.json()


def test_course_discord_endpoints_accept_tz_aware_start_date(linked_discord_user, side_course_dojo):
    _, session, _, discord_id = linked_discord_user
    set_course(side_course_dojo, {"start_date": "2026-01-01T00:00:00-07:00"})
    insert_activity(discord_id, "memes", [(1, 1, "2026-02-01T00:00:00")])
    insert_activity(discord_id, "thanks", [(2, 1, "2026-02-01T00:00:00")])

    response = session.get(f"{DISCORD_API}/course/{side_course_dojo}/memes")
    assert response.status_code == 200, f"tz-aware start broke memes: {response.text[:200]}"
    assert response.json() == {"success": True, "memes": 1}, response.json()

    response = session.get(f"{DISCORD_API}/course/{side_course_dojo}/thanks")
    assert response.status_code == 200, f"tz-aware start broke thanks: {response.text[:200]}"
    assert response.json() == {"success": True, "thanks": 1}, response.json()


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


def test_course_identity_reports_discord_warnings(side_official_course_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    set_course(side_official_course_dojo, {
        "start_date": "2026-01-01T00:00:00",
        "students": ["S1"],
        "student_id": "ASURITE",
        "discord_role": "Test Role",
    })
    url = f"{DOJO_URL}/dojo/{side_official_course_dojo}/course/identity"

    response = session.patch(url, json={"identity": "S1"})
    assert response.status_code == 200, f"{response.status_code} {response.text[:200]}"
    assert response.json() == {"success": True, "warning": "Your Discord account is not linked"}, response.json()

    link_discord(user_id, 64_000_000_000 + user_id)
    try:
        response = session.patch(url, json={"identity": "S1"})
        assert response.status_code == 200, f"{response.status_code} {response.text[:200]}"
        assert response.json() == {
            "success": True,
            "warning": "Your Discord account has not joined the official Discord server",
        }, response.json()
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

    status, headers, body = ctfd_direct("http://ctfd:8000/sensai/foo?bar=1", session=session)
    assert status == 200, f"expected 200, got {status}"
    assert headers["x-accel-redirect"] == "@sensai", headers
    assert headers["x-forwarded-prefix"] == "/sensai", headers
    assert headers["redirect_uri"] == "http://sensai/sensai/foo?bar=1", headers
    assert headers["redirect_auth"] == f"User {user_id}", headers
    assert headers["content-length"] == "0", headers
    assert body.strip() == "", f"expected an empty body, got {body[:100]!r}"

    status, headers, _ = ctfd_direct("http://ctfd:8000/sensai/foo", session=admin_session)
    assert status == 200, f"expected 200, got {status}"
    assert headers["redirect_auth"] == f"Admin {get_user_id('admin')}", headers


def test_sensai_proxy_preserves_path_and_query(side_other_user):
    _, session, _, _ = side_other_user
    for url, expected in [
        ("http://ctfd:8000/sensai/", "http://sensai/sensai/?"),
        ("http://ctfd:8000/sensai/a%20b", "http://sensai/sensai/a%20b?"),
        ("http://ctfd:8000/sensai/x?a=1&b=2", "http://sensai/sensai/x?a=1&b=2"),
    ]:
        status, headers, _ = ctfd_direct(url, session=session)
        assert status == 200, f"{url} returned {status}"
        assert headers["redirect_uri"] == expected, f"{url} -> {headers.get('redirect_uri')}"


def test_sensai_proxy_post_bypasses_csrf_and_rejects_other_methods(side_other_user):
    _, session, _, _ = side_other_user

    status, headers, _ = ctfd_direct("http://ctfd:8000/sensai/chat", session=session, method="POST")
    assert status == 200, f"POST without a CSRF nonce returned {status}"
    assert headers.get("x-accel-redirect") == "@sensai", headers

    status, headers, _ = ctfd_direct("http://ctfd:8000/sensai/chat", session=session, method="PUT")
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
    assert "research@pwn.college" in response.text, "the opt-out contact address is missing"
    assert "Research Opt-Out Request" in response.text, "the opt-out subject line is missing"

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
