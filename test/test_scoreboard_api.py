import json
import random
import re
import string
import time

import pytest
import requests

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    flask_exec,
    login,
    redis_cli,
    solve_challenge,
    wait_for_background_worker,
)

pytestmark = pytest.mark.timeout(180)

SB_CREW_TAG = "SBCREW"
SB_HIDDEN_TAG = "SBHID"
ENTRY_KEYS = {"rank", "solves", "user_id", "name", "url", "symbol", "belt", "badges", "crew"}

def sb_flask_exec(code):
    return flask_exec(code)


def rand_id(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def make_dojo(filename, marker, session):
    spec = open(TEST_DOJOS_LOCATION / filename).read().replace(marker, f"{marker}-{rand_id()}", 1)
    return create_dojo_yml(spec, session=session)


def register(*, suffix="", email_domain="example.com"):
    base = rand_id(12)
    name = f"{base}{suffix}"
    return name, login(name, base, register=True, email=f"{base}@{email_domain}")


def join(session, dojo):
    response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200, f"failed to join {dojo}: {response.status_code}"


def challenge_ids(dojo):
    rows = db_sql(
        "SELECT dm.id, dc.id, dc.challenge_id FROM dojo_challenges dc "
        "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = {dojo_db_id(dojo)}"
    )
    return {
        (line.split("|")[0], line.split("|")[1]): int(line.split("|")[2])
        for line in rows.strip().splitlines()
    }


def user_ids(names):
    quoted = ", ".join("'" + name.replace("'", "''") + "'" for name in names)
    rows = db_sql(f"SELECT id, name FROM users WHERE name IN ({quoted})")
    result = {}
    for line in rows.strip().splitlines():
        user_id, name = line.split("|", 1)
        result[name] = int(user_id)
    assert set(result) == set(names), f"missing users: {set(names) - set(result)}"
    return result


def derive_flags(pairs):
    flags = flask_exec(
        "import os\n"
        "from itsdangerous.url_safe import URLSafeSerializer\n"
        "serializer = URLSafeSerializer(os.environ['SECRET_KEY'])\n"
        f"for user_id, challenge_id in {pairs!r}:\n"
        "    print('pwn.college{' + serializer.dumps([user_id, challenge_id])[::-1] + '}')"
    ).strip().splitlines()
    assert len(flags) == len(pairs), f"expected {len(pairs)} flags, got {flags}"
    return flags


def bulk_solve(dojo, plan, sessions, uids, cids):
    """Solve (user_name, module, challenge) triples in order.

    The stats worker's staleness guard drops a solve event whose publication
    predates the cache's last write, so events are drained one at a time to keep
    the incremental scoreboard deterministic regardless of worker backlog.
    """
    flags = derive_flags([(uids[name], cids[(module, challenge)]) for name, module, challenge in plan])
    wait_for_background_worker(timeout=60)
    for (name, module, challenge), flag in zip(plan, flags):
        solve_challenge(dojo, module, challenge, session=sessions[name], flag=flag)
        wait_for_background_worker(timeout=60)


def asset_name(url):
    return url.split("?")[0].rsplit("/", 1)[-1]


def board(session, dojo, module="_", duration=0, page=1, **params):
    getter = session.get if session is not None else requests.get
    response = getter(
        f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/{module}/{duration}/{page}", params=params
    )
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
    return response.json()


def all_standings(session, dojo, module="_", duration=0):
    standings = []
    page = 1
    while True:
        result = board(session, dojo, module, duration, page)
        standings.extend(result["standings"])
        if page + 1 not in result["pages"]:
            return standings
        page += 1


def names_on(standings):
    return [entry["name"] for entry in standings]


def entry_for(standings, name):
    return next((entry for entry in standings if entry["name"] == name), None)


def crew_board(session, dojo, module="_", duration=0, page=1, **params):
    getter = session.get if session is not None else requests.get
    response = getter(
        f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/{module}/crews/{duration}/{page}", params=params
    )
    assert response.status_code == 200, f"expected 200, got {response.status_code}: {response.text}"
    return response.json()


def redis_cmd(*args):
    result = redis_cli(*args, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def recalc_dojo(dojo_id):
    output = sb_flask_exec(
        "from CTFd.plugins.dojo_plugin.worker.handlers.scoreboard import handle_scoreboard_update\n"
        f"handle_scoreboard_update({{'model_type': 'dojo', 'model_id': {dojo_id}}})\n"
        "print('RECALC-OK')\n"
    )
    assert "RECALC-OK" in output, output


def scores_report(dojo_id, uids, module_indices):
    output = sb_flask_exec(
        "import json\n"
        "from CTFd.plugins.dojo_plugin.utils.scores import (\n"
        "    get_user_dojo_rank, get_user_dojo_solves, get_user_module_rank, get_user_module_solves)\n"
        f"report = {{}}\n"
        f"for uid in {list(uids)!r}:\n"
        f"    entry = {{'rank': get_user_dojo_rank({dojo_id}, uid), 'solves': get_user_dojo_solves({dojo_id}, uid)}}\n"
        f"    for mi in {list(module_indices)!r}:\n"
        f"        entry[str(mi)] = [get_user_module_rank({dojo_id}, mi, uid), get_user_module_solves({dojo_id}, mi, uid)]\n"
        "    report[str(uid)] = entry\n"
        "print('SCORES-JSON', json.dumps(report))\n"
    )
    match = re.search(r"SCORES-JSON (.*)", output)
    assert match, output
    return json.loads(match.group(1))


def get_page(url, tries=3):
    """GET a rendered page, retrying the gateway errors a loaded dev instance emits."""
    for attempt in range(tries):
        response = requests.get(url, timeout=40)
        if response.status_code not in (502, 503, 504) or attempt == tries - 1:
            return response
        time.sleep(2)


def wait_until(predicate, timeout=30, interval=0.5):
    deadline = time.time() + timeout
    result = predicate()
    while not result and time.time() < deadline:
        time.sleep(interval)
        result = predicate()
    return result


@pytest.fixture(scope="module")
def sb_main(admin_session):
    """A populated public dojo with a deterministic set of solvers.

    m1 holds a required and a non-required challenge; m2 hides its scoreboard in
    the UI and is solved by one tagged and one untagged user; m3 is solved only by
    an untagged user; m4 is never solved; m5 is never solved and is reserved for
    the synthetic-cache pagination tests.
    """
    dojo = make_dojo("scoreboard_api_main.yml", "sb-api-main", admin_session)
    dojo_id = dojo_db_id(dojo)
    cids = challenge_ids(dojo)

    alice, alice_session = register(email_domain="asu.edu")
    bob, bob_session = register(email_domain="mit.edu")
    carol, carol_session = register(email_domain="example.com")
    dave, dave_session = register()
    crew1, crew1_session = register(suffix=f" [{SB_CREW_TAG}]")
    crew2, crew2_session = register(suffix=f" [{SB_CREW_TAG}]")
    nobody, nobody_session = register()

    sessions = {
        alice: alice_session, bob: bob_session, carol: carol_session, dave: dave_session,
        crew1: crew1_session, crew2: crew2_session, nobody: nobody_session,
    }
    uids = user_ids(list(sessions))

    bulk_solve(dojo, [
        (alice, "m1", "apple"),
        (alice, "m1", "banana"),
        (bob, "m1", "apple"),
        (carol, "m1", "apple"),
        (dave, "m1", "banana"),
        (crew1, "m1", "apple"),
        (crew2, "m1", "apple"),
        (alice, "m2", "cherry"),
        (crew1, "m2", "cherry"),
        (alice, "m3", "date"),
    ], sessions, uids, cids)

    wait_for_background_worker(timeout=30)

    return dict(
        dojo=dojo, dojo_id=dojo_id, cids=cids, uids=uids, sessions=sessions,
        alice=alice, bob=bob, carol=carol, dave=dave,
        crew1=crew1, crew2=crew2, nobody=nobody,
    )


@pytest.fixture(scope="module")
def sb_filter(admin_session, example_dojo):
    """A public dojo used for the filtering/staleness behaviors.

    The incremental (solve-time) scoreboard is snapshotted here, before any test
    gets a chance to force a full recalculation, so that the incremental and
    recalculated behaviors can be asserted by independent tests in any order.
    """
    dojo = make_dojo("scoreboard_api_filter.yml", "sb-api-filter", admin_session)
    dojo_id = dojo_db_id(dojo)
    cids = challenge_ids(dojo)

    control, control_session = register()
    hidden, hidden_session = register(suffix=f" [{SB_HIDDEN_TAG}]")
    promoted, promoted_session = register()
    duplicate, duplicate_session = register()
    shared, shared_session = register()
    cached, cached_session = register()
    recent, recent_session = register()
    backdated, backdated_session = register()
    replayed, replayed_session = register()
    counter, counter_session = register()
    lag_first, lag_first_session = register()
    lag_second, lag_second_session = register()

    sessions = {
        control: control_session, hidden: hidden_session, promoted: promoted_session,
        duplicate: duplicate_session, shared: shared_session, cached: cached_session,
        recent: recent_session, backdated: backdated_session, replayed: replayed_session,
        counter: counter_session, lag_first: lag_first_session, lag_second: lag_second_session,
    }
    uids = user_ids(list(sessions))

    assert hidden_session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": True}).status_code == 200

    join(promoted_session, dojo)
    promote = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/admins/promote", json={"user_id": uids[promoted]}
    )
    assert promote.status_code == 200, f"failed to promote: {promote.status_code} {promote.text}"

    bulk_solve(dojo, [
        (control, "hello", "apple"),
        (hidden, "hello", "apple"),
        (promoted, "hello", "apple"),
        (replayed, "hello", "apple"),
        (duplicate, "dup", "berry"),
        (shared, "shared", "apple"),
        (cached, "cache", "cherry"),
        (recent, "window", "fig"),
        (backdated, "window", "fig"),
        (counter, "counts", "grape"),
        (counter, "counts", "grapefruit"),
        (lag_first, "lag", "lemon"),
        (lag_second, "lag", "lemon"),
    ], sessions, uids, cids)

    wait_for_background_worker(timeout=30)

    snapshot = {
        "_": all_standings(control_session, dojo),
        "hello": all_standings(control_session, dojo, "hello"),
    }

    return dict(
        dojo=dojo, dojo_id=dojo_id, cids=cids, uids=uids, sessions=sessions, snapshot=snapshot,
        control=control, hidden=hidden, promoted=promoted, duplicate=duplicate, shared=shared,
        cached=cached, recent=recent, backdated=backdated, replayed=replayed, counter=counter,
        lag_first=lag_first, lag_second=lag_second,
    )


@pytest.fixture(scope="module")
def sb_private(admin_session, example_dojo):
    dojo = make_dojo("scoreboard_api_private.yml", "sb-api-private", admin_session)
    return dict(dojo=dojo, dojo_id=dojo_db_id(dojo), cids=challenge_ids(dojo))


@pytest.fixture(scope="module")
def sb_award(admin_session, belt_dojos, example_dojo):
    """A public dojo that hides its scoreboard in the UI and grants an emoji on completion.

    'awarded' completes it (emoji) and solves the orange belt requirement;
    'control' only solves half of it, so it earns neither.
    """
    dojo = make_dojo("scoreboard_api_award.yml", "sb-api-award", admin_session)
    cids = challenge_ids(dojo)
    example_apple = challenge_ids(example_dojo)[("hello", "apple")]

    awarded, awarded_session = register()
    control, control_session = register()
    sessions = {awarded: awarded_session, control: control_session}
    uids = user_ids(list(sessions))

    flags = derive_flags([
        (uids[awarded], cids[("hello", "apple")]),
        (uids[awarded], cids[("hello", "banana")]),
        (uids[awarded], example_apple),
        (uids[control], cids[("hello", "apple")]),
    ])
    wait_for_background_worker(timeout=60)
    for target_dojo, module, challenge, session, flag in [
        (dojo, "hello", "apple", awarded_session, flags[0]),
        (dojo, "hello", "banana", awarded_session, flags[1]),
        (example_dojo, "hello", "apple", awarded_session, flags[2]),
        (dojo, "hello", "apple", control_session, flags[3]),
    ]:
        solve_challenge(target_dojo, module, challenge, session=session, flag=flag)
        wait_for_background_worker(timeout=60)

    return dict(dojo=dojo, dojo_id=dojo_db_id(dojo), cids=cids, uids=uids, sessions=sessions,
                awarded=awarded, control=control)


def test_scoreboard_entry_shape_and_no_email(sb_main):
    standings = all_standings(sb_main["sessions"][sb_main["alice"]], sb_main["dojo"])
    entry = entry_for(standings, sb_main["alice"])
    assert entry is not None, f"{sb_main['alice']} missing from standings {names_on(standings)}"
    assert set(entry) == ENTRY_KEYS, f"unexpected standing keys: {sorted(entry)}"
    assert "email" not in entry, "scoreboard standings must not leak email addresses"
    assert "challenges" not in entry, "scoreboard standings must not expose the raw challenge list"
    assert entry["url"] == f"/hacker/{sb_main['uids'][sb_main['alice']]}", entry["url"]
    assert entry["crew"] is None, "an untagged user has no crew"

    crew_entry = entry_for(standings, sb_main["crew1"])
    assert crew_entry["crew"] == {
        "tag": SB_CREW_TAG, "key": SB_CREW_TAG.lower(), "base_name": sb_main["crew1"].split(" [")[0],
    }, crew_entry["crew"]


def test_scoreboard_rank_ordering_and_tiebreak(sb_main):
    session = sb_main["sessions"][sb_main["alice"]]
    expected = [sb_main["alice"], sb_main["crew1"], sb_main["bob"], sb_main["carol"], sb_main["crew2"]]
    expected_solves = {sb_main["alice"]: 3, sb_main["crew1"]: 2, sb_main["bob"]: 1,
                       sb_main["carol"]: 1, sb_main["crew2"]: 1}

    def check(standings, label):
        assert names_on(standings) == expected, f"{label}: got {names_on(standings)}"
        assert [entry["rank"] for entry in standings] == list(range(1, len(standings) + 1)), \
            f"{label}: ranks must be contiguous, got {[e['rank'] for e in standings]}"
        for name, solves in expected_solves.items():
            assert entry_for(standings, name)["solves"] == solves, f"{label}: wrong solve count for {name}"

    check(all_standings(session, sb_main["dojo"]), "incremental")
    recalc_dojo(sb_main["dojo_id"])
    check(all_standings(session, sb_main["dojo"]), "recalculated")


def test_scoreboard_excludes_non_required_challenges(sb_main):
    session = sb_main["sessions"][sb_main["dave"]]
    dojo_standings = all_standings(session, sb_main["dojo"])
    assert entry_for(dojo_standings, sb_main["dave"]) is None, \
        "a user whose only solve is a 'required: false' challenge must not reach the scoreboard"
    assert entry_for(dojo_standings, sb_main["alice"])["solves"] == 3, \
        "alice solved 4 challenges but only 3 of them are required"

    module_standings = all_standings(session, sb_main["dojo"], "m1")
    assert entry_for(module_standings, sb_main["dave"]) is None, "dave must not be on the m1 scoreboard"
    assert entry_for(module_standings, sb_main["alice"])["solves"] == 1, \
        "only m1/apple is required, m1/banana must not count"


def test_scoreboard_module_scoped(sb_main):
    session = sb_main["sessions"][sb_main["bob"]]

    m1 = names_on(all_standings(session, sb_main["dojo"], "m1"))
    assert m1 == [sb_main["alice"], sb_main["bob"], sb_main["carol"], sb_main["crew1"], sb_main["crew2"]], m1

    m2 = all_standings(session, sb_main["dojo"], "m2")
    assert names_on(m2) == [sb_main["alice"], sb_main["crew1"]], names_on(m2)
    assert entry_for(m2, sb_main["bob"]) is None, "bob solved nothing in m2"

    m3 = all_standings(session, sb_main["dojo"], "m3")
    assert names_on(m3) == [sb_main["alice"]], names_on(m3)

    m4 = board(session, sb_main["dojo"], "m4")
    assert m4["standings"] == [], "nobody solved anything in m4"
    assert m4["pages"] == [], "an empty board advertises no pages"


def test_scoreboard_symbol_by_email_domain(sb_main):
    standings = all_standings(sb_main["sessions"][sb_main["alice"]], sb_main["dojo"])
    expected = {sb_main["alice"]: "fork.png", sb_main["bob"]: "student.png", sb_main["carol"]: "hacker.png"}
    for name, symbol in expected.items():
        entry = entry_for(standings, name)
        assert asset_name(entry["symbol"]) == symbol, f"{name}: expected {symbol}, got {entry['symbol']}"
        assert "email" not in entry, "the email used to pick the symbol must not be returned"


def test_scoreboard_me_entry(sb_main):
    session = sb_main["sessions"][sb_main["alice"]]
    result = board(session, sb_main["dojo"])
    assert "me" in result, "an authenticated solver gets a 'me' entry"
    assert result["me"]["user_id"] == sb_main["uids"][sb_main["alice"]]
    assert result["me"]["rank"] == entry_for(result["standings"], sb_main["alice"])["rank"]
    assert (result["me"]["rank"] - 1) // 20 + 1 in result["pages"], result["pages"]

    anonymous = board(None, sb_main["dojo"])
    assert "me" not in anonymous, "anonymous requests get no 'me' entry"

    non_solver = board(sb_main["sessions"][sb_main["nobody"]], sb_main["dojo"])
    assert "me" not in non_solver, "a user who is not on the board gets no 'me' entry"


def test_scoreboard_anonymous_readable(sb_main):
    result = board(None, sb_main["dojo"])
    assert len(result["standings"]) >= 1, "a public dojo's scoreboard is readable without authentication"
    assert "me" not in result
    for entry in result["standings"]:
        assert "email" not in entry, "anonymous readers must not receive email addresses"


def test_scoreboard_unsupported_duration_empty(sb_main):
    result = board(sb_main["sessions"][sb_main["alice"]], sb_main["dojo"], duration=365)
    assert result["standings"] == [], "only durations 0/7/30 are precomputed"
    assert result["pages"] == []
    assert "me" not in result


def test_scoreboard_pagination_and_me_page_hint(sb_main):
    alice_id = sb_main["uids"][sb_main["alice"]]
    entries = [
        {"rank": i, "solves": 100 - i, "user_id": 9_000_000 + i,
         "name": f"sb-synthetic-{i}", "email": f"sb-synthetic-{i}@example.com"}
        for i in range(1, 26)
    ]
    entries[-1]["user_id"] = alice_id
    entries[-1]["name"] = sb_main["alice"]
    entries[-1]["email"] = "unused@example.com"
    key = f"stats:scoreboard:module:{sb_main['dojo_id']}:4:0"
    assert redis_cmd("SET", key, json.dumps(entries, separators=(",", ":"))) == "OK"

    session = sb_main["sessions"][sb_main["alice"]]
    page1 = board(session, sb_main["dojo"], "m5", page=1)
    assert len(page1["standings"]) == 20, "standings are paged at 20 entries"
    assert [entry["rank"] for entry in page1["standings"]] == list(range(1, 21))
    assert {1, 2} <= set(page1["pages"]), page1["pages"]
    assert page1["me"]["rank"] == 25, "'me' is reported even when off the requested page"
    assert page1["me"]["user_id"] == alice_id
    assert (page1["me"]["rank"] - 1) // 20 + 1 in page1["pages"], \
        "the page holding 'me' is advertised even when another page was requested"

    page2 = board(session, sb_main["dojo"], "m5", page=2)
    assert len(page2["standings"]) == 5, "page 2 holds the remaining 5 entries"
    assert page2["standings"][0]["rank"] == 21
    page1_ids = {entry["user_id"] for entry in page1["standings"]}
    assert not page1_ids & {entry["user_id"] for entry in page2["standings"]}, "pages must not overlap"

    out_of_range = board(session, sb_main["dojo"], "m5", page=999)
    assert out_of_range["standings"] == [], "an out-of-range page yields no standings"
    assert 1 in out_of_range["pages"], "real pages are still advertised"


def test_module_show_scoreboard_false_still_served(sb_main):
    standings = all_standings(sb_main["sessions"][sb_main["alice"]], sb_main["dojo"], "m2")
    assert entry_for(standings, sb_main["alice"]) is not None, \
        "'show_scoreboard: false' is a UI-only flag; the module scoreboard API still serves standings"


def test_scores_ranks_solves_and_module_scoping(sb_main):
    names = [sb_main["alice"], sb_main["crew1"], sb_main["dave"], sb_main["bob"], sb_main["nobody"]]
    uids = [sb_main["uids"][name] for name in names]
    report = scores_report(sb_main["dojo_id"], uids, [0, 1, 3])
    by_name = {name: report[str(sb_main["uids"][name])] for name in names}

    assert by_name[sb_main["alice"]]["rank"] == 1, "alice has the most solves in the dojo"
    assert by_name[sb_main["alice"]]["solves"] == 3, \
        "the scores cache excludes 'required: false' challenges"
    assert by_name[sb_main["crew1"]]["rank"] == 2
    assert by_name[sb_main["crew1"]]["solves"] == 2
    assert by_name[sb_main["nobody"]]["rank"] is None, "a user with no solves is unranked"
    assert by_name[sb_main["nobody"]]["solves"] == 0

    assert by_name[sb_main["dave"]]["solves"] == 0, \
        "dave only solved a non-required challenge"
    assert by_name[sb_main["dave"]]["rank"] is None, \
        "the scores ranking excludes users with only optional solves"

    assert by_name[sb_main["alice"]]["0"] == [1, 1], "alice tops m1 with 1 required solve"
    assert by_name[sb_main["alice"]]["1"] == [1, 1], "alice tops m2 with 1 solve"
    assert by_name[sb_main["bob"]]["1"][0] is None, "bob solved nothing in m2"
    assert by_name[sb_main["alice"]]["3"][0] is None, "nobody solved anything in m4"


def test_hacker_page_renders_ranks(sb_main, sb_filter):
    alice_id = sb_main["uids"][sb_main["alice"]]
    output = sb_flask_exec(
        "from CTFd.plugins.dojo_plugin.utils.scores import get_dojo_scores, get_user_dojo_solves\n"
        f"scores = get_dojo_scores({sb_main['dojo_id']})\n"
        f"print('RANKINFO', scores['ranks'].index({alice_id}) + 1, len(scores['ranks']),"
        f" get_user_dojo_solves({sb_main['dojo_id']}, {alice_id}))\n"
    )
    match = re.search(r"RANKINFO (\d+) (\d+) (\d+)", output)
    assert match, output
    rank, max_rank, solves = match.groups()

    response = get_page(f"{DOJO_URL}/hacker/{alice_id}")
    assert response.status_code == 200, "a public profile is readable without authentication"
    assert f"{rank} / {max_rank}" in response.text, \
        f"expected the cached dojo rank {rank} / {max_rank} on the profile page"
    required_count = int(db_sql(
        f"SELECT COUNT(*) FROM dojo_challenges WHERE dojo_id = {sb_main['dojo_id']} AND required"
    ).strip())
    assert f"{solves} / {required_count}" in response.text, \
        f"expected the cached solve count {solves} of {required_count} required challenges"

    assert get_page(f"{DOJO_URL}/hacker/{sb_main['alice']}").status_code == 200

    hidden_id = sb_filter["uids"][sb_filter["hidden"]]
    assert get_page(f"{DOJO_URL}/hacker/{hidden_id}").status_code == 404, \
        "hidden users' profiles are not viewable by others"


def test_solve_credited_to_every_dojo_sharing_the_challenge(sb_filter, example_dojo):
    name = sb_filter["shared"]
    session = sb_filter["sessions"][name]

    own = board(session, sb_filter["dojo"]).get("me")
    assert own is not None and own["solves"] >= 1, \
        "the solve counts on the dojo it was submitted through"

    example = board(session, example_dojo, "hello").get("me")
    assert example is not None and example["solves"] >= 1, \
        "an imported challenge is one Challenges row, so the solve also lands on the source dojo's board"
    assert board(session, example_dojo).get("me") is not None, \
        "the solve also lands on the source dojo's dojo-level board"


def test_scoreboard_excludes_hidden_users_incremental(sb_filter):
    for module, standings in sb_filter["snapshot"].items():
        assert entry_for(standings, sb_filter["hidden"]) is None, \
            f"hidden user appeared on the incrementally-updated {module} scoreboard"


def test_hidden_user_gets_no_me_entry(sb_filter):
    session = sb_filter["sessions"][sb_filter["hidden"]]
    assert "me" not in board(session, sb_filter["dojo"]), "hidden users get no 'me' entry"
    assert "me_crew" not in crew_board(session, sb_filter["dojo"]), \
        "hidden users get no 'me_crew' entry even though their name carries a crew tag"


def test_scoreboard_excludes_dojo_admins_incremental(sb_filter):
    for module, standings in sb_filter["snapshot"].items():
        assert entry_for(standings, sb_filter["promoted"]) is None, \
            f"dojo admin appeared on the incrementally-updated {module} scoreboard"


def test_scoreboard_duration_windows(sb_filter):
    backdated_id = sb_filter["uids"][sb_filter["backdated"]]
    challenge_id = sb_filter["cids"][("window", "fig")]
    db_sql(
        f"UPDATE submissions SET date = NOW() - INTERVAL '10 days' "
        f"WHERE user_id = {backdated_id} AND challenge_id = {challenge_id}"
    )
    recalc_dojo(sb_filter["dojo_id"])

    session = sb_filter["sessions"][sb_filter["control"]]
    for duration in [0, 7, 30]:
        standings = all_standings(session, sb_filter["dojo"], duration=duration)
        assert entry_for(standings, sb_filter["recent"]) is not None, \
            f"a fresh solve belongs on the {duration}-day board"
        present = entry_for(standings, sb_filter["backdated"]) is not None
        if duration == 7:
            assert not present, "a 10-day-old solve must not appear on the 7-day board"
        else:
            assert present, f"a 10-day-old solve belongs on the {duration}-day board"


def test_queued_solve_events_are_not_dropped(sb_filter):
    first, second = sb_filter["lag_first"], sb_filter["lag_second"]
    session = sb_filter["sessions"][first]
    challenge_id = sb_filter["cids"][("lag", "lemon")]
    cache_key = f"stats:scoreboard:module:{sb_filter['dojo_id']}:5:0"

    standings = all_standings(session, sb_filter["dojo"], "lag")
    assert {entry["name"] for entry in standings} == {first, second}, \
        f"precondition: both users solved lag/lemon, got {names_on(standings)}"

    redis_cmd("DEL", cache_key, f"{cache_key}:updated")
    events = [
        json.dumps({"type": "challenge_solve",
                    "payload": {"user_id": sb_filter["uids"][name], "challenge_id": challenge_id}})
        for name in [first, second]
    ]
    redis_cli("EVAL",
              "redis.call('XADD', KEYS[1], '*', 'data', ARGV[1]); "
              "redis.call('XADD', KEYS[1], '*', 'data', ARGV[2])",
              "1", "stat:events", *events)
    wait_for_background_worker(timeout=60)

    replayed = names_on(all_standings(session, sb_filter["dojo"], "lag"))
    assert set(replayed) == {first, second}, \
        f"both queued solve events must be applied, got {replayed}"


def test_private_dojo_scoreboard_and_scores(sb_private, example_dojo, admin_session):
    member, member_session = register()
    outsider, outsider_session = register()
    uids = user_ids([member, outsider])

    join(member_session, sb_private["dojo"])
    flags = derive_flags([
        (uids[member], sb_private["cids"][("m1", "own")]),
        (uids[outsider], sb_private["cids"][("m1", "apple")]),
    ])
    wait_for_background_worker(timeout=60)
    solve_challenge(sb_private["dojo"], "m1", "own", session=member_session, flag=flags[0])
    wait_for_background_worker(timeout=60)
    solve_challenge(example_dojo, "hello", "apple", session=outsider_session, flag=flags[1])
    wait_for_background_worker(timeout=60)

    def standings():
        return all_standings(admin_session, sb_private["dojo"])

    assert entry_for(standings(), member) is not None, "a member's solve lands on the private dojo's board"
    assert entry_for(standings(), outsider) is None, \
        "a non-member's solve of an imported challenge must not reach the private dojo's board"

    recalc_dojo(sb_private["dojo_id"])
    assert entry_for(standings(), outsider) is None, \
        "the recalculated board must also exclude the non-member"
    assert entry_for(standings(), member) is not None

    report = scores_report(sb_private["dojo_id"], [uids[member]], [])
    assert report[str(uids[member])]["rank"] is None, \
        "private dojos are excluded from the profile scores ranking"
    assert report[str(uids[member])]["solves"] == 0


def test_scoreboard_404s(sb_private, sb_main):
    name, session = register()

    private_url = f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{sb_private['dojo']}/_/0/1"
    assert session.get(private_url).status_code == 404, \
        "a private dojo's scoreboard is not visible to non-members"
    join(session, sb_private["dojo"])
    assert session.get(private_url).status_code == 200, "joining makes the scoreboard accessible"

    unknown_module = session.get(
        f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{sb_main['dojo']}/no-such-module/0/1")
    assert unknown_module.status_code == 404, "an unknown module id is a 404"

    unknown_dojo = session.get(
        f"{DOJO_URL}/pwncollege_api/v1/scoreboard/sb-no-such-dojo-{rand_id()}/_/0/1")
    assert unknown_dojo.status_code == 404, "an unknown dojo id is a 404"


def test_scoreboard_badges_and_belt(sb_award):
    awarded, control = sb_award["awarded"], sb_award["control"]
    awarded_session = sb_award["sessions"][awarded]

    def awarded_entry():
        entry = entry_for(all_standings(awarded_session, sb_award["dojo"]), awarded)
        return entry if entry and asset_name(entry["belt"]) == "orange.svg" and entry["badges"] else None

    entry = wait_until(awarded_entry, timeout=30)
    assert entry is not None, "expected the awarded user to carry an orange belt and a badge"
    badge = next((badge for badge in entry["badges"] if badge["emoji"] == "🏅"), None)
    assert badge is not None, f"expected the dojo's award emoji in badges, got {entry['badges']}"
    assert badge["count"] == 1, badge
    assert badge["stale"] is False, badge

    control_entry = entry_for(all_standings(awarded_session, sb_award["dojo"]), control)
    assert asset_name(control_entry["belt"]) == "white.svg", \
        f"a beltless user gets the white belt, got {control_entry['belt']}"
    assert control_entry["badges"] == [], "a user who did not complete the dojo has no badges"


def test_dojo_show_scoreboard_false_still_served(sb_award):
    standings = board(None, sb_award["dojo"])["standings"]
    assert {sb_award["awarded"], sb_award["control"]} <= set(names_on(standings)), \
        "'show_scoreboard: false' hides the board in the UI but the API still serves standings"


def test_score_endpoint_format(example_dojo):
    name, session = register()
    uids = user_ids([name])
    challenge_id = challenge_ids(example_dojo)[("hello", "apple")]
    solve_challenge(example_dojo, "hello", "apple", session=session,
                    flag=derive_flags([(uids[name], challenge_id)])[0])

    output = sb_flask_exec(
        "from CTFd.models import Challenges\n"
        "from CTFd.plugins.dojo_plugin.models import Dojos, DojoChallenges\n"
        "query = (Challenges.query.join(DojoChallenges).join(Dojos)\n"
        "         .filter(Dojos.official, DojoChallenges.visible()).distinct()\n"
        "         .with_entities(Challenges.id))\n"
        "print('MAXSCORE', query.count())\n"
    )
    max_score = int(re.search(r"MAXSCORE (\d+)", output).group(1))

    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/score", params={"username": name})
    assert response.status_code == 200, response.text
    fields = response.json().split(":")
    assert len(fields) == 6, f"expected rank:solves:max:solves:max:users, got {response.json()}"
    rank, solves, reported_max, solves_again, max_again, user_count = [int(field) for field in fields]
    assert solves == solves_again == 1, f"the user solved exactly one official challenge, got {fields}"
    assert reported_max == max_again == max_score, f"expected max_score {max_score}, got {fields}"
    assert rank >= 1 and user_count >= 1, fields

    assert session.patch(f"{DOJO_URL}/api/v1/users/me", json={"hidden": True}).status_code == 200
    hidden = requests.get(f"{DOJO_URL}/pwncollege_api/v1/score", params={"username": name})
    assert hidden.status_code == 400, "a hidden user is not exposed by the score endpoint"
    assert "does not exist" in hidden.json()["error"], hidden.json()


def test_score_endpoint_errors(sb_main):
    missing = requests.get(f"{DOJO_URL}/pwncollege_api/v1/score")
    assert missing.status_code == 400
    assert "username" in missing.json()["error"], missing.json()

    unknown = requests.get(f"{DOJO_URL}/pwncollege_api/v1/score",
                           params={"username": f"sb-no-such-user-{rand_id()}"})
    assert unknown.status_code == 400
    assert "does not exist" in unknown.json()["error"], unknown.json()

    unranked = requests.get(f"{DOJO_URL}/pwncollege_api/v1/score",
                            params={"username": sb_main["nobody"]})
    assert unranked.status_code == 400
    assert "not ranked" in unranked.json()["error"], unranked.json()
