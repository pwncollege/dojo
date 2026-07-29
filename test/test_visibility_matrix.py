import datetime
import hashlib
import json
import random
import string
import time

import pytest
import requests
import yaml

from utils import (
    DOJO_URL,
    challenge_flag,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    flask_exec,
    get_user_id,
    login,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
    wait_for_background_worker,
    workspace_run,
)

MISSING_USER_ID = 99999999


def rand_token(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def register_user():
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    return name, login(name, name, register=True)


def imported(module="hello", challenge="apple", dojo="example"):
    return {"import": {"dojo": dojo, "module": module, "challenge": challenge}}


def text_file(path, content):
    return {"type": "text", "path": path, "content": content}


def create_spec_dojo(admin_session, spec):
    return create_dojo_yml(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), session=admin_session)


def local_dojo_spec(prefix, name, dojo_type, challenges=("apple",), module="hello", **extra):
    """A dojo whose challenges are its own, so solving one only touches this dojo's caches."""
    spec = {
        "id": f"vismatrix-{prefix}-{rand_token()}",
        "name": name,
        "modules": [{
            "id": module,
            "name": module.title(),
            "challenges": [{"id": challenge, "name": challenge.title()} for challenge in challenges],
        }],
        "files": [text_file(f"{module}/{challenge}/src", "#!/opt/pwn.college/bash\ncat /flag\n")
                  for challenge in challenges],
    }
    if dojo_type:
        spec["type"] = dojo_type
    spec.update(extra)
    return spec


def publish_stat_event(event_type, payload):
    event = json.dumps({
        "type": event_type,
        "payload": payload,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    dojo_run("docker", "exec", "cache", "redis-cli", "XADD", "stat:events", "*", "data", event)


def cache_stamp(cache_key):
    result = dojo_run("docker", "exec", "cache", "redis-cli", "GET", f"{cache_key}:updated", check=False)
    value = result.stdout.strip()
    return float(value) if value else 0.0


def recompute(cache_key, event_type, payload, timeout=45):
    """Ask the background worker to rebuild a cache, and wait until it actually has."""
    before = cache_stamp(cache_key)
    publish_stat_event(event_type, payload)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cache_stamp(cache_key) > before:
            return
        time.sleep(0.25)
    raise AssertionError(f"the background worker did not refresh {cache_key} within {timeout}s")


def wait_until(predicate, timeout=45, description="condition"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError(f"timed out after {timeout}s waiting for {description}")


def dojo_scoreboard_cache_key(dojo):
    return f"stats:scoreboard:dojo:{dojo_db_id(dojo)}:0"


def all_standings(session, dojo, module="_"):
    standings = []
    page = 1
    while True:
        response = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/{module}/0/{page}")
        assert response.status_code == 200, f"Expected 200 from the scoreboard API, got {response.status_code}"
        result = response.json()
        standings.extend(result["standings"])
        if page + 1 not in result["pages"]:
            return standings
        page += 1


def set_hidden(session, hidden):
    response = session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": hidden})
    assert response.status_code == 200, f"Expected 200 setting hidden={hidden}, got {response.status_code}"


def join_dojo(session, dojo):
    response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200, f"Expected to join {dojo}, got {response.status_code}"


def modules_of(session, dojo):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/modules")
    assert response.status_code == 200, f"Expected 200 from the modules API, got {response.status_code}"
    return response.json()["modules"]


def module_named(modules, module_id):
    module = next((m for m in modules if m["id"] == module_id), None)
    assert module is not None, f"module {module_id} missing from {[m['id'] for m in modules]}"
    return module


@pytest.fixture(scope="module")
def visibility_matrix_dojo(admin_session, example_dojo):
    """A dojo whose modules exercise every kind of visibility window."""
    return create_spec_dojo(admin_session, {
        "id": f"vismatrix-{rand_token()}",
        "name": "Visibility Matrix Dojo",
        "type": "public",
        "modules": [
            {
                "id": "neighbors",
                "name": "Neighbors",
                "challenges": [
                    {"id": "one", "name": "One", **imported("hello", "apple")},
                    {"id": "two", "name": "Two", "visibility": {"start": "2099-01-01T00:00:00Z"},
                     **imported("hello", "banana")},
                    {"id": "three", "name": "Three", **imported("world", "earth")},
                ],
            },
            {
                "id": "expiry",
                "name": "Expiry",
                "challenges": [
                    {"id": "expired", "name": "Expired", "visibility": {"stop": "2000-01-01T00:00:00Z"},
                     **imported("world", "mars")},
                    {"id": "open", "name": "Open", **imported("hello", "apple")},
                ],
            },
            {
                "id": "resources",
                "name": "Resources",
                "resources": [
                    {"type": "markdown", "name": "FutureResource", "content": "FUTURE_RESOURCE_MARKER",
                     "visibility": {"start": "2099-01-01T00:00:00Z"}},
                    {"type": "markdown", "name": "NowResource", "content": "NOW_RESOURCE_MARKER"},
                    {"type": "challenge", "id": "res-challenge", "name": "Res Challenge",
                     **imported("hello", "apple")},
                ],
            },
        ],
    })


@pytest.fixture(scope="module")
def course_dojo(admin_session, example_dojo):
    return create_spec_dojo(admin_session, {
        "id": f"vismatrix-course-{rand_token()}",
        "name": "Visibility Matrix Course",
        "type": "public",
        "modules": [{"id": "m", "name": "M", "challenges": [{"id": "c", "name": "C", **imported()}]}],
        "files": [text_file("course.yml", "student_id: Student ID\nstudents:\n  - tok-alpha\n")],
    })


def test_self_profile_requires_auth_and_is_about_requester(random_user):
    name, session = random_user
    other_name, other_session = register_user()

    anonymous = requests.get(f"{DOJO_URL}/hacker/", allow_redirects=False)
    assert anonymous.status_code == 302, f"Expected a redirect for an anonymous /hacker/, got {anonymous.status_code}"
    assert "/login" in anonymous.headers["Location"], \
        f"Expected a redirect to the login page, got {anonymous.headers['Location']}"
    assert name not in anonymous.text and other_name not in anonymous.text, \
        "an anonymous /hacker/ redirect must not disclose any user"

    as_json = requests.get(f"{DOJO_URL}/hacker/", headers={"Content-Type": "application/json"},
                           allow_redirects=False)
    assert as_json.status_code == 403, f"Expected 403 for an anonymous JSON /hacker/, got {as_json.status_code}"
    assert name not in as_json.text and other_name not in as_json.text, \
        "the 403 body must not disclose any user"

    mine = session.get(f"{DOJO_URL}/hacker/")
    assert mine.status_code == 200, f"Expected 200 for an authed /hacker/, got {mine.status_code}"
    assert name in mine.text, "/hacker/ must render the requesting user's own handle"
    assert other_name not in mine.text, "/hacker/ must not disclose another user's handle"

    theirs = other_session.get(f"{DOJO_URL}/hacker/")
    assert theirs.status_code == 200, f"Expected 200 for an authed /hacker/, got {theirs.status_code}"
    assert other_name in theirs.text, "/hacker/ is scoped to whoever is making the request"
    assert name not in theirs.text, "/hacker/ must not disclose another user's handle"


def test_public_profile_lookup_by_id_and_by_name(random_user):
    name, _ = random_user
    user_id = get_user_id(name)

    by_id = requests.get(f"{DOJO_URL}/hacker/{user_id}")
    assert by_id.status_code == 200, f"Expected an anonymous profile read to succeed, got {by_id.status_code}"
    assert name in by_id.text, "the profile must render the profile owner's handle"

    by_name = requests.get(f"{DOJO_URL}/hacker/{name}")
    assert by_name.status_code == 200, f"Expected /hacker/<name> to resolve, got {by_name.status_code}"
    assert name in by_name.text, "/hacker/<name> must resolve to the same user as /hacker/<id>"

    unknown_name = f"nosuchuser-{rand_token()}"
    assert requests.get(f"{DOJO_URL}/hacker/{unknown_name}").status_code == 404, \
        "an unknown user name must 404 rather than fall back to some other user"

    assert db_sql(f"SELECT count(*) FROM users WHERE id={MISSING_USER_ID}").strip() == "0"
    assert requests.get(f"{DOJO_URL}/hacker/{MISSING_USER_ID}").status_code == 404, \
        "an unknown user id must 404"


def test_numeric_username_is_shadowed_by_the_id_route():
    numeric_name = str(90000000 + random.randint(0, 999999))
    assert db_sql(f"SELECT count(*) FROM users WHERE id={numeric_name}").strip() == "0", \
        "test precondition: the numeric name must not also be a valid user id"
    login(numeric_name, "password123", register=True, email=f"n{numeric_name}@example.com")
    user_id = get_user_id(numeric_name)

    assert requests.get(f"{DOJO_URL}/hacker/{numeric_name}").status_code == 404, \
        "an all-digits name is routed as a user id, so the name lookup is unreachable"
    by_id = requests.get(f"{DOJO_URL}/hacker/{user_id}")
    assert by_id.status_code == 200, f"the user is still reachable by id, got {by_id.status_code}"
    assert numeric_name in by_id.text


def test_hidden_flag_is_self_service_and_reversible(random_user):
    name, session = random_user
    user_id = get_user_id(name)

    me = session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert me.status_code == 200
    assert me.json()["hidden"] is False, "a fresh account is not hidden"

    set_hidden(session, True)
    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["hidden"] is True
    assert db_sql(f"SELECT hidden FROM users WHERE id={user_id}").strip() == "t"

    set_hidden(session, False)
    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["hidden"] is False
    assert db_sql(f"SELECT hidden FROM users WHERE id={user_id}").strip() == "f"


def test_hidden_profile_is_404_for_everyone_else_and_reversible(random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)
    _, other_session = register_user()

    set_hidden(session, True)
    for label, requester in (("anonymous", requests), ("another user", other_session), ("site admin", admin_session)):
        for url in (f"{DOJO_URL}/hacker/{user_id}", f"{DOJO_URL}/hacker/{name}"):
            response = requester.get(url)
            assert response.status_code == 404, \
                f"{label} got {response.status_code} for a hidden user's {url}; there is no admin bypass"

    own = session.get(f"{DOJO_URL}/hacker/")
    assert own.status_code == 200 and name in own.text, "hiding must not lock the user out of their own profile"

    set_hidden(session, False)
    restored = requests.get(f"{DOJO_URL}/hacker/{user_id}")
    assert restored.status_code == 200, f"unhiding must restore the public profile, got {restored.status_code}"
    assert name in restored.text


def test_ctfd_user_api_hides_hidden_users(random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)
    _, other_session = register_user()

    def query_names(requester, **params):
        response = requester.get(f"{DOJO_URL}/api/v1/users", params={"q": name, "field": "name", **params})
        assert response.status_code == 200, f"Expected 200 from the user search, got {response.status_code}"
        return [user["name"] for user in response.json()["data"]]

    assert name in query_names(requests), "guard: a visible user must be findable before hiding"

    set_hidden(session, True)

    for label, requester in (("anonymous", requests), ("another user", other_session)):
        response = requester.get(f"{DOJO_URL}/api/v1/users/{user_id}")
        assert response.status_code == 404, f"{label} got {response.status_code} for a hidden user record"
    assert admin_session.get(f"{DOJO_URL}/api/v1/users/{user_id}").status_code == 200, \
        "site admins can still read a hidden user's record"

    assert query_names(requests) == [], "a hidden user must not appear in the public user search"
    assert name in query_names(admin_session, view="admin"), \
        "the admin view of the user search still lists hidden users"


def test_activity_endpoint_visibility_matrix(random_user, admin_session, example_dojo):
    name, session = random_user
    user_id = get_user_id(name)
    _, other_session = register_user()
    activity_url = f"{DOJO_URL}/pwncollege_api/v1/activity/{user_id}"

    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    wait_for_background_worker()

    public = requests.get(activity_url)
    assert public.status_code == 200, f"a visible user's activity is public, got {public.status_code}"
    assert public.json()["data"]["total_solves"] >= 1, "the solve must be reflected in the activity payload"

    set_hidden(session, True)

    mine = session.get(activity_url)
    assert mine.status_code == 200, "a hidden user still reads their own activity"
    assert mine.json()["data"]["total_solves"] >= 1

    for label, requester in (("anonymous", requests), ("another user", other_session), ("site admin", admin_session)):
        response = requester.get(activity_url)
        assert response.status_code == 404, f"{label} got {response.status_code} for a hidden user's activity"

    assert requests.get(f"{DOJO_URL}/pwncollege_api/v1/activity/{MISSING_USER_ID}").status_code == 404


def test_hidden_user_public_awards_are_admin_only(random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)
    award_name = f"vmaward{rand_token()}"
    db_sql(
        "INSERT INTO awards (user_id, type, name, description, date, value, icon) "
        f"VALUES ({user_id}, 'emoji', '{award_name}', 'visibility matrix award', NOW(), 0, '🧪')"
    )

    set_hidden(session, True)
    public_awards = f"{DOJO_URL}/api/v1/users/{user_id}/awards"

    assert session.get(public_awards).status_code == 404, \
        "a hidden user's own public award listing is suppressed too"
    assert requests.get(public_awards).status_code == 404, "anonymous visitors get 404"
    assert admin_session.get(public_awards).status_code == 200, "site admins keep access to the public award listing"

    own = session.get(f"{DOJO_URL}/api/v1/users/me/awards")
    assert own.status_code == 200, f"the hidden user's own awards endpoint must keep working, got {own.status_code}"
    assert award_name in {award["name"] for award in own.json()["data"]}


def test_self_patch_cannot_escalate_or_target_others(random_user):
    name, session = random_user
    user_id = get_user_id(name)
    other_name, _ = register_user()
    other_id = get_user_id(other_name)

    session.patch(f"{DOJO_URL}/api/v1/users/me", json={"type": "admin", "hidden": True})
    assert db_sql(f"SELECT type FROM users WHERE id={user_id}").strip() == "user", \
        "the self view must not accept a privilege change"
    assert session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me").json()["admin"] is False

    response = session.patch(f"{DOJO_URL}/api/v1/users/{other_id}", json={"hidden": True})
    assert response.status_code == 403, f"a non-admin must not PATCH another user, got {response.status_code}"
    assert db_sql(f"SELECT hidden FROM users WHERE id={other_id}").strip() == "f", \
        "the other user's hidden flag must be untouched"


def test_banned_user_keeps_a_public_profile(random_user, admin_session):
    name, _ = random_user
    user_id = get_user_id(name)

    try:
        response = admin_session.patch(f"{DOJO_URL}/api/v1/users/{user_id}", json={"banned": True})
        assert response.status_code == 200, f"Expected the ban to apply, got {response.status_code}"
        assert db_sql(f"SELECT banned FROM users WHERE id={user_id}").strip() == "t"

        profile = requests.get(f"{DOJO_URL}/hacker/{user_id}")
        assert profile.status_code == 200, \
            f"profile visibility keys off `hidden` only, so a banned user still renders; got {profile.status_code}"
        assert name in profile.text
    finally:
        admin_session.patch(f"{DOJO_URL}/api/v1/users/{user_id}", json={"banned": False})


def test_default_admin_account_is_hidden(admin_session):
    assert db_sql("SELECT hidden FROM users WHERE name='admin'").strip() == "t", \
        "the bootstrapped admin account is created hidden"
    admin_id = get_user_id("admin")

    assert requests.get(f"{DOJO_URL}/hacker/{admin_id}").status_code == 404
    assert admin_session.get(f"{DOJO_URL}/hacker/{admin_id}").status_code == 404, \
        "not even the admin can reach their own public profile page"

    own = admin_session.get(f"{DOJO_URL}/hacker/")
    assert own.status_code == 200 and "admin" in own.text, "the admin still has a self profile"


def test_ctfd_user_directory_is_disabled(random_user, admin_session):
    name, _ = random_user
    for path in ("/users", "/user", "/scoreboard"):
        for label, requester in (("anonymous", requests), ("site admin", admin_session)):
            response = requester.get(f"{DOJO_URL}{path}", allow_redirects=False)
            assert response.status_code != 200, \
                f"{label} got a 200 from the removed CTFd view {path}"
            assert name not in response.text, f"{path} must never serve a user listing to {label}"


def test_score_and_validate_apis_hide_hidden_users(random_user, example_dojo):
    name, session = random_user
    email = f"{name}@example.com"
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)

    score_url = f"{DOJO_URL}/pwncollege_api/v1/score"
    validate_url = f"{DOJO_URL}/pwncollege_api/v1/score/validate"

    ranked = requests.get(score_url, params={"username": name})
    assert ranked.status_code == 200, f"a ranked visible user gets their score, got {ranked.status_code}"
    fields = ranked.json().split(":")
    assert len(fields) == 6, f"expected rank:score:max:solved:count:users, got {ranked.json()!r}"
    assert all(field.isdigit() for field in fields), f"every score field is numeric, got {fields}"

    assert requests.get(score_url).status_code == 400, "the username parameter is required"

    assert requests.get(validate_url, params={"username": name, "email": email}).json() == 1
    assert requests.get(validate_url, params={"username": name, "email": "wrong@example.com"}).json() == 0
    assert requests.get(validate_url, params={"username": name}).status_code == 400

    set_hidden(session, True)

    hidden_score = requests.get(score_url, params={"username": name})
    assert hidden_score.status_code == 400, f"a hidden user has no public score, got {hidden_score.status_code}"
    assert hidden_score.json()["error"] == "user does not exist"

    assert requests.get(validate_url, params={"username": name, "email": email}).json() == 0, \
        "validation must not confirm a hidden account"


@pytest.mark.timeout(120)
def test_hidden_user_drops_out_of_scoreboard_me(admin_session, random_user):
    name, session = random_user
    dojo = create_spec_dojo(admin_session, local_dojo_spec("me", "Visibility Matrix Me", "public"))
    join_dojo(session, dojo)
    solve_challenge_offline(dojo, "hello", "apple", session=session, user=name)

    url = f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1"
    wait_until(lambda: "me" in session.get(url).json(),
               description="the solver's personal scoreboard entry to be computed")
    assert session.get(url).json()["me"]["name"] == name

    set_hidden(session, True)
    assert "me" not in session.get(url).json(), \
        "a hidden user must not be given a personal scoreboard entry"


@pytest.mark.timeout(120)
def test_hidden_user_absent_from_public_standings(admin_session, random_user):
    hidden_name, hidden_session = random_user
    control_name, control_session = register_user()
    dojo = create_spec_dojo(admin_session, local_dojo_spec("standings", "Visibility Matrix Standings", "public"))

    set_hidden(hidden_session, True)
    for solver_name, solver_session in ((hidden_name, hidden_session), (control_name, control_session)):
        join_dojo(solver_session, dojo)
        solve_challenge_offline(dojo, "hello", "apple", session=solver_session, user=solver_name)

    anonymous = requests.Session()
    wait_until(lambda: any(standing["name"] == control_name for standing in all_standings(anonymous, dojo)),
               description="the visible solver to reach the standings")
    assert not any(standing["name"] == hidden_name for standing in all_standings(anonymous, dojo)), \
        "the incremental scoreboard update must skip hidden users"

    recompute(dojo_scoreboard_cache_key(dojo), "scoreboard_update",
              {"model_type": "dojo", "model_id": dojo_db_id(dojo)})
    recomputed = all_standings(anonymous, dojo)
    assert any(standing["name"] == control_name for standing in recomputed), \
        "guard: the recomputed standings still hold the visible solver"
    assert not any(standing["name"] == hidden_name for standing in recomputed), \
        "a full scoreboard recompute must also exclude hidden users"


@pytest.mark.timeout(180)
def test_hidden_user_excluded_from_belts(random_user):
    name, session = random_user
    user_id = get_user_id(name)
    db_sql(
        "INSERT INTO awards (user_id, type, name, description, date, value) "
        f"VALUES ({user_id}, 'belt', 'orange', 'Orange Belt', NOW(), 0)"
    )

    recompute("stats:belts", "belts_update", {})
    belts = requests.get(f"{DOJO_URL}/pwncollege_api/v1/belts").json()
    assert str(user_id) in belts["users"], "guard: a visible belted user is listed in the public belts data"

    set_hidden(session, True)
    recompute("stats:belts", "belts_update", {})

    belts = requests.get(f"{DOJO_URL}/pwncollege_api/v1/belts").json()
    assert str(user_id) not in belts["users"], "a hidden user must drop out of the public belts data"
    assert name not in requests.get(f"{DOJO_URL}/belts").text, \
        "a hidden user must not be rendered on the public belts page"


@pytest.mark.timeout(180)
def test_hidden_user_excluded_from_emoji_cache(completionist_user, simple_award_dojo):
    name, session = completionist_user
    dojo_id = dojo_db_id(simple_award_dojo)
    scoreboard_key = dojo_scoreboard_cache_key(simple_award_dojo)

    recompute("stats:emojis", "emojis_update", {})
    recompute(scoreboard_key, "scoreboard_update", {"model_type": "dojo", "model_id": dojo_id})

    anonymous = requests.Session()
    standings = all_standings(anonymous, simple_award_dojo)
    mine = next((standing for standing in standings if standing["name"] == name), None)
    assert mine is not None, "guard: the completionist must appear in the public standings first"
    assert mine["badges"], "guard: the completionist earned a dojo emoji badge"

    set_hidden(session, True)
    recompute("stats:emojis", "emojis_update", {})
    recompute(scoreboard_key, "scoreboard_update", {"model_type": "dojo", "model_id": dojo_id})

    standings = all_standings(anonymous, simple_award_dojo)
    assert not any(standing["name"] == name for standing in standings), \
        "a hidden user must disappear from the public standings entirely"

    own = session.get(f"{DOJO_URL}/hacker/")
    assert own.status_code == 200
    assert "🧪" in own.text, "the hidden user's own profile still computes their badges live"


def test_feed_suppresses_hidden_user_events(random_user, simple_award_dojo):
    name, session = random_user
    join_dojo(session, simple_award_dojo)

    def feed_has_user():
        response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events", params={"limit": 100})
        assert response.status_code == 200
        return any(event["user_name"] == name for event in response.json()["data"])

    set_hidden(session, True)
    solve_challenge_offline(simple_award_dojo, "hello", "apple", session=session, user=name)
    assert not feed_has_user(), "no activity feed event may be published for a hidden user"

    set_hidden(session, False)
    solve_challenge_offline(simple_award_dojo, "hello", "banana", session=session, user=name)
    wait_until(feed_has_user, timeout=20,
               description="the same action by a visible user to produce a feed event")


def test_hidden_user_keeps_own_progress_and_awards(random_user, simple_award_dojo):
    name, session = random_user
    user_id = get_user_id(name)

    set_hidden(session, True)
    join_dojo(session, simple_award_dojo)
    for challenge in ("apple", "banana"):
        solve_challenge_offline(simple_award_dojo, "hello", challenge, session=session, user=name)

    solves = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{simple_award_dojo}/solves")
    assert solves.status_code == 200
    assert len(solves.json()["solves"]) == 2, "hiding must not hide a user's own solves from themselves"

    emoji_count = int(db_sql(f"SELECT count(*) FROM awards WHERE user_id={user_id} AND type='emoji'").strip())
    assert emoji_count >= 1, "dojo completion still grants the dojo emoji award to a hidden user"

    awards = session.get(f"{DOJO_URL}/api/v1/users/me/awards")
    assert awards.status_code == 200
    assert len(awards.json()["data"]) >= 1, "the award is visible on the user's own awards endpoint"


def test_dojo_solves_api_username_lookup_excludes_hidden(random_user, example_dojo):
    name, session = random_user
    _, other_session = register_user()
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    set_hidden(session, True)

    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves"

    lookup = other_session.get(url, params={"username": name})
    assert lookup.status_code == 400, f"a hidden user must not be looked up by name, got {lookup.status_code}"
    assert lookup.json()["error"] == "User not found"

    anonymous = requests.get(url)
    assert anonymous.status_code == 400, "an anonymous request with no username has no user to report on"

    own = session.get(url)
    assert own.status_code == 200, f"the hidden user still gets their own solves, got {own.status_code}"
    assert [solve["challenge_id"] for solve in own.json()["solves"]] == ["apple"]


def test_solves_export_authorization_and_formats(example_dojo, admin_session, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    private_key = db_sql("SELECT private_key FROM dojos WHERE id='example' AND official").strip()
    assert private_key, "test precondition: the example dojo is a repository dojo with a deploy key"
    code = hashlib.md5(private_key.encode() + b"SOLVES").hexdigest()

    join_dojo(session, example_dojo)
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    set_hidden(session, True)

    export = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{code}/json")
    assert export.status_code == 200, f"the correct solves code must be accepted, got {export.status_code}"
    assert isinstance(export.json(), list), "the json export is a list of solve rows"

    assert requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/wrongcode/json").status_code == 403, \
        "a wrong solves code is rejected"
    assert requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{code}/xml").status_code == 400, \
        "an unknown export format is a bad request"
    assert requests.get(f"{DOJO_URL}/dojo/no-such-dojo-{rand_token()}/solves/{code}/json").status_code == 404

    filtered = requests.get(f"{DOJO_URL}/dojo/{example_dojo}/solves/{code}/json", params={"user_name": name})
    assert filtered.status_code == 200
    rows = filtered.json()
    assert rows, "the export deliberately keeps hidden members' solves so instructors do not lose data"
    assert all(row["user_id"] == user_id for row in rows)
    assert any(row["challenge"] == "apple" for row in rows)


def test_solves_code_check_rejects_a_keyless_dojo(simple_award_dojo):
    assert db_sql(f"SELECT private_key FROM dojos WHERE dojo_id={dojo_db_id(simple_award_dojo)}").strip() == "", \
        "test precondition: a spec-created dojo has no private key"
    response = requests.get(f"{DOJO_URL}/dojo/{simple_award_dojo}/solves/deadbeef/json")
    assert response.status_code == 403, \
        f"a dojo with no solves code must refuse every code rather than error, got {response.status_code}"


def test_dojo_route_404_for_non_viewable_dojo(random_private_dojo, random_user, admin_session):
    _, session = random_user
    url = f"{DOJO_URL}/{random_private_dojo}/"

    assert requests.get(url).status_code == 404, "a private dojo is invisible to anonymous visitors"
    assert session.get(url).status_code == 404, "a private dojo is invisible to non-members"
    assert admin_session.get(url).status_code == 200, "site admins bypass membership entirely"

    join_dojo(session, random_private_dojo)
    assert session.get(url).status_code == 200, "joining makes the dojo viewable"

    assert requests.get(f"{DOJO_URL}/no-such-dojo-{rand_token()}/").status_code == 404


def test_dojo_admin_routes_404_before_403(random_private_dojo, random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)
    urls = [f"{DOJO_URL}/dojo/{random_private_dojo}/admin/", f"{DOJO_URL}/dojo/{random_private_dojo}/admin/activity"]

    for url in urls:
        assert session.get(url).status_code == 404, f"a non-member must not learn that {url} exists"

    join_dojo(session, random_private_dojo)
    for url in urls:
        assert session.get(url).status_code == 403, f"a plain member is refused {url}"
        assert admin_session.get(url).status_code == 200, f"a site admin may open {url}"

    promote = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{random_private_dojo}/admins/promote", json={"user_id": user_id}
    )
    assert promote.status_code == 200, f"Expected the promotion to succeed, got {promote.status_code}"
    for url in urls:
        assert session.get(url).status_code == 200, f"a promoted dojo admin may open {url}"


def test_dojo_admin_member_list_shows_hidden_members(example_dojo, random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)

    join_dojo(session, example_dojo)
    set_hidden(session, True)

    page = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert page.status_code == 200
    assert name in page.text, "the dojo member list is not filtered by the users' hidden flag"
    assert admin_session.get(f"{DOJO_URL}/hacker/{user_id}").status_code == 404, \
        "the profile the member list links to stays protected"


def test_join_dojo_password_enforcement(admin_session, example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    dojo = create_spec_dojo(admin_session, {
        "id": f"vismatrix-pass-{rand_token()}",
        "name": "Visibility Matrix Password",
        "type": "public",
        "password": "correcthorse1",
        "modules": [{"id": "hello", "name": "Hello", "challenges": [{"id": "apple", "name": "Apple", **imported()}]}],
    })
    dojo_id = dojo_db_id(dojo)

    assert session.get(f"{DOJO_URL}/{dojo}/").status_code == 404, \
        "a password protected public dojo is not viewable before joining"
    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 403, "joining requires the password"
    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/wrongpass").status_code == 403, "a wrong password is refused"
    assert db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id={dojo_id} AND user_id={user_id}").strip() == "0"

    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/correcthorse1").status_code == 200
    assert db_sql(f"SELECT type FROM dojo_users WHERE dojo_id={dojo_id} AND user_id={user_id}").strip() == "member"
    assert session.get(f"{DOJO_URL}/{dojo}/").status_code == 200, "the dojo is viewable once joined"


def test_promote_dojo_requires_site_admin(admin_session, example_dojo, guest_dojo_admin):
    name, session = guest_dojo_admin
    user_id = get_user_id(name)
    dojo = create_spec_dojo(admin_session, {
        "id": f"vismatrix-promote-{rand_token()}",
        "name": "Visibility Matrix Promote",
        "type": "public",
        "modules": [{"id": "hello", "name": "Hello", "challenges": [{"id": "apple", "name": "Apple", **imported()}]}],
    })
    dojo_id = dojo_db_id(dojo)

    join_dojo(session, dojo)
    assert admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/admins/promote", json={"user_id": user_id}
    ).status_code == 200

    refused = session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/promote", json={})
    assert refused.status_code == 403, f"a dojo admin may not make their dojo official, got {refused.status_code}"
    assert db_sql(f"SELECT official FROM dojos WHERE dojo_id={dojo_id}").strip() == "f"

    assert admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/promote", json={}).status_code == 200
    assert db_sql(f"SELECT official FROM dojos WHERE dojo_id={dojo_id}").strip() == "t"


def test_admins_promote_authorization_and_validation(admin_session, example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    outsider_name, _ = register_user()
    outsider_id = get_user_id(outsider_name)
    dojo = create_spec_dojo(admin_session, {
        "id": f"vismatrix-admins-{rand_token()}",
        "name": "Visibility Matrix Admins",
        "type": "public",
        "modules": [{"id": "hello", "name": "Hello", "challenges": [{"id": "apple", "name": "Apple", **imported()}]}],
    })
    dojo_id = dojo_db_id(dojo)
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/admins/promote"

    join_dojo(session, dojo)
    refused = session.post(url, json={"user_id": user_id})
    assert refused.status_code == 403, f"a plain member cannot promote anyone, got {refused.status_code}"

    missing = admin_session.post(url, json={})
    assert missing.status_code == 400 and missing.json()["error"] == "User not specified."

    outsider = admin_session.post(url, json={"user_id": outsider_id})
    assert outsider.status_code == 400, f"a non-member cannot be promoted, got {outsider.status_code}"
    assert "not currently a dojo member" in outsider.json()["error"]

    assert db_sql(f"SELECT type FROM dojo_users WHERE dojo_id={dojo_id} AND user_id={user_id}").strip() == "member", \
        "no refused call may change a membership type"
    assert db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id={dojo_id} AND user_id={outsider_id}").strip() == "0"


def test_grant_award_authorization_and_validation(admin_session, event_dojo, example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant"

    def award_count():
        return int(db_sql(f"SELECT count(*) FROM awards WHERE user_id={user_id}").strip())

    before = award_count()

    join_dojo(session, event_dojo)
    member = session.post(url, json={"user_id": user_id, "emoji": "🥈", "description": "self service"})
    assert member.status_code == 403, f"a plain member cannot grant awards, got {member.status_code}"

    not_emoji = admin_session.post(url, json={"user_id": user_id, "emoji": "x", "description": "d"})
    assert not_emoji.status_code == 400 and not_emoji.json()["error"] == "emoji must be emoji."

    incomplete = admin_session.post(url, json={"user_id": user_id})
    assert incomplete.status_code == 400, f"missing fields are a bad request, got {incomplete.status_code}"

    unknown = admin_session.post(url, json={"user_id": MISSING_USER_ID, "emoji": "🥈", "description": "d"})
    assert unknown.status_code == 404, f"an unknown target user is a 404, got {unknown.status_code}"

    assert award_count() == before, "no refused grant may create an award"

    plain_dojo = create_spec_dojo(admin_session, {
        "id": f"vismatrix-noaward-{rand_token()}",
        "name": "Visibility Matrix No Award",
        "type": "public",
        "modules": [{"id": "hello", "name": "Hello", "challenges": [{"id": "apple", "name": "Apple", **imported()}]}],
    })
    no_permission = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{plain_dojo}/award/grant",
        json={"user_id": user_id, "emoji": "🥈", "description": "d"},
    )
    assert no_permission.status_code == 403, \
        f"a dojo without the grant_awards permission refuses even site admins, got {no_permission.status_code}"
    assert award_count() == before


def test_dojo_update_and_delete_authorization(admin_session, example_dojo, guest_dojo_admin):
    name, session = guest_dojo_admin
    user_id = get_user_id(name)

    assert requests.post(f"{DOJO_URL}/dojo/{example_dojo}/update/wrongcode").status_code == 403, \
        "the update endpoint requires the dojo's update code"
    assert requests.post(f"{DOJO_URL}/dojo/no-such-dojo-{rand_token()}/update/x").status_code == 404

    dojo = create_spec_dojo(admin_session, {
        "id": f"vismatrix-delete-{rand_token()}",
        "name": "Visibility Matrix Delete",
        "type": "public",
        "modules": [{"id": "hello", "name": "Hello", "challenges": [{"id": "apple", "name": "Apple", **imported()}]}],
    })
    dojo_id = dojo_db_id(dojo)

    join_dojo(session, dojo)
    assert admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/admins/promote", json={"user_id": user_id}
    ).status_code == 200

    refused = session.post(f"{DOJO_URL}/dojo/{dojo}/delete/", json={})
    assert refused.status_code == 403, f"a dojo admin may not delete the dojo, got {refused.status_code}"
    assert db_sql(f"SELECT count(*) FROM dojos WHERE dojo_id={dojo_id}").strip() == "1", "the dojo survives"

    deleted = admin_session.post(f"{DOJO_URL}/dojo/{dojo}/delete/", json={})
    assert deleted.status_code == 200, f"a site admin may delete the dojo, got {deleted.status_code}"
    assert db_sql(f"SELECT count(*) FROM dojos WHERE dojo_id={dojo_id}").strip() == "0"


def test_spec_dojo_creation_requires_site_admin(random_user):
    _, session = random_user
    dojo_id = f"sneaky-{rand_token()}"

    keys = dojo_run("docker", "exec", "cache", "redis-cli", "--scan", "--pattern", "flask_cache_rl:*").stdout.split()
    for key in keys:
        dojo_run("docker", "exec", "cache", "redis-cli", "DEL", key)

    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", json={"spec": f"id: {dojo_id}\nmodules: []\n"})
    assert response.status_code == 400, \
        f"a non-admin spec creation must be refused on authorization, got {response.status_code}: {response.text[:200]}"
    assert "admin" in response.json()["error"], f"Unexpected error: {response.json()['error']}"
    assert db_sql(f"SELECT count(*) FROM dojos WHERE id='{dojo_id}'").strip() == "0", "no dojo may be created"


def test_dojo_list_api_anonymous_scope(random_private_dojo, example_dojo, random_user):
    _, session = random_user

    def listed(requester):
        response = requester.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
        assert response.status_code == 200, f"the dojo list is anonymous-accessible, got {response.status_code}"
        return [dojo["id"] for dojo in response.json()["dojos"]]

    anonymous = listed(requests)
    assert example_dojo in anonymous, "official dojos are listed anonymously"
    assert random_private_dojo not in anonymous, "a private dojo is never listed anonymously"
    assert random_private_dojo not in listed(session), "a private dojo is not listed to non-members"

    join_dojo(session, random_private_dojo)
    assert random_private_dojo in listed(session), "a member sees the dojos they belong to"
    assert random_private_dojo not in listed(requests), "joining does not make the dojo public"


def test_search_is_scoped_to_viewable_dojos(admin_session, example_dojo, random_user):
    _, session = random_user
    token = f"zqxsecret{rand_token()}"
    dojo = create_spec_dojo(admin_session, {
        "id": f"vismatrix-search-{rand_token()}",
        "name": f"{token} Dojo",
        "description": "private search fixture",
        "modules": [{
            "id": "m",
            "name": f"{token} Module",
            "challenges": [{"id": "c", "name": f"{token} Challenge", **imported()}],
        }],
    })

    def results(requester):
        response = requester.get(f"{DOJO_URL}/pwncollege_api/v1/search", params={"q": token})
        assert response.status_code == 200, f"Expected 200 from search, got {response.status_code}"
        return response.json()["results"]

    for label, requester in (("anonymous", requests), ("a non-member", session)):
        found = results(requester)
        assert found["dojos"] == [] and found["modules"] == [] and found["challenges"] == [], \
            f"{label} must not see a private dojo's content in search: {found}"

    admin_found = results(admin_session)
    assert admin_found["dojos"] and admin_found["modules"] and admin_found["challenges"], \
        "site admins can search their own private dojos"

    join_dojo(session, dojo)
    member_found = results(session)
    assert [d["id"] for d in member_found["dojos"]] == [dojo], "the dojo appears once the user joins"
    assert [m["id"] for m in member_found["modules"]] == ["m"]
    assert [c["id"] for c in member_found["challenges"]] == ["c"]

    assert requests.get(f"{DOJO_URL}/pwncollege_api/v1/search", params={"q": "a"}).status_code == 400, \
        "a one character query is refused"


def test_dojos_page_lists_only_viewable_dojos(admin_session, example_dojo, random_user):
    _, session = random_user
    name = f"Zqxprivate {rand_token()} Dojo"
    dojo = create_spec_dojo(admin_session, {
        "id": f"vismatrix-listing-{rand_token()}",
        "name": name,
        "type": "topic",
        "modules": [{"id": "m", "name": "M", "challenges": [{"id": "c", "name": "C", **imported()}]}],
    })

    assert name not in requests.get(f"{DOJO_URL}/dojos").text, "anonymous visitors never see a private dojo"
    assert name not in session.get(f"{DOJO_URL}/dojos").text, "non-members never see a private dojo"
    assert name in admin_session.get(f"{DOJO_URL}/dojos").text, "site admins see it throughout"

    join_dojo(session, dojo)
    assert name in session.get(f"{DOJO_URL}/dojos").text, "members see the dojo in their listing"


def test_course_user_parameter_requires_dojo_admin(course_dojo, random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)
    other_name, _ = register_user()
    other_id = get_user_id(other_name)
    url = f"{DOJO_URL}/dojo/{course_dojo}/course"

    join_dojo(session, course_dojo)
    assert session.get(url).status_code == 200, "a member may view their own course page"
    identity = session.patch(f"{DOJO_URL}/dojo/{course_dojo}/course/identity", json={"identity": "tok-alpha"})
    assert identity.status_code == 200 and identity.json()["success"] is True

    refused = session.get(url, params={"user": other_id})
    assert refused.status_code == 403, f"viewing another user's course page needs dojo admin, got {refused.status_code}"

    assert admin_session.get(url, params={"user": MISSING_USER_ID}).status_code == 404

    as_admin = admin_session.get(url, params={"user": user_id})
    assert as_admin.status_code == 200, f"a dojo admin may view a member's course page, got {as_admin.status_code}"
    assert "tok-alpha" in as_admin.text, "the page carries the requested user's course identity"

    as_other = admin_session.get(url, params={"user": other_id})
    assert as_other.status_code == 200
    assert "tok-alpha" not in as_other.text, "the page is scoped to the user named in the query"


def test_course_admin_user_page_authorization(course_dojo, example_dojo, random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)

    non_course = f"{DOJO_URL}/dojo/{example_dojo}/admin/users/{user_id}"
    assert session.get(non_course).status_code == 404, "a dojo without a course has no such page"
    assert admin_session.get(non_course).status_code == 404, "the course check runs before the admin check"

    join_dojo(session, course_dojo)
    member = session.get(f"{DOJO_URL}/dojo/{course_dojo}/admin/users/{user_id}")
    assert member.status_code == 403, f"a plain member is refused the course admin page, got {member.status_code}"

    anonymous = requests.get(f"{DOJO_URL}/dojo/{course_dojo}/admin/users/{user_id}", allow_redirects=False)
    assert anonymous.status_code == 302 and "/login" in anonymous.headers["Location"], \
        "anonymous visitors are sent to the login page"

    as_admin = admin_session.get(f"{DOJO_URL}/dojo/{course_dojo}/admin/users/{user_id}")
    assert as_admin.status_code == 200, f"a site admin may view a member's page, got {as_admin.status_code}"
    assert name in as_admin.text

    assert admin_session.get(
        f"{DOJO_URL}/dojo/{course_dojo}/admin/users/{MISSING_USER_ID}"
    ).status_code == 404, "an unknown user id is a 404"


@pytest.mark.timeout(180)
def test_profile_dojo_list_is_scoped_to_the_viewer(admin_session, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    _, other_session = register_user()
    secret_name = f"Zqxsecret {rand_token()} Dojo"
    public_name = f"Zqxpublic {rand_token()} Dojo"
    secret = create_spec_dojo(admin_session, local_dojo_spec("secret", secret_name, "topic"))
    public = create_spec_dojo(admin_session, local_dojo_spec("shared", public_name, "public"))

    for dojo in (secret, public):
        join_dojo(session, dojo)
        solve_challenge_offline(dojo, "hello", "apple", session=session, user=name)
        recompute(f"stats:scores:dojo:{dojo_db_id(dojo)}", "scores_update", {"dojo_id": dojo_db_id(dojo)})

    own = session.get(f"{DOJO_URL}/hacker/")
    assert own.status_code == 200
    assert secret_name in own.text, "the profile owner can see their progress in a dojo they belong to"
    assert public_name in own.text, "guard: progress in a viewable dojo is rendered"

    theirs = other_session.get(f"{DOJO_URL}/hacker/{user_id}")
    assert theirs.status_code == 200
    assert secret_name not in theirs.text, \
        "the dojo list is computed from the viewer's viewable dojos, so private progress is not disclosed"
    assert public_name in theirs.text, "progress in a dojo the viewer can see is disclosed"


@pytest.mark.timeout(180)
def test_profile_excludes_course_and_hidden_type_dojos(admin_session, random_user):
    name, session = random_user
    dojos = {}
    for dojo_type in ("public", "hidden", "course"):
        dojo_name = f"Zqx{dojo_type} {rand_token()} Dojo"
        dojos[dojo_type] = (dojo_name, create_spec_dojo(
            admin_session, local_dojo_spec(dojo_type, dojo_name, dojo_type)))

    for _, dojo in dojos.values():
        join_dojo(session, dojo)
        solve_challenge_offline(dojo, "hello", "apple", session=session, user=name)
        recompute(f"stats:scores:dojo:{dojo_db_id(dojo)}", "scores_update", {"dojo_id": dojo_db_id(dojo)})

    profile = session.get(f"{DOJO_URL}/hacker/")
    assert profile.status_code == 200
    assert dojos["public"][0] in profile.text, "guard: a public dojo with solves does show up on the profile"
    assert dojos["hidden"][0] not in profile.text, "hidden-type dojos are excluded from every profile"
    assert dojos["course"][0] not in profile.text, "course-type dojos are excluded from every profile"


def test_invisible_challenge_solve_endpoint_404(visibility_test_dojo, random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)
    join_dojo(session, visibility_test_dojo)

    hidden_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{visibility_test_dojo}/module2/challenge-b/solve"
    flag = challenge_flag(visibility_test_dojo, "module2", "challenge-b", user=name)
    response = session.post(hidden_url, json={"submission": flag})
    assert response.status_code == 404, f"an invisible challenge cannot be solved, got {response.status_code}"
    assert response.json()["error"] == "Challenge not found"

    admin_flag = challenge_flag(visibility_test_dojo, "module2", "challenge-b", user="admin")
    admin_response = admin_session.post(hidden_url, json={"submission": admin_flag})
    assert admin_response.status_code == 404, \
        f"the solve endpoint has no admin exemption for visibility, got {admin_response.status_code}"

    challenge_id = db_sql(
        "SELECT dc.challenge_id FROM dojo_challenges dc "
        "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = {dojo_db_id(visibility_test_dojo)} AND dm.id = 'module2' AND dc.id = 'challenge-b'"
    ).strip()
    assert db_sql(
        f"SELECT count(*) FROM solves WHERE challenge_id={challenge_id} AND user_id IN ({user_id}, {get_user_id('admin')})"
    ).strip() == "0", "the refused submission must not record a solve"

    solve_challenge_offline(visibility_test_dojo, "module2", "challenge-c", session=session, user=name)


def test_invisible_challenge_description_endpoint(visibility_test_dojo, random_user, admin_session):
    _, session = random_user
    join_dojo(session, visibility_test_dojo)
    hidden_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{visibility_test_dojo}/module2/challenge-b/description"

    member = session.get(hidden_url)
    assert member.status_code == 404, f"a member cannot read an invisible description, got {member.status_code}"
    assert member.json()["success"] is False

    as_admin = admin_session.get(hidden_url)
    assert as_admin.status_code == 200, f"a dojo admin can read it, got {as_admin.status_code}"
    assert "Challenge with future visibility" in as_admin.json()["description"]

    visible_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{visibility_test_dojo}/module2/challenge-c/description"
    assert session.get(visible_url).status_code == 200, "a visible challenge's description is readable by members"

    anonymous = requests.get(visible_url, allow_redirects=False)
    assert anonymous.status_code in (302, 403), \
        f"the description endpoint is authed-only, got {anonymous.status_code}"


def test_invisible_challenge_survey_endpoint(visibility_test_dojo, random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)
    join_dojo(session, visibility_test_dojo)
    hidden_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{visibility_test_dojo}/module2/challenge-b/surveys"

    for label, requester in (("a member", session), ("a site admin", admin_session)):
        response = requester.get(hidden_url)
        assert response.status_code == 404, \
            f"{label} got {response.status_code} for an invisible challenge's survey"

    visible = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{visibility_test_dojo}/module2/challenge-c/surveys")
    assert visible.status_code == 200, f"a visible challenge answers the survey query, got {visible.status_code}"
    assert visible.json()["type"] == "none", "a challenge with no survey reports type none"

    posted = session.post(hidden_url, json={"response": "hello"})
    assert posted.status_code == 404, f"a survey cannot be posted to an invisible challenge, got {posted.status_code}"
    assert db_sql(f"SELECT count(*) FROM survey_responses WHERE user_id={user_id}").strip() == "0"


def test_past_stop_window_hides_challenge(visibility_matrix_dojo, random_user, admin_session):
    _, session = random_user
    join_dojo(session, visibility_matrix_dojo)

    member = module_named(modules_of(session, visibility_matrix_dojo), "expiry")
    assert [c["id"] for c in member["challenges"]] == ["open"], \
        "a window that has already ended hides the challenge exactly like one that has not started"

    as_admin = module_named(modules_of(admin_session, visibility_matrix_dojo), "expiry")
    assert [c["id"] for c in as_admin["challenges"]] == ["expired", "open"], \
        "dojo admins retain access to expired challenges"

    start = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
        "dojo": visibility_matrix_dojo, "module": "expiry", "challenge": "expired", "practice": False,
    })
    assert start.status_code == 200
    assert start.json()["success"] is False, "a member must not be able to start an expired challenge"
    assert start.json()["error"] == "Invalid challenge"


def test_dojo_level_visibility_cascades(admin_session, example_dojo, random_user):
    _, session = random_user
    dojo = create_spec_dojo(admin_session, {
        "id": f"vismatrix-cascade-{rand_token()}",
        "name": "Visibility Matrix Cascade",
        "type": "public",
        "visibility": {"start": "2099-01-01T00:00:00Z"},
        "modules": [{
            "id": "m",
            "name": "M",
            "resources": [
                {"type": "markdown", "name": "CascadeResource", "content": "hi"},
                {"type": "challenge", "id": "c", "name": "C", **imported()},
            ],
        }],
    })

    join_dojo(session, dojo)
    assert modules_of(session, dojo) == [], \
        "a dojo level visibility window hides every module from members until it opens"

    admin_modules = modules_of(admin_session, dojo)
    assert len(admin_modules) == 1, f"dojo admins still see the module, got {admin_modules}"
    assert [c["id"] for c in admin_modules[0]["challenges"]] == ["c"]
    assert [r["name"] for r in admin_modules[0]["resources"]] == ["CascadeResource"]

    start = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
        "dojo": dojo, "module": "m", "challenge": "c", "practice": False,
    })
    assert start.status_code == 200 and start.json()["success"] is False, \
        "the cascaded window also blocks starting the challenge"


def test_resource_visibility_window(visibility_matrix_dojo, random_user, admin_session):
    _, session = random_user
    join_dojo(session, visibility_matrix_dojo)

    member = module_named(modules_of(session, visibility_matrix_dojo), "resources")
    assert [r["name"] for r in member["resources"]] == ["NowResource"], \
        "a resource outside its visibility window is omitted for members"

    as_admin = module_named(modules_of(admin_session, visibility_matrix_dojo), "resources")
    assert [r["name"] for r in as_admin["resources"]] == ["FutureResource", "NowResource"], \
        "dojo admins see resources regardless of their window"

    member_page = session.get(f"{DOJO_URL}/{visibility_matrix_dojo}/resources/")
    assert member_page.status_code == 200
    assert "NOW_RESOURCE_MARKER" in member_page.text, "guard: an in-window resource renders on the module page"
    assert "FUTURE_RESOURCE_MARKER" not in member_page.text, \
        "the rendered module page must not leak the content of an out-of-window resource"

    admin_page = admin_session.get(f"{DOJO_URL}/{visibility_matrix_dojo}/resources/")
    assert admin_page.status_code == 200
    assert "FUTURE_RESOURCE_MARKER" in admin_page.text, "dojo admins see the out-of-window resource"


@pytest.mark.timeout(180)
def test_show_challenges_only_affects_page_rendering(hidden_challenges_dojo, random_user):
    name, session = random_user
    join_dojo(session, hidden_challenges_dojo)

    page = session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/")
    assert page.status_code == 200
    assert "CHALLENGE" not in page.text, "show_challenges=False suppresses challenge rendering on the module page"

    module = module_named(modules_of(session, hidden_challenges_dojo), "module")
    assert len(module["challenges"]) == 1, \
        "show_challenges only affects rendering; the modules API still lists the challenge"

    try:
        start = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
            "dojo": hidden_challenges_dojo, "module": "module",
            "challenge": module["challenges"][0]["id"], "practice": False,
        })
        assert start.status_code == 200
        assert start.json()["success"] is True, \
            f"the challenge is still startable, got {start.json().get('error')}"
    finally:
        remove_workspace_container(name)


def test_progression_locked_description(progression_locked_dojo, random_user, admin_session):
    name, session = random_user
    join_dojo(session, progression_locked_dojo)
    url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{progression_locked_dojo}/progression-locked-module/locked-challenge/description"

    assert admin_session.get(url).status_code == 200, "dojo admins are exempt from progression locks"

    locked = session.get(url)
    assert locked.status_code == 403, f"a locked challenge's description is refused, got {locked.status_code}"
    assert locked.json()["error"] == "This challenge is locked"

    solve_challenge_offline(progression_locked_dojo, "progression-locked-module", "unlocked-challenge",
                            session=session, user=name)

    unlocked = session.get(url)
    assert unlocked.status_code == 200, f"solving the prerequisite unlocks the description, got {unlocked.status_code}"
    assert unlocked.json()["description"] is not None


@pytest.mark.timeout(120)
def test_scoreboard_excludes_dojo_admins(admin_session, guest_dojo_admin):
    name, session = guest_dojo_admin
    user_id = get_user_id(name)
    control_name, control_session = register_user()
    dojo = create_spec_dojo(admin_session, local_dojo_spec("ignoreadmins", "Visibility Matrix Ignore Admins", "public"))

    join_dojo(session, dojo)
    assert admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/admins/promote", json={"user_id": user_id}
    ).status_code == 200

    solve_challenge_offline(dojo, "hello", "apple", session=session, user=name)
    join_dojo(control_session, dojo)
    solve_challenge_offline(dojo, "hello", "apple", session=control_session, user=control_name)
    recompute(dojo_scoreboard_cache_key(dojo), "scoreboard_update",
              {"model_type": "dojo", "model_id": dojo_db_id(dojo)})

    standings = all_standings(requests.Session(), dojo)
    assert any(standing["name"] == control_name for standing in standings), \
        "guard: a plain member's solve does reach the standings"
    assert not any(standing["name"] == name for standing in standings), \
        "a dojo admin's solves are excluded from that dojo's scoreboard"

    solves = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/solves")
    assert solves.status_code == 200
    assert [solve["challenge_id"] for solve in solves.json()["solves"]] == ["apple"], \
        "the per-user solves API still reports the dojo admin's own solves"


def test_workspace_view_of_another_user_requires_admin(random_user, admin_session):
    name, _ = random_user
    user_id = get_user_id(name)
    _, other_session = register_user()
    url = f"{DOJO_URL}/pwncollege_api/v1/workspace"

    for params in ({"user": user_id}, {"user": user_id, "service": "terminal"}):
        response = other_session.get(url, params=params)
        assert response.status_code == 403, \
            f"a user must not open another user's workspace ({params}), got {response.status_code}"

    as_admin = admin_session.get(url, params={"user": user_id})
    assert as_admin.status_code == 200, f"site admins may inspect a workspace, got {as_admin.status_code}"

    anonymous = requests.get(url, params={"user": user_id}, allow_redirects=False)
    assert anonymous.status_code in (302, 403), \
        f"the workspace endpoint is authed-only, got {anonymous.status_code}"


@pytest.mark.timeout(300)
def test_cli_token_authenticates_as_container_user(example_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    me_url = f"{DOJO_URL}/pwncollege_api/v1/users/me"

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        token = workspace_run("printenv DOJO_AUTH_TOKEN", user=name).stdout.strip()
        assert token.startswith("sk-workspace-local-"), f"unexpected container token format: {token[:24]}"

        tokened = requests.Session()
        authed = tokened.get(me_url, headers={"Authorization": f"Bearer {token}"})
        assert authed.status_code == 200, f"the container token must authenticate, got {authed.status_code}"
        assert authed.json()["id"] == user_id and authed.json()["name"] == name

        without_header = tokened.get(me_url, allow_redirects=False)
        assert without_header.status_code in (302, 403), \
            "the container token must not establish a login session for later requests"

        forged = requests.get(me_url, headers={"Authorization": "Bearer sk-workspace-local-garbage"})
        assert forged.status_code == 401, f"a forged token is rejected, got {forged.status_code}"
        assert forged.json()["error"] == "Failed to authenticate container token."

        start_challenge(example_dojo, "hello", "banana", session=session)
        stale_challenge = requests.get(me_url, headers={"Authorization": f"Bearer {token}"})
        assert stale_challenge.status_code == 403, \
            f"a token minted for another challenge is refused, got {stale_challenge.status_code}"
        assert stale_challenge.json()["error"] == "Token failed to authenticate active challenge container."

        remove_workspace_container(name)
        no_container = requests.get(me_url, headers={"Authorization": f"Bearer {token}"})
        assert no_container.status_code == 403, \
            f"a token without a running container is refused, got {no_container.status_code}"
        assert no_container.json()["error"] == "No active challenge container."
    finally:
        remove_workspace_container(name)


def test_ssh_service_token_auth(random_private_dojo, random_user):
    name, session = random_user
    user_id = get_user_id(name)
    join_dojo(session, random_private_dojo)

    def mint(target_id):
        output = flask_exec(
            "from itsdangerous.url_safe import URLSafeTimedSerializer\n"
            "from CTFd.plugins.dojo_plugin.config import DOJO_SSH_SERVICE_KEY\n"
            f"print(URLSafeTimedSerializer(DOJO_SSH_SERVICE_KEY).dumps([{target_id}, 'ssh-tui']))\n"
        )
        return output.strip().splitlines()[-1].strip()

    def dojo_ids(**headers):
        response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos", headers=headers)
        assert response.status_code == 200, f"Expected 200 from the dojo list, got {response.status_code}"
        return [dojo["id"] for dojo in response.json()["dojos"]]

    assert random_private_dojo not in dojo_ids(), "guard: the private dojo is not listed anonymously"
    assert random_private_dojo in dojo_ids(Authorization=f"Bearer sk-ssh-service-{mint(user_id)}"), \
        "an ssh service token makes the request act as that user"

    bad = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos",
                       headers={"Authorization": "Bearer sk-ssh-service-garbage"})
    assert bad.status_code == 401, f"a bad signature is rejected, got {bad.status_code}"
    assert bad.json()["error"] == "Failed to authenticate ssh service token."

    unknown = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos",
                           headers={"Authorization": f"Bearer sk-ssh-service-{mint(MISSING_USER_ID)}"})
    assert unknown.status_code == 404, f"a token for an unknown user is a 404, got {unknown.status_code}"


@pytest.mark.timeout(180)
def test_active_module_neighbors_skip_invisible(visibility_matrix_dojo, random_user):
    name, session = random_user
    join_dojo(session, visibility_matrix_dojo)

    try:
        start_challenge(visibility_matrix_dojo, "neighbors", "one", session=session)
        response = session.get(f"{DOJO_URL}/active-module")
        assert response.status_code == 200, f"Expected 200 from /active-module, got {response.status_code}"
        active = response.json()
        assert active["c_current"]["challenge_reference_id"] == "one"
        assert active["c_previous"] == {}, "the first visible challenge has no predecessor"
        assert active["c_next"]["challenge_reference_id"] == "three", \
            "the invisible neighbour must be skipped when reporting the next challenge"
    finally:
        remove_workspace_container(name)


@pytest.mark.timeout(180)
def test_active_module_with_invisible_current_challenge(visibility_matrix_dojo, random_user, admin_session):
    name, session = random_user
    user_id = get_user_id(name)
    join_dojo(session, visibility_matrix_dojo)
    assert admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{visibility_matrix_dojo}/admins/promote", json={"user_id": user_id}
    ).status_code == 200

    try:
        start_challenge(visibility_matrix_dojo, "neighbors", "two", session=session)
        response = session.get(f"{DOJO_URL}/active-module")
        assert response.status_code == 200, f"Expected 200 from /active-module, got {response.status_code}"
        assert response.json()["c_current"]["challenge_reference_id"] == "two", \
            "/active-module must describe whatever challenge is actually running"
    finally:
        remove_workspace_container(name)
