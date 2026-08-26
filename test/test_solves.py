import random
import re
import string

import pytest
import requests

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    challenge_db_id,
    challenge_flag,
    create_dojo_yml,
    db_sql,
    get_user_id,
    login,
    parse_csrf_token,
    redis_cli,
    remove_workspace_container,
    start_challenge,
    wait_for_background_worker,
    workspace_run,
)

API = f"{DOJO_URL}/pwncollege_api/v1"
CLI_AUTH_PREFIX = "sk-workspace-local-"


def random_id(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def register_user():
    name = random_id(16)
    return name, login(name, name, register=True)


def anonymous_session():
    session = requests.Session()
    session.headers["CSRF-Token"] = parse_csrf_token(session.get(f"{DOJO_URL}/login").text)
    return session


def solve_post(session, dojo, module, challenge, submission):
    return session.post(f"{API}/dojos/{dojo}/{module}/{challenge}/solve", json={"submission": submission})


def submission_counts(user_name, challenge_id):
    rows = db_sql(
        f"SELECT type, count(*) FROM submissions "
        f"WHERE user_id = {get_user_id(user_name)} AND challenge_id = {challenge_id} GROUP BY type"
    )
    return {line.split("|")[0]: int(line.split("|")[1]) for line in rows.strip().splitlines() if line}


def submission_total(challenge_id):
    return int(db_sql(f"SELECT count(*) FROM submissions WHERE challenge_id = {challenge_id}"))


def clear_score_validate_ratelimit():
    keys = redis_cli(
        "--scan",
        "--pattern", "flask_cache_rl:*:pwncollege_api.score_validate_user",
    ).stdout.split()
    for key in keys:
        redis_cli("DEL", key)


def score_validate(username=None, email=None):
    params = {}
    if username is not None:
        params["username"] = username
    if email is not None:
        params["email"] = email
    return requests.get(f"{API}/score/validate", params=params)


@pytest.fixture(scope="module")
def unofficial_public_dojo(admin_session):
    spec = open(TEST_DOJOS_LOCATION / "solves_dojo.yml").read().replace(
        "solves-test-dojo", f"solves-test-dojo-{random_id()}"
    )
    return create_dojo_yml(spec, session=admin_session)


def test_workspace_flag_matches_derived_flag_and_records_one_solve(example_dojo, random_user):
    name, session = random_user
    challenge_id = challenge_db_id(example_dojo, "hello", "apple")
    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        container_flag = workspace_run("cat /flag", user=name, root=True).stdout.strip()
        assert container_flag == challenge_flag(example_dojo, "hello", "apple", user=name), \
            "challenge_flag() must derive exactly the flag the workspace container was given"

        response = solve_post(session, example_dojo, "hello", "apple", container_flag)
        assert response.status_code == 200, response.text[:200]
        assert response.json() == {"success": True, "status": "solved"}, response.json()
        assert submission_counts(name, challenge_id) == {"correct": 1}, \
            "a correct flag must create exactly one correct submission"
    finally:
        remove_workspace_container(name)


def test_solve_incorrect_flag_records_only_a_failed_submission(example_dojo, random_user):
    name, session = random_user
    challenge_id = challenge_db_id(example_dojo, "hello", "apple")

    response = solve_post(session, example_dojo, "hello", "apple", "pwn.college{totallybogus}")
    assert response.status_code == 400, response.text[:200]
    assert response.json() == {"success": False, "status": "incorrect"}, response.json()
    assert submission_counts(name, challenge_id) == {"incorrect": 1}, \
        "a wrong flag must record one incorrect submission and no solve"


def test_solve_accepts_wrapped_bare_and_padded_flag_forms(example_dojo):
    name, session = register_user()

    def token_of(module, challenge):
        flag = challenge_flag(example_dojo, module, challenge, user=name)
        match = re.fullmatch(r"pwn\.college\{(.*)\}", flag)
        assert match, f"unexpected flag format: {flag}"
        return flag, match.group(1)

    apple_flag, apple_token = token_of("hello", "apple")
    _, banana_token = token_of("hello", "banana")
    _, earth_token = token_of("world", "earth")

    variants = [
        ("hello", "apple", f"  {apple_flag}\n"),
        ("hello", "banana", banana_token),
        ("world", "earth", f"ctf{{{earth_token}}}"),
    ]
    for module, challenge, submission in variants:
        response = solve_post(session, example_dojo, module, challenge, submission)
        assert response.status_code == 200, f"{submission!r}: {response.text[:200]}"
        assert response.json() == {"success": True, "status": "solved"}, \
            f"flag form {submission!r} should have been accepted: {response.json()}"

    assert apple_token != banana_token, "flags must be per-challenge"


def test_practice_flag_is_not_a_valid_submission(example_dojo, random_user):
    name, session = random_user
    challenge_id = challenge_db_id(example_dojo, "hello", "apple")
    try:
        start_challenge(example_dojo, "hello", "apple", practice=True, session=session)
        container_flag = workspace_run("cat /flag", user=name, root=True).stdout.strip()
        assert container_flag == "pwn.college{practice}", \
            f"practice containers must not receive a real flag, got {container_flag}"

        response = solve_post(session, example_dojo, "hello", "apple", container_flag)
        assert response.status_code == 400, response.text[:200]
        assert response.json() == {"success": False, "status": "incorrect"}, response.json()
        assert submission_counts(name, challenge_id).get("correct", 0) == 0, \
            "the practice flag must never register a solve"
    finally:
        remove_workspace_container(name)


def test_solve_rejects_another_users_flag(example_dojo):
    name_a, _ = register_user()
    name_b, session_b = register_user()
    challenge_id = challenge_db_id(example_dojo, "hello", "apple")
    flag_a = challenge_flag(example_dojo, "hello", "apple", user=name_a)

    response = solve_post(session_b, example_dojo, "hello", "apple", flag_a)
    assert response.status_code == 400, response.text[:200]
    assert response.json() == {"success": False, "status": "incorrect"}, response.json()
    assert submission_counts(name_b, challenge_id) == {"incorrect": 1}, \
        "submitting someone else's flag must not solve the challenge"
    assert submission_counts(name_a, challenge_id) == {}, \
        "the flag's owner must not be credited for a submission they never made"


def test_solve_rejects_a_flag_for_a_different_challenge(example_dojo, random_user):
    name, session = random_user
    apple_id = challenge_db_id(example_dojo, "hello", "apple")
    banana_id = challenge_db_id(example_dojo, "hello", "banana")
    apple_flag = challenge_flag(example_dojo, "hello", "apple", user=name)

    response = solve_post(session, example_dojo, "hello", "banana", apple_flag)
    assert response.status_code == 400, response.text[:200]
    assert response.json() == {"success": False, "status": "incorrect"}, response.json()
    assert submission_counts(name, banana_id).get("correct", 0) == 0
    assert submission_counts(name, apple_id).get("correct", 0) == 0, \
        "a misdirected flag must not solve the challenge it was minted for either"


def test_already_solved_short_circuits_flag_validation(example_dojo, random_user):
    name, session = random_user
    challenge_id = challenge_db_id(example_dojo, "hello", "apple")
    flag = challenge_flag(example_dojo, "hello", "apple", user=name)

    assert solve_post(session, example_dojo, "hello", "apple", flag).json() == \
        {"success": True, "status": "solved"}

    duplicate = solve_post(session, example_dojo, "hello", "apple", flag)
    assert duplicate.status_code == 200, duplicate.text[:200]
    assert duplicate.json() == {"success": True, "status": "already_solved"}, duplicate.json()

    bogus = solve_post(session, example_dojo, "hello", "apple", "pwn.college{garbage}")
    assert bogus.status_code == 200, bogus.text[:200]
    assert bogus.json() == {"success": True, "status": "already_solved"}, bogus.json()

    assert submission_counts(name, challenge_id) == {"correct": 1}, \
        "resubmitting after a solve must not record extra submissions"


def test_solve_requires_authentication(example_dojo):
    challenge_id = challenge_db_id(example_dojo, "hello", "apple")
    before = submission_total(challenge_id)

    bare = requests.post(f"{API}/dojos/{example_dojo}/hello/apple/solve", json={"submission": "x"})
    assert bare.status_code == 403, bare.text[:200]

    csrf_valid = solve_post(anonymous_session(), example_dojo, "hello", "apple", "x")
    assert csrf_valid.status_code == 403, csrf_valid.text[:200]

    assert submission_total(challenge_id) == before, \
        "unauthenticated submissions must not be recorded"


def test_solve_missing_submission_is_rejected(example_dojo, random_user):
    _, session = random_user
    response = session.post(f"{API}/dojos/{example_dojo}/hello/apple/solve", json={})
    assert response.status_code == 400, response.text[:200]
    assert response.json()["success"] is False, response.json()

    response = session.post(f"{API}/dojos/{example_dojo}/hello/apple/solve", json={"submission": 1337})
    assert response.status_code == 400, response.text[:200]
    assert response.json()["success"] is False, response.json()


def test_solve_unknown_dojo_module_or_challenge_is_404(example_dojo, random_user):
    _, session = random_user
    for path in [
        f"{API}/dojos/nope-nope-nope/hello/apple/solve",
        f"{API}/dojos/{example_dojo}/no-such-module/apple/solve",
        f"{API}/dojos/{example_dojo}/hello/does-not-exist/solve",
    ]:
        response = session.post(path, json={"submission": "x"})
        assert response.status_code == 404, f"{path}: {response.status_code} {response.text[:200]}"

    response = session.post(f"{API}/dojos/{example_dojo}/hello/does-not-exist/solve", json={"submission": "x"})
    assert response.json()["success"] is False, response.json()
    assert "not found" in response.json()["error"].lower(), response.json()


def test_solve_private_dojo_is_404_until_the_user_joins(random_private_dojo):
    name, session = register_user()
    url = f"{API}/dojos/{random_private_dojo}/test-module/test-challenge/solve"

    response = session.post(url, json={"submission": "x"})
    assert response.status_code == 404, \
        f"non-members must not be able to reach a private dojo's solve endpoint: {response.text[:200]}"

    assert session.get(f"{DOJO_URL}/dojo/{random_private_dojo}/join/").status_code == 200

    response = session.post(url, json={"submission": "x"})
    assert response.status_code == 400, response.text[:200]
    assert response.json() == {"success": False, "status": "incorrect"}, response.json()

    flag = challenge_flag(random_private_dojo, "test-module", "test-challenge", user=name)
    response = session.post(url, json={"submission": flag})
    assert response.status_code == 200, response.text[:200]
    assert response.json() == {"success": True, "status": "solved"}, response.json()


def test_solve_invisible_challenge_is_404_even_for_admins(visibility_test_dojo, admin_session):
    name, session = register_user()
    assert session.get(f"{DOJO_URL}/dojo/{visibility_test_dojo}/join/").status_code == 200

    hidden_url = f"{API}/dojos/{visibility_test_dojo}/module2/challenge-b/solve"
    hidden_flag = challenge_flag(visibility_test_dojo, "module2", "challenge-b", user=name)

    response = session.post(hidden_url, json={"submission": hidden_flag})
    assert response.status_code == 404, \
        f"an unreleased challenge must not be solvable: {response.text[:200]}"

    admin_response = admin_session.post(hidden_url, json={"submission": "x"})
    assert admin_response.status_code == 404, \
        f"the solve endpoint has no admin bypass for visibility: {admin_response.text[:200]}"

    visible_response = session.post(
        f"{API}/dojos/{visibility_test_dojo}/module2/challenge-c/solve", json={"submission": "x"}
    )
    assert visible_response.status_code == 400, visible_response.text[:200]
    assert visible_response.json() == {"success": False, "status": "incorrect"}, visible_response.json()

    assert submission_counts(name, challenge_db_id(visibility_test_dojo, "module2", "challenge-b")) == {}, \
        "a 404 from an invisible challenge must not record a submission"


def test_first_solver_of_a_challenge_gets_first_blood(unofficial_public_dojo):
    name_a, session_a = register_user()
    name_b, session_b = register_user()

    for name, session in [(name_a, session_a), (name_b, session_b)]:
        flag = challenge_flag(unofficial_public_dojo, "solves-module", "first-blood-challenge", user=name)
        response = solve_post(session, unofficial_public_dojo, "solves-module", "first-blood-challenge", flag)
        assert response.status_code == 200, response.text[:200]
        assert response.json() == {"success": True, "status": "solved"}, response.json()

    wait_for_background_worker(timeout=2)

    response = requests.get(f"{API}/feed/events", params={"limit": 100})
    assert response.status_code == 200, response.text[:200]
    solves = {
        event["user_name"]: event
        for event in response.json()["data"]
        if event["type"] == "challenge_solve" and event["data"]["challenge_id"] == "first-blood-challenge"
    }

    assert name_a in solves, f"no challenge_solve feed event for the first solver: {solves.keys()}"
    assert name_b in solves, f"no challenge_solve feed event for the second solver: {solves.keys()}"
    assert solves[name_a]["data"]["first_blood"] is True, solves[name_a]["data"]
    assert solves[name_b]["data"]["first_blood"] is False, solves[name_b]["data"]
    assert solves[name_a]["data"]["dojo_id"] == unofficial_public_dojo, solves[name_a]["data"]


def test_score_counts_only_official_dojo_solves(example_dojo, unofficial_public_dojo):
    name, session = register_user()

    unofficial_flag = challenge_flag(unofficial_public_dojo, "solves-module", "unofficial-challenge", user=name)
    response = solve_post(session, unofficial_public_dojo, "solves-module", "unofficial-challenge", unofficial_flag)
    assert response.status_code == 200, response.text[:200]

    response = requests.get(f"{API}/score", params={"username": name})
    assert response.status_code == 400, response.text[:200]
    assert response.json()["error"] == "user is not ranked", response.json()

    official_flag = challenge_flag(example_dojo, "hello", "apple", user=name)
    assert solve_post(session, example_dojo, "hello", "apple", official_flag).status_code == 200

    response = requests.get(f"{API}/score", params={"username": name})
    assert response.status_code == 200, response.text[:200]
    score = response.json()
    fields = score.split(":")
    assert len(fields) == 6, f"unexpected score format: {score}"
    rank, solves, max_score, solved, chall_count, user_count = (int(field) for field in fields)
    assert solves == 1, f"only the official solve should count, got {score}"
    assert solved == solves and max_score == chall_count, score
    assert rank >= 1 and user_count >= 1, score
    assert max_score >= 1, score


def test_score_requires_a_known_user():
    response = requests.get(f"{API}/score")
    assert response.status_code == 400, response.text[:200]
    assert "username" in response.json()["error"], response.json()

    response = requests.get(f"{API}/score", params={"username": f"nosuchuser-{random_id(12)}"})
    assert response.status_code == 400, response.text[:200]
    assert response.json()["error"] == "user does not exist", response.json()


def test_score_validate_matches_name_and_email_of_visible_users():
    clear_score_validate_ratelimit()
    name = random_id(16)
    email = f"{name}@example.com"
    login(name, name, register=True, email=email)

    assert score_validate(name, email).json() == 1, "an exact name/email pair must validate"
    assert score_validate(name, f"other-{email}").json() == 0, "a wrong email must not validate"
    assert score_validate(f"nosuchuser-{random_id(12)}", email).json() == 0, \
        "a nonexistent username must not validate"

    for params in [{}, {"username": name}, {"email": email}]:
        response = requests.get(f"{API}/score/validate", params=params)
        assert response.status_code == 400, f"{params}: {response.text[:200]}"
        assert "username" in response.json()["error"] and "email" in response.json()["error"], \
            response.json()

    db_sql(f"UPDATE users SET hidden = true WHERE id = {get_user_id(name)}")
    assert score_validate(name, email).json() == 0, "hidden users must not be validatable"


def test_score_validate_is_ratelimited():
    clear_score_validate_ratelimit()
    name = f"nosuchuser-{random_id(12)}"
    statuses = [score_validate(name, f"{name}@example.com").status_code for _ in range(11)]
    assert statuses[:10] == [200] * 10, statuses
    assert statuses[10] == 429, statuses

    response = score_validate(name, f"{name}@example.com")
    assert response.status_code == 429, response.text[:200]
    assert response.json()["code"] == 429, response.json()
    clear_score_validate_ratelimit()


def test_solve_cli_token_is_scoped_to_the_running_container(example_dojo):
    name, session = register_user()
    apple_id = challenge_db_id(example_dojo, "hello", "apple")
    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        token = workspace_run("printenv DOJO_AUTH_TOKEN", user=name).stdout.strip()
        assert token.startswith(CLI_AUTH_PREFIX), f"unexpected cli token: {token[:32]}"
        headers = {"Authorization": f"Bearer {token}"}

        garbage = requests.post(
            f"{API}/dojos/{example_dojo}/hello/apple/solve",
            json={"submission": "pwn.college{nope}"},
            headers={"Authorization": f"Bearer {CLI_AUTH_PREFIX}garbage"},
        )
        assert garbage.status_code == 401, garbage.text[:200]
        assert garbage.json()["success"] is False, garbage.json()

        non_cli = requests.post(
            f"{API}/dojos/{example_dojo}/hello/apple/solve",
            json={"submission": "pwn.college{nope}"},
            headers={"Authorization": "Bearer not-a-dojo-token"},
        )
        assert non_cli.status_code == 403, non_cli.text[:200]

        wrong_flag = requests.post(
            f"{API}/dojos/{example_dojo}/hello/apple/solve",
            json={"submission": "pwn.college{nope}"}, headers=headers,
        )
        assert wrong_flag.status_code == 400, wrong_flag.text[:200]
        assert wrong_flag.json() == {"success": False, "status": "incorrect"}, wrong_flag.json()

        real_flag = challenge_flag(example_dojo, "hello", "apple", user=name)
        solved = requests.post(
            f"{API}/dojos/{example_dojo}/hello/apple/solve",
            json={"submission": real_flag}, headers=headers,
        )
        assert solved.status_code == 200, solved.text[:200]
        assert solved.json() == {"success": True, "status": "solved"}, solved.json()
        assert submission_counts(name, apple_id) == {"correct": 1, "incorrect": 1}, \
            "the cli token path must record submissions for the token's own user"

        start_challenge(example_dojo, "hello", "banana", session=session)
        stale = requests.post(
            f"{API}/dojos/{example_dojo}/hello/banana/solve",
            json={"submission": "pwn.college{nope}"}, headers=headers,
        )
        assert stale.status_code == 403, stale.text[:200]
        assert "active challenge container" in stale.json()["error"], stale.json()

        remove_workspace_container(name)
        containerless = requests.post(
            f"{API}/dojos/{example_dojo}/hello/banana/solve",
            json={"submission": "pwn.college{nope}"}, headers=headers,
        )
        assert containerless.status_code == 403, containerless.text[:200]
        assert "No active challenge container" in containerless.json()["error"], containerless.json()

        assert submission_counts(name, challenge_db_id(example_dojo, "hello", "banana")) == {}, \
            "a rejected cli token must not record a submission"
    finally:
        remove_workspace_container(name)
