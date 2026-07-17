import json
import random
import re
import string
import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

import requests

from utils import (
    DOJO_URL,
    create_dojo_yml,
    dojo_run,
    login,
    remove_workspace_container,
    solve_challenge,
    start_challenge,
    wait_for_background_worker,
    workspace_run,
)


def redis_cli(*args):
    result = dojo_run("docker", "exec", "cache", "redis-cli", *args)
    return result.stdout.rstrip("\n")


def snapshot_redis_keys(keys):
    return {
        key: (redis_cli("EXISTS", key) == "1", redis_cli("GET", key))
        for key in keys
    }


@contextmanager
def without_redis_keys(keys):
    keys = list(dict.fromkeys(keys))
    snapshot = snapshot_redis_keys(keys)
    if keys:
        redis_cli("DEL", *keys)
    try:
        yield
    finally:
        for key, (exists, value) in snapshot.items():
            if exists:
                redis_cli("SET", key, value)
            else:
                redis_cli("DEL", key)


def profile_solve_ids(user_id, dojo_reference_id, module_id):
    result = dojo_run(
        "dojo",
        "flask",
        input=(
            "import json\n"
            "from CTFd.models import Users\n"
            "from CTFd.plugins.dojo_plugin.models import Dojos\n"
            "from CTFd.plugins.dojo_plugin.pages.users import build_user_solves\n"
            f"user = Users.query.get({user_id})\n"
            f"dojo = Dojos.from_id({dojo_reference_id!r}).first()\n"
            "solves = build_user_solves(user, [dojo])\n"
            f"solve_ids = sorted(solves.get(dojo.dojo_id, {{}}).get({module_id!r}, {{}}))\n"
            "print('PROFILE_SOLVE_IDS=' + json.dumps(solve_ids))\n"
        ),
    )
    solve_ids_match = re.search(r"PROFILE_SOLVE_IDS=(\[.*\])", result.stdout)
    assert solve_ids_match, result.stdout
    return json.loads(solve_ids_match.group(1))


def scoreboard_standings(session, dojo_reference_id, module_id="_"):
    response = session.get(
        f"{DOJO_URL}/pwncollege_api/v1/scoreboard/"
        f"{dojo_reference_id}/{module_id}/0/1"
    )
    assert response.status_code == 200
    return response.json()["standings"]


def feed_user_ids(session):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/feed/events?limit=100")
    assert response.status_code == 200
    return {event["user_id"] for event in response.json()["data"]}


class ProfileElementParser(HTMLParser):
    def __init__(
        self,
        *,
        element_id=None,
        href_suffix=None,
        tag_name=None,
        required_classes=(),
    ):
        super().__init__(convert_charrefs=True)
        self.element_id = element_id
        self.href_suffix = href_suffix
        self.tag_name = tag_name
        self.required_classes = set(required_classes)
        self.root_tag = None
        self.root_depth = 0
        self.completed = False
        self.text = []
        self.classes = []

    def matches(self, tag, attributes):
        if self.tag_name is not None and tag != self.tag_name:
            return False
        if not self.required_classes.issubset(
            attributes.get("class", "").split()
        ):
            return False
        if self.element_id is not None:
            return attributes.get("id") == self.element_id
        href = attributes.get("href")
        return href is not None and href.rstrip("/").endswith(
            self.href_suffix.rstrip("/")
        )

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self.root_depth == 0:
            if self.completed or not self.matches(tag, attributes):
                return
            self.root_tag = tag
            self.root_depth = 1
        elif tag == self.root_tag:
            self.root_depth += 1
        self.classes.extend(attributes.get("class", "").split())

    def handle_startendtag(self, _tag, attrs):
        if self.root_depth:
            self.classes.extend(dict(attrs).get("class", "").split())

    def handle_endtag(self, tag):
        if self.root_depth and tag == self.root_tag:
            self.root_depth -= 1
            if self.root_depth == 0:
                self.completed = True

    def handle_data(self, data):
        if self.root_depth:
            self.text.append(data)


def profile_element(profile_html, **selector):
    parser = ProfileElementParser(**selector)
    parser.feed(profile_html)
    parser.close()
    assert parser.completed, selector
    return " ".join(" ".join(parser.text).split()), parser.classes


def challenge_display_matches(challenge_id, text):
    tokens = re.findall(r"[^\W_]+", challenge_id)
    if not tokens:
        return False
    pattern = r"(?<!\w)" + r"[\W_]+".join(
        re.escape(token) for token in tokens
    ) + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def assert_profile_progress(
    profile_html,
    dojo_reference_id,
    dojo_hex_id,
    module_position,
    *,
    solve_count,
    challenge_count,
    rank,
    rank_count,
    solved_challenges,
):
    dojo_text, _ = profile_element(
        profile_html,
        href_suffix=f"/{dojo_reference_id}",
        tag_name="a",
        required_classes=("text-decoration-none",),
    )
    module_header_text, _ = profile_element(
        profile_html,
        element_id=f"modules-{dojo_hex_id}-header-button-{module_position}",
    )
    module_body_text, module_body_classes = profile_element(
        profile_html,
        element_id=f"modules-{dojo_hex_id}-body-{module_position}",
    )

    expected_summary = (
        f"{solve_count} / {challenge_count} {rank} / {rank_count}"
    )
    assert dojo_text.endswith(expected_summary), dojo_text
    assert module_header_text.endswith(expected_summary), module_header_text
    assert module_body_classes.count("challenge-solved") == solve_count
    assert (
        module_body_text.count("Time of First Successful Submission")
        == solve_count
    )
    for challenge in solved_challenges:
        assert challenge_display_matches(challenge, module_body_text)


def test_target_progress_parser():
    profile_html = """
    <a href="/unrelated~00000001/"><h4>74 / 74</h4></a>
    <div id="modules-00000001-body-1">
      <i class="challenge-solved"></i>
    </div>
    <h2><span title="Test badge"><a href="/dojo/simple-award~deadbeef/">🧪</a></span></h2>
    <a class="text-decoration-none" href="/dojo/simple-award~deadbeef/">
      <h4>2 / 2 1 / 1</h4>
    </a>
    <button id="modules-deadbeef-header-button-1"><span>2 / 2 1 / 1</span></button>
    <div id="modules-deadbeef-body-1">
      <div><i class="challenge-solved"></i>Shared Apple</div>
      <h6>Time of First Successful Submission: first</h6>
      <div><i class="challenge-solved"></i>Optional Banana</div>
      <h6>Time of First Successful Submission: second</h6>
    </div>
    """
    assert_profile_progress(
        profile_html,
        "simple-award~deadbeef",
        "deadbeef",
        1,
        solve_count=2,
        challenge_count=2,
        rank=1,
        rank_count=1,
        solved_challenges=("shared-apple", "optional-banana"),
    )
    assert challenge_display_matches("shared-apple", "Shared Apple")
    assert challenge_display_matches("optional_banana", "Optional Banana")
    assert not challenge_display_matches("apple", "Pineapple")
    assert not challenge_display_matches("shared-apple", "Shared Pineapple")


def test_hidden_user_self_access(
    admin_session,
    random_user,
    simple_award_dojo,
    belt_dojos,
):
    user_name, user_session = random_user
    user_response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert user_response.status_code == 200
    user_id = user_response.json()["id"]

    assert user_session.get(f"{DOJO_URL}/dojo/{simple_award_dojo}/join/").status_code == 200
    for challenge in ("apple", "banana"):
        start_challenge(simple_award_dojo, "hello", challenge, session=user_session)
        solve_challenge(
            simple_award_dojo,
            "hello",
            challenge,
            session=user_session,
            user=user_name,
        )
    start_challenge(
        belt_dojos["orange"],
        "test",
        "test",
        session=user_session,
    )
    solve_challenge(
        belt_dojos["orange"],
        "test",
        "test",
        session=user_session,
        user=user_name,
    )

    race_dojo_id = "hidden-race-" + "".join(
        random.choices(string.ascii_lowercase, k=12)
    )
    race_dojo = create_dojo_yml(
        f"""
id: {race_dojo_id}
type: public
modules:
  - id: race
    challenges:
      - id: alpha
      - id: beta
      - id: gamma
files:
  - type: text
    path: race/alpha/src
    content: |
      #!/opt/pwn.college/bash
      cat /flag
  - type: text
    path: race/beta/src
    content: |
      #!/opt/pwn.college/bash
      cat /flag
  - type: text
    path: race/gamma/src
    content: |
      #!/opt/pwn.college/bash
      cat /flag
""",
        session=admin_session,
    )
    start_challenge(race_dojo, "race", "alpha", session=user_session)
    solve_challenge(
        race_dojo,
        "race",
        "alpha",
        session=user_session,
        user=user_name,
    )
    remove_workspace_container(user_name)

    source_name = "".join(random.choices(string.ascii_lowercase, k=16))
    source_session = login(source_name, source_name, register=True)
    source_response = source_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert source_response.status_code == 200
    source_id = source_response.json()["id"]
    assert (
        source_session.get(f"{DOJO_URL}/dojo/{simple_award_dojo}/join/").status_code
        == 200
    )
    start_challenge(simple_award_dojo, "hello", "apple", session=source_session)
    solve_challenge(
        simple_award_dojo,
        "hello",
        "apple",
        session=source_session,
        user=source_name,
    )
    remove_workspace_container(source_name)

    wait_for_background_worker(timeout=30)
    other_name = "".join(random.choices(string.ascii_lowercase, k=16))
    other_session = login(other_name, other_name, register=True)
    private_dojo_id = "hidden-private-" + "".join(
        random.choices(string.ascii_lowercase, k=12)
    )
    viewer_private_dojo = create_dojo_yml(
        f"""
id: {private_dojo_id}
type: topic
modules:
  - id: shared
    challenges:
      - id: shared-apple
        required: false
        import:
          dojo: {simple_award_dojo}
          module: hello
          challenge: apple
      - id: duplicate-apple
        required: false
        import:
          dojo: {simple_award_dojo}
          module: hello
          challenge: apple
      - id: optional-banana
        required: false
        import:
          dojo: {simple_award_dojo}
          module: hello
          challenge: banana
""",
        session=admin_session,
    )
    assert (
        other_session.get(f"{DOJO_URL}/dojo/{viewer_private_dojo}/join/").status_code
        == 200
    )
    assert profile_solve_ids(user_id, viewer_private_dojo, "shared") == []
    assert (
        user_session.get(f"{DOJO_URL}/dojo/{viewer_private_dojo}/join/").status_code
        == 200
    )
    assert profile_solve_ids(user_id, viewer_private_dojo, "shared") == [
        "duplicate-apple",
        "optional-banana",
        "shared-apple",
    ]
    profile_collision_dojo = create_dojo_yml(
        """
id: simple-award
name: Profile Key Collision
type: public
modules:
  - id: collision
    challenges:
      - id: untouched
files:
  - type: text
    path: collision/untouched/src
    content: |
      #!/opt/pwn.college/bash
      cat /flag
""",
        session=admin_session,
    )
    wait_for_background_worker(timeout=30)

    score_query_audit = dojo_run(
        "dojo",
        "flask",
        input=(
            "import json\n"
            "from unittest.mock import patch\n"
            "from sqlalchemy.orm import Query\n"
            "from CTFd.models import Users\n"
            "from CTFd.plugins.dojo_plugin.models import Dojos\n"
            "from CTFd.plugins.dojo_plugin.pages.users import build_user_scores, build_user_solves\n"
            "from CTFd.plugins.dojo_plugin.utils.scores import calculate_profile_scores\n"
            f"user = Users.query.get({user_id})\n"
            f"dojo = Dojos.from_id({simple_award_dojo!r}).first()\n"
            f"private_dojo = Dojos.from_id({viewer_private_dojo!r}).first()\n"
            f"race_dojo = Dojos.from_id({race_dojo!r}).first()\n"
            f"collision_dojo = Dojos.from_id({profile_collision_dojo!r}).first()\n"
            "row_counts = []\n"
            "query_all = Query.all\n"
            "def counted_all(query):\n"
            "    rows = query_all(query)\n"
            "    row_counts.append(len(rows))\n"
            "    return rows\n"
            "with patch.object(Query, 'all', counted_all):\n"
            "    dojo_scores, module_scores = calculate_profile_scores(user.id, {dojo.dojo_id, private_dojo.dojo_id})\n"
            f"assert dojo_scores[dojo.dojo_id] == {{'rank': 1, 'population': 2, 'solves': 2}}, dojo_scores\n"
            "assert dojo_scores[private_dojo.dojo_id] == {'rank': 1, 'population': 1, 'solves': 3}, dojo_scores\n"
            "assert module_scores[(private_dojo.dojo_id, private_dojo.modules[0].module_index)] == {'rank': 1, 'population': 1, 'solves': 3}, module_scores\n"
            "assert row_counts == [2, 2], row_counts\n"
            "profile_dojo_scores, profile_module_scores = build_user_scores(user, [dojo, collision_dojo])\n"
            "assert set(profile_dojo_scores['dojo_populations']) == {dojo.dojo_id, collision_dojo.dojo_id}, profile_dojo_scores\n"
            "assert profile_dojo_scores['dojo_populations'][dojo.dojo_id] == 2, profile_dojo_scores\n"
            "assert profile_dojo_scores['dojo_populations'][collision_dojo.dojo_id] == 0, profile_dojo_scores\n"
            "assert profile_dojo_scores['user_ranks'][user.id] == {dojo.dojo_id: 1}, profile_dojo_scores\n"
            "assert set(profile_module_scores['module_populations']) == {dojo.dojo_id, collision_dojo.dojo_id}, profile_module_scores\n"
            "profile_solves = build_user_solves(user, [dojo, collision_dojo])\n"
            "assert set(profile_solves) == {dojo.dojo_id, collision_dojo.dojo_id}, profile_solves\n"
            "assert set(profile_solves[dojo.dojo_id]['hello']) == {'apple', 'banana'}, profile_solves\n"
            "assert profile_solves[collision_dojo.dojo_id] == {}, profile_solves\n"
            "def dojo_cache_ids(item):\n"
            "    return {'dojo_id': item.dojo_id, 'hex_dojo_id': item.hex_dojo_id, 'module_indices': [module.module_index for module in item.modules], 'module_positions': {module.id: position for position, module in enumerate(item.modules, 1)}}\n"
            "cache_ids = dojo_cache_ids(dojo)\n"
            "cache_ids['private'] = dojo_cache_ids(private_dojo)\n"
            "cache_ids['race'] = dojo_cache_ids(race_dojo)\n"
            "cache_ids['profile_query_rows'] = row_counts\n"
            "print('HIDDEN_CACHE_IDS=' + json.dumps(cache_ids))\n"
        ),
    )
    cache_ids_match = re.search(
        r"HIDDEN_CACHE_IDS=(\{.*\})", score_query_audit.stdout
    )
    assert cache_ids_match, score_query_audit.stdout
    dojo_cache_ids = json.loads(cache_ids_match.group(1))
    assert dojo_cache_ids["profile_query_rows"] == [2, 2]
    dojo_id = dojo_cache_ids["dojo_id"]
    dojo_hex_id = dojo_cache_ids["hex_dojo_id"]
    hello_module_position = dojo_cache_ids["module_positions"]["hello"]
    public_module_score_keys = [
        f"stats:scores:module:{dojo_id}:{module_index}"
        for module_index in dojo_cache_ids["module_indices"]
    ]
    public_score_keys = [f"stats:scores:dojo:{dojo_id}", *public_module_score_keys]
    expected_scores = {
        "ranks": [user_id, source_id],
        "solves": {str(user_id): 2, str(source_id): 1},
    }
    for score_key in public_score_keys:
        assert json.loads(redis_cli("GET", score_key)) == expected_scores

    private_cache_ids = dojo_cache_ids["private"]
    private_numeric_dojo_id = private_cache_ids["dojo_id"]
    private_dojo_hex_id = private_cache_ids["hex_dojo_id"]
    private_module_position = private_cache_ids["module_positions"]["shared"]
    private_module_score_keys = [
        f"stats:scores:module:{private_numeric_dojo_id}:{module_index}"
        for module_index in private_cache_ids["module_indices"]
    ]
    private_score_keys = [
        f"stats:scores:dojo:{private_numeric_dojo_id}",
        *private_module_score_keys,
    ]
    score_keys = [*public_score_keys, *private_score_keys]
    race_cache_ids = dojo_cache_ids["race"]
    race_numeric_dojo_id = race_cache_ids["dojo_id"]
    race_dojo_hex_id = race_cache_ids["hex_dojo_id"]
    race_module_index = race_cache_ids["module_indices"][0]
    race_module_position = race_cache_ids["module_positions"]["race"]
    race_scoreboard_key = f"stats:scoreboard:dojo:{race_numeric_dojo_id}:0"
    race_stats_key = f"stats:dojo:{race_dojo}"
    race_challenge_solves_key = (
        f"stats:challenge_solves:module:{race_numeric_dojo_id}:{race_module_index}"
    )

    visible_profile = user_session.get(f"{DOJO_URL}/hacker/")
    assert visible_profile.status_code == 200
    assert f'href="/dojo/{profile_collision_dojo}"' not in visible_profile.text
    assert_profile_progress(
        visible_profile.text,
        simple_award_dojo,
        dojo_hex_id,
        hello_module_position,
        solve_count=2,
        challenge_count=2,
        rank=1,
        rank_count=2,
        solved_challenges=("apple", "banana"),
    )
    assert_profile_progress(
        visible_profile.text,
        viewer_private_dojo,
        private_dojo_hex_id,
        private_module_position,
        solve_count=3,
        challenge_count=3,
        rank=1,
        rank_count=1,
        solved_challenges=("shared-apple", "duplicate-apple", "optional-banana"),
    )
    assert "🧪" in visible_profile.text
    assert "/belt/orange.svg" in visible_profile.text

    anonymous_session = requests.Session()

    outage_check = dojo_run(
        "dojo",
        "flask",
        input=(
            "import json\n"
            "from unittest.mock import patch\n"
            "from CTFd.models import Users, db\n"
            "from CTFd.plugins.dojo_plugin.models import PublicStatsCacheVersions, UserVisibilityUpdates, UserVisibilityVersions\n"
            "from CTFd.plugins.dojo_plugin.utils.background_stats import get_cached_stat, get_public_cached_stat\n"
            "from CTFd.plugins.dojo_plugin.utils.events import publish_pending_user_visibility_events\n"
            "from CTFd.plugins.dojo_plugin.utils.feed import get_recent_events, get_redis_client, is_public_feed_event\n"
            "from CTFd.plugins.dojo_plugin.utils.public_stats import affected_public_cache_keys\n"
            f"user = Users.query.get({source_id})\n"
            "assert not is_public_feed_event([])\n"
            "assert not is_public_feed_event({'user_id': 'invalid', 'visibility_revision': 0})\n"
            "assert not is_public_feed_event({'user_id': user.id})\n"
            f"cache_key = 'stats:scores:dojo:{dojo_id}'\n"
            "raw_cache = get_cached_stat(cache_key)\n"
            f"assert {source_id} in [int(user_id) for user_id in raw_cache['ranks']], raw_cache\n"
            f"assert {source_id} in [event['user_id'] for event in get_recent_events(limit=100)]\n"
            "user.hidden = True\n"
            "db.session.commit()\n"
            "with patch('CTFd.plugins.dojo_plugin.utils.background_stats.invalidate_public_cached_stats', return_value=False), patch('CTFd.plugins.dojo_plugin.utils.feed.remove_user_events', return_value=False), patch('CTFd.plugins.dojo_plugin.utils.events.publish_user_visibility_event', return_value=None):\n"
            "    publish_pending_user_visibility_events()\n"
            "assert UserVisibilityUpdates.query.filter_by(user_id=user.id).count() == 1\n"
            "assert get_cached_stat(cache_key) == raw_cache\n"
            "assert get_public_cached_stat(cache_key) is None\n"
            "user.hidden = False\n"
            "db.session.commit()\n"
            "affected_keys = affected_public_cache_keys(db.session.connection(), user.id)\n"
            "versions = PublicStatsCacheVersions.query.filter(PublicStatsCacheVersions.cache_key.in_(affected_keys)).all()\n"
            "assert len(versions) == len(affected_keys)\n"
            "assert all(version.revision != version.ready_revision for version in versions)\n"
            "with patch('CTFd.plugins.dojo_plugin.utils.feed.remove_user_events', return_value=False):\n"
            "    publish_pending_user_visibility_events()\n"
            "    assert UserVisibilityUpdates.query.filter_by(user_id=user.id).count() == 1\n"
            "    assert get_public_cached_stat(cache_key) is None\n"
            f"    assert {source_id} not in [event['user_id'] for event in get_recent_events(limit=100)]\n"
            "    raw_events = get_redis_client().zrange('activity_feed:events', 0, -1)\n"
            f"    assert {source_id} in [json.loads(event)['user_id'] for event in raw_events]\n"
            "    stale_event = next(json.loads(event) for event in raw_events if json.loads(event)['user_id'] == user.id)\n"
            "    visibility_revision = UserVisibilityVersions.query.filter_by(user_id=user.id).one().revision\n"
            "    assert stale_event['visibility_revision'] != visibility_revision\n"
            "    assert not is_public_feed_event(stale_event)\n"
            "publish_pending_user_visibility_events()\n"
            f"assert {source_id} not in [json.loads(event)['user_id'] for event in get_redis_client().zrange('activity_feed:events', 0, -1)]\n"
            "print('VISIBILITY_OUTAGE_FAIL_CLOSED')\n"
        ),
    )
    assert "VISIBILITY_OUTAGE_FAIL_CLOSED" in outage_check.stdout
    wait_for_background_worker(timeout=30)
    transition_check = dojo_run(
        "dojo",
        "flask",
        input=(
            "from CTFd.models import db\n"
            "from CTFd.plugins.dojo_plugin.models import PublicStatsCacheVersions, UserVisibilityUpdates\n"
            "from CTFd.plugins.dojo_plugin.utils.public_stats import affected_public_cache_keys\n"
            f"assert UserVisibilityUpdates.query.filter_by(user_id={source_id}).count() == 0\n"
            f"keys = affected_public_cache_keys(db.session.connection(), {source_id})\n"
            "versions = PublicStatsCacheVersions.query.filter(PublicStatsCacheVersions.cache_key.in_(keys)).all()\n"
            "assert len(versions) == len(keys)\n"
            "assert all(version.revision == version.ready_revision for version in versions)\n"
            "print('VISIBILITY_TRANSITION_COMPLETE')\n"
        ),
    )
    assert "VISIBILITY_TRANSITION_COMPLETE" in transition_check.stdout
    assert any(
        standing["user_id"] == source_id
        for standing in scoreboard_standings(
            anonymous_session,
            simple_award_dojo,
            "hello",
        )
    )

    start_challenge(race_dojo, "race", "beta", session=user_session)
    beta_flag = workspace_run(
        "cat /flag",
        user=user_name,
        root=True,
    ).stdout.strip()
    visibility_session = login(user_name, user_name)
    race_barrier = threading.Barrier(2)

    def hide_user():
        race_barrier.wait()
        return visibility_session.patch(
            f"{DOJO_URL}/api/v1/users/me",
            json={"hidden": True},
        )

    def solve_while_hiding():
        race_barrier.wait()
        return user_session.post(
            f"{DOJO_URL}/pwncollege_api/v1/dojos/"
            f"{race_dojo}/race/beta/solve",
            json={"submission": beta_flag},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        hidden_response_future = executor.submit(hide_user)
        solve_response_future = executor.submit(solve_while_hiding)
        hidden_response = hidden_response_future.result(timeout=30)
        concurrent_solve_response = solve_response_future.result(timeout=30)
    assert hidden_response.status_code == 200
    assert hidden_response.json()["data"]["hidden"] is True
    assert concurrent_solve_response.status_code == 200
    assert concurrent_solve_response.json()["success"] is True

    assert profile_solve_ids(user_id, simple_award_dojo, "hello") == [
        "apple",
        "banana",
    ]

    assert all(
        standing["user_id"] != user_id
        for standing in scoreboard_standings(
            anonymous_session,
            simple_award_dojo,
            "hello",
        )
    )
    assert all(
        standing["user_id"] != user_id
        for standing in scoreboard_standings(
            anonymous_session,
            race_dojo,
            "race",
        )
    )
    assert user_name not in anonymous_session.get(f"{DOJO_URL}/belts").text
    assert user_id not in feed_user_ids(anonymous_session)
    assert (
        anonymous_session.get(
            f"{DOJO_URL}/pwncollege_api/v1/score",
            params={"username": user_name},
        ).status_code
        == 400
    )

    wait_for_background_worker(timeout=30)
    belts_cache = json.loads(redis_cli("GET", "stats:belts"))
    emojis_cache = json.loads(redis_cli("GET", "stats:emojis"))
    assert str(user_id) not in belts_cache["users"]
    assert str(user_id) not in emojis_cache["emojis"]
    assert all(
        standing["user_id"] != user_id
        for standing in scoreboard_standings(
            anonymous_session,
            simple_award_dojo,
            "hello",
        )
    )
    assert any(
        standing["user_id"] == source_id
        for standing in scoreboard_standings(
            anonymous_session,
            simple_award_dojo,
            "hello",
        )
    )
    race_stats = json.loads(redis_cli("GET", race_stats_key))
    race_challenge_solves = json.loads(
        redis_cli("GET", race_challenge_solves_key)
    )
    assert race_stats["users"] == 0
    assert race_stats["solves"] == 0
    assert race_challenge_solves == {}
    assert json.loads(redis_cli("GET", race_scoreboard_key)) == []

    start_challenge(race_dojo, "race", "gamma", session=user_session)
    solve_challenge(
        race_dojo,
        "race",
        "gamma",
        session=user_session,
        user=user_name,
    )
    remove_workspace_container(user_name)
    wait_for_background_worker(timeout=30)
    assert json.loads(redis_cli("GET", race_scoreboard_key)) == []
    assert json.loads(redis_cli("GET", race_stats_key))["solves"] == 0
    assert json.loads(redis_cli("GET", race_challenge_solves_key)) == {}
    assert profile_solve_ids(user_id, race_dojo, "race") == [
        "alpha",
        "beta",
        "gamma",
    ]

    activity_cache_key = f"stats:activity:{user_id}"
    temporary_keys = [activity_cache_key, f"{activity_cache_key}:updated"]
    for key in score_keys:
        temporary_keys.extend((key, f"{key}:updated", f"{key}:visibility"))
    private_read_keys = [
        "stats:belts",
        "stats:belts:updated",
        "stats:belts:visibility",
        "stats:emojis",
        "stats:emojis:updated",
        "stats:emojis:visibility",
        *temporary_keys,
    ]

    def assert_hidden_profile(response, path):
        assert response.status_code == 200, path
        assert_profile_progress(
            response.text,
            simple_award_dojo,
            dojo_hex_id,
            hello_module_position,
            solve_count=2,
            challenge_count=2,
            rank=1,
            rank_count=2,
            solved_challenges=("apple", "banana"),
        )
        assert_profile_progress(
            response.text,
            viewer_private_dojo,
            private_dojo_hex_id,
            private_module_position,
            solve_count=3,
            challenge_count=3,
            rank=1,
            rank_count=1,
            solved_challenges=(
                "shared-apple",
                "duplicate-apple",
                "optional-banana",
            ),
        )
        assert "🧪" in response.text, path
        assert "/belt/orange.svg" in response.text, path

    with without_redis_keys(temporary_keys):
        cache_before_private_reads = snapshot_redis_keys(private_read_keys)
        profile_paths = [
            "/hacker/",
            f"/hacker/{user_id}",
            f"/hacker/{user_name}",
        ]
        for path in profile_paths:
            response = user_session.get(f"{DOJO_URL}{path}")
            assert_hidden_profile(response, path)

        activity_path = f"/pwncollege_api/v1/activity/{user_id}"
        activity_response = user_session.get(f"{DOJO_URL}{activity_path}")
        assert activity_response.status_code == 200
        assert activity_response.json()["data"]["total_solves"] >= 2
        assert other_session.get(f"{DOJO_URL}{activity_path}").status_code == 404
        assert anonymous_session.get(f"{DOJO_URL}{activity_path}").status_code == 404
        assert admin_session.get(f"{DOJO_URL}{activity_path}").status_code == 200
        assert snapshot_redis_keys(private_read_keys) == cache_before_private_reads

    hidden_profile_paths = [f"/hacker/{user_id}", f"/hacker/{user_name}"]
    for path in hidden_profile_paths:
        assert other_session.get(f"{DOJO_URL}{path}").status_code == 404
        assert anonymous_session.get(f"{DOJO_URL}{path}").status_code == 404
        assert admin_session.get(f"{DOJO_URL}{path}").status_code == 404

    public_user_api_paths = [
        f"/api/v1/users/{user_id}",
        f"/api/v1/users/{user_id}/solves",
        f"/api/v1/users/{user_id}/fails",
        f"/api/v1/users/{user_id}/awards",
    ]
    for path in public_user_api_paths:
        assert user_session.get(f"{DOJO_URL}{path}").status_code == 200
        assert other_session.get(f"{DOJO_URL}{path}").status_code == 404
        assert anonymous_session.get(f"{DOJO_URL}{path}").status_code == 404
        assert admin_session.get(f"{DOJO_URL}{path}").status_code == 200

    private_user_api_paths = [
        "/api/v1/users/me",
        "/api/v1/users/me/solves",
        "/api/v1/users/me/fails",
        "/api/v1/users/me/awards",
        "/pwncollege_api/v1/users/me",
    ]
    for path in private_user_api_paths:
        assert user_session.get(f"{DOJO_URL}{path}").status_code == 200

    banned_response = admin_session.patch(
        f"{DOJO_URL}/api/v1/users/{source_id}",
        json={"banned": True},
    )
    assert banned_response.status_code == 200
    assert banned_response.json()["data"]["banned"] is True
    assert all(
        standing["user_id"] != source_id
        for standing in scoreboard_standings(
            anonymous_session,
            simple_award_dojo,
            "hello",
        )
    )
    wait_for_background_worker(timeout=30)
    assert all(
        standing["user_id"] != source_id
        for standing in scoreboard_standings(
            anonymous_session,
            simple_award_dojo,
            "hello",
        )
    )
    assert source_id not in feed_user_ids(anonymous_session)
    assert (
        anonymous_session.get(
            f"{DOJO_URL}/pwncollege_api/v1/score",
            params={"username": source_name},
        ).status_code
        == 400
    )

    banned_profile_paths = [
        "/hacker/",
        f"/hacker/{source_id}",
        f"/hacker/{source_name}",
    ]
    for path in banned_profile_paths:
        assert source_session.get(f"{DOJO_URL}{path}").status_code == 403
    for path in banned_profile_paths[1:]:
        assert user_session.get(f"{DOJO_URL}{path}").status_code == 404
        assert anonymous_session.get(f"{DOJO_URL}{path}").status_code == 404
        assert admin_session.get(f"{DOJO_URL}{path}").status_code == 404

    banned_activity_path = f"/pwncollege_api/v1/activity/{source_id}"
    assert source_session.get(f"{DOJO_URL}{banned_activity_path}").status_code == 403
    assert user_session.get(f"{DOJO_URL}{banned_activity_path}").status_code == 404
    assert anonymous_session.get(f"{DOJO_URL}{banned_activity_path}").status_code == 404
    assert admin_session.get(f"{DOJO_URL}{banned_activity_path}").status_code == 200

    for suffix in ("", "/solves", "/fails", "/awards"):
        path = f"/api/v1/users/{source_id}{suffix}"
        assert source_session.get(f"{DOJO_URL}{path}").status_code == 403
        assert user_session.get(f"{DOJO_URL}{path}").status_code == 404
        assert anonymous_session.get(f"{DOJO_URL}{path}").status_code == 404
        assert admin_session.get(f"{DOJO_URL}{path}").status_code == 200
