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
    challenge_db_id,
    create_dojo_yml,
    db_sql,
    get_user_id,
    login,
    redis_cli,
    solve_challenge_offline,
    wait_for_background_worker,
)

BELT_ORDER = ["orange", "yellow", "green", "purple", "blue", "brown", "red", "black"]


def random_suffix(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def http_get(session, url, **kwargs):
    """GET, retrying gateway errors: nginx drops requests while workspace containers rewire the nested network."""
    for _ in range(4):
        response = session.get(url, **kwargs)
        if response.status_code not in (502, 503, 504):
            return response
        time.sleep(1)
    return response


def new_user():
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    for attempt in range(3):
        try:
            return name, login(name, name, register=True)
        except AssertionError:
            if attempt == 2:
                raise
            time.sleep(1)


def award_spec(dojo_id, *, dojo_type="public", emoji=None, challenges=("apple",), name=None):
    spec = {
        "id": dojo_id,
        "modules": [{"id": "hello", "challenges": [{"id": challenge} for challenge in challenges]}],
        "files": [
            {"type": "text", "path": f"hello/{challenge}/src", "content": "#!/opt/pwn.college/bash\ncat /flag\n"}
            for challenge in challenges
        ],
    }
    if dojo_type:
        spec["type"] = dojo_type
    if emoji:
        spec["award"] = {"emoji": emoji}
    if name:
        spec["name"] = name
    return yaml.safe_dump(spec, allow_unicode=True)


def hex_id(dojo_reference_id):
    return dojo_reference_id.split("~", 1)[1]


def publish_stat_event(event_type):
    event = json.dumps({
        "type": event_type,
        "payload": {},
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    redis_cli("XADD", "stat:events", "*", "data", event)
    wait_for_background_worker(timeout=15)


def recalculate_belts():
    publish_stat_event("belts_update")


def recalculate_emojis():
    publish_stat_event("emojis_update")


def belts_payload():
    response = http_get(requests, f"{DOJO_URL}/pwncollege_api/v1/belts")
    assert response.status_code == 200, f"Expected 200 from the belts API, got {response.status_code}"
    return response.json()


def scoreboard_page(session, dojo, page=1, module="_"):
    response = http_get(session, f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/{module}/0/{page}")
    assert response.status_code == 200, f"Expected 200 from the scoreboard API, got {response.status_code}"
    return response.json()


def scoreboard_me(session, dojo, *, retries=20):
    for _ in range(retries):
        board = scoreboard_page(session, dojo)
        if board.get("me"):
            return board["me"]
        wait_for_background_worker(timeout=1)
    raise AssertionError(f"user never appeared on the scoreboard of {dojo}")


def scoreboard_standing(session, dojo, user_name, *, retries=20, max_pages=5):
    for _ in range(retries):
        for page in range(1, max_pages + 1):
            board = scoreboard_page(session, dojo, page=page)
            for entry in board["standings"]:
                if entry["name"] == user_name:
                    return entry
            if not board["standings"]:
                break
        wait_for_background_worker(timeout=1)
    raise AssertionError(f"user {user_name} never appeared on the scoreboard of {dojo}")


def badge_for(entry, category):
    return next((badge for badge in entry["badges"] if badge["category"] == category), None)


def emoji_award_rows(user_id, category):
    return db_sql(
        f"SELECT name FROM awards WHERE type='emoji' AND user_id={user_id} AND category='{category}'"
    ).split()


def belt_names(user_id):
    return db_sql(f"SELECT name FROM awards WHERE type='belt' AND user_id={user_id} ORDER BY name").split()


def feed_events():
    response = http_get(requests, f"{DOJO_URL}/pwncollege_api/v1/feed/events", params={"limit": 100})
    assert response.status_code == 200, f"Expected 200 from the feed API, got {response.status_code}"
    return response.json()["data"]


@pytest.fixture(scope="module")
def simple_award_dojo(admin_session):
    return create_dojo_yml(
        award_spec(f"awards-simple-{random_suffix()}", emoji="🧪", challenges=("apple", "banana")),
        session=admin_session,
    )


@pytest.fixture(scope="module")
def codepoints_award_dojo(admin_session):
    return create_dojo_yml(
        award_spec(f"awards-codepoints-{random_suffix()}", emoji="🐻‍❄️", challenges=("apple", "banana")),
        session=admin_session,
    )


@pytest.fixture(scope="module")
def arena_dojo(admin_session):
    """A public, award-free dojo that several users solve, so badges can be compared across viewers."""
    return create_dojo_yml(award_spec(f"awards-arena-{random_suffix()}"), session=admin_session)


@pytest.fixture(scope="module")
def awarded_user(simple_award_dojo, codepoints_award_dojo):
    name, session = new_user()
    for dojo in [simple_award_dojo, codepoints_award_dojo]:
        assert http_get(session, f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 200
        for challenge in ["apple", "banana"]:
            solve_challenge_offline(dojo, "hello", challenge, session=session, user=name)
    recalculate_emojis()
    return name, session


def test_belt_backfill_grants_every_qualified_color(belt_dojos):
    user_name, session = new_user()
    user_id = get_user_id(user_name)

    for color in ["blue", "green", "yellow"]:
        solve_challenge_offline(belt_dojos[color], "test", "test", session=session, user=user_name)
    assert belt_names(user_id) == [], "belts were granted before the lowest requirement was met"

    solve_challenge_offline(belt_dojos["orange"], "test", "test", session=session, user=user_name)
    assert belt_names(user_id) == ["blue", "green", "orange", "yellow"], \
        "completing the final prerequisite should backfill every qualified belt"

    recalculate_belts()
    payload = belts_payload()
    for color in ["orange", "yellow", "green", "blue"]:
        assert str(user_id) in payload["dates"][color], f"missing {color} date for backfilled user"
    assert user_id in payload["ranks"]["blue"], "user should be ranked under their highest belt"
    assert user_id not in payload["ranks"]["orange"], "user should not be ranked under a lower belt"
    assert payload["users"][str(user_id)]["color"] == "blue", "displayed belt should jump to the highest color"


def test_belt_requires_official_dojo(belt_dojos, admin_session):
    impostor = create_dojo_yml(award_spec("intro-to-cybersecurity"), session=admin_session)
    assert "~" in impostor, "an unofficial dojo must not claim the bare belt-requirement reference id"

    user_name, session = new_user()
    user_id = get_user_id(user_name)
    solve_challenge_offline(impostor, "hello", "apple", session=session, user=user_name)

    assert belt_names(user_id) == [], "an unofficial dojo must not confer a belt"
    entry = scoreboard_me(session, impostor)
    assert entry["belt"] == "/belt/white.svg", f"expected a white belt, got {entry['belt']}"


def test_belt_credit_follows_challenge_not_dojo(belt_dojos, example_dojo):
    user_name, session = new_user()
    user_id = get_user_id(user_name)

    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=user_name)

    assert belt_names(user_id) == ["orange"], \
        "solving the imported challenge elsewhere should satisfy the belt requirement"
    recalculate_belts()
    assert user_id in belts_payload()["ranks"]["orange"]


def test_belt_grant_is_idempotent_and_never_revoked(belt_dojos, simple_award_dojo, admin_session):
    user_name, session = new_user()
    user_id = get_user_id(user_name)
    solve_challenge_offline(belt_dojos["orange"], "test", "test", session=session, user=user_name)
    assert belt_names(user_id) == ["orange"]

    db_sql(f"DELETE FROM submissions WHERE user_id={user_id}")

    assert http_get(session, f"{DOJO_URL}/dojo/{simple_award_dojo}/join/").status_code == 200
    for challenge in ["apple", "banana"]:
        solve_challenge_offline(simple_award_dojo, "hello", challenge, session=session, user=user_name)

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{belt_dojos['orange']}/awards/prune", json={})
    assert response.status_code == 200, f"Expected 200 from prune, got {response.status_code}"

    assert belt_names(user_id) == ["orange"], "belts must never be revoked or duplicated"
    recalculate_belts()
    assert user_id in belts_payload()["ranks"]["orange"], "belt must survive the loss of the solve that earned it"


def test_belts_api_payload_shape_and_anonymous_access():
    payload = belts_payload()
    assert set(payload) >= {"dates", "users", "ranks"}, f"unexpected belts payload keys: {sorted(payload)}"
    assert isinstance(payload["users"], dict)
    for color in BELT_ORDER:
        assert color in payload["dates"], f"missing dates entry for {color}"
        assert isinstance(payload["ranks"][color], list), f"ranks[{color}] should be a list"


def test_belts_api_and_page_report_highest_belt_only(belt_dojos):
    user_name, session = new_user()
    user_id = get_user_id(user_name)
    solve_challenge_offline(belt_dojos["orange"], "test", "test", session=session, user=user_name)
    solve_challenge_offline(belt_dojos["yellow"], "test", "test", session=session, user=user_name)
    recalculate_belts()

    payload = belts_payload()
    assert user_id in payload["ranks"]["yellow"], "user should be ranked under their highest belt"
    assert user_id not in payload["ranks"]["orange"], "user should appear in ranks exactly once"
    assert payload["users"][str(user_id)]["color"] == "yellow"
    assert payload["users"][str(user_id)]["handle"] == user_name

    orange_date = payload["dates"]["orange"][str(user_id)]
    yellow_date = payload["dates"]["yellow"][str(user_id)]
    assert datetime.datetime.fromisoformat(orange_date) <= datetime.datetime.fromisoformat(yellow_date), \
        "dates should record when each individual belt was earned"

    page = http_get(requests, f"{DOJO_URL}/belts")
    assert page.status_code == 200
    body = page.text
    assert body.count(user_name) == 1, "a belted user should be listed exactly once on the belts page"
    assert body.index("Yellow Belts") < body.index(user_name) < body.index("Orange Belts"), \
        "the user should be listed under their highest belt color"


def test_belts_api_and_page_exclude_hidden_and_unbelted_users(belt_dojos, arena_dojo):
    hidden_name, hidden_session = new_user()
    hidden_id = get_user_id(hidden_name)
    solve_challenge_offline(belt_dojos["orange"], "test", "test", session=hidden_session, user=hidden_name)
    recalculate_belts()
    assert hidden_id in belts_payload()["ranks"]["orange"]
    assert hidden_name in http_get(requests, f"{DOJO_URL}/belts").text

    plain_name, plain_session = new_user()
    assert http_get(plain_session, f"{DOJO_URL}/dojo/{arena_dojo}/join/").status_code == 200
    solve_challenge_offline(arena_dojo, "hello", "apple", session=plain_session, user=plain_name)

    response = hidden_session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": True})
    assert response.status_code == 200, f"Expected 200 hiding the user, got {response.status_code}"
    recalculate_belts()

    payload = belts_payload()
    assert hidden_id not in payload["ranks"]["orange"], "hidden users must not be ranked"
    assert str(hidden_id) not in payload["users"], "hidden users must not appear in the belts payload"
    assert str(hidden_id) not in payload["dates"]["orange"], "hidden users must not appear in belt dates"

    body = http_get(requests, f"{DOJO_URL}/belts").text
    assert hidden_name not in body, "hidden users must not be listed on the belts page"
    assert plain_name not in body, "unbelted users must not be listed on the belts page"


def test_belts_api_ranks_ordered_by_date(belt_dojos):
    first_name, first_session = new_user()
    second_name, second_session = new_user()

    solve_challenge_offline(belt_dojos["orange"], "test", "test", session=first_session, user=first_name)
    solve_challenge_offline(belt_dojos["orange"], "test", "test", session=second_session, user=second_name)
    recalculate_belts()

    ranks = belts_payload()["ranks"]["orange"]
    first_id, second_id = get_user_id(first_name), get_user_id(second_name)
    assert first_id in ranks and second_id in ranks
    assert ranks.index(first_id) < ranks.index(second_id), "ranks should be ordered by ascension date"


def test_emoji_award_row_and_badge_contract(awarded_user, simple_award_dojo, codepoints_award_dojo, arena_dojo):
    user_name, session = awarded_user
    user_id = get_user_id(user_name)
    simple_hex = hex_id(simple_award_dojo)
    codepoints_hex = hex_id(codepoints_award_dojo)

    rows = db_sql("SELECT name, coalesce(icon, 'NULL'), description FROM awards "
                  f"WHERE type='emoji' AND user_id={user_id} AND category='{simple_hex}'").strip().split("\n")
    assert len(rows) == 1, f"expected exactly one emoji award row, got {rows}"
    award_name, icon, description = rows[0].split("|", 2)
    assert award_name == "CURRENT", f"expected a CURRENT award, got {award_name}"
    assert icon == "NULL", "completion awards must not store the emoji character"
    display_name = db_sql(f"SELECT coalesce(name, '') FROM dojos WHERE dojo_id = x'{simple_hex}'::int").strip()
    expected = display_name or simple_award_dojo
    assert description == f"Awarded for completing the {expected} dojo."

    entry = scoreboard_me(session, simple_award_dojo)
    for badge in entry["badges"]:
        assert set(badge) == {"text", "emoji", "count", "url", "stale", "category"}, \
            f"unexpected badge fields: {sorted(badge)}"
        assert isinstance(badge["count"], int)
        assert isinstance(badge["stale"], bool)

    simple_badge = badge_for(entry, simple_hex)
    assert simple_badge is not None, "the completed dojo should contribute a badge"
    assert simple_badge["emoji"] == "🧪"
    assert simple_badge["count"] == 1
    assert simple_badge["stale"] is False
    assert simple_badge["url"] == f"/dojo/{simple_award_dojo}", "an emoji dojo badge should link to its dojo"

    codepoints_badge = badge_for(entry, codepoints_hex)
    assert codepoints_badge is not None
    assert codepoints_badge["emoji"] == "🐻‍❄️", "multi-codepoint emoji must be preserved verbatim"

    assert http_get(session, f"{DOJO_URL}/dojo/{arena_dojo}/join/").status_code == 200
    solve_challenge_offline(arena_dojo, "hello", "apple", session=session, user=user_name)
    recalculate_emojis()
    assert emoji_award_rows(user_id, simple_hex) == ["CURRENT"], "later solves must not duplicate the emoji award"
    assert badge_for(scoreboard_me(session, simple_award_dojo), simple_hex)["count"] == 1


def test_emoji_requires_full_completion_and_an_award_config(simple_award_dojo, event_dojo):
    user_name, session = new_user()
    user_id = get_user_id(user_name)

    assert http_get(session, f"{DOJO_URL}/dojo/{simple_award_dojo}/join/").status_code == 200
    solve_challenge_offline(simple_award_dojo, "hello", "apple", session=session, user=user_name)

    assert http_get(session, f"{DOJO_URL}/dojo/{event_dojo}/join/").status_code == 200
    solve_challenge_offline(event_dojo, "award", "award", session=session, user=user_name)
    recalculate_emojis()

    assert emoji_award_rows(user_id, hex_id(simple_award_dojo)) == [], \
        "partial completion must not grant an emoji award"
    assert emoji_award_rows(user_id, hex_id(event_dojo)) == [], \
        "a dojo without an award config must not grant an emoji award"
    assert scoreboard_me(session, simple_award_dojo)["badges"] == []
    assert scoreboard_me(session, event_dojo)["badges"] == []


def test_emoji_character_resolved_live_from_dojo_config(awarded_user, simple_award_dojo):
    user_name, session = awarded_user
    simple_hex = hex_id(simple_award_dojo)
    assert badge_for(scoreboard_me(session, simple_award_dojo), simple_hex)["emoji"] == "🧪"

    try:
        db_sql(f"UPDATE dojos SET data = jsonb_set(data, '{{award,emoji}}', '\"🚀\"') "
               f"WHERE dojo_id = x'{simple_hex}'::int")
        badge = badge_for(scoreboard_me(session, simple_award_dojo), simple_hex)
        assert badge["emoji"] == "🚀", "the badge emoji should follow the dojo config without regranting"
    finally:
        db_sql(f"UPDATE dojos SET data = jsonb_set(data, '{{award,emoji}}', '\"🧪\"') "
               f"WHERE dojo_id = x'{simple_hex}'::int")

    assert badge_for(scoreboard_me(session, simple_award_dojo), simple_hex)["emoji"] == "🧪"


def test_emoji_badge_visibility_respects_dojo_access(admin_session, arena_dojo):
    private_dojo = create_dojo_yml(
        award_spec(f"awards-private-{random_suffix()}", dojo_type="topic", emoji="🛸"), session=admin_session)
    example_dojo_rid = create_dojo_yml(
        award_spec(f"awards-example-{random_suffix()}", dojo_type="example", emoji="🧬"), session=admin_session)
    private_hex, example_hex = hex_id(private_dojo), hex_id(example_dojo_rid)

    owner_name, owner_session = new_user()
    owner_id = get_user_id(owner_name)
    for dojo in [private_dojo, example_dojo_rid, arena_dojo]:
        assert http_get(owner_session, f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 200
        solve_challenge_offline(dojo, "hello", "apple", session=owner_session, user=owner_name)
    recalculate_emojis()

    assert emoji_award_rows(owner_id, private_hex) == ["CURRENT"]
    assert emoji_award_rows(owner_id, example_hex) == ["CURRENT"]

    own_view = scoreboard_me(owner_session, arena_dojo)
    assert badge_for(own_view, private_hex) is not None, "a member should see their own private-dojo badge"
    assert badge_for(own_view, example_hex) is None, "example dojos must never contribute badges"

    _, other_session = new_user()
    other_view = scoreboard_standing(other_session, arena_dojo, owner_name)
    assert badge_for(other_view, private_hex) is None, \
        "badges from a dojo the viewer cannot see must be hidden"
    assert badge_for(other_view, example_hex) is None


def test_custom_awards_fold_by_emoji(admin_session, event_dojo, arena_dojo):
    user_name, session = new_user()
    user_id = get_user_id(user_name)
    grant_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant"

    for emoji, description in [("🥈", "Test emoji 1"), ("🥈", "Test emoji 2"), ("🥇", "Test emoji 3")]:
        response = admin_session.post(grant_url, json={"user_id": user_id, "emoji": emoji, "description": description})
        assert response.status_code == 200, f"Expected 200 granting {emoji}, got {response.status_code}"

    assert http_get(session, f"{DOJO_URL}/dojo/{arena_dojo}/join/").status_code == 200
    solve_challenge_offline(arena_dojo, "hello", "apple", session=session, user=user_name)
    recalculate_emojis()

    badges = scoreboard_me(session, arena_dojo)["badges"]
    silver = [badge for badge in badges if badge["emoji"] == "🥈"]
    gold = [badge for badge in badges if badge["emoji"] == "🥇"]
    assert len(silver) == 1, "identical custom emoji should fold into a single badge"
    assert silver[0]["count"] == 2
    assert set(silver[0]["text"].split("\n")) == {"Test emoji 1", "Test emoji 2"}
    assert silver[0]["url"] == "#", "a badge from a dojo without an emoji award should not link to a dojo"
    assert len(gold) == 1, "distinct custom emoji should be separate badges"
    assert gold[0]["count"] == 1


def test_grant_award_authorization(random_user_session, event_dojo):
    user_name, _ = new_user()
    user_id = get_user_id(user_name)
    event_hex = hex_id(event_dojo)
    grant_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant"
    body = {"user_id": user_id, "emoji": "🥈", "description": "nope"}

    assert random_user_session.post(grant_url, json=body).status_code == 403, \
        "non-admins must not be able to grant awards"
    assert requests.post(grant_url, json=body).status_code == 403, \
        "anonymous requests must not be able to grant awards"
    assert emoji_award_rows(user_id, event_hex) == []


def test_grant_award_validation(admin_session, event_dojo):
    user_name, _ = new_user()
    user_id = get_user_id(user_name)
    event_hex = hex_id(event_dojo)
    grant_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant"

    for body in [{"emoji": "🥈", "description": "d"},
                 {"user_id": user_id, "description": "d"},
                 {"user_id": user_id, "emoji": "🥈"}]:
        response = admin_session.post(grant_url, json=body)
        assert response.status_code == 400, f"expected 400 for {sorted(body)}, got {response.status_code}"
        assert response.json()["success"] is False
        assert response.json()["error"] == "Must supply user_id, emoji, and description."

    for bad_emoji in ["not-an-emoji", "", "🥈🥈"]:
        response = admin_session.post(grant_url, json={"user_id": user_id, "emoji": bad_emoji, "description": "d"})
        assert response.status_code == 400, f"expected 400 for emoji {bad_emoji!r}, got {response.status_code}"
        assert response.json()["error"] == "emoji must be emoji."

    assert emoji_award_rows(user_id, event_hex) == [], "rejected grants must not create awards"

    response = admin_session.post(grant_url, json={"user_id": 999999, "emoji": "🥈", "description": "x"})
    assert response.status_code == 404, f"expected 404 for an unknown user, got {response.status_code}"
    assert response.json()["success"] is False
    assert db_sql("SELECT count(*) FROM awards WHERE user_id=999999").strip() == "0"

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/no-such-dojo-xyz/award/grant",
                                  json={"user_id": user_id, "emoji": "🥈", "description": "x"})
    assert response.status_code == 404, f"expected 404 for an unknown dojo, got {response.status_code}"

    response = admin_session.post(grant_url, json={"user_id": user_id, "emoji": "🐻‍❄️", "description": "polar"})
    assert response.status_code == 200, "multi-codepoint emoji should be accepted"
    assert emoji_award_rows(user_id, event_hex) == ["CUSTOM"]


def test_prune_stales_and_restores_awards(admin_session, completionist_user, simple_award_dojo, codepoints_award_dojo):
    user_name, session = completionist_user
    user_id = get_user_id(user_name)
    simple_hex, codepoints_hex = hex_id(simple_award_dojo), hex_id(codepoints_award_dojo)
    prune_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{simple_award_dojo}/awards/prune"

    banana_id = challenge_db_id(simple_award_dojo, "hello", "banana")
    db_sql(f"DELETE FROM submissions WHERE user_id={user_id} AND challenge_id={banana_id}")

    response = admin_session.post(prune_url, json={})
    assert response.status_code == 200
    assert response.json() == {"success": True, "pruned_awards": 1}, \
        f"prune should report the awards it staled, got {response.json()}"

    response = admin_session.post(prune_url, json={})
    assert response.status_code == 200
    assert response.json()["pruned_awards"] == 0, "pruning twice must not re-count already-stale awards"
    assert emoji_award_rows(user_id, simple_hex) == ["STALE"], "pruning must stale in place, not duplicate"

    assert emoji_award_rows(user_id, codepoints_hex) == ["CURRENT"], "pruning must be scoped to its own dojo"
    recalculate_emojis()
    assert badge_for(scoreboard_me(session, simple_award_dojo), simple_hex)["stale"] is True
    assert badge_for(scoreboard_me(session, codepoints_award_dojo), codepoints_hex)["stale"] is False

    solve_challenge_offline(simple_award_dojo, "hello", "banana", session=session, user=user_name)
    recalculate_emojis()
    assert emoji_award_rows(user_id, simple_hex) == ["CURRENT"], "re-completion should restore the existing award row"
    assert badge_for(scoreboard_me(session, simple_award_dojo), simple_hex)["stale"] is False


def test_prune_preserves_completers_and_custom_awards(admin_session, awarded_user, codepoints_award_dojo,
                                                      event_dojo, arena_dojo):
    user_name, session = awarded_user
    user_id = get_user_id(user_name)
    codepoints_hex = hex_id(codepoints_award_dojo)

    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{codepoints_award_dojo}/awards/prune", json={})
    assert response.status_code == 200
    assert response.json()["pruned_awards"] == 0, "a fully-satisfied dojo should prune nothing"
    assert emoji_award_rows(user_id, codepoints_hex) == ["CURRENT"]
    recalculate_emojis()
    assert badge_for(scoreboard_me(session, codepoints_award_dojo), codepoints_hex)["stale"] is False

    custom_name, custom_session = new_user()
    custom_id = get_user_id(custom_name)
    event_hex = hex_id(event_dojo)
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant",
                                  json={"user_id": custom_id, "emoji": "🥈", "description": "Granted, not earned"})
    assert response.status_code == 200

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/awards/prune", json={})
    assert response.status_code == 200
    assert response.json()["pruned_awards"] == 0, "custom awards must never be pruned"
    assert emoji_award_rows(custom_id, event_hex) == ["CUSTOM"]

    assert http_get(custom_session, f"{DOJO_URL}/dojo/{arena_dojo}/join/").status_code == 200
    solve_challenge_offline(arena_dojo, "hello", "apple", session=custom_session, user=custom_name)
    recalculate_emojis()
    badge = badge_for(scoreboard_me(custom_session, arena_dojo), event_hex)
    assert badge is not None and badge["stale"] is False


def test_prune_requires_dojo_admin_and_existing_dojo(admin_session, random_user_session, awarded_user,
                                                     simple_award_dojo, random_private_dojo):
    user_name, _ = awarded_user
    user_id = get_user_id(user_name)
    simple_hex = hex_id(simple_award_dojo)
    prune_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{simple_award_dojo}/awards/prune"
    before = emoji_award_rows(user_id, simple_hex)

    assert random_user_session.post(prune_url, json={}).status_code == 403, "non-admins must not prune"
    assert requests.post(prune_url, json={}).status_code == 403, "anonymous requests must not prune"
    assert emoji_award_rows(user_id, simple_hex) == before, "a rejected prune must not change awards"

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/definitely-not-a-dojo/awards/prune", json={})
    assert response.status_code == 404, f"expected 404 for an unknown dojo, got {response.status_code}"

    response = random_user_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{random_private_dojo}/awards/prune", json={})
    assert response.status_code == 404, \
        f"an inaccessible dojo should be indistinguishable from a missing one, got {response.status_code}"


def test_belt_and_emoji_feed_events(belt_dojos, simple_award_dojo, admin_session):
    user_name, session = new_user()
    solve_challenge_offline(belt_dojos["orange"], "test", "test", session=session, user=user_name)

    belt_event = next((event for event in feed_events()
                       if event["type"] == "belt_earned" and event["user_name"] == user_name), None)
    assert belt_event is not None, "earning a belt should publish a feed event"
    assert belt_event["data"]["belt"] == "orange"
    assert belt_event["data"]["belt_name"] == "Orange Belt"
    assert belt_event["data"]["dojo_id"] == "intro-to-cybersecurity"
    assert belt_event["user_belt"] == "orange"

    assert http_get(session, f"{DOJO_URL}/dojo/{simple_award_dojo}/join/").status_code == 200
    for challenge in ["apple", "banana"]:
        solve_challenge_offline(simple_award_dojo, "hello", challenge, session=session, user=user_name)

    emoji_event = next((event for event in feed_events()
                        if event["type"] == "emoji_earned" and event["user_name"] == user_name), None)
    assert emoji_event is not None, "completing a public award dojo should publish a feed event"
    assert emoji_event["data"]["emoji"] == "🧪"
    assert emoji_event["data"]["dojo_id"] == simple_award_dojo
    assert "🧪" in emoji_event["user_emojis"]
    assert "CURRENT" not in emoji_event["user_emojis"]

    private_dojo = create_dojo_yml(
        award_spec(f"awards-quiet-{random_suffix()}", dojo_type="topic", emoji="🛸"), session=admin_session)
    assert http_get(session, f"{DOJO_URL}/dojo/{private_dojo}/join/").status_code == 200
    solve_challenge_offline(private_dojo, "hello", "apple", session=session, user=user_name)

    assert emoji_award_rows(get_user_id(user_name), hex_id(private_dojo)) == ["CURRENT"], \
        "a private award dojo should still grant its award"
    assert not any(event["type"] == "emoji_earned" and event["user_name"] == user_name
                   and event["data"].get("dojo_id") == private_dojo
                   for event in feed_events()), "a private dojo completion must not publish a feed event"

    solve_challenge_offline(belt_dojos["yellow"], "test", "test", session=session, user=user_name)
    later_public_event = next((event for event in feed_events()
                               if event["type"] == "belt_earned"
                               and event["user_name"] == user_name
                               and event["data"]["belt"] == "yellow"), None)
    assert later_public_event is not None, "the later public solve should publish an event"
    assert "🧪" in later_public_event["user_emojis"], \
        "public emoji awards should remain visible in later public events"
    assert "🛸" not in later_public_event["user_emojis"], \
        "a later public event must not expose the user's private-dojo award"


def test_dojos_list_api_exposes_award_config(admin_session, simple_award_dojo, event_dojo):
    response = http_get(admin_session, f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert response.status_code == 200
    dojos = {dojo["id"]: dojo for dojo in response.json()["dojos"]}

    assert simple_award_dojo in dojos, "the award dojo should be listed"
    assert dojos[simple_award_dojo]["award"] == {"emoji": "🧪"}
    assert event_dojo in dojos
    assert dojos[event_dojo]["award"] in (None, {}), \
        f"a dojo without an award should report none, got {dojos[event_dojo]['award']}"


def test_dojo_page_renders_awardee_list(admin_session):
    dojo = create_dojo_yml(
        award_spec(f"awards-listing-{random_suffix()}", emoji="🎖️", challenges=("apple", "banana")),
        session=admin_session)
    user_name, session = new_user()
    for challenge in ["apple", "banana"]:
        solve_challenge_offline(dojo, "hello", challenge, session=session, user=user_name)
    user_id = get_user_id(user_name)
    assert emoji_award_rows(user_id, hex_id(dojo)) == ["CURRENT"]

    response = http_get(admin_session, f"{DOJO_URL}/{dojo}/")
    assert response.status_code == 200, f"the dojo page should render its awardees, got {response.status_code}"
    assert user_name in response.text, "the awardee should be listed on the dojo page"

    banana_id = challenge_db_id(dojo, "hello", "banana")
    db_sql(f"DELETE FROM submissions WHERE user_id={user_id} AND challenge_id={banana_id}")
    prune = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/awards/prune", json={})
    assert prune.status_code == 200 and prune.json()["pruned_awards"] == 1
    assert http_get(admin_session, f"{DOJO_URL}/{dojo}/").status_code == 200, \
        "the dojo page should render with staled awards"

    db_sql("UPDATE dojos SET data = data - 'award' || jsonb_build_object('award', jsonb_build_object('belt', 'orange')) "
           f"WHERE dojo_id = x'{hex_id(dojo)}'::int")
    assert http_get(admin_session, f"{DOJO_URL}/{dojo}/").status_code == 200, \
        "the dojo page should render for belt-award dojos"
