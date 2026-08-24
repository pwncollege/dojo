import random
import re
import string
import time
from urllib.parse import urlparse

import pytest

from utils import (
    DOJO_URL,
    challenge_db_id,
    challenge_flag,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    flask_exec,
    get_user_id,
    login,
    make_dojo_official,
    parse_csrf_token,
    solve_challenge_offline,
    wait_for_background_worker,
)

API = f"{DOJO_URL}/pwncollege_api/v1"
ATTEMPT_URL = f"{DOJO_URL}/api/v1/challenges/attempt"


def random_id(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def register_user():
    name = random_id(16)
    return name, login(name, name, register=True)


def attempt(session, challenge_id, submission):
    return session.post(ATTEMPT_URL, json={"challenge_id": challenge_id, "submission": submission})


def solve_count(user_name, challenge_id):
    return int(db_sql(
        f"SELECT COUNT(*) FROM submissions WHERE user_id = {get_user_id(user_name)} "
        f"AND challenge_id = {challenge_id} AND type = 'correct'"
    ))


def imported_challenge(challenge_id, name, source="apple", required=True):
    required_line = "" if required else "        required: false\n"
    return (
        f"      - id: {challenge_id}\n"
        f"        name: {name}\n"
        f"{required_line}"
        f"        import:\n"
        f"          dojo: example\n"
        f"          module: hello\n"
        f"          challenge: {source}\n"
    )


@pytest.fixture(scope="module")
def flows_dojo(admin_session, example_dojo):
    spec = (
        f"id: cf-flows-{random_id()}\n"
        "name: Client Flows Dojo\n"
        "type: public\n"
        "modules:\n"
        "  - id: flows\n"
        "    name: Flows Module\n"
        "    challenges:\n"
        + imported_challenge("required-one", "Required One", "apple")
        + imported_challenge("optional-one", "Optional One", "banana", required=False)
    )
    reference_id = create_dojo_yml(spec, session=admin_session)
    make_dojo_official(reference_id, admin_session)
    return reference_id.split("~")[0]


@pytest.fixture(scope="module")
def flows_solver(flows_dojo):
    name, session = register_user()
    solve_challenge_offline(flows_dojo, "flows", "required-one", session=session, user=name)
    solve_challenge_offline(flows_dojo, "flows", "optional-one", session=session, user=name)
    wait_for_background_worker(timeout=10)
    return name, session


@pytest.fixture(scope="module")
def password_dojo(admin_session, example_dojo):
    spec = (
        f"id: cf-locked-{random_id()}\n"
        "name: Password Dojo\n"
        "password: hunter2hunter2\n"
        "modules:\n"
        "  - id: locked-module\n"
        "    name: Locked Module\n"
        "    challenges:\n"
        + imported_challenge("locked-challenge", "Locked Challenge")
    )
    return create_dojo_yml(spec, session=admin_session)


@pytest.fixture(scope="module")
def open_private_dojo(admin_session, example_dojo):
    spec = (
        f"id: cf-open-{random_id()}\n"
        "name: Open Private Dojo\n"
        "modules:\n"
        "  - id: open-module\n"
        "    name: Open Module\n"
        "    challenges:\n"
        + imported_challenge("open-challenge", "Open Challenge")
    )
    return create_dojo_yml(spec, session=admin_session)


def test_attempt_endpoint_is_the_browser_solve_path(example_dojo):
    name, session = register_user()
    challenge_id = challenge_db_id(example_dojo, "hello", "apple")
    flag = challenge_flag(example_dojo, "hello", "apple", user=name)

    response = attempt(session, challenge_id, flag)
    assert response.status_code == 200, f"attempt returned {response.status_code}: {response.text[:200]}"
    body = response.json()
    assert body["success"] is True, body
    assert body["data"]["status"] == "correct", body
    assert solve_count(name, challenge_id) == 1, "the browser attempt path must register exactly one solve"

    deadline = time.time() + 40
    board = {}
    while time.time() < deadline:
        wait_for_background_worker(timeout=5)
        board = session.get(f"{API}/scoreboard/{example_dojo}/hello/0/1").json()
        if board.get("me"):
            break
        time.sleep(1)
    assert board.get("me"), "a solve made through /api/v1/challenges/attempt must reach the dojo scoreboard"
    assert board["me"]["name"] == name, board["me"]


def test_survey_form_submits_without_javascript(surveys_dojo):
    name, session = register_user()
    assert session.get(f"{DOJO_URL}/dojo/{surveys_dojo}/join/").status_code == 200

    module_page = session.get(f"{DOJO_URL}/{surveys_dojo}/surveys-module-1")
    assert module_page.status_code == 200, module_page.status_code
    actions = re.findall(r'<form[^>]*action="([^"]*surveys[^"]*)"', module_page.text)
    assert actions, "the module page must render a survey form"

    before = int(db_sql(f"SELECT count(*) FROM survey_responses WHERE user_id = {get_user_id(name)}"))
    action = actions[0]
    response = session.post(
        f"{DOJO_URL.rstrip('/')}{action}",
        data={"nonce": parse_csrf_token(module_page.text), "response": "native-form-response"},
        headers={"CSRF-Token": None},
    )
    assert response.status_code == 200, \
        f"The rendered survey form failed without JavaScript: {response.status_code} {response.text[:200]}"
    assert response.json()["success"] is True, response.json()
    after = int(db_sql(f"SELECT count(*) FROM survey_responses WHERE user_id = {get_user_id(name)}"))
    assert after == before + 1, "The native form submission did not store its survey response"


def test_dojo_admin_invite_link_embeds_password(admin_session, password_dojo, open_private_dojo):
    name, session = register_user()
    user_id = get_user_id(name)

    def invite_link(dojo):
        page = admin_session.get(f"{DOJO_URL}/dojo/{dojo}/admin/")
        assert page.status_code == 200, page.status_code
        match = re.search(r'id="user-token-result"[^>]*value="([^"]+)"', page.text)
        assert match, "the dojo admin page renders a share link"
        return match.group(1)

    def membership(dojo):
        return db_sql(
            f"SELECT type FROM dojo_users WHERE user_id = {user_id} AND dojo_id = {dojo_db_id(dojo)}"
        ).strip()

    link = invite_link(password_dojo)
    assert link.endswith(f"/dojo/{password_dojo}/join/hunter2hunter2"), link

    assert session.get(f"{DOJO_URL}/dojo/{password_dojo}/join/").status_code == 403
    assert membership(password_dojo) == "", "a wrong password creates no membership"

    response = session.get(f"{DOJO_URL}{urlparse(link).path}")
    assert response.status_code == 200, response.status_code
    assert membership(password_dojo) == "member"

    open_link = invite_link(open_private_dojo)
    assert open_link.endswith(f"/dojo/{open_private_dojo}/join/"), open_link
    assert session.get(f"{DOJO_URL}{urlparse(open_link).path}").status_code == 200
    assert membership(open_private_dojo) == "member"


def test_profile_dojo_progress_survives_duplicate_dojo_ids(admin_session, example_dojo):
    shared_id = f"cf-twin-{random_id()}"
    name, session = register_user()

    def twin_spec(challenge, source):
        return (
            f"id: {shared_id}\n"
            "name: Twin Dojo\n"
            "type: public\n"
            "modules:\n"
            "  - id: twin-module\n"
            "    name: Twin Module\n"
            "    challenges:\n"
            + imported_challenge(challenge, challenge.title(), source)
        )

    official = create_dojo_yml(twin_spec("twin-one", "apple"), session=admin_session)
    make_dojo_official(official, admin_session)
    official = official.split("~")[0]
    unofficial = create_dojo_yml(twin_spec("twin-two", "banana"), session=admin_session)

    solve_challenge_offline(official, "twin-module", "twin-one", session=session, user=name)
    assert session.get(f"{DOJO_URL}/dojo/{unofficial}/join/").status_code == 200
    solve_challenge_offline(unofficial, "twin-module", "twin-two", session=session, user=name)

    assert admin_session.get(f"{DOJO_URL}/hacker/{get_user_id(name)}").status_code == 200

    ranks = flask_exec(
        "from CTFd.plugins.dojo_plugin.pages.users import build_user_scores\n"
        "from CTFd.plugins.dojo_plugin.models import Dojos\n"
        "from CTFd.models import Users\n"
        f"user = Users.query.filter_by(name={name!r}).first()\n"
        f"dojos = Dojos.query.filter_by(id={shared_id!r}).all()\n"
        "dojo_scores, _ = build_user_scores(user, dojos)\n"
        "print(len(dojos), len(dojo_scores['dojo_ranks']))\n"
    ).strip()
    dojo_count, rank_count = (int(value) for value in ranks.split())
    assert dojo_count == 2, ranks
    assert rank_count == 2, "two dojos sharing an id must keep separate progress entries on a profile"


def test_dojo_progress_counts_only_required_solves(flows_dojo, flows_solver):
    name, session = flows_solver

    dojos = session.get(f"{API}/dojos").json()["dojos"]
    entry = next(dojo for dojo in dojos if dojo["id"] == flows_dojo)
    assert entry["challenges_count"] == 1, f"the dojos API counts required challenges only: {entry}"
    assert entry["modules_count"] == 1, entry

    counts = flask_exec(
        "from CTFd.plugins.dojo_plugin.models import Dojos, DojoChallenges\n"
        "from CTFd.models import Users\n"
        f"dojo = Dojos.from_id({flows_dojo!r}).first()\n"
        f"user = Users.query.filter_by(name={name!r}).first()\n"
        "solves = DojoChallenges.solves(user=user, ignore_visibility=True, ignore_admins=False)"
        ".filter(DojoChallenges.dojo_id == dojo.dojo_id).count()\n"
        "print(solves, dojo.required_challenges_count, len(dojo.challenges))\n"
    ).strip()
    solves, required, total = (int(value) for value in counts.split())
    assert total == 2, counts
    assert required == 1, counts
    assert solves <= required, f"solving optional challenges must not push dojo progress past 100%: {counts}"

    assert session.get(f"{DOJO_URL}/{flows_dojo}").status_code == 200
    assert session.get(f"{DOJO_URL}/hacker/{get_user_id(name)}").status_code == 200


def test_module_card_progress_cannot_exceed_denominator(admin_session, example_dojo):
    spec = (
        f"id: cf-window-{random_id()}\n"
        "name: Visibility Window Dojo\n"
        "type: public\n"
        "modules:\n"
        "  - id: window\n"
        "    name: Window Module\n"
        "    challenges:\n"
        "      - id: closing-one\n"
        "        name: Closing One\n"
        "        visibility:\n"
        "          stop: '2099-01-01T00:00:00Z'\n"
        "        import:\n"
        "          dojo: example\n"
        "          module: hello\n"
        "          challenge: apple\n"
    )
    dojo = create_dojo_yml(spec, session=admin_session)
    name, session = register_user()
    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 200

    solve_challenge_offline(dojo, "window", "closing-one", session=session, user=name)
    db_sql(
        f"UPDATE dojo_challenge_visibilities SET stop = NOW() - INTERVAL '1 day' "
        f"WHERE dojo_id = {dojo_db_id(dojo)}"
    )

    counts = flask_exec(
        "from CTFd.plugins.dojo_plugin.models import Dojos\n"
        "from CTFd.models import Users\n"
        f"dojo = Dojos.from_id({dojo!r}).first()\n"
        f"user = Users.query.filter_by(name={name!r}).first()\n"
        "module = dojo.modules[0]\n"
        "solved = module.visible_solves(user=user, ignore_admins=False).count()\n"
        "print(solved, len(module.visible_challenges(required_only=True)))\n"
    ).strip()
    solved, visible_required = (int(value) for value in counts.split())

    assert session.get(f"{DOJO_URL}/{dojo}").status_code == 200
    assert visible_required == 0, counts
    assert solved <= visible_required, f"module progress must not render more solves than challenges: {counts}"
