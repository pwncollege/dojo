import datetime
import json
import random
import string
import time

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
    wait_for_background_worker,
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


def set_hidden(session, hidden):
    response = session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": hidden})
    assert response.status_code == 200, f"Expected 200 setting hidden={hidden}, got {response.status_code}"


def join_dojo(session, dojo):
    response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200, f"Expected to join {dojo}, got {response.status_code}"


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
