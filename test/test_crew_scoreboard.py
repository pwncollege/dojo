import random
import re
import string
import time

import pytest

from utils import DOJO_URL, login, create_dojo_yml, start_challenge, solve_challenge, workspace_run, wait_for_background_worker


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
    wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-loading').length === 0"))


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

    browser.execute_script("setScoreboardView('hackers')")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-row').length === 0 && $('#scoreboard .scoreboard-name').length > 0"))
    hacker_names = browser.execute_script("return $('#scoreboard .scoreboard-name').map((i, e) => e.getAttribute('title')).get()")
    assert name_c in hacker_names
    chip_tags = browser.execute_script("return $('#scoreboard .scoreboard-name .crew-tag-text').map((i, e) => e.textContent).get()")
    assert chip_tags.count(tag) == 2


@pytest.mark.timeout(180)
def test_crew_tag_xss_safe(browser_fixture, crew_dojo):
    browser = browser_fixture
    prefix = "<img src=x onerror=window.__xss2=1>"
    tag = "<svg onload=__x=1>"
    name, password, session = register_user(tag=tag, name_prefix=prefix)
    join_dojo(session, crew_dojo)
    solve(crew_dojo, name, session, "apple")
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


def test_crew_parse_tag(browser_fixture, example_dojo):
    browser = browser_fixture
    browser.get(f"{DOJO_URL}/dojo/{example_dojo}")
    wait_until(lambda: browser.execute_script("return typeof window.parseCrewTag === 'function'"))

    def parse(name):
        return browser.execute_script("return window.parseCrewTag(arguments[0])", name)

    assert parse("Zardus [Shellphish]") == {"tag": "Shellphish", "key": "shellphish", "baseName": "Zardus"}
    assert parse("[Shellphish]") == {"tag": "Shellphish", "key": "shellphish", "baseName": ""}
    assert parse("[abc] Zardus") is None
    assert parse("A [x] [y]") == {"tag": "y", "key": "y", "baseName": "A [x]"}
    assert parse("A [[x]]") is None
    assert parse("A []") is None
    assert parse("A [ ]") is None
    assert parse("A [\u200b]") is None
    assert parse("plain") is None
    assert parse("[") is None
    assert parse("]") is None
    assert parse("A [" + "x" * 25 + "]") is None
    assert parse("A [" + "x" * 21 + "]") is None
    assert parse("x [a\u200bb]")["key"] == parse("x [ab]")["key"]
    assert parse("x [Shell  phish]")["key"] == parse("x [Shell phish]")["key"]
    assert parse("x [SHELLPHISH]")["key"] == parse("x [shellphish]")["key"]
    assert parse("x [Shell\u00adphish]")["key"] == parse("x [Shellphish]")["key"]
    assert parse("x [ｓｈｅｌｌｐｈｉｓｈ]")["key"] == "shellphish"
    assert parse("x [Shellphish\ufe0f]")["key"] == "shellphish"
    assert parse("x [💀🔥]") == {"tag": "💀🔥", "key": "💀🔥", "baseName": "x"}
    assert parse("x [  padded  ]") == {"tag": "padded", "key": "padded", "baseName": "x"}


def test_crew_aggregation_logic(browser_fixture, example_dojo):
    browser = browser_fixture
    browser.get(f"{DOJO_URL}/dojo/{example_dojo}")
    wait_until(lambda: browser.execute_script("return typeof window.parseCrewTag === 'function'"))

    result = browser.execute_script("""
        const pages = new Map();
        pages.set(1, [
            {user_id: 1, name: "a [X]", solves: 5, rank: 1},
            {user_id: 2, name: "b [X]", solves: 4, rank: 2},
        ]);
        pages.set(2, [
            {user_id: 2, name: "b [X]", solves: 4, rank: 2},
            {user_id: 3, name: "c [Y]", solves: 3, rank: 3},
            {user_id: 4, name: "d [__proto__]", solves: 2, rank: 4},
            {user_id: 5, name: "e", solves: 1, rank: 5},
        ]);
        const standings = dedupStandings({pagesByNumber: pages});
        const crews = aggregateCrews(standings);
        return {
            standings: standings.length,
            crews: crews.map(crew => ({tag: crew.tag, score: crew.score, members: crew.members.length, rank: crew.rank})),
        };
    """)
    assert result["standings"] == 5
    assert result["crews"] == [
        {"tag": "X", "score": 9, "members": 2, "rank": 1},
        {"tag": "Y", "score": 3, "members": 1, "rank": 2},
        {"tag": "__proto__", "score": 2, "members": 1, "rank": 3},
    ]

    tiebreaks = browser.execute_script("""
        const standings = [
            {user_id: 1, name: "a [Big]", solves: 3, rank: 1},
            {user_id: 2, name: "b [Big]", solves: 3, rank: 2},
            {user_id: 3, name: "c [Small]", solves: 6, rank: 3},
        ];
        return aggregateCrews(standings).map(crew => crew.tag);
    """)
    assert tiebreaks == ["Small", "Big"]


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
    wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-loading').length === 0 && $('#scoreboard tr').length > 0"))
    rows = browser.execute_script("return $('#scoreboard .crew-row').length")
    browser.execute_script("setScoreboardView('hackers'); setScoreboardView('crews');")
    wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-loading').length === 0 && $('#scoreboard tr').length > 0"))
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
    wait_for_background_worker(timeout=30)

    open_crew_view(browser, dojo)
    title = wait_until(lambda: browser.execute_script("return $('#scoreboard .crew-empty-title').text()") or None)
    assert title == "No crews yet."
    assert "add a tag in brackets" in browser.execute_script("return $('#scoreboard .crew-empty-hint').text()")
