import json
import random
import re
import string
import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from utils import (
    DOJO_URL,
    challenge_db_id,
    challenge_flag,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    flask_exec,
    get_user_id,
    login,
    make_dojo_official,
    parse_csrf_token,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
    wait_for_background_worker,
    workspace_run,
)

API = f"{DOJO_URL}/pwncollege_api/v1"
ATTEMPT_URL = f"{DOJO_URL}/api/v1/challenges/attempt"


def random_id(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def anonymous_session():
    session = requests.Session()
    session.headers["CSRF-Token"] = parse_csrf_token(session.get(f"{DOJO_URL}/login").text)
    return session


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


def ctfd_env(name):
    result = dojo_run("docker", "exec", "ctfd", "printenv", name, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def redis_get(key):
    result = dojo_run("docker", "exec", "cache", "redis-cli", "--no-raw", "GET", key, check=False)
    raw = result.stdout.strip()
    if not raw or raw == "(nil)" or raw == '""':
        return None
    if raw.startswith('"') and raw.endswith('"'):
        raw = json.loads(raw)
    return json.loads(raw)


def redis_del(key):
    dojo_run("docker", "exec", "cache", "redis-cli", "DEL", key, check=False)


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
def attribution_dojos(admin_session, example_dojo):
    source_spec = (
        f"id: cf-src-{random_id()}\n"
        "name: Attribution Source Dojo\n"
        "type: public\n"
        "modules:\n"
        "  - id: source-module\n"
        "    name: Source Module\n"
        "    challenges:\n"
        "      - id: shared\n"
        "        name: Shared Challenge\n"
        "files:\n"
        "  - type: text\n"
        "    path: source-module/shared/run\n"
        "    content: |\n"
        "      #!/opt/pwn.college/bash\n"
        "      cat /flag\n"
    )
    source = create_dojo_yml(source_spec, session=admin_session)
    make_dojo_official(source, admin_session)
    source = source.split("~")[0]

    importer_spec = (
        f"id: cf-dst-{random_id()}\n"
        "name: Attribution Importer Dojo\n"
        "type: public\n"
        "modules:\n"
        "  - id: importer-module\n"
        "    name: Importer Module\n"
        "    challenges:\n"
        "      - id: borrowed\n"
        "        import:\n"
        f"          dojo: {source}\n"
        "          module: source-module\n"
        "          challenge: shared\n"
    )
    importer = create_dojo_yml(importer_spec, session=admin_session)
    make_dojo_official(importer, admin_session)
    return source, importer.split("~")[0]


@pytest.fixture(scope="module")
def interfaces_flow_dojo(admin_session, example_dojo):
    spec = (
        f"id: cf-iface-{random_id()}\n"
        "name: Client Flows Interfaces Dojo\n"
        "type: public\n"
        "modules:\n"
        "  - id: iface\n"
        "    name: Interface Module\n"
        "    challenges:\n"
        "      - id: shell-port\n"
        "        name: Shell Port\n"
        "        interfaces:\n"
        "        - name: Shell\n"
        "          port: 7681\n"
        "        import:\n"
        "          dojo: example\n"
        "          module: hello\n"
        "          challenge: apple\n"
    )
    return create_dojo_yml(spec, session=admin_session)


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


@pytest.fixture(scope="module")
def course_flow_dojo(admin_session, example_dojo):
    spec = (
        f"id: cf-course-{random_id()}\n"
        "name: Client Flows Course\n"
        "type: course\n"
        "modules:\n"
        "  - id: course-module\n"
        "    name: Course Module\n"
        "    challenges:\n"
        + imported_challenge("course-challenge", "Course Challenge")
    )
    reference_id = create_dojo_yml(spec, session=admin_session)
    make_dojo_official(reference_id, admin_session)
    reference_id = reference_id.split("~")[0]
    data = json.loads(db_sql(f"SELECT data FROM dojos WHERE id = '{reference_id}'"))
    data["course"] = {"student_id": "ASURITE", "students": {"cf-roster-token": {}}}
    db_sql(f"UPDATE dojos SET data = '{json.dumps(data)}' WHERE id = '{reference_id}'")
    return reference_id


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


def test_attempt_endpoint_surfaces_flagexception_messages(example_dojo):
    name, session = register_user()
    other_name, _ = register_user()

    apple_id = challenge_db_id(example_dojo, "hello", "apple")
    banana_id = challenge_db_id(example_dojo, "hello", "banana")

    someone_elses_flag = challenge_flag(example_dojo, "hello", "banana", user=other_name)
    response = attempt(session, banana_id, someone_elses_flag)
    assert response.status_code == 200, response.text[:200]
    assert response.json()["data"]["status"] == "incorrect", response.json()
    assert response.json()["data"]["message"] == "This flag is not yours!", response.json()

    wrong_challenge_flag = challenge_flag(example_dojo, "hello", "banana", user=name)
    response = attempt(session, apple_id, wrong_challenge_flag)
    assert response.status_code == 200, response.text[:200]
    assert response.json()["data"]["status"] == "incorrect", response.json()
    assert response.json()["data"]["message"] == "This flag is not for this challenge!", response.json()

    assert solve_count(name, apple_id) == 0, "a rejected flag must not create a solve"
    assert solve_count(name, banana_id) == 0, "a rejected flag must not create a solve"

    dojo_response = session.post(
        f"{API}/dojos/{example_dojo}/hello/apple/solve", json={"submission": wrong_challenge_flag}
    )
    assert dojo_response.status_code == 400, dojo_response.text[:200]
    assert dojo_response.json() == {"success": False, "status": "incorrect"}, dojo_response.json()


def test_attempt_endpoint_status_vocabulary(example_dojo):
    name, session = register_user()
    apple_id = challenge_db_id(example_dojo, "hello", "apple")
    banana_id = challenge_db_id(example_dojo, "hello", "banana")

    anonymous = anonymous_session()
    response = anonymous.post(ATTEMPT_URL, json={"challenge_id": apple_id, "submission": "pwn.college{nope}"})
    assert response.status_code == 403, response.text[:200]
    assert response.json()["data"]["status"] == "authentication_required", response.json()

    flag = challenge_flag(example_dojo, "hello", "apple", user=name)
    assert attempt(session, apple_id, flag).json()["data"]["status"] == "correct"
    response = attempt(session, apple_id, flag)
    assert response.status_code == 200, response.text[:200]
    assert response.json()["data"]["status"] == "already_solved", response.json()
    assert solve_count(name, apple_id) == 1, "resubmitting a correct flag must not create a second solve"

    statuses = []
    for index in range(14):
        response = attempt(session, banana_id, f"pwn.college{{wrong-{index}}}")
        statuses.append((response.status_code, response.json()["data"]["status"]))
        if response.json()["data"]["status"] == "ratelimited":
            break
    assert (429, "ratelimited") in statuses, f"expected a ratelimited status after repeated wrong flags: {statuses}"
    assert solve_count(name, banana_id) == 0, "ratelimited submissions must not create a solve"


def test_attempt_endpoint_is_dojo_agnostic(visibility_test_dojo, open_private_dojo, progression_locked_dojo):
    name, session = register_user()

    hidden_id = challenge_db_id(visibility_test_dojo, "module2", "challenge-b")
    hidden_flag = challenge_flag(visibility_test_dojo, "module2", "challenge-b", user=name)
    response = session.post(
        f"{API}/dojos/{visibility_test_dojo}/module2/challenge-b/solve", json={"submission": hidden_flag}
    )
    assert response.status_code == 404, "the dojo solve endpoint gates on challenge visibility"
    assert attempt(session, hidden_id, hidden_flag).json()["data"]["status"] == "correct"
    assert solve_count(name, hidden_id) == 1, "CTFd's attempt endpoint solves the challenge row itself"

    private_id = challenge_db_id(open_private_dojo, "open-module", "open-challenge")
    private_flag = challenge_flag(open_private_dojo, "open-module", "open-challenge", user=name)
    assert session.get(f"{DOJO_URL}/{open_private_dojo}").status_code == 404, "non-members cannot view a private dojo"
    response = session.post(
        f"{API}/dojos/{open_private_dojo}/open-module/open-challenge/solve", json={"submission": private_flag}
    )
    assert response.status_code == 404, "the dojo solve endpoint gates on dojo viewability"
    assert attempt(session, private_id, private_flag).json()["data"]["status"] == "correct"
    assert solve_count(name, private_id) == 1

    locked_id = challenge_db_id(progression_locked_dojo, "progression-locked-module", "locked-challenge")
    locked_flag = challenge_flag(progression_locked_dojo, "progression-locked-module", "locked-challenge", user=name)
    response = session.post(
        f"{API}/dojos/{progression_locked_dojo}/progression-locked-module/locked-challenge/solve",
        json={"submission": locked_flag},
    )
    assert response.status_code == 200, "progression locking gates starting a challenge, not submitting its flag"
    assert response.json()["status"] == "solved", response.json()
    assert solve_count(name, locked_id) == 1


def test_survey_post_requires_top_level_response_key(surveys_dojo):
    name, session = register_user()
    assert session.get(f"{DOJO_URL}/dojo/{surveys_dojo}/join/").status_code == 200
    user_id = get_user_id(name)
    challenge_id = challenge_db_id(surveys_dojo, "surveys-module-1", "challenge-level")
    url = f"{API}/dojos/{surveys_dojo}/surveys-module-1/challenge-level/surveys"

    def response_rows():
        return db_sql(
            f"SELECT prompt, response FROM survey_responses WHERE user_id = {user_id} "
            f"AND challenge_id = {challenge_id}"
        ).strip()

    response = session.post(url, json={"rating": "5"})
    assert response.status_code == 400, response.text[:200]
    assert response.json() == {"success": False, "error": "Missing response"}, response.json()
    assert response_rows() == "", "a rejected survey submission must not be stored"

    for _ in range(2):
        response = session.post(url, json={"response": "ok"})
        assert response.status_code == 200, response.text[:200]
        assert response.json() == {"success": True}, response.json()

    rows = response_rows().split("\n")
    assert len(rows) == 2, f"each accepted survey submission must be stored separately: {rows}"
    assert all(row == "Challenge-level prompt|ok" for row in rows), rows

    dojo_id = int(db_sql(
        f"SELECT dojo_id FROM survey_responses WHERE user_id = {user_id} AND challenge_id = {challenge_id} LIMIT 1"
    ))
    assert dojo_id == dojo_db_id(surveys_dojo), "the survey response records the dojo it was submitted through"


def test_surveys_get_is_anonymous_but_post_is_not(surveys_dojo, open_private_dojo):
    anonymous = anonymous_session()
    url = f"{API}/dojos/{surveys_dojo}/surveys-module-1/challenge-level/surveys"

    response = anonymous.get(url)
    assert response.status_code == 200, response.text[:200]
    assert response.json()["prompt"] == "Challenge-level prompt", response.json()
    assert response.json()["type"] == "user-specified", response.json()

    response = anonymous.post(url, json={"response": "anonymous"})
    assert response.status_code == 403, "survey submission requires authentication"

    private_url = f"{API}/dojos/{open_private_dojo}/open-module/open-challenge/surveys"
    assert anonymous.get(private_url).status_code == 404, "surveys of a non-viewable dojo stay hidden"


def test_survey_form_action_route_exists(surveys_dojo):
    name, session = register_user()
    assert session.get(f"{DOJO_URL}/dojo/{surveys_dojo}/join/").status_code == 200

    module_page = session.get(f"{DOJO_URL}/{surveys_dojo}/surveys-module-1")
    assert module_page.status_code == 200, module_page.status_code
    actions = re.findall(r'<form[^>]*action="([^"]*surveys[^"]*)"', module_page.text)
    assert actions, "the module page must render a survey form"

    for action in set(actions):
        response = session.post(f"{DOJO_URL.rstrip('/')}{action}", json={"response": "fallback"})
        assert response.status_code != 404, \
            f"the survey form action rendered by module.html must resolve to a route: {action}"


def test_search_response_contract_and_links(searchable_dojo, random_user_session):
    searchable_dojo = searchable_dojo.split("~")[0]
    for query in ["", "a"]:
        response = random_user_session.get(f"{API}/search", params={"q": query})
        assert response.status_code == 400, f"query {query!r} returned {response.status_code}"
        assert response.json() == {"success": False, "error": "Query too short."}, response.json()

    response = random_user_session.get(f"{API}/search", params={"q": "Searchable Dojo"})
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert body["success"] is True
    results = body["results"]
    assert set(results) == {"dojos", "modules", "challenges"}, sorted(results)
    assert all(isinstance(results[key], list) for key in results), results

    dojo_result = next(item for item in results["dojos"] if item["id"] == searchable_dojo)
    assert dojo_result["name"] == "Searchable Dojo", dojo_result
    assert dojo_result["description"], dojo_result
    assert dojo_result["link"] == f"/{searchable_dojo}", dojo_result

    response = random_user_session.get(f"{API}/search", params={"q": "search testing"})
    module_result = next(item for item in response.json()["results"]["modules"] if item["dojo"]["id"] == searchable_dojo)
    for key in ["name", "link", "description"]:
        assert module_result[key], f"module result is missing {key}: {module_result}"
    assert module_result["dojo"]["name"] == "Searchable Dojo", module_result

    response = random_user_session.get(f"{API}/search", params={"q": "about apples"})
    challenge_result = next(
        item for item in response.json()["results"]["challenges"] if item["dojo"]["id"] == searchable_dojo
    )
    for key in ["name", "link", "description"]:
        assert challenge_result[key], f"challenge result is missing {key}: {challenge_result}"
    assert challenge_result["dojo"]["name"] == "Searchable Dojo", challenge_result
    assert challenge_result["module"]["name"] == "Hello Module", challenge_result

    for link in [dojo_result["link"], module_result["link"], challenge_result["link"], challenge_result["module"]["link"]]:
        assert random_user_session.get(f"{DOJO_URL}{link}").status_code == 200, f"search link {link} does not resolve"


def test_challenge_deep_link_renders_module_page(searchable_dojo, random_user_session):
    searchable_dojo = searchable_dojo.split("~")[0]
    response = random_user_session.get(f"{API}/search", params={"q": "Apple Challenge"})
    challenge_result = next(
        item for item in response.json()["results"]["challenges"] if item["dojo"]["id"] == searchable_dojo
    )
    challenge_link = challenge_result["link"]
    module_link = challenge_result["module"]["link"]

    challenge_page = random_user_session.get(f"{DOJO_URL}{challenge_link}")
    module_page = random_user_session.get(f"{DOJO_URL}{module_link}")
    assert challenge_page.status_code == 200, challenge_link
    assert module_page.status_code == 200, module_link
    assert "Hello Module" in challenge_page.text, "the deep link renders the module the challenge belongs to"
    assert "Apple Challenge" in challenge_page.text
    assert "Apple Challenge" in module_page.text

    bogus = random_user_session.get(f"{DOJO_URL}{module_link}/no-such-challenge")
    assert bogus.status_code == 404, "an unknown challenge id under a real module must 404"


def test_workspace_api_and_active_module_track_started_challenge(example_dojo):
    name, session = register_user()
    try:
        assert session.get(f"{DOJO_URL}/active-module").json() == {}, "no container means no active module"

        start_challenge(example_dojo, "hello", "apple", session=session)

        response = session.get(f"{API}/workspace", params={"service": "terminal"})
        assert response.status_code == 200, response.text[:200]
        body = response.json()
        assert set(body) >= {"success", "active", "iframe_src", "service", "port", "setPort", "current_challenge"}, body
        assert body["success"] is True and body["active"] is True, body
        assert body["service"] == "terminal" and body["port"] is None, body
        assert isinstance(body["setPort"], bool), body
        assert body["setPort"] == (ctfd_env("DOJO_ENV") == "development"), body
        assert body["current_challenge"] == {
            "dojo_id": example_dojo, "module_id": "hello", "challenge_id": "apple"
        }, body

        active = session.get(f"{DOJO_URL}/active-module").json()
        assert active["c_current"]["dojo_reference_id"] == example_dojo, active
        assert active["c_current"]["module_id"] == "hello", active
        assert active["c_current"]["challenge_reference_id"] == "apple", active
        assert active["c_current"]["challenge_id"] == challenge_db_id(example_dojo, "hello", "apple"), active
        assert active["c_current"]["description"], "the current challenge carries its rendered description"
        assert active["c_previous"] == {}, active
        assert active["c_next"]["challenge_reference_id"] == "banana", active
        assert active["c_next"]["description"] is None, "only the current challenge carries a description"
        assert session.get(
            f"{DOJO_URL}/{active['c_next']['dojo_reference_id']}/{active['c_next']['module_id']}"
            f"/{active['c_next']['challenge_reference_id']}"
        ).status_code == 200, "the link the actionbar builds from /active-module must resolve"
    finally:
        remove_workspace_container(name)


def test_workspace_desktop_services(example_dojo):
    name, session = register_user()
    try:
        start_challenge(example_dojo, "hello", "apple", session=session)

        windows = session.get(f"{API}/workspace", params={"service": "desktop-windows"}).json()
        assert windows["success"] is True and windows["active"] is True, windows
        parsed = urlparse(windows["iframe_src"])
        params = parse_qs(parsed.query)
        assert parsed.path.endswith("/6082/vnc.html"), windows["iframe_src"]
        assert params["autoconnect"] == ["1"], params
        assert params["resize"] == ["local"], params
        assert params["password"] == ["password"], params
        assert "/6082/websockify" in params["path"][0], params

        desktop = session.get(f"{API}/workspace", params={"service": "desktop"}).json()
        assert desktop["success"] is True, desktop
        desktop_parsed = urlparse(desktop["iframe_src"])
        desktop_params = parse_qs(desktop_parsed.query)
        assert desktop_parsed.path.endswith("/6080/vnc.html"), desktop["iframe_src"]
        assert desktop_params["resize"] == ["remote"], desktop_params
        assert desktop_params["password"] != ["password"], "the linux desktop uses a per-container password"
        assert "/6080/websockify" in desktop_params["path"][0], desktop_params
    finally:
        remove_workspace_container(name)


def test_workspace_pages_and_docker_state_without_container():
    _, session = register_user()

    for path in ["/workspace", "/workspace/terminal", "/workspace/8080"]:
        assert session.get(f"{DOJO_URL}{path}").status_code == 200, path
    assert "No active challenge session" in session.get(f"{DOJO_URL}/workspace").text

    assert session.get(f"{API}/workspace", params={"service": "terminal"}).json() == {
        "success": False, "active": False
    }
    assert session.get(f"{API}/docker").json() == {"success": False, "error": "No active challenge"}
    assert session.delete(f"{API}/docker", json={}).json() == {
        "success": False, "error": "No active challenge container"
    }


def test_docker_api_reports_missing_container(example_dojo):
    name, session = register_user()
    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        assert session.get(f"{API}/docker").json() == {
            "success": True, "dojo": example_dojo, "module": "hello", "challenge": "apple", "practice": False
        }
        assert session.get(f"{API}/workspace", params={"service": "terminal"}).json()["active"] is True

        remove_workspace_container(name)

        body = session.get(f"{API}/docker").json()
        assert body["success"] is False, body
        assert body["error"] in ("No active challenge", "No challenge container"), body
        assert body["error"] == "No active challenge", "a removed container leaves no resolvable challenge"
        assert session.delete(f"{API}/docker", json={}).json()["error"] == "No active challenge container"
    finally:
        remove_workspace_container(name)


def test_actionbar_restart_roundtrip(open_private_dojo):
    name, session = register_user()
    try:
        assert session.get(f"{DOJO_URL}/dojo/{open_private_dojo}/join/").status_code == 200
        start_challenge(open_private_dojo, "open-module", "open-challenge", session=session)

        state = session.get(f"{API}/docker").json()
        assert state == {
            "success": True,
            "dojo": open_private_dojo,
            "module": "open-module",
            "challenge": "open-challenge",
            "practice": False,
        }, state
        assert "~" in state["dojo"], "a private dojo is identified by its <id>~<hex> reference id"

        response = session.post(f"{API}/docker", json={
            "dojo": state["dojo"], "module": state["module"], "challenge": state["challenge"], "practice": True
        })
        assert response.status_code == 200 and response.json()["success"], response.text[:200]

        assert session.get(f"{API}/docker").json()["practice"] is True
        assert workspace_run("cat /run/dojo/sys/workspace/privileged", user=name).stdout.strip() == "1"
    finally:
        remove_workspace_container(name)


def test_interface_service_routing_starts_on_demand_service(interfaces_flow_dojo):
    name, session = register_user()
    try:
        assert session.get(f"{DOJO_URL}/dojo/{interfaces_flow_dojo}/join/").status_code == 200
        start_challenge(interfaces_flow_dojo, "iface", "shell-port", session=session)

        def ttyd_count():
            return int(workspace_run("pgrep -c ttyd || true", user=name).stdout.strip() or 0)

        assert ttyd_count() == 0, "no terminal service runs before the workspace asks for one"

        by_port = session.get(f"{API}/workspace", params={"port": 7681}).json()
        assert by_port["success"] is True, by_port
        assert str(by_port["port"]) == "7681", by_port
        assert by_port["service"] is None, by_port
        assert "/7681/" in by_port["iframe_src"], by_port
        assert ttyd_count() == 0, "a raw ?port= request does not start the on-demand terminal service"

        by_service = session.get(f"{API}/workspace", params={"service": "terminal"}).json()
        assert by_service["success"] is True, by_service
        assert ttyd_count() >= 1, "?service=terminal must start the on-demand terminal service"
    finally:
        remove_workspace_container(name)


def test_container_counts_track_container_lifecycle(flows_dojo):
    name, session = register_user()
    reference_id = flows_dojo

    def container_entries():
        stats = redis_get("stats:containers") or []
        return [entry for entry in stats if entry.get("dojo") == reference_id
                and entry.get("module") == "flows" and entry.get("challenge") == "required-one"]

    def wait_for_entries(expected):
        deadline = time.time() + 25
        while time.time() < deadline:
            wait_for_background_worker(timeout=5)
            if len(container_entries()) == expected:
                return True
            time.sleep(1)
        return False

    try:
        assert session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
        assert len(container_entries()) == 0, "a dojo nobody is hacking has no container-stats entries"

        start_challenge(reference_id, "flows", "required-one", session=session)
        assert wait_for_entries(1), "starting a container must add exactly one entry at the dojo/module/challenge scope"

        assert session.delete(f"{API}/docker", json={}).json()["success"] is True
        assert wait_for_entries(0), "terminating a container must remove its entry from the container stats"
    finally:
        remove_workspace_container(name)


def test_feed_limit_bounds():
    for limit in ["0", "-5"]:
        response = requests.get(f"{API}/feed/events", params={"limit": limit})
        assert response.status_code == 200, response.text[:200]
        body = response.json()
        assert body["data"] == [], body
        assert body["meta"]["count"] == 0, body

    response = requests.get(f"{API}/feed/events", params={"limit": "500"})
    body = response.json()
    assert body["meta"]["limit"] == 100, body
    assert len(body["data"]) <= 100, len(body["data"])

    response = requests.get(f"{API}/feed/events", params={"limit": "abc"})
    body = response.json()
    assert body["meta"]["limit"] == 50, body
    assert body["meta"]["offset"] == 0, body


def test_feed_user_emojis_are_resolved_emoji_characters(simple_award_dojo, example_dojo):
    name, session = register_user()
    user_id = get_user_id(name)
    hex_id = simple_award_dojo.split("~")[1]

    db_sql(f"""
        INSERT INTO awards (user_id, type, name, description, date, value, icon)
        VALUES
            ({user_id}, 'emoji', 'CUSTOM', 'first custom', NOW(), 0, '🦄'),
            ({user_id}, 'emoji', 'CUSTOM', 'second custom', NOW(), 0, '🦄'),
            ({user_id}, 'emoji', 'CUSTOM', 'third custom', NOW(), 0, '🐙')
    """)

    assert session.get(f"{DOJO_URL}/dojo/{simple_award_dojo}/join/").status_code == 200
    solve_challenge_offline(simple_award_dojo, "hello", "apple", session=session, user=name)
    solve_challenge_offline(simple_award_dojo, "hello", "banana", session=session, user=name)

    def latest_event():
        events = requests.get(f"{API}/feed/events", params={"limit": 100}).json()["data"]
        mine = [event for event in events if event["user_name"] == name]
        assert mine, f"no feed event was published for {name}"
        return mine[0]

    event = latest_event()
    emojis = event["user_emojis"]
    assert isinstance(emojis, list), event
    assert emojis.count("🦄") == 1, f"duplicate award emojis collapse: {emojis}"
    assert "🐙" in emojis, emojis
    assert "🧪" in emojis, f"the dojo award emoji is resolved from the award category: {emojis}"
    assert not ({"CURRENT", "STALE", "CUSTOM"} & set(emojis)), f"award names must not leak into the feed: {emojis}"

    db_sql(f"UPDATE awards SET name = 'STALE' WHERE user_id = {user_id} AND icon = '🐙'")
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)

    emojis = latest_event()["user_emojis"]
    assert "🐙" not in emojis, f"stale awards are excluded from feed emojis: {emojis}"
    assert "🦄" in emojis and "🧪" in emojis, emojis
    assert int(db_sql(f"SELECT COUNT(*) FROM awards WHERE user_id = {user_id} AND category = '{hex_id}'")) >= 1


def test_award_popup_can_resolve_dojo_emoji(simple_award_dojo):
    name, session = register_user()
    hex_id = simple_award_dojo.split("~")[1]

    assert session.get(f"{DOJO_URL}/dojo/{simple_award_dojo}/join/").status_code == 200
    solve_challenge_offline(simple_award_dojo, "hello", "apple", session=session, user=name)
    solve_challenge_offline(simple_award_dojo, "hello", "banana", session=session, user=name)

    awards = session.get(f"{DOJO_URL}/api/v1/users/me/awards").json()["data"]
    completion = [award for award in awards if award["category"] == hex_id]
    assert len(completion) == 1, f"completing a dojo grants one award in its category: {completion}"
    assert completion[0]["icon"] is None, "dojo-completion awards carry no icon; the emoji comes from the dojo"

    dojos = session.get(f"{API}/dojos").json()["dojos"]
    matching = [dojo for dojo in dojos if dojo["hex_id"] == hex_id]
    assert len(matching) == 1, f"exactly one dojo resolves the award category: {matching}"
    assert matching[0]["award"]["emoji"] == "🧪", matching[0]

    db_id = dojo_db_id(simple_award_dojo)
    data = json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id = {db_id}"))
    data.pop("award", None)
    db_sql(f"UPDATE dojos SET data = '{json.dumps(data)}' WHERE dojo_id = {db_id}")

    dojos = session.get(f"{API}/dojos").json()["dojos"]
    matching = [dojo for dojo in dojos if dojo["hex_id"] == hex_id]
    assert matching[0]["award"] is None, "dropping the award config leaves the client with no emoji to render"
    assert int(db_sql(f"SELECT COUNT(*) FROM awards WHERE category = '{hex_id}'")) >= 1


def test_feed_solve_event_attributes_the_solving_dojo(attribution_dojos):
    source, importer = attribution_dojos
    name, session = register_user()

    solve_challenge_offline(importer, "importer-module", "borrowed", session=session, user=name)

    events = requests.get(f"{API}/feed/events", params={"limit": 100}).json()["data"]
    solves = [event for event in events if event["user_name"] == name and event["type"] == "challenge_solve"]
    assert solves, f"solving an official dojo challenge publishes a feed event: {name}"
    data = solves[0]["data"]

    assert session.get(f"{DOJO_URL}/{data['dojo_id']}/{data['module_id']}").status_code == 200, data
    assert (data["dojo_id"], data["module_id"]) in [
        (source, "source-module"), (importer, "importer-module")
    ], f"the event's module must belong to the event's dojo: {data}"
    assert data["dojo_id"] == importer, f"the feed must attribute the solve to the dojo it happened in: {data}"


def test_feed_page_ids_match_the_events_api(flows_dojo):
    name, session = register_user()
    solve_challenge_offline(flows_dojo, "flows", "required-one", session=session, user=name)

    page_ids = re.findall(r'data-event-id="([^"]+)"', requests.get(f"{DOJO_URL}/feed").text)
    api_ids = [event["id"] for event in requests.get(f"{API}/feed/events", params={"limit": 100}).json()["data"]]

    assert page_ids, "the feed page pre-renders recent events"
    assert len(page_ids) <= 20, f"the feed page pre-renders at most 20 events, got {len(page_ids)}"
    assert set(page_ids) <= set(api_ids), "pre-rendered event ids must be the same ids the events API emits"
    positions = [api_ids.index(event_id) for event_id in page_ids]
    assert positions == sorted(positions), "pre-rendered events keep the API's newest-first ordering"


def test_settings_hidden_select_submits_string_booleans():
    name, session = register_user()
    user_id = get_user_id(name)
    other_name, other_session = register_user()

    def settings_patch(hidden):
        return session.patch(f"{DOJO_URL}/api/v1/users/me", json={
            "name": name,
            "email": f"{name}@example.com",
            "affiliation": "",
            "website": "",
            "country": "",
            "hidden": hidden,
        })

    assert other_session.get(f"{DOJO_URL}/hacker/{user_id}").status_code == 200

    response = settings_patch("True")
    assert response.status_code == 200, response.text[:200]
    assert session.get(f"{API}/users/me").json()["hidden"] is True
    assert other_session.get(f"{DOJO_URL}/hacker/{user_id}").status_code == 404, "hidden profiles 404 for other users"

    response = settings_patch("False")
    assert response.status_code == 200, response.text[:200]
    assert session.get(f"{API}/users/me").json()["hidden"] is False, "the settings form must be able to unhide"
    assert other_session.get(f"{DOJO_URL}/hacker/{user_id}").status_code == 200


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


def test_admin_dojos_page_is_reachable(admin_session):
    response = admin_session.get(f"{DOJO_URL}/admin/dojos")
    assert response.status_code == 200, response.status_code

    anonymous = anonymous_session()
    response = anonymous.get(f"{DOJO_URL}/admin/dojos", allow_redirects=False)
    assert response.status_code == 302, response.status_code
    assert "/login" in response.headers["Location"], response.headers["Location"]


def test_admin_menu_entries_have_routes(admin_session):
    targets = json.loads(flask_exec(
        "import json\n"
        "from CTFd.plugins import get_admin_plugin_menu_bar\n"
        "print(json.dumps([entry.route for entry in get_admin_plugin_menu_bar()]))\n"
    ))
    assert targets, "the plugin must register at least one admin menu entry"
    for target in targets:
        response = admin_session.get(f"{DOJO_URL}{target}")
        assert response.status_code != 404, f"the registered admin menu entry must resolve to a view: {target}"


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
        + imported_challenge("visible-one", "Visible One", "apple")
        + "      - id: future-one\n"
        "        name: Future One\n"
        "        visibility:\n"
        "          start: '2099-01-01T00:00:00Z'\n"
        "        import:\n"
        "          dojo: example\n"
        "          module: hello\n"
        "          challenge: banana\n"
    )
    dojo = create_dojo_yml(spec, session=admin_session)
    name, session = register_user()
    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 200

    solve_challenge_offline(dojo, "window", "visible-one", session=session, user=name)
    future_id = challenge_db_id(dojo, "window", "future-one")
    assert attempt(session, future_id, challenge_flag(dojo, "window", "future-one", user=name)
                   ).json()["data"]["status"] == "correct"

    counts = flask_exec(
        "from CTFd.plugins.dojo_plugin.models import Dojos\n"
        "from CTFd.models import Users\n"
        f"dojo = Dojos.from_id({dojo!r}).first()\n"
        f"user = Users.query.filter_by(name={name!r}).first()\n"
        "module = dojo.modules[0]\n"
        "solved = module.solves(user=user, ignore_admins=False).count()\n"
        "print(solved, len(module.visible_challenges(required_only=True)))\n"
    ).strip()
    solved, visible_required = (int(value) for value in counts.split())

    assert session.get(f"{DOJO_URL}/{dojo}").status_code == 200
    assert visible_required == 1, counts
    assert solved <= visible_required, f"module progress must not render more solves than challenges: {counts}"


def test_dojo_page_theme_assets_resolve(flows_dojo, random_user_session):
    page = random_user_session.get(f"{DOJO_URL}/{flows_dojo}")
    assert page.status_code == 200

    assets = set(re.findall(r'(?:src|href)="([^"]*/themes/dojo_theme/static/[^"]+)"', page.text))
    assert assets, "the dojo page references theme assets"
    broken = [asset for asset in sorted(assets)
              if random_user_session.get(f"{DOJO_URL}{asset.replace('&amp;', '&')}").status_code != 200]
    assert not broken, f"every theme asset referenced by the dojo page must load: {broken}"


def test_stat_dashboard_payload_shape(flows_dojo, flows_solver):
    _, session = flows_solver
    cache_key = f"stats:dojo:{flows_dojo}"

    deadline = time.time() + 25
    while time.time() < deadline and not redis_get(cache_key):
        wait_for_background_worker(timeout=5)
        time.sleep(1)

    stats = redis_get(cache_key)
    assert stats, f"solving in a dojo must populate {cache_key}"
    chart = stats["chart_data"]
    assert len(chart["labels"]) == 4, chart
    assert len(chart["solves"]) == 4 and len(chart["users"]) == 4, chart
    assert set(stats["trends"]) == {"solves", "users", "active", "challenges"}, stats["trends"]
    assert all(isinstance(value, int) for value in stats["trends"].values()), stats["trends"]
    assert stats["recent_solves"], stats
    for solve in stats["recent_solves"]:
        assert solve["challenge_name"], solve
        assert solve["date_display"], solve

    redis_del(cache_key)
    skeleton = flask_exec(
        "from CTFd.plugins.dojo_plugin.utils.stats import get_dojo_stats\n"
        "from CTFd.plugins.dojo_plugin.models import Dojos\n"
        f"stats = get_dojo_stats(Dojos.from_id({flows_dojo!r}).first())\n"
        "print(stats['chart_data'], stats['recent_solves'], stats['trends'], stats['solves'])\n"
    )
    assert "'labels': []" in skeleton and "'solves': []" in skeleton, skeleton
    assert session.get(f"{DOJO_URL}/{flows_dojo}").status_code == 200, "a cache miss still renders the dojo page"


def test_scoreboard_url_shapes(flows_dojo, flows_solver):
    name, session = flows_solver

    for path in [f"{flows_dojo}/_/30/1", f"{flows_dojo}/flows/30/1"]:
        deadline = time.time() + 40
        body = {}
        while time.time() < deadline:
            wait_for_background_worker(timeout=5)
            response = session.get(f"{API}/scoreboard/{path}")
            assert response.status_code == 200, path
            body = response.json()
            if any(entry["name"] == name for entry in body["standings"]):
                break
            time.sleep(1)

        assert isinstance(body["standings"], list), body
        assert isinstance(body["pages"], list), body
        assert body["standings"], f"a dojo with solves has standings at {path}"
        for entry in body["standings"]:
            assert {"rank", "name", "solves", "belt", "symbol", "url", "badges"} <= set(entry), entry
        assert body["me"]["name"] == name, f"a listed solver gets a 'me' entry at {path}: {body}"

    for path, mode in [(f"{flows_dojo}/_/crews/30/1", "cumulative"), (f"{flows_dojo}/flows/crews/30/1", "unique")]:
        response = session.get(f"{API}/scoreboard/{path}", params={"mode": mode})
        assert response.status_code == 200, path
        body = response.json()
        assert isinstance(body["standings"], list), body
        assert isinstance(body["pages"], list), body
        assert body["mode"] == mode, body
        if not body["standings"]:
            assert body["board_empty"] is False, "the crew board reports emptiness separately from an empty dojo"
        for crew in body["standings"]:
            assert crew["tag"] and crew["key"], crew
            assert crew["members"], crew
            for member in crew["members"]:
                assert member["belt"] and member["symbol"] and member["name"], member


def test_course_identity_uses_the_warning_channel(course_flow_dojo):
    name, session = register_user()
    user_id = get_user_id(name)
    dojo_id = dojo_db_id(course_flow_dojo)

    def identity_rows():
        return db_sql(
            f"SELECT type, token FROM dojo_users WHERE user_id = {user_id} AND dojo_id = {dojo_id}"
        ).strip()

    response = session.patch(f"{DOJO_URL}/dojo/{course_flow_dojo}/course/identity",
                             json={"identity": "cf-roster-token"})
    assert response.status_code == 200, response.text[:200]
    assert response.json() == {"success": True}, "an on-roster identity reports plain success"
    assert identity_rows() == "student|cf-roster-token", identity_rows()

    response = session.patch(f"{DOJO_URL}/dojo/{course_flow_dojo}/course/identity",
                             json={"identity": "not-on-the-roster"})
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert body["success"] is True, body
    assert "error" not in body, "an off-roster identity is a warning, not an error"
    assert "ASURITE" in body["warning"], body
    assert identity_rows() == "student|not-on-the-roster", "re-identifying replaces the token in place"


def test_course_discord_endpoints_without_a_linked_account(course_flow_dojo):
    name, session = register_user()

    for resource in ["memes", "thanks"]:
        response = session.get(f"{API}/discord/course/{course_flow_dojo}/{resource}")
        assert response.status_code == 200, response.text[:200]
        body = response.json()
        assert body["success"] is False, body
        assert body["error"] == "Discord not linked", body
        assert resource not in body, f"the grade script receives no {resource} count when Discord is unlinked: {body}"

    assert session.get(f"{DOJO_URL}/dojo/{course_flow_dojo}/course").status_code == 200
