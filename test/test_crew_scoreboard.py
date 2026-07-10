import random
import re
import string
import time

import pytest

from utils import DOJO_URL, dojo_run, login, create_dojo_yml, start_challenge, solve_challenge, workspace_run, wait_for_background_worker, remove_workspace_container


CREW_DOJO_SPEC = """
id: crew-dojo
name: Crew Dojo
modules:
  - id: hello
    name: Hello
    challenges:
      - id: apple
        import:
          dojo: example
          module: hello
          challenge: apple
      - id: banana
        import:
          dojo: example
          module: hello
          challenge: banana
"""


@pytest.fixture(scope="module")
def crew_dojo(admin_session, example_dojo):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = CREW_DOJO_SPEC.replace("crew-dojo", f"crew-dojo-{suffix}")
    return create_dojo_yml(spec, session=admin_session)


def register_user(tag=None, name_prefix=None):
    user_id = "".join(random.choices(string.ascii_lowercase, k=12))
    name = f"{name_prefix or ''}{user_id}"
    if tag is not None:
        name = f"{name} [{tag}]"
    session = login(name, user_id, register=True, email=f"{user_id}@example.com")
    return name, user_id, session


def join_dojo(session, dojo):
    response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200


def solve(dojo, user_name, session, challenge):
    start_challenge(dojo, "hello", challenge, session=session)
    result = workspace_run(f"/challenge/{challenge}", user=user_name)
    flag = re.search(r"pwn\.college{\S+}", result.stdout).group()
    solve_challenge(dojo, "hello", challenge, session=session, flag=flag)


def browser_login(browser, name, password):
    browser.get(f"{DOJO_URL}/login")
    browser.find_element("id", "name").send_keys(name)
    browser.find_element("id", "password").send_keys(password)
    browser.find_element("id", "_submit").click()


def wait_until(predicate, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.5)
    raise AssertionError("timed out waiting for condition")


def open_crew_view(browser, dojo):
    browser.get(f"{DOJO_URL}/dojo/{dojo}")
    wait_until(lambda: browser.execute_script("return typeof setScoreboardView === 'function' && $('#scoreboard tr').length > 0"))
    browser.execute_script("setScoreboardView('crews')")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .scoreboard-loading').length === 0 && $('#scoreboard tr').length > 0"))


@pytest.mark.timeout(300)
def test_crew_scoreboard_happy_path(browser_fixture, crew_dojo):
    browser = browser_fixture
    tag = "".join(random.choices(string.ascii_uppercase, k=8))
    name_a, password_a, session_a = register_user(tag=tag)
    name_b, _, session_b = register_user(tag=tag)
    name_c, _, session_c = register_user()

    for name, session in [(name_a, session_a), (name_b, session_b), (name_c, session_c)]:
        join_dojo(session, crew_dojo)

    solve(crew_dojo, name_a, session_a, "apple")
    solve(crew_dojo, name_a, session_a, "banana")
    solve(crew_dojo, name_b, session_b, "apple")
    solve(crew_dojo, name_c, session_c, "apple")
    for name in [name_a, name_b, name_c]:
        remove_workspace_container(name)
    wait_for_background_worker(timeout=30)

    browser_login(browser, name_a, password_a)
    open_crew_view(browser, crew_dojo)

    crew_row = wait_until(lambda: next(
        (row for row in browser.find_elements("css selector", ".crew-row")
         if row.find_element("css selector", ".crew-tag-text").text == tag), None))
    assert crew_row.find_element("css selector", ".crew-member-count").text == "2 members"
    assert crew_row.find_element("css selector", ".crew-score").text == "3"
    assert "scoreboard-row-me" in crew_row.get_attribute("class")

    assert name_c not in browser.execute_script("return $('#scoreboard').text()")

    browser.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", crew_row)
    member_names = wait_until(lambda: browser.execute_script(
        "return $('#scoreboard .crew-member-row .scoreboard-name').map((i, e) => e.textContent).get()") or None)
    assert member_names == [name_a.replace(f" [{tag}]", ""), name_b.replace(f" [{tag}]", "")]

    member_titles = browser.execute_script(
        "return $('#scoreboard .crew-member-row .scoreboard-name').map((i, e) => e.getAttribute('title')).get()")
    assert member_titles == [name_a, name_b]
    assert name_c not in browser.execute_script("return $('#scoreboard').text()")

    browser.execute_script("setCrewMode('unique')")
    wait_until(lambda: browser.execute_script("return $('#scoreboard-th-score').text() === 'Unique' && $('#scoreboard .crew-row').length > 0"))
    unique_crew_row = wait_until(lambda: next(
        (row for row in browser.find_elements("css selector", ".crew-row")
         if row.find_element("css selector", ".crew-tag-text").text == tag), None))
    assert unique_crew_row.find_element("css selector", ".crew-score").text == "2"
    assert browser.execute_script("return location.hash") == "#crews-unique"
    browser.execute_script("setCrewMode('cumulative')")
    wait_until(lambda: browser.execute_script("return $('#scoreboard-th-score').text() === 'Score' && $('#scoreboard .crew-row').length > 0"))

    browser.execute_script("setScoreboardView('hackers')")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-row').length === 0 && $('#scoreboard .scoreboard-name').length > 0"))
    assert browser.execute_script("return $('#scoreboard-crew-mode-toggle').prop('hidden')")
    hacker_names = browser.execute_script("return $('#scoreboard .scoreboard-name').map((i, e) => e.getAttribute('title')).get()")
    assert name_c in hacker_names
    chip_tags = browser.execute_script("return $('#scoreboard .scoreboard-name .crew-tag-text').map((i, e) => e.textContent).get()")
    assert chip_tags.count(tag) == 2

    browser.get(f"{DOJO_URL}/login")
    browser.get(f"{DOJO_URL}/dojo/{crew_dojo}#crews-unique")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-row').length > 0"))
    assert browser.execute_script("return $('#scoreboard-th-score').text()") == "Unique"
    assert browser.execute_script("return $('#scoreboard-crew-mode-unique').hasClass('scoreboard-view-selected')")
    assert browser.execute_script("return $('#scoreboard-view-crews').hasClass('scoreboard-view-selected')")


@pytest.mark.timeout(180)
def test_crew_tag_xss_safe(browser_fixture, crew_dojo):
    browser = browser_fixture
    prefix = "<img src=x onerror=window.__xss2=1>"
    tag = "<svg onload=__x=1>"
    name, password, session = register_user(tag=tag, name_prefix=prefix)
    join_dojo(session, crew_dojo)
    solve(crew_dojo, name, session, "apple")
    remove_workspace_container(name)
    wait_for_background_worker(timeout=30)

    browser_login(browser, name, password)
    open_crew_view(browser, crew_dojo)
    wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-row').length > 0"))

    assert browser.execute_script("return window.__x") is None
    assert browser.execute_script("return window.__xss2") is None
    assert browser.execute_script("return $('#scoreboard svg, #scoreboard img:not(.scoreboard-symbol):not(.scoreboard-belt):not(.crew-face)').length") == 0
    tag_texts = browser.execute_script("return $('#scoreboard .crew-tag-text').map((i, e) => e.textContent).get()")
    assert tag in tag_texts

    xss_crew_row = next(row for row in browser.find_elements("css selector", ".crew-row")
                        if row.find_element("css selector", ".crew-tag-text").text == tag)
    browser.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", xss_crew_row)
    wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-member-row').length > 0"))
    assert browser.execute_script("return window.__x") is None
    assert browser.execute_script("return window.__xss2") is None
    member_name = browser.execute_script("return $('#scoreboard .crew-member-row .scoreboard-name').first().text()")
    assert prefix in member_name
    assert browser.execute_script("return $('#scoreboard .crew-member-row img:not(.scoreboard-symbol):not(.scoreboard-belt)').length") == 0


def flask_exec(code):
    import base64
    encoded = base64.b64encode(code.encode()).decode()
    result = dojo_run("dojo", "flask", input=f'import base64; exec(base64.b64decode("{encoded}").decode())\n')
    return result.stdout


CREW_PARSE_UNIT = r"""
from CTFd.plugins.dojo_plugin.utils.crews import parse_crew_tag, aggregate_crews

assert parse_crew_tag("Zardus [Shellphish]") == {"tag": "Shellphish", "key": "shellphish", "base_name": "Zardus"}
assert parse_crew_tag("[Shellphish]") == {"tag": "Shellphish", "key": "shellphish", "base_name": ""}
assert parse_crew_tag("[abc] Zardus") is None
assert parse_crew_tag("A [x] [y]") == {"tag": "y", "key": "y", "base_name": "A [x]"}
assert parse_crew_tag("A [[x]]") is None
assert parse_crew_tag("A []") is None
assert parse_crew_tag("A [ ]") is None
assert parse_crew_tag("A [\u200b]") is None
assert parse_crew_tag("plain") is None
assert parse_crew_tag("[") is None
assert parse_crew_tag("]") is None
assert parse_crew_tag("A [" + "x" * 25 + "]") is None
assert parse_crew_tag("A [" + "x" * 21 + "]") is None
assert parse_crew_tag("x [a\u200bb]")["key"] == parse_crew_tag("x [ab]")["key"]
assert parse_crew_tag("x [Shell  phish]")["key"] == parse_crew_tag("x [Shell phish]")["key"]
assert parse_crew_tag("x [SHELLPHISH]")["key"] == parse_crew_tag("x [shellphish]")["key"]
assert parse_crew_tag("x [Shell\u00adphish]")["key"] == parse_crew_tag("x [Shellphish]")["key"]
assert parse_crew_tag("x [\uff53\uff48\uff45\uff4c\uff4c]")["key"] == "shell"
assert parse_crew_tag("x [Shellphish\ufe0f]")["key"] == "shellphish"
assert parse_crew_tag("x [\U0001f480\U0001f525]") == {"tag": "\U0001f480\U0001f525", "key": "\U0001f480\U0001f525", "base_name": "x"}
assert parse_crew_tag("x [  padded  ]") == {"tag": "padded", "key": "padded", "base_name": "x"}

standings = [
    {"user_id": 1, "name": "a [X]", "solves": 5, "rank": 1},
    {"user_id": 2, "name": "b [X]", "solves": 4, "rank": 2},
    {"user_id": 3, "name": "c [Y]", "solves": 3, "rank": 3},
    {"user_id": 4, "name": "d [__proto__]", "solves": 2, "rank": 4},
    {"user_id": 5, "name": "e", "solves": 1, "rank": 5},
]
crews = aggregate_crews(standings)
assert [(c["tag"], c["score"], len(c["members"]), c["rank"]) for c in crews] == [("X", 9, 2, 1), ("Y", 3, 1, 2), ("__proto__", 2, 1, 3)]
assert all(c["unique"] is None and c["unique_rank"] is None for c in crews)

challenge_map = {1: {10, 11, 12, 13, 14}, 2: {10, 11, 12, 13}, 3: {10, 11, 12}, 4: {20, 21}}
crews = aggregate_crews(standings, challenge_map)
x = next(c for c in crews if c["key"] == "x")
y = next(c for c in crews if c["key"] == "y")
proto = next(c for c in crews if c["key"] == "__proto__")
assert (x["score"], x["unique"], x["rank"]) == (9, 5, 1)
assert (y["score"], y["unique"], y["rank"]) == (3, 3, 2)
assert x["unique_rank"] == 1 and y["unique_rank"] == 2 and proto["unique_rank"] == 3
assert x["members"][0]["challenges"] == [10, 11, 12, 13, 14]

overlap = aggregate_crews([
    {"user_id": 1, "name": "a [Dup]", "solves": 3, "rank": 1},
    {"user_id": 2, "name": "b [Dup]", "solves": 3, "rank": 2},
    {"user_id": 3, "name": "c [Wide]", "solves": 4, "rank": 3},
], {1: {1, 2, 3}, 2: {1, 2, 3}, 3: {1, 2, 3, 4}})
dup = next(c for c in overlap if c["key"] == "dup")
wide = next(c for c in overlap if c["key"] == "wide")
assert (dup["score"], dup["unique"], dup["rank"]) == (6, 3, 1)
assert (wide["score"], wide["unique"], wide["rank"]) == (4, 4, 2)
assert wide["unique_rank"] == 1 and dup["unique_rank"] == 2

tie = aggregate_crews([
    {"user_id": 1, "name": "a [Big]", "solves": 3, "rank": 1},
    {"user_id": 2, "name": "b [Big]", "solves": 3, "rank": 2},
    {"user_id": 3, "name": "c [Small]", "solves": 6, "rank": 3},
])
assert [c["tag"] for c in tie] == ["Small", "Big"]
assert aggregate_crews([]) == []

print("CREW-UNIT-OK")
"""


def test_crew_parse_and_aggregation_unit():
    assert "CREW-UNIT-OK" in flask_exec(CREW_PARSE_UNIT)


@pytest.mark.timeout(300)
def test_crew_scoreboard_api(crew_dojo):
    tag = "".join(random.choices(string.ascii_uppercase, k=8))
    name_a, _, session_a = register_user(tag=tag)
    name_b, _, session_b = register_user(tag=tag.lower())
    name_c, _, session_c = register_user()

    for name, session in [(name_a, session_a), (name_b, session_b), (name_c, session_c)]:
        join_dojo(session, crew_dojo)

    solve(crew_dojo, name_a, session_a, "apple")
    solve(crew_dojo, name_b, session_b, "banana")
    solve(crew_dojo, name_c, session_c, "apple")
    for name in [name_a, name_b, name_c]:
        remove_workspace_container(name)
    wait_for_background_worker(timeout=30)

    result = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/crews/0/1")
    assert result.status_code == 404

    result = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/_/crews/0/1")
    assert result.status_code == 200
    board = result.json()
    assert board["mode"] == "cumulative"

    crew = next(c for c in board["standings"] if c["key"] == tag.lower())
    assert crew["score"] == 2
    assert crew["unique"] == 2
    assert len(crew["members"]) == 2
    member_names = [member["name"] for member in crew["members"]]
    assert name_a in member_names and name_b in member_names
    for member in crew["members"]:
        assert "email" not in member
        assert "challenges" not in member
        assert member["crew"]["key"] == tag.lower()
    assert all(name_c != member["name"] for c in board["standings"] for member in c["members"])

    assert "me_crew" in board
    assert board["me_crew"]["key"] == tag.lower()

    unique_board = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/_/crews/0/1?mode=unique").json()
    assert unique_board["mode"] == "unique"
    unique_crew = next(c for c in unique_board["standings"] if c["key"] == tag.lower())
    assert unique_crew["unique"] == 2
    unique_ranks = [c["rank"] for c in unique_board["standings"]]
    assert unique_ranks == sorted(unique_ranks)

    solve(crew_dojo, name_b, session_b, "apple")
    remove_workspace_container(name_b)
    wait_for_background_worker(timeout=30)
    overlap_board = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/_/crews/0/1").json()
    overlap_crew = next(c for c in overlap_board["standings"] if c["key"] == tag.lower())
    assert overlap_crew["score"] == 3
    assert overlap_crew["unique"] == 2

    module_board = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/hello/crews/0/1").json()
    module_crew = next(c for c in module_board["standings"] if c["key"] == tag.lower())
    assert module_crew["score"] == 3
    assert module_crew["unique"] == 2

    solo_tag = "".join(random.choices(string.ascii_uppercase, k=8))
    name_s, _, session_s = register_user(tag=solo_tag)
    join_dojo(session_s, crew_dojo)
    solve(crew_dojo, name_s, session_s, "apple")
    solve(crew_dojo, name_s, session_s, "banana")
    remove_workspace_container(name_s)
    wait_for_background_worker(timeout=30)

    def crew_order(mode):
        board = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/_/crews/0/1?mode={mode}").json()
        assert [c["rank"] for c in board["standings"]] == list(range(1, len(board["standings"]) + 1))
        return [c["key"] for c in board["standings"]]

    cumulative_order = crew_order("cumulative")
    unique_order = crew_order("unique")
    assert cumulative_order.index(tag.lower()) < cumulative_order.index(solo_tag.lower())
    assert unique_order.index(solo_tag.lower()) < unique_order.index(tag.lower())

    flask_exec(f"""
from CTFd.plugins.dojo_plugin.models import Dojos
from CTFd.plugins.dojo_plugin.worker.handlers.scoreboard import handle_scoreboard_update
dojo = Dojos.from_id({crew_dojo!r}).first()
handle_scoreboard_update({{"model_type": "dojo", "model_id": dojo.dojo_id}})
print("RECALC-DONE", dojo.dojo_id)
""")
    recalc_board = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/_/crews/0/1").json()
    recalc_crew = next(c for c in recalc_board["standings"] if c["key"] == tag.lower())
    assert recalc_crew["score"] == 3
    assert recalc_crew["unique"] == 2
    recalc_solo = next(c for c in recalc_board["standings"] if c["key"] == solo_tag.lower())
    assert recalc_solo["score"] == 2
    assert recalc_solo["unique"] == 2

    dojo_id = flask_exec(f"""
from CTFd.plugins.dojo_plugin.models import Dojos
print("DOJO-ID", Dojos.from_id({crew_dojo!r}).first().dojo_id)
""")
    dojo_id = re.search(r"DOJO-ID (-?\d+)", dojo_id).group(1)
    dojo_run("docker", "exec", "cache", "redis-cli", "DEL", f"stats:crews:dojo:{dojo_id}:0")
    fallback_board = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/_/crews/0/1").json()
    fallback_crew = next(c for c in fallback_board["standings"] if c["key"] == tag.lower())
    assert fallback_crew["score"] == 3
    assert fallback_crew["unique"] is None
    dojo_run("docker", "exec", "cache", "redis-cli", "DEL", f"stats:crews:dojo:{dojo_id}:0")
    fallback_unique = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/_/crews/0/1?mode=unique")
    assert fallback_unique.status_code == 200
    assert fallback_unique.json()["mode"] == "unique"

    hacker_board = session_a.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{crew_dojo}/_/0/1").json()
    tagged = next(entry for entry in hacker_board["standings"] if entry["name"] == name_a)
    assert tagged["crew"]["tag"] == tag
    assert tagged["crew"]["key"] == tag.lower()
    untagged = next(entry for entry in hacker_board["standings"] if entry["name"] == name_c)
    assert untagged["crew"] is None



def test_crew_view_toggle_race(browser_fixture, example_dojo):
    browser = browser_fixture
    browser.get(f"{DOJO_URL}/dojo/{example_dojo}")
    wait_until(lambda: browser.execute_script("return typeof setScoreboardView === 'function' && $('#scoreboard tr').length > 0"))

    browser.execute_script("loadScoreboard(7, 1); loadScoreboard(0, 1);")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .scoreboard-loading').length === 0 && $('#scoreboard tr').length > 0"))
    time.sleep(1)
    assert browser.execute_script("return $('#scoreboard-heading').text()") == "All-Time Scoreboard:"
    assert browser.execute_script("return $('#scoreboard-control-all').hasClass('scoreboard-page-selected')")

    browser.execute_script("setScoreboardView('crews'); setScoreboardView('hackers');")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .scoreboard-loading').length === 0 && $('#scoreboard tr').length > 0"))
    time.sleep(1)
    assert browser.execute_script("return $('#scoreboard .crew-row').length") == 0
    assert browser.execute_script("return $('#scoreboard-heading').text()") == "All-Time Scoreboard:"
    assert browser.execute_script("return $('#scoreboard-th-name').text()") == "Hacker"

    browser.execute_script("setScoreboardView('crews')")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .scoreboard-loading').length === 0 && $('#scoreboard tr').length > 0"))
    rows = browser.execute_script("return $('#scoreboard .crew-row').length")
    browser.execute_script("setScoreboardView('hackers'); setScoreboardView('crews');")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .scoreboard-loading').length === 0 && $('#scoreboard tr').length > 0"))
    time.sleep(1)
    assert browser.execute_script("return $('#scoreboard .crew-row').length") == rows
    assert browser.execute_script("return $('#scoreboard-heading').text()") == "All-Time Crew Scoreboard:"


@pytest.mark.timeout(180)
def test_crew_empty_states(browser_fixture, admin_session, example_dojo):
    browser = browser_fixture
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = CREW_DOJO_SPEC.replace("crew-dojo", f"crew-empty-{suffix}")
    dojo = create_dojo_yml(spec, session=admin_session)

    name, password, session = register_user()
    join_dojo(session, dojo)

    browser_login(browser, name, password)
    open_crew_view(browser, dojo)
    note = wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-note').text()") or None)
    assert note == "No solves yet — no crews to show."

    solve(dojo, name, session, "apple")
    remove_workspace_container(name)
    wait_for_background_worker(timeout=30)

    open_crew_view(browser, dojo)
    title = wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-empty-title').text()") or None)
    assert title == "No crews yet."
    assert "add a tag in brackets" in browser.execute_script("return $('#scoreboard .crew-empty-hint').text()")
