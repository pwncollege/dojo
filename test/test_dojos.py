import subprocess
import concurrent.futures
import json
import re
import requests
import random
import shutil
import string
import threading
import time
import yaml

from utils import DOJO_CONTAINER, TEST_DOJOS_LOCATION, DOJO_URL, create_dojo_yml, start_challenge, solve_challenge, workspace_run, login, db_sql, dojo_run, get_user_id, make_dojo_official, wait_for_background_worker


TRANSFER_TEST_IMAGE = "pwncollege-challenge"


def get_dojo_modules(dojo):
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/modules")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    return response.json()["modules"]


def transfer_dojo_spec(dojo_id, resources):
    return {
        "id": dojo_id,
        "name": dojo_id.replace("-", " ").title(),
        "type": "public",
        "modules": [{
            "id": "module",
            "name": "Module",
            "resources": [
                {
                    "type": "challenge",
                    "id": resource["id"],
                    "name": resource["id"].replace("-", " ").title(),
                    "image": TRANSFER_TEST_IMAGE,
                    **({"transfer": resource["transfer"]} if resource.get("transfer") else {}),
                }
                for resource in resources
            ],
        }],
    }


def create_transfer_dojo(dojo_id, resources, admin_session):
    return create_dojo_yml(
        yaml.safe_dump(transfer_dojo_spec(dojo_id, resources), sort_keys=False),
        session=admin_session,
    )


def grant_dojo_admin(dojo, user_name, user_session, admin_session):
    assert user_session.get(f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 200
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/admins/promote",
        json={"user_id": get_user_id(user_name)},
    )
    assert response.status_code == 200, response.text


def update_transfer_dojo(dojo, spec, session):
    return session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update",
        json=spec,
        timeout=30,
    )


def promote_dojo_request(dojo, session):
    return session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/promote",
        json={},
        timeout=30,
    )


def dojo_database_id(dojo):
    return int.from_bytes(
        bytes.fromhex(dojo.rsplit("~", 1)[1]),
        "big",
        signed=True,
    )


def transfer_cache_snapshot(dojo_modules, user_ids, *, warm=False, timestamps=None):
    script = f"""
import json

from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import Dojos, DojoModules
from CTFd.plugins.dojo_plugin.utils.background_stats import (
    get_cached_stat,
    get_cache_updated_at,
    set_cached_stat,
)
from CTFd.plugins.dojo_plugin.utils.crews import aggregate_crews
from CTFd.plugins.dojo_plugin.worker.handlers.activity import calculate_activity
from CTFd.plugins.dojo_plugin.worker.handlers.awards import (
    CACHE_KEY_BELTS,
    CACHE_KEY_EMOJIS,
    calculate_belts,
    calculate_emojis,
)
from CTFd.plugins.dojo_plugin.worker.handlers.dojo_stats import calculate_dojo_stats
from CTFd.plugins.dojo_plugin.worker.handlers.scoreboard import (
    COMMON_DURATIONS,
    calculate_challenge_solves,
    calculate_member_challenges,
    calculate_scoreboard,
    challenge_solves_cache_key,
)
from CTFd.plugins.dojo_plugin.worker.handlers.scores import (
    calculate_dojo_scores,
    calculate_module_scores,
    dojo_scores_cache_key,
    module_scores_cache_key,
)

dojo_modules = {dojo_modules!r}
user_ids = {tuple(user_ids)!r}
warm = {warm!r}
expected_timestamps = {timestamps!r}

def normalized(value):
    return json.loads(json.dumps(value, sort_keys=True))

expected = {{}}

def record(key, value):
    expected[key] = normalized(value)

for dojo_id, module_indexes in dojo_modules.items():
    dojo = Dojos.query.filter_by(dojo_id=dojo_id).one()
    record(f"stats:dojo:{{dojo.reference_id}}", calculate_dojo_stats(dojo))
    for duration in COMMON_DURATIONS:
        scoreboard = calculate_scoreboard(dojo, duration)
        member_challenges = calculate_member_challenges(
            dojo,
            duration,
            scoreboard,
        )
        record(f"stats:scoreboard:dojo:{{dojo_id}}:{{duration}}", scoreboard)
        record(
            f"stats:crews:dojo:{{dojo_id}}:{{duration}}",
            aggregate_crews(scoreboard, member_challenges),
        )
    record(dojo_scores_cache_key(dojo_id), calculate_dojo_scores(dojo_id))
    for module_index in module_indexes:
        module = DojoModules.query.get((dojo_id, module_index))
        assert module is not None
        for duration in COMMON_DURATIONS:
            scoreboard = calculate_scoreboard(module, duration)
            member_challenges = calculate_member_challenges(
                module,
                duration,
                scoreboard,
            )
            record(
                f"stats:scoreboard:module:{{dojo_id}}:{{module_index}}:{{duration}}",
                scoreboard,
            )
            record(
                f"stats:crews:module:{{dojo_id}}:{{module_index}}:{{duration}}",
                aggregate_crews(scoreboard, member_challenges),
            )
        record(
            challenge_solves_cache_key(dojo_id, module_index),
            calculate_challenge_solves(module),
        )
        record(
            module_scores_cache_key(dojo_id, module_index),
            calculate_module_scores(dojo_id, module_index),
        )

for user_id in user_ids:
    record(f"stats:activity:{{user_id}}", calculate_activity(user_id))

record(CACHE_KEY_BELTS, calculate_belts())
record(CACHE_KEY_EMOJIS, calculate_emojis())

if warm:
    for key, value in expected.items():
        set_cached_stat(key, value)

actual = {{key: get_cached_stat(key) for key in expected}}
mismatches = {{
    key: {{"actual": actual[key], "expected": expected[key]}}
    for key in expected
    if actual[key] != expected[key]
}}
current_timestamps = {{key: get_cache_updated_at(key) for key in expected}}
timestamp_mismatches = {{}}
if expected_timestamps is not None:
    timestamp_mismatches = {{
        key: {{
            "actual": current_timestamps[key],
            "expected": expected_timestamps[key],
        }}
        for key in expected
        if current_timestamps[key] != expected_timestamps[key]
    }}

print("TRANSFER_CACHE_SNAPSHOT=" + json.dumps({{
    "mismatches": mismatches,
    "timestamp_mismatches": timestamp_mismatches,
    "timestamps": current_timestamps,
}}, sort_keys=True))
"""
    result = dojo_run("dojo", "flask", input=f"exec({script!r})\n")
    marker = "TRANSFER_CACHE_SNAPSHOT="
    marker_index = result.stdout.rfind(marker)
    assert marker_index != -1, result.stdout
    output = result.stdout[marker_index + len(marker):].splitlines()[0]
    return json.loads(output)


def warm_transfer_caches(dojo_modules, user_ids=()):
    wait_for_background_worker(timeout=30)
    snapshot = transfer_cache_snapshot(dojo_modules, user_ids, warm=True)
    assert snapshot["mismatches"] == {}
    return snapshot["timestamps"]


def assert_transfer_caches_match_database(
    dojo_modules,
    user_ids=(),
    *,
    timestamps=None,
    timeout=30,
):
    deadline = time.monotonic() + timeout
    while True:
        snapshot = transfer_cache_snapshot(
            dojo_modules,
            user_ids,
            timestamps=timestamps,
        )
        if (
            not snapshot["mismatches"] and
            not snapshot["timestamp_mismatches"]
        ):
            return
        if time.monotonic() >= deadline:
            raise AssertionError(snapshot)
        time.sleep(0.1)


def delete_dojo_request(dojo, session):
    return session.post(
        f"{DOJO_URL}/dojo/{dojo}/delete/",
        json={"dojo": dojo},
        timeout=30,
    )


def dojo_challenge_rows(dojo):
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    rows = db_sql(
        "SELECT name, id FROM challenges "
        f"WHERE type = 'dojo' AND category = '{dojo_hex_id}' ORDER BY name"
    )
    return {
        name: int(challenge_id)
        for name, challenge_id in (
            row.split("|", 1)
            for row in rows.splitlines()
            if row
        )
    }


def coordinate_challenge_rows(dojo, coordinate):
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    module_id, challenge_id = coordinate
    rows = db_sql(
        "SELECT type, id FROM challenges "
        f"WHERE category = '{dojo_hex_id}' "
        f"AND name = '{module_id}:{challenge_id}' ORDER BY type, id"
    )
    return {
        (challenge_type, int(database_id))
        for challenge_type, database_id in (
            row.split("|", 1)
            for row in rows.splitlines()
            if row
        )
    }


def dojo_logical_challenge_rows(dojo):
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    rows = db_sql(
        "SELECT dm.id, dc.id, dc.challenge_id "
        "FROM dojo_challenges dc "
        "JOIN dojo_modules dm "
        "ON dm.dojo_id = dc.dojo_id "
        "AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = x'{dojo_hex_id}'::int "
        "ORDER BY dm.id, dc.id"
    )
    return {
        f"{module_id}:{challenge_id}": int(database_challenge_id)
        for module_id, challenge_id, database_challenge_id in (
            row.split("|", 2)
            for row in rows.splitlines()
            if row
        )
    }


def challenge_flag_ids(challenge_id):
    rows = db_sql(
        f"SELECT id FROM flags WHERE challenge_id = {challenge_id} ORDER BY id"
    )
    return tuple(int(row) for row in rows.splitlines() if row)


def challenge_solve_ids(challenge_id):
    rows = db_sql(
        "SELECT id FROM submissions "
        f"WHERE type = 'correct' AND challenge_id = {challenge_id} ORDER BY id"
    )
    return tuple(int(row) for row in rows.splitlines() if row)


def challenge_transfer_provenance(challenge_id):
    row = db_sql(
        "SELECT module_id, dojo_challenge_id, data ->> 'version', "
        "data -> 'transfer' ->> 'module', data -> 'transfer' ->> 'challenge' "
        "FROM dojo_challenge_transfer_provenances "
        f"WHERE challenge_id = {challenge_id}"
    ).strip()
    return tuple(row.split("|")) if row else None


def challenge_transfer_source_dojo_id(challenge_id):
    return db_sql(
        "SELECT COALESCE(data -> 'transfer' ->> 'dojo_id', 'NULL') "
        "FROM dojo_challenge_transfer_provenances "
        f"WHERE challenge_id = {challenge_id}"
    ).strip()


def create_challenge_type_collision(dojo, coordinate, challenge_type, user_id):
    assert challenge_type in {"standard", "dynamic"}
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    module_id, challenge_id = coordinate
    database_id = int(db_sql(
        "INSERT INTO challenges (type, category, name, state) "
        f"VALUES ('{challenge_type}', '{dojo_hex_id}', "
        f"'{module_id}:{challenge_id}', 'visible') RETURNING id"
    ).strip())
    db_sql(
        "INSERT INTO flags (type, challenge_id, content) "
        f"VALUES ('static', {database_id}, 'collision-{database_id}')"
    )
    db_sql(
        "INSERT INTO submissions "
        "(type, challenge_id, user_id, ip, provided, date) "
        f"VALUES ('correct', {database_id}, {user_id}, "
        "'127.0.0.1', 'collision', NOW())"
    )
    return database_id


def add_challenge_flag_and_solve(challenge_id, user_id, label):
    flag_id = int(db_sql(
        "INSERT INTO flags (type, challenge_id, content) "
        f"VALUES ('static', {challenge_id}, '{label}') RETURNING id"
    ).strip())
    solve_id = int(db_sql(
        "INSERT INTO submissions "
        "(type, challenge_id, user_id, ip, provided, date) "
        f"VALUES ('correct', {challenge_id}, {user_id}, "
        f"'127.0.0.1', '{label}', NOW()) RETURNING id"
    ).strip())
    return flag_id, solve_id


def create_same_type_challenge_duplicate(dojo, coordinate, user_id, label):
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    module_id, challenge_id = coordinate
    database_id = int(db_sql(
        "INSERT INTO challenges (type, category, name, state) "
        f"VALUES ('dojo', '{dojo_hex_id}', "
        f"'{module_id}:{challenge_id}', 'visible') RETURNING id"
    ).strip())
    flag_id, solve_id = add_challenge_flag_and_solve(
        database_id,
        user_id,
        label,
    )
    return database_id, flag_id, solve_id


def create_challenge_dependents(dojo, challenge_id, user_id, label):
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    pointer_id = int(db_sql(
        "INSERT INTO challenges (type, category, name, state, next_id) "
        f"VALUES ('standard', 'duplicate-regression', '{label}', "
        f"'hidden', {challenge_id}) RETURNING id"
    ).strip())
    hint_id = int(db_sql(
        "INSERT INTO hints (type, challenge_id, content, cost) "
        f"VALUES ('standard', {challenge_id}, '{label}', 0) RETURNING id"
    ).strip())
    tag_id = int(db_sql(
        "INSERT INTO tags (challenge_id, value) "
        f"VALUES ({challenge_id}, '{label}') RETURNING id"
    ).strip())
    topic_id = int(db_sql(
        "INSERT INTO topics (value) "
        f"VALUES ('{label}') RETURNING id"
    ).strip())
    challenge_topic_id = int(db_sql(
        "INSERT INTO challenge_topics (challenge_id, topic_id) "
        f"VALUES ({challenge_id}, {topic_id}) RETURNING id"
    ).strip())
    file_id = int(db_sql(
        "INSERT INTO files (type, location, challenge_id) "
        f"VALUES ('challenge', '{label}', {challenge_id}) RETURNING id"
    ).strip())
    comment_id = int(db_sql(
        "INSERT INTO comments (type, content, challenge_id) "
        f"VALUES ('challenge', '{label}', {challenge_id}) RETURNING id"
    ).strip())
    survey_id = int(db_sql(
        "INSERT INTO survey_responses "
        "(dojo_id, challenge_id, user_id, prompt, response, timestamp) "
        f"VALUES (x'{dojo_hex_id}'::int, {challenge_id}, {user_id}, "
        f"'{label}', '{label}', NOW()) "
        "RETURNING id"
    ).strip())
    return {
        "challenge_topics": challenge_topic_id,
        "comments": comment_id,
        "files": file_id,
        "hints": hint_id,
        "pointer": pointer_id,
        "survey_responses": survey_id,
        "tags": tag_id,
    }


def challenge_database_state(challenge_id):
    challenge = db_sql(
        "SELECT row_to_json(challenge_row)::text "
        f"FROM challenges challenge_row WHERE id = {challenge_id}"
    ).strip()
    flags = db_sql(
        "SELECT row_to_json(flag_row)::text "
        f"FROM flags flag_row WHERE challenge_id = {challenge_id} ORDER BY id"
    ).splitlines()
    submissions = db_sql(
        "SELECT row_to_json(submission_row)::text FROM submissions submission_row "
        f"WHERE challenge_id = {challenge_id} ORDER BY id"
    ).splitlines()
    provenance = db_sql(
        "SELECT row_to_json(provenance_row)::text "
        "FROM dojo_challenge_transfer_provenances provenance_row "
        f"WHERE challenge_id = {challenge_id}"
    ).strip()
    return challenge, tuple(flags), tuple(submissions), provenance


def add_challenge_type_collision_provenance(dojo, challenge_id, coordinate):
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    module_id, dojo_challenge_id = coordinate
    source_dojo_id = int.from_bytes(
        bytes.fromhex(dojo_hex_id),
        "big",
        signed=True,
    )
    db_sql(
        "INSERT INTO dojo_challenge_transfer_provenances "
        "(challenge_id, dojo_id, module_id, dojo_challenge_id, data) "
        f"VALUES ({challenge_id}, x'{dojo_hex_id}'::int, "
        f"'{module_id}', '{dojo_challenge_id}', "
        "jsonb_build_object("
        "'version', 1, 'transfer', jsonb_build_object("
        f"'dojo', NULL, 'dojo_id', {source_dojo_id}, "
        "'module', 'module', 'challenge', 'collision-source')))"
    )


def clone_authenticated_session(session):
    clone = requests.Session()
    clone.cookies.update(session.cookies)
    clone.headers.update(session.headers)
    return clone


def initialize_git_backed_dojo(dojo):
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    dojo_path = f"/data/dojos/{dojo_hex_id}"
    root = dojo_run(
        "mktemp", "-d", "/data/dojos/tmp/transfer-test.XXXXXXXX"
    ).stdout.strip()
    remote_path = f"{root}/remote.git"
    ctfd_remote_path = remote_path.replace("/data/dojos/", "/var/dojos/", 1)
    work_path = f"{root}/work"
    dojo_run("git", "init", "-b", "main", dojo_path)
    dojo_run("git", "-C", dojo_path, "config", "user.email", "test@pwn.college")
    dojo_run("git", "-C", dojo_path, "config", "user.name", "Test")
    dojo_run("git", "-C", dojo_path, "add", "dojo.yml")
    dojo_run("git", "-C", dojo_path, "commit", "-m", "Initial")
    dojo_run("git", "init", "--bare", "-b", "main", remote_path)
    dojo_run("git", "-C", dojo_path, "remote", "add", "origin", remote_path)
    dojo_run("git", "-C", dojo_path, "push", "-u", "origin", "main")
    dojo_run("git", "clone", remote_path, work_path)
    dojo_run("git", "-C", dojo_path, "remote", "set-url", "origin", ctfd_remote_path)
    dojo_run("git", "-C", work_path, "config", "user.email", "test@pwn.college")
    dojo_run("git", "-C", work_path, "config", "user.name", "Test")
    update_code = db_sql(
        f"UPDATE dojos SET private_key = 'test-key-{dojo_hex_id}' "
        f"WHERE dojo_id = x'{dojo_hex_id}'::int RETURNING update_code"
    ).strip()
    return root, work_path, dojo_path, update_code


def push_git_dojo_spec(work_path, spec, message):
    dojo_run(
        "tee",
        f"{work_path}/dojo.yml",
        input=yaml.safe_dump(spec, sort_keys=False),
    )
    dojo_run("git", "-C", work_path, "add", "dojo.yml")
    dojo_run("git", "-C", work_path, "commit", "-m", message)
    dojo_run("git", "-C", work_path, "push", "origin", "main")
    return dojo_run("git", "-C", work_path, "rev-parse", "HEAD").stdout.strip()


def dojo_temporary_entries():
    return set(
        dojo_run(
            "find",
            "/data/dojos/tmp",
            "-mindepth", "1",
            "-maxdepth", "1",
            "-printf", "%f\\n",
        ).stdout.splitlines()
    )


def dojo_topology_database_state(dojo):
    dojo_hex_id = dojo.rsplit("~", 1)[1]
    queries = (
        (
            "SELECT row_to_json(dojo_row)::text FROM dojos dojo_row "
            f"WHERE dojo_id = x'{dojo_hex_id}'::int"
        ),
        (
            "SELECT row_to_json(user_row)::text FROM dojo_users user_row "
            f"WHERE dojo_id = x'{dojo_hex_id}'::int ORDER BY user_id"
        ),
        (
            "SELECT row_to_json(module_row)::text FROM dojo_modules module_row "
            f"WHERE dojo_id = x'{dojo_hex_id}'::int ORDER BY module_index"
        ),
        (
            "SELECT row_to_json(challenge_row)::text "
            "FROM dojo_challenges challenge_row "
            f"WHERE dojo_id = x'{dojo_hex_id}'::int "
            "ORDER BY module_index, challenge_index"
        ),
        (
            "SELECT row_to_json(resource_row)::text "
            "FROM dojo_resources resource_row "
            f"WHERE dojo_id = x'{dojo_hex_id}'::int "
            "ORDER BY module_index, resource_index"
        ),
        (
            "SELECT row_to_json(challenge_row)::text "
            "FROM challenges challenge_row "
            f"WHERE category = '{dojo_hex_id}' ORDER BY id"
        ),
        (
            "SELECT row_to_json(flag_row)::text FROM flags flag_row "
            "JOIN challenges ON challenges.id = flag_row.challenge_id "
            f"WHERE challenges.category = '{dojo_hex_id}' ORDER BY flag_row.id"
        ),
        (
            "SELECT row_to_json(submission_row)::text "
            "FROM submissions submission_row "
            "JOIN challenges ON challenges.id = submission_row.challenge_id "
            f"WHERE challenges.category = '{dojo_hex_id}' "
            "ORDER BY submission_row.id"
        ),
        (
            "SELECT row_to_json(provenance_row)::text "
            "FROM dojo_challenge_transfer_provenances provenance_row "
            "LEFT JOIN challenges "
            "ON challenges.id = provenance_row.challenge_id "
            f"WHERE provenance_row.dojo_id = x'{dojo_hex_id}'::int "
            f"OR challenges.category = '{dojo_hex_id}' "
            "ORDER BY provenance_row.challenge_id"
        ),
    )
    return tuple(tuple(db_sql(query).splitlines()) for query in queries)


def dojo_filesystem_state(dojo):
    dojo_path = f"/data/dojos/{dojo.rsplit('~', 1)[1]}"
    metadata = dojo_run(
        "find",
        dojo_path,
        "-printf", "%P|%y|%m|%s|%l\n",
    ).stdout.splitlines()
    contents = dojo_run(
        "find",
        dojo_path,
        "-type", "f",
        "-exec", "sha256sum", "{}", "+",
    ).stdout.splitlines()
    return tuple(sorted(metadata)), tuple(sorted(contents))


def finish_database_transaction(transaction, commit):
    if transaction.poll() is not None:
        if commit:
            assert transaction.returncode == 0, transaction.stderr.read()
        return
    try:
        transaction.stdin.write(f"{'COMMIT' if commit else 'ROLLBACK'};\n\\q\n")
        transaction.stdin.flush()
        transaction.stdin.close()
    except (BrokenPipeError, ValueError):
        pass
    try:
        returncode = transaction.wait(timeout=10 if commit else 5)
    except subprocess.TimeoutExpired:
        transaction.kill()
        transaction.wait()
        if commit:
            raise
        return
    if commit:
        assert returncode == 0, transaction.stderr.read()


def begin_pending_database_update(statement, marker):
    transaction = subprocess.Popen(
        [
            shutil.which("docker"), "exec", "-i", DOJO_CONTAINER,
            "dojo", "db", "-qAt", "-v", "ON_ERROR_STOP=1",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        transaction.stdin.write(
            f"BEGIN;\n{statement.rstrip().rstrip(';')} /* {marker} */;\n"
        )
        transaction.stdin.flush()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            active = db_sql(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE state = 'idle in transaction' "
                f"AND query LIKE '%{marker}%'"
            ).strip()
            if active != "0":
                return transaction
            time.sleep(0.1)
        raise AssertionError("Concurrent role change did not acquire its row lock")
    except BaseException:
        finish_database_transaction(transaction, False)
        raise


def wait_for_update_database_lock(future, required_query, forbidden_query=None):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if future.done():
            raise AssertionError(
                f"Dojo update completed before role change committed: {future.result().text}"
            )
        forbidden_filter = (
            f"AND query NOT ILIKE '%{forbidden_query}%' "
            if forbidden_query else ""
        )
        blocked = db_sql(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE wait_event_type = 'Lock' "
            "AND query ILIKE '%for update%' "
            f"AND query ILIKE '%{required_query}%' "
            f"{forbidden_filter}"
        ).strip()
        if blocked != "0":
            return
        time.sleep(0.1)
    raise AssertionError("Dojo update did not wait for the authorization row lock")


def wait_for_advisory_database_lock(future):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if future.done():
            raise AssertionError(
                f"Request completed before advisory lock release: {future.result().text}"
            )
        blocked = db_sql(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE wait_event_type = 'Lock' "
            "AND query ILIKE '%pg_advisory_xact_lock%'"
        ).strip()
        if blocked != "0":
            return
        time.sleep(0.1)
    raise AssertionError("Request did not wait for the dojo id advisory lock")


def test_create_dojo(example_dojo, admin_session):
    assert admin_session.get(f"{DOJO_URL}/{example_dojo}/").status_code == 200
    assert admin_session.get(f"{DOJO_URL}/{example_dojo}/").status_code == 200


def test_get_dojo_modules(example_dojo):
    modules = get_dojo_modules(example_dojo)

    hello_module = modules[0]
    assert hello_module['id'] == "hello", f"Expected module id to be 'hello' but got {hello_module['id']}"
    assert hello_module['name'] == "Hello", f"Expected module name to be 'Hello' but got {hello_module['name']}"

    world_module = modules[1]
    assert world_module['id'] == "world", f"Expected module id to be 'world' but got {world_module['id']}"
    assert world_module['name'] == "World", f"Expected module name to be 'World' but got {world_module['name']}"


def test_delete_dojo(admin_session):
    reference_id = create_dojo_yml("""id: delete-test""", session=admin_session)
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
    assert admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={"dojo": reference_id}).status_code == 200
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 404


def test_delete_dojo_revalidates_concurrent_global_admin_demotion(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"delete-demotion-{suffix}"
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    user_name, user_session = random_user
    user_id = get_user_id(user_name)
    promotion = admin_session.patch(
        f"{DOJO_URL}/api/v1/users/{user_id}",
        json={"type": "admin"},
    )
    assert promotion.status_code == 200, promotion.text
    assert db_sql(
        "SELECT count(*) FROM dojo_users "
        f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int "
        f"AND user_id = {user_id}"
    ).strip() == "0"
    database_state = dojo_topology_database_state(dojo)
    filesystem_state = dojo_filesystem_state(dojo)
    temporary_entries = dojo_temporary_entries()
    marker = f"delete_demotion_race_{suffix}"
    user_lock = begin_pending_database_update(
        f"UPDATE users SET type = 'user' WHERE id = {user_id}",
        marker,
    )
    delete_session = clone_authenticated_session(user_session)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        future = executor.submit(delete_dojo_request, dojo, delete_session)
        wait_for_update_database_lock(future, "users.type", "dojo_users")
        finish_database_transaction(user_lock, True)
        response = future.result(timeout=10)
        assert response.status_code == 403, response.text
    finally:
        finish_database_transaction(user_lock, False)
        executor.shutdown(wait=True, cancel_futures=True)
        delete_session.close()
        restoration = admin_session.patch(
            f"{DOJO_URL}/api/v1/users/{user_id}",
            json={"type": "user"},
        )
        assert restoration.status_code == 200, restoration.text

    assert dojo_topology_database_state(dojo) == database_state
    assert dojo_filesystem_state(dojo) == filesystem_state
    assert dojo_temporary_entries() == temporary_entries
    assert db_sql(f"SELECT type FROM users WHERE id = {user_id}").strip() == "user"


def test_delete_dojo_global_authorization_survives_lock_wait(admin_session, random_user):
    user_name, user_session = random_user
    user_id = get_user_id(user_name)
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"delete-auth-global-{suffix}"
    dojo = create_transfer_dojo(
        dojo_id,
        [{"id": "source"}],
        admin_session,
    )
    promotion = admin_session.patch(
        f"{DOJO_URL}/api/v1/users/{user_id}",
        json={"type": "admin"},
    )
    assert promotion.status_code == 200, promotion.text
    assert db_sql(
        "SELECT count(*) FROM dojo_users "
        f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int "
        f"AND user_id = {user_id}"
    ).strip() == "0"
    marker = f"delete_authorized_race_global_admin_{suffix}"
    user_lock = begin_pending_database_update(
        "SELECT type FROM users "
        f"WHERE id = {user_id} FOR UPDATE",
        marker,
    )
    delete_session = clone_authenticated_session(user_session)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        future = executor.submit(delete_dojo_request, dojo, delete_session)
        wait_for_update_database_lock(future, "users.type", "dojo_users")
        finish_database_transaction(user_lock, True)
        response = future.result(timeout=10)
        assert response.status_code == 200, response.text
    finally:
        finish_database_transaction(user_lock, False)
        executor.shutdown(wait=True, cancel_futures=True)
        delete_session.close()
        restoration = admin_session.patch(
            f"{DOJO_URL}/api/v1/users/{user_id}",
            json={"type": "user"},
        )
        assert restoration.status_code == 200, restoration.text

    assert db_sql(
        "SELECT count(*) FROM dojos "
        f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int"
    ).strip() == "0"
    assert admin_session.get(f"{DOJO_URL}/{dojo}/").status_code == 404


def test_delete_dojo_admin_remains_forbidden(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"delete-dojo-admin-{suffix}"
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    user_name, user_session = random_user
    grant_dojo_admin(dojo, user_name, user_session, admin_session)
    database_state = dojo_topology_database_state(dojo)
    filesystem_state = dojo_filesystem_state(dojo)
    response = delete_dojo_request(dojo, user_session)
    assert response.status_code == 403, response.text
    assert dojo_topology_database_state(dojo) == database_state
    assert dojo_filesystem_state(dojo) == filesystem_state


def test_update_dojo(admin_session):
    random_id = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"update-dojo-{random_id}"
    original_name = "Update Test"
    updated_name = "Update Test Updated"
    spec = yaml.safe_load(open(TEST_DOJOS_LOCATION / "simple_award_dojo.yml").read())
    spec["id"] = dojo_id
    spec["name"] = original_name
    dojo_reference_id = create_dojo_yml(
        yaml.safe_dump(spec, sort_keys=False),
        session=admin_session,
    )

    spec["name"] = updated_name
    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo_reference_id}/update",
        json=spec,
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.json()}"
    assert response.json()["success"]

    list_response = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert list_response.status_code == 200, f"Expected status code 200, but got {list_response.status_code}"
    updated = next(dojo for dojo in list_response.json()["dojos"] if dojo["id"] == dojo_reference_id)
    assert updated["name"] == updated_name


def test_ordinary_updates_consolidate_same_type_challenge_duplicates(
    admin_session,
    random_user,
):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"duplicate-{suffix}"
    spec = transfer_dojo_spec(dojo_id, [{"id": "source"}])
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    user_name, user_session = random_user
    grant_dojo_admin(dojo, user_name, user_session, admin_session)
    live_id = dojo_challenge_rows(dojo)["module:source"]
    live_flag_id, live_solve_id = add_challenge_flag_and_solve(
        live_id,
        get_user_id(user_name),
        f"live-{suffix}",
    )
    api_user_name = f"duplicate-api-{suffix}"
    api_user_session = login(api_user_name, api_user_name, register=True)
    git_user_name = f"duplicate-git-{suffix}"
    git_user_session = login(git_user_name, git_user_name, register=True)
    git_root = None
    try:
        api_duplicate_id, api_flag_id, api_solve_id = (
            create_same_type_challenge_duplicate(
                dojo,
                ("module", "source"),
                get_user_id(api_user_name),
                f"api-{suffix}",
            )
        )
        assert coordinate_challenge_rows(dojo, ("module", "source")) == {
            ("dojo", live_id),
            ("dojo", api_duplicate_id),
        }
        db_sql(
            "UPDATE dojo_challenges "
            f"SET challenge_id = {api_duplicate_id} "
            f"WHERE challenge_id = {live_id}"
        )
        canonical_id = api_duplicate_id
        orphan_id = live_id
        assert dojo_challenge_rows(dojo) == {"module:source": canonical_id}
        add_challenge_type_collision_provenance(
            dojo,
            live_id,
            ("module", "source"),
        )
        add_challenge_type_collision_provenance(
            dojo,
            api_duplicate_id,
            ("module", "source"),
        )
        dependent_ids = create_challenge_dependents(
            dojo,
            orphan_id,
            get_user_id(api_user_name),
            f"dependent-{suffix}",
        )
        response = update_transfer_dojo(dojo, spec, user_session)
        assert response.status_code == 200, response.text
        assert coordinate_challenge_rows(dojo, ("module", "source")) == {
            ("dojo", canonical_id),
        }
        assert dojo_challenge_rows(dojo) == {"module:source": canonical_id}
        assert {
            live_flag_id,
            api_flag_id,
        }.issubset(challenge_flag_ids(canonical_id))
        assert {
            live_solve_id,
            api_solve_id,
        }.issubset(challenge_solve_ids(canonical_id))
        assert challenge_transfer_provenance(canonical_id) is None
        assert db_sql(
            "SELECT next_id FROM challenges "
            f"WHERE id = {dependent_ids['pointer']}"
        ).strip() == str(canonical_id)
        for table in (
            "challenge_topics",
            "comments",
            "files",
            "hints",
            "survey_responses",
            "tags",
        ):
            assert db_sql(
                f"SELECT challenge_id FROM {table} "
                f"WHERE id = {dependent_ids[table]}"
            ).strip() == str(canonical_id)
        assert challenge_database_state(orphan_id) == ("", (), (), "")

        git_root, work_path, dojo_path, update_code = initialize_git_backed_dojo(dojo)
        git_duplicate_id, git_flag_id, git_solve_id = (
            create_same_type_challenge_duplicate(
                dojo,
                ("module", "source"),
                get_user_id(git_user_name),
                f"git-{suffix}",
            )
        )
        spec["name"] = "Duplicate Consolidated By Git"
        git_commit = push_git_dojo_spec(
            work_path,
            spec,
            "Consolidate duplicate challenge",
        )
        response = requests.post(
            f"{DOJO_URL}/dojo/{dojo}/update/{update_code}",
            timeout=30,
        )
        assert response.status_code == 200, response.text
        assert dojo_run(
            "git",
            "-C",
            dojo_path,
            "rev-parse",
            "HEAD",
        ).stdout.strip() == git_commit
        assert coordinate_challenge_rows(dojo, ("module", "source")) == {
            ("dojo", canonical_id),
        }
        assert dojo_challenge_rows(dojo) == {"module:source": canonical_id}
        assert {
            live_flag_id,
            api_flag_id,
            git_flag_id,
        }.issubset(challenge_flag_ids(canonical_id))
        assert {
            live_solve_id,
            api_solve_id,
            git_solve_id,
        }.issubset(challenge_solve_ids(canonical_id))
        assert challenge_database_state(git_duplicate_id) == ("", (), (), "")

        collision_id, collision_flag_id, collision_solve_id = (
            create_same_type_challenge_duplicate(
                dojo,
                ("module", "source"),
                get_user_id(user_name),
                f"collision-{suffix}",
            )
        )
        response = update_transfer_dojo(dojo, spec, user_session)
        assert response.status_code == 200, response.text
        assert coordinate_challenge_rows(dojo, ("module", "source")) == {
            ("dojo", canonical_id),
        }
        assert collision_flag_id in challenge_flag_ids(canonical_id)
        assert db_sql(
            "SELECT type, challenge_id FROM submissions "
            f"WHERE id = {collision_solve_id}"
        ).strip() == f"discard|{canonical_id}"
        assert challenge_database_state(collision_id) == ("", (), (), "")
    finally:
        if git_root is not None:
            dojo_run("rm", "-rf", git_root)
        api_user_session.close()
        git_user_session.close()


def test_internal_transfer_recalculates_warmed_module_caches(
    admin_session,
    random_user,
):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"cache-move-{suffix}"
    original_spec = {
        "id": dojo_id,
        "name": "Cache Move",
        "type": "public",
        "modules": [
            {
                "id": "source-module",
                "name": "Source Module",
                "resources": [{
                    "type": "challenge",
                    "id": "source",
                    "name": "Source",
                    "image": TRANSFER_TEST_IMAGE,
                }],
            },
            {
                "id": "destination-module",
                "name": "Destination Module",
                "resources": [],
            },
        ],
    }
    dojo = create_dojo_yml(
        yaml.safe_dump(original_spec, sort_keys=False),
        session=admin_session,
    )
    user_name, _ = random_user
    user_id = get_user_id(user_name)
    challenge_id = dojo_challenge_rows(dojo)["source-module:source"]
    add_challenge_flag_and_solve(challenge_id, user_id, f"move-{suffix}")
    dojo_modules = {dojo_database_id(dojo): (0, 1)}
    warm_transfer_caches(dojo_modules, (user_id,))

    moved_spec = {
        **original_spec,
        "modules": [
            {
                **original_spec["modules"][0],
                "resources": [],
            },
            {
                **original_spec["modules"][1],
                "resources": [{
                    "type": "challenge",
                    "id": "moved",
                    "name": "Moved",
                    "image": TRANSFER_TEST_IMAGE,
                    "transfer": {
                        "module": "source-module",
                        "challenge": "source",
                    },
                }],
            },
        ],
    }
    response = update_transfer_dojo(dojo, moved_spec, admin_session)
    assert response.status_code == 200, response.text
    assert dojo_challenge_rows(dojo) == {
        "destination-module:moved": challenge_id,
    }
    wait_for_background_worker(timeout=30)
    assert_transfer_caches_match_database(dojo_modules, (user_id,))


def test_duplicate_solve_consolidation_recalculates_warmed_caches(
    admin_session,
    random_user,
):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"cache-duplicate-{suffix}"
    spec = transfer_dojo_spec(dojo_id, [{"id": "source"}])
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    user_name, _ = random_user
    user_id = get_user_id(user_name)
    canonical_id = dojo_challenge_rows(dojo)["module:source"]
    add_challenge_flag_and_solve(canonical_id, user_id, f"canonical-{suffix}")
    duplicate_id, _, duplicate_solve_id = create_same_type_challenge_duplicate(
        dojo,
        ("module", "source"),
        user_id,
        f"duplicate-{suffix}",
    )
    dojo_modules = {dojo_database_id(dojo): (0,)}
    warm_transfer_caches(dojo_modules, (user_id,))

    response = update_transfer_dojo(dojo, spec, admin_session)
    assert response.status_code == 200, response.text
    assert db_sql(
        "SELECT type, challenge_id FROM submissions "
        f"WHERE id = {duplicate_solve_id}"
    ).strip() == f"discard|{canonical_id}"
    assert challenge_database_state(duplicate_id) == ("", (), (), "")
    wait_for_background_worker(timeout=30)
    assert_transfer_caches_match_database(dojo_modules, (user_id,))


def test_duplicate_consolidation_rollback_emits_no_cache_events(
    admin_session,
    random_user,
):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"cache-rollback-{suffix}"
    spec = transfer_dojo_spec(dojo_id, [{"id": "source"}])
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    user_name, _ = random_user
    user_id = get_user_id(user_name)
    canonical_id = dojo_challenge_rows(dojo)["module:source"]
    add_challenge_flag_and_solve(canonical_id, user_id, f"canonical-{suffix}")
    duplicate_id, _, duplicate_solve_id = create_same_type_challenge_duplicate(
        dojo,
        ("module", "source"),
        user_id,
        f"duplicate-{suffix}",
    )
    add_challenge_type_collision_provenance(
        dojo,
        canonical_id,
        ("module", "source"),
    )
    add_challenge_type_collision_provenance(
        dojo,
        duplicate_id,
        ("module", "source"),
    )
    db_sql(
        "UPDATE dojo_challenge_transfer_provenances "
        "SET data = jsonb_set(data, '{transfer,challenge}', "
        "to_jsonb('conflicting-source'::text)) "
        f"WHERE challenge_id = {duplicate_id}"
    )
    dojo_modules = {dojo_database_id(dojo): (0,)}
    timestamps = warm_transfer_caches(dojo_modules, (user_id,))

    response = update_transfer_dojo(dojo, spec, admin_session)
    assert response.status_code == 400, response.text
    assert "conflicting transfer provenance" in response.json()["error"]
    assert db_sql(
        "SELECT type, challenge_id FROM submissions "
        f"WHERE id = {duplicate_solve_id}"
    ).strip() == f"correct|{duplicate_id}"
    assert coordinate_challenge_rows(dojo, ("module", "source")) == {
        ("dojo", canonical_id),
        ("dojo", duplicate_id),
    }
    time.sleep(1)
    assert_transfer_caches_match_database(
        dojo_modules,
        (user_id,),
        timestamps=timestamps,
        timeout=0,
    )


def test_community_dojo_internal_transfer_preserves_identity(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"internal-{suffix}"
    dojo = create_transfer_dojo(dojo_id, [{"id": "old"}], admin_session)
    user_name, user_session = random_user
    grant_dojo_admin(dojo, user_name, user_session, admin_session)

    original_id = dojo_challenge_rows(dojo)["module:old"]
    original_flags = challenge_flag_ids(original_id)
    moved_spec = transfer_dojo_spec(dojo_id, [{
        "id": "new",
        "transfer": {"challenge": "old"},
    }])

    git_root, work_path, dojo_path, update_code = initialize_git_backed_dojo(dojo)
    try:
        moved_commit = push_git_dojo_spec(work_path, moved_spec, "Move challenge")
        temporary_entries = dojo_temporary_entries()
        response = requests.post(
            f"{DOJO_URL}/dojo/{dojo}/update/{update_code}",
            timeout=30,
        )
        assert response.status_code == 200, response.text
        assert dojo_run("git", "-C", dojo_path, "rev-parse", "HEAD").stdout.strip() == moved_commit
        assert dojo_temporary_entries() == temporary_entries
        assert dojo_challenge_rows(dojo) == {"module:new": original_id}
        assert challenge_flag_ids(original_id) == original_flags
        assert challenge_transfer_provenance(original_id) == (
            "module", "new", "1", "module", "old",
        )

        invalid_spec = transfer_dojo_spec(dojo_id, [{
            "id": "invalid",
            "transfer": {"challenge": "missing"},
        }])
        push_git_dojo_spec(work_path, invalid_spec, "Invalid move")
        temporary_entries = dojo_temporary_entries()
        response = requests.post(
            f"{DOJO_URL}/dojo/{dojo}/update/{update_code}",
            timeout=30,
        )
        assert response.status_code == 400, response.text
        assert dojo_run("git", "-C", dojo_path, "rev-parse", "HEAD").stdout.strip() == moved_commit
        assert dojo_temporary_entries() == temporary_entries
        assert dojo_challenge_rows(dojo) == {"module:new": original_id}
        assert challenge_transfer_provenance(original_id) == (
            "module", "new", "1", "module", "old",
        )
    finally:
        dojo_run("rm", "-rf", git_root)

    for _ in range(2):
        response = update_transfer_dojo(dojo, moved_spec, user_session)
        assert response.status_code == 200, response.text
        assert dojo_challenge_rows(dojo) == {"module:new": original_id}

    replacement_spec = transfer_dojo_spec(dojo_id, [
        {"id": "old"},
        {"id": "new", "transfer": {"challenge": "old"}},
    ])
    response = update_transfer_dojo(dojo, replacement_spec, user_session)
    assert response.status_code == 200, response.text
    rows = dojo_challenge_rows(dojo)
    assert rows["module:new"] == original_id
    assert rows["module:old"] != original_id
    assert challenge_flag_ids(original_id) == original_flags

    db_sql(
        "DELETE FROM dojo_challenge_transfer_provenances "
        f"WHERE challenge_id = {original_id}"
    )
    rows_before_legacy_replay = dojo_challenge_rows(dojo)
    replacement_id = rows_before_legacy_replay["module:old"]
    replacement_flags = challenge_flag_ids(replacement_id)
    response = update_transfer_dojo(dojo, moved_spec, user_session)
    assert response.status_code == 400, response.text
    assert dojo_challenge_rows(dojo) == rows_before_legacy_replay
    assert challenge_transfer_provenance(original_id) is None

    response = update_transfer_dojo(dojo, moved_spec, admin_session)
    assert response.status_code == 200, response.text
    assert dojo_challenge_rows(dojo) == rows_before_legacy_replay
    assert challenge_flag_ids(original_id) == original_flags
    assert challenge_flag_ids(replacement_id) == replacement_flags
    assert challenge_transfer_provenance(original_id) == (
        "module", "new", "1", "module", "old",
    )


def test_concurrent_git_updates_cannot_install_stale_checkout(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"git-order-{suffix}"
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    old_spec = transfer_dojo_spec(dojo_id, [{"id": "source"}])
    old_spec["name"] = "Older Checkout"
    old_spec["modules"][0]["resources"][0]["privileged"] = True
    latest_spec = transfer_dojo_spec(dojo_id, [{"id": "source"}])
    latest_spec["name"] = "Latest Checkout"
    latest_spec["modules"][0]["resources"][0]["privileged"] = False

    git_root, work_path, dojo_path, _ = initialize_git_backed_dojo(dojo)
    try:
        old_commit = push_git_dojo_spec(work_path, old_spec, "Older checkout")
        assert old_commit != dojo_run(
            "git", "-C", dojo_path, "rev-parse", "HEAD"
        ).stdout.strip()
        temporary_entries = dojo_temporary_entries()
        ctfd_work_path = work_path.replace("/data/dojos/", "/var/dojos/", 1)
        ctfd_dojo_path = dojo_path.replace("/data/dojos/", "/var/dojos/", 1)
        dojo_database_id = int.from_bytes(
            bytes.fromhex(dojo.rsplit("~", 1)[1]),
            "big",
            signed=True,
        )
        concurrency_script = """
import pathlib
import subprocess
import threading
import yaml
from flask import current_app
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import DojoChallenges, Dojos
import CTFd.plugins.dojo_plugin.utils.dojo as dojo_utils

app = current_app._get_current_object()
dojo_id = __DOJO_ID__
work_path = __WORK_PATH__
live_path = __LIVE_PATH__
latest_spec = __LATEST_SPEC__
older_clone_ready = threading.Event()
release_older = threading.Event()
latest_finished = threading.Event()
clone_counts = {}
completed = []
errors = []
real_clone_url = dojo_utils.dojo_clone_url

def controlled_clone(url, private_key):
    thread_name = threading.current_thread().name
    clone_counts[thread_name] = clone_counts.get(thread_name, 0) + 1
    checkout = real_clone_url(url, private_key)
    if thread_name == "older-update" and clone_counts[thread_name] == 1:
        older_clone_ready.set()
        assert release_older.wait(30)
    return checkout

def update(label):
    with app.app_context():
        try:
            dojo = Dojos.query.filter_by(dojo_id=dojo_id).one()
            dojo_utils.dojo_update(dojo)
            completed.append(label)
        except BaseException as error:
            errors.append((label, repr(error)))
        finally:
            if label == "latest":
                latest_finished.set()

dojo_utils.dojo_clone_url = controlled_clone
older_thread = threading.Thread(target=update, args=("older",), name="older-update")
latest_thread = None
latest_completed_before_release = False
try:
    older_thread.start()
    assert older_clone_ready.wait(30), errors
    remote_url = subprocess.run(
        ["git", "-C", live_path, "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", work_path, "remote", "set-url", "origin", remote_url],
        check=True,
    )
    pathlib.Path(work_path, "dojo.yml").write_text(
        yaml.safe_dump(latest_spec, sort_keys=False)
    )
    subprocess.run(["git", "-C", work_path, "add", "dojo.yml"], check=True)
    subprocess.run(
        ["git", "-C", work_path, "commit", "-m", "Latest checkout"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", work_path, "push", "origin", "main"],
        check=True,
        capture_output=True,
    )
    latest_commit = subprocess.run(
        ["git", "-C", work_path, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    latest_thread = threading.Thread(
        target=update,
        args=("latest",),
        name="latest-update",
    )
    latest_thread.start()
    latest_completed_before_release = latest_finished.wait(30)
finally:
    release_older.set()
    older_thread.join(30)
    if latest_thread is not None:
        latest_thread.join(30)
    dojo_utils.dojo_clone_url = real_clone_url

assert latest_completed_before_release
assert not older_thread.is_alive()
assert latest_thread is not None and not latest_thread.is_alive()
assert errors == []
assert sorted(completed) == ["latest", "older"]
assert clone_counts == {"older-update": 2, "latest-update": 1}
live_commit = subprocess.run(
    ["git", "-C", live_path, "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
assert live_commit == latest_commit
live_spec = yaml.safe_load(pathlib.Path(live_path, "dojo.yml").read_text())
assert live_spec["name"] == "Latest Checkout"
assert live_spec["modules"][0]["resources"][0]["privileged"] is False
db.session.expire_all()
dojo = Dojos.query.filter_by(dojo_id=dojo_id).one()
challenge = DojoChallenges.query.filter_by(
    dojo_id=dojo_id,
    module_index=0,
    challenge_index=0,
).one()
assert dojo.name == "Latest Checkout"
assert challenge.privileged is False
print(f"LATEST_CHECKOUT_WON:{latest_commit}")
"""
        concurrency_script = (
            concurrency_script
            .replace("__DOJO_ID__", repr(dojo_database_id))
            .replace("__WORK_PATH__", repr(ctfd_work_path))
            .replace("__LIVE_PATH__", repr(ctfd_dojo_path))
            .replace("__LATEST_SPEC__", repr(latest_spec))
        )
        result = dojo_run(
            "dojo",
            "flask",
            input=concurrency_script,
            check=False,
        )
        shell_diagnostics = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert result.returncode == 0, shell_diagnostics
        marker = re.search(
            r"LATEST_CHECKOUT_WON:([0-9a-f]{40})(?![0-9a-f])",
            result.stdout,
        )
        assert marker is not None, shell_diagnostics
        latest_commit = marker.group(1)
        assert dojo_temporary_entries() == temporary_entries
        live_commit = dojo_run(
            "git", "-C", dojo_path, "rev-parse", "HEAD"
        ).stdout.strip()
        remote_commit = dojo_run(
            "git",
            "--git-dir", f"{git_root}/remote.git",
            "rev-parse", "refs/heads/main",
        ).stdout.strip()
        assert live_commit == remote_commit == latest_commit
        assert db_sql(
            "SELECT name FROM dojos "
            f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int"
        ).strip() == "Latest Checkout"
    finally:
        dojo_run("rm", "-rf", git_root)


def test_git_update_head_probe_timeout_is_atomic(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"git-timeout-{suffix}"
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    update_spec = transfer_dojo_spec(dojo_id, [{"id": "source"}])
    update_spec["name"] = "Must Not Install"
    update_spec["modules"][0]["resources"][0]["privileged"] = True
    original_rows = dojo_challenge_rows(dojo)
    original_flags = challenge_flag_ids(original_rows["module:source"])
    original_challenge_data = db_sql(
        "SELECT data FROM dojo_challenges "
        f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int "
        "AND module_index = 0 AND challenge_index = 0"
    ).strip()
    original_name = db_sql(
        "SELECT name FROM dojos "
        f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int"
    ).strip()

    git_root, work_path, dojo_path, _ = initialize_git_backed_dojo(dojo)
    try:
        remote_commit = push_git_dojo_spec(work_path, update_spec, "Rejected update")
        live_commit = dojo_run(
            "git", "-C", dojo_path, "rev-parse", "HEAD"
        ).stdout.strip()
        assert remote_commit != live_commit
        temporary_entries = dojo_temporary_entries()
        dojo_database_id = int.from_bytes(
            bytes.fromhex(dojo.rsplit("~", 1)[1]),
            "big",
            signed=True,
        )
        fault_script = """
import subprocess
from CTFd.plugins.dojo_plugin.models import Dojos
import CTFd.plugins.dojo_plugin.utils.dojo as dojo_utils

dojo_id = __DOJO_ID__
probe_timeouts = []
real_git_command = dojo_utils.dojo_git_command

def timeout_head_probe(dojo, *args, **kwargs):
    if args and args[0] == "ls-remote":
        probe_timeouts.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
    return real_git_command(dojo, *args, **kwargs)

dojo_utils.dojo_git_command = timeout_head_probe
try:
    dojo = Dojos.query.filter_by(dojo_id=dojo_id).one()
    try:
        dojo_utils.dojo_update(dojo)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError("Timed-out repository probe installed an update")
finally:
    dojo_utils.dojo_git_command = real_git_command

assert probe_timeouts == [dojo_utils.DOJO_UPDATE_HEAD_TIMEOUT]
print("HEAD_PROBE_TIMEOUT_ROLLED_BACK")
"""
        fault_script = fault_script.replace(
            "__DOJO_ID__",
            repr(dojo_database_id),
        )
        result = dojo_run("dojo", "flask", input=fault_script)
        assert "HEAD_PROBE_TIMEOUT_ROLLED_BACK" in result.stdout
        assert dojo_temporary_entries() == temporary_entries
        assert dojo_run(
            "git", "-C", dojo_path, "rev-parse", "HEAD"
        ).stdout.strip() == live_commit
        assert dojo_challenge_rows(dojo) == original_rows
        assert challenge_flag_ids(original_rows["module:source"]) == original_flags
        assert db_sql(
            "SELECT data FROM dojo_challenges "
            f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int "
            "AND module_index = 0 AND challenge_index = 0"
        ).strip() == original_challenge_data
        assert db_sql(
            "SELECT name FROM dojos "
            f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int"
        ).strip() == original_name
    finally:
        dojo_run("rm", "-rf", git_root)


def test_community_dojo_internal_transfer_rejects_invalid_plans(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"invalid-{suffix}"
    dojo = create_transfer_dojo(
        dojo_id,
        [{"id": "source"}, {"id": "occupied"}],
        admin_session,
    )
    user_name, user_session = random_user
    grant_dojo_admin(dojo, user_name, user_session, admin_session)
    original_rows = dojo_challenge_rows(dojo)
    original_flags = {
        challenge_id: challenge_flag_ids(challenge_id)
        for challenge_id in original_rows.values()
    }

    invalid_specs = [
        transfer_dojo_spec(dojo_id, [{
            "id": "moved",
            "transfer": {"challenge": "missing"},
        }]),
        transfer_dojo_spec(dojo_id, [{
            "id": "occupied",
            "transfer": {"challenge": "missing"},
        }]),
        transfer_dojo_spec(dojo_id, [
            {"id": "source"},
            {"id": "occupied", "transfer": {"challenge": "source"}},
        ]),
        transfer_dojo_spec(dojo_id, [
            {"id": "first", "transfer": {"challenge": "source"}},
            {"id": "second", "transfer": {"challenge": "source"}},
        ]),
    ]

    for spec in invalid_specs:
        response = update_transfer_dojo(dojo, spec, user_session)
        assert response.status_code == 400, response.text
        assert dojo_challenge_rows(dojo) == original_rows
        assert {
            challenge_id: challenge_flag_ids(challenge_id)
            for challenge_id in original_rows.values()
        } == original_flags
        assert all(
            challenge_transfer_provenance(challenge_id) is None
            for challenge_id in original_rows.values()
        )


def test_community_dojo_challenge_type_collisions_are_isolated(admin_session, random_user):
    user_name, user_session = random_user
    user_id = get_user_id(user_name)

    for challenge_type in ("standard", "dynamic"):
        suffix = "".join(random.choices(string.ascii_lowercase, k=8))
        dojo_id = f"type-collision-{challenge_type}-{suffix}"
        dojo = create_transfer_dojo(
            dojo_id,
            [
                {"id": "source"},
                {"id": "to-move"},
                {"id": "replay-source"},
            ],
            admin_session,
        )
        grant_dojo_admin(dojo, user_name, user_session, admin_session)
        initial_rows = dojo_challenge_rows(dojo)
        collision_states = {}

        ordinary_collision = create_challenge_type_collision(
            dojo,
            ("module", "ordinary"),
            challenge_type,
            user_id,
        )
        collision_states[ordinary_collision] = challenge_database_state(
            ordinary_collision
        )
        ordinary_spec = transfer_dojo_spec(dojo_id, [
            {"id": "source"},
            {"id": "to-move"},
            {"id": "replay-source"},
            {"id": "ordinary"},
        ])
        response = update_transfer_dojo(dojo, ordinary_spec, user_session)
        assert response.status_code == 200, response.text
        ordinary_rows = dojo_challenge_rows(dojo)
        assert ordinary_rows == {
            **initial_rows,
            "module:ordinary": ordinary_rows["module:ordinary"],
        }
        assert ordinary_rows["module:ordinary"] != ordinary_collision
        assert dojo_logical_challenge_rows(dojo) == ordinary_rows
        assert coordinate_challenge_rows(dojo, ("module", "ordinary")) == {
            ("dojo", ordinary_rows["module:ordinary"]),
            (challenge_type, ordinary_collision),
        }
        assert {
            challenge_id: challenge_database_state(challenge_id)
            for challenge_id in collision_states
        } == collision_states

        detached_spec = transfer_dojo_spec(dojo_id, [
            {"id": "to-move"},
            {"id": "replay-source"},
        ])
        response = update_transfer_dojo(dojo, detached_spec, user_session)
        assert response.status_code == 200, response.text
        assert dojo_challenge_rows(dojo) == ordinary_rows
        assert dojo_logical_challenge_rows(dojo) == {
            "module:to-move": initial_rows["module:to-move"],
            "module:replay-source": initial_rows["module:replay-source"],
        }

        source_collision = create_challenge_type_collision(
            dojo,
            ("module", "source"),
            challenge_type,
            user_id,
        )
        collision_states[source_collision] = challenge_database_state(
            source_collision
        )
        assert coordinate_challenge_rows(dojo, ("module", "source")) == {
            ("dojo", initial_rows["module:source"]),
            (challenge_type, source_collision),
        }
        source_spec = transfer_dojo_spec(dojo_id, [
            {"id": "ordinary"},
            {
                "id": "source-moved",
                "transfer": {"challenge": "source"},
            },
            {"id": "to-move"},
            {"id": "replay-source"},
        ])
        response = update_transfer_dojo(dojo, source_spec, user_session)
        assert response.status_code == 200, response.text
        source_rows = dojo_challenge_rows(dojo)
        assert source_rows == {
            "module:ordinary": ordinary_rows["module:ordinary"],
            "module:source-moved": initial_rows["module:source"],
            "module:to-move": initial_rows["module:to-move"],
            "module:replay-source": initial_rows["module:replay-source"],
        }
        assert source_rows["module:source-moved"] != source_collision
        assert dojo_logical_challenge_rows(dojo) == source_rows
        assert coordinate_challenge_rows(dojo, ("module", "ordinary")) == {
            ("dojo", ordinary_rows["module:ordinary"]),
            (challenge_type, ordinary_collision),
        }
        assert coordinate_challenge_rows(dojo, ("module", "source")) == {
            (challenge_type, source_collision),
        }
        assert coordinate_challenge_rows(dojo, ("module", "source-moved")) == {
            ("dojo", initial_rows["module:source"]),
        }
        assert {
            challenge_id: challenge_database_state(challenge_id)
            for challenge_id in collision_states
        } == collision_states

        destination_collision = create_challenge_type_collision(
            dojo,
            ("module", "destination"),
            challenge_type,
            user_id,
        )
        collision_states[destination_collision] = challenge_database_state(
            destination_collision
        )
        destination_spec = transfer_dojo_spec(dojo_id, [
            {"id": "ordinary"},
            {
                "id": "source-moved",
                "transfer": {"challenge": "source"},
            },
            {
                "id": "destination",
                "transfer": {"challenge": "to-move"},
            },
            {"id": "replay-source"},
        ])
        response = update_transfer_dojo(dojo, destination_spec, user_session)
        assert response.status_code == 200, response.text
        destination_rows = dojo_challenge_rows(dojo)
        assert destination_rows == {
            "module:ordinary": ordinary_rows["module:ordinary"],
            "module:source-moved": initial_rows["module:source"],
            "module:destination": initial_rows["module:to-move"],
            "module:replay-source": initial_rows["module:replay-source"],
        }
        assert destination_rows["module:destination"] != destination_collision
        assert dojo_logical_challenge_rows(dojo) == destination_rows
        assert coordinate_challenge_rows(dojo, ("module", "destination")) == {
            ("dojo", initial_rows["module:to-move"]),
            (challenge_type, destination_collision),
        }
        assert {
            challenge_id: challenge_database_state(challenge_id)
            for challenge_id in collision_states
        } == collision_states

        replay_spec = transfer_dojo_spec(dojo_id, [
            {"id": "ordinary"},
            {
                "id": "source-moved",
                "transfer": {"challenge": "source"},
            },
            {
                "id": "destination",
                "transfer": {"challenge": "to-move"},
            },
            {
                "id": "replayed",
                "transfer": {"challenge": "replay-source"},
            },
        ])
        response = update_transfer_dojo(dojo, replay_spec, user_session)
        assert response.status_code == 200, response.text
        replay_rows = dojo_challenge_rows(dojo)
        replayed_id = initial_rows["module:replay-source"]
        assert replay_rows == {
            "module:ordinary": ordinary_rows["module:ordinary"],
            "module:source-moved": initial_rows["module:source"],
            "module:destination": initial_rows["module:to-move"],
            "module:replayed": replayed_id,
        }
        assert challenge_transfer_provenance(replayed_id) == (
            "module", "replayed", "1", "module", "replay-source",
        )
        assert coordinate_challenge_rows(dojo, ("module", "replayed")) == {
            ("dojo", replayed_id),
        }

        replay_collision = create_challenge_type_collision(
            dojo,
            ("module", "replayed"),
            challenge_type,
            user_id,
        )
        add_challenge_type_collision_provenance(
            dojo,
            replay_collision,
            ("module", "replayed"),
        )
        collision_states[replay_collision] = challenge_database_state(
            replay_collision
        )
        assert challenge_transfer_provenance(replay_collision) == (
            "module", "replayed", "1", "module", "collision-source",
        )
        assert coordinate_challenge_rows(dojo, ("module", "replayed")) == {
            ("dojo", replayed_id),
            (challenge_type, replay_collision),
        }
        detached_replay_spec = transfer_dojo_spec(dojo_id, [
            {"id": "ordinary"},
            {
                "id": "source-moved",
                "transfer": {"challenge": "source"},
            },
            {
                "id": "destination",
                "transfer": {"challenge": "to-move"},
            },
        ])
        response = update_transfer_dojo(
            dojo,
            detached_replay_spec,
            user_session,
        )
        assert response.status_code == 200, response.text
        assert dojo_challenge_rows(dojo) == replay_rows
        assert dojo_logical_challenge_rows(dojo) == {
            coordinate: challenge_id
            for coordinate, challenge_id in replay_rows.items()
            if coordinate != "module:replayed"
        }
        response = update_transfer_dojo(dojo, replay_spec, user_session)
        assert response.status_code == 200, response.text
        assert dojo_challenge_rows(dojo) == replay_rows
        assert dojo_logical_challenge_rows(dojo) == replay_rows
        assert challenge_transfer_provenance(replayed_id) == (
            "module", "replayed", "1", "module", "replay-source",
        )
        assert {
            challenge_id: challenge_database_state(challenge_id)
            for challenge_id in collision_states
        } == collision_states

        canonical_states = {
            challenge_id: challenge_database_state(challenge_id)
            for challenge_id in replay_rows.values()
        }
        dojo_hex_id = dojo.rsplit("~", 1)[1]
        db_sql(
            "UPDATE dojo_challenges "
            f"SET challenge_id = {ordinary_collision} "
            f"WHERE dojo_id = x'{dojo_hex_id}'::int AND id = 'ordinary'"
        )
        assert dojo_logical_challenge_rows(dojo)["module:ordinary"] == ordinary_collision
        response = update_transfer_dojo(dojo, replay_spec, user_session)
        assert response.status_code == 400, response.text
        assert dojo_challenge_rows(dojo) == replay_rows
        assert dojo_logical_challenge_rows(dojo)["module:ordinary"] == ordinary_collision
        assert {
            challenge_id: challenge_database_state(challenge_id)
            for challenge_id in replay_rows.values()
        } == canonical_states
        assert {
            challenge_id: challenge_database_state(challenge_id)
            for challenge_id in collision_states
        } == collision_states


def test_community_whole_dojo_import_copies_modules(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"whole-import-source-{suffix}"
    destination_id = f"whole-destination-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    destination_dojo = create_transfer_dojo(
        destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    source_rows = dojo_challenge_rows(source_dojo)
    source_state = dojo_topology_database_state(source_dojo)

    response = update_transfer_dojo(
        destination_dojo,
        {
            "id": destination_id,
            "name": "Whole Import Destination",
            "type": "public",
            "import": {"dojo": source_dojo},
        },
        admin_session,
    )
    assert response.status_code == 200, response.text
    assert dojo_logical_challenge_rows(destination_dojo) == {
        "module:source": source_rows["module:source"],
    }
    assert dojo_topology_database_state(source_dojo) == source_state


def test_community_import_final_topology_invariant(admin_session, random_user):
    user_name, _ = random_user
    user_id = get_user_id(user_name)
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"final-invariant-source-{suffix}"
    destination_id = f"final-destination-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    destination_dojo = create_transfer_dojo(
        destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    collision_id = create_challenge_type_collision(
        source_dojo,
        ("module", "collision"),
        "standard",
        user_id,
    )
    destination_database_id = int.from_bytes(
        bytes.fromhex(destination_dojo.rsplit("~", 1)[1]),
        "big",
        signed=True,
    )
    spec = transfer_dojo_spec(destination_id, [
        {"id": "keep"},
        {"id": "imported"},
    ])
    spec["modules"][0]["resources"][1]["import"] = {
        "dojo": source_dojo,
        "module": "module",
        "challenge": "source",
    }
    source_state = dojo_topology_database_state(source_dojo)
    destination_state = dojo_topology_database_state(destination_dojo)
    source_files = dojo_filesystem_state(source_dojo)
    destination_files = dojo_filesystem_state(destination_dojo)
    temporary_entries = dojo_temporary_entries()
    invariant_script = """
from CTFd.models import Challenges, db
from CTFd.plugins.dojo_plugin.models import DojoChallenges, Dojos
import CTFd.plugins.dojo_plugin.utils.dojo as dojo_utils

destination_id = __DESTINATION_ID__
collision_id = __COLLISION_ID__
spec = __SPEC__
real_init = DojoChallenges.__init__
corrupted = []

def inject_invalid_challenge(self, *args, **kwargs):
    imported = kwargs.get("default") is not None
    real_init(self, *args, **kwargs)
    if imported:
        self.challenge = Challenges.query.filter_by(id=collision_id).one()
        corrupted.append(self)

DojoChallenges.__init__ = inject_invalid_challenge
try:
    destination = Dojos.query.filter_by(dojo_id=destination_id).one()
    try:
        dojo_utils.dojo_from_spec(spec, dojo=destination)
    except AssertionError as error:
        assert corrupted
        assert str(error) == (
            "Dojo challenge association must reference a challenge of type `dojo`"
        )
    else:
        raise AssertionError("Final import topology invariant did not reject")
finally:
    db.session.rollback()
    DojoChallenges.__init__ = real_init

print("FINAL_IMPORT_TOPOLOGY_INVARIANT_OK")
"""
    invariant_script = (
        invariant_script
        .replace("__DESTINATION_ID__", repr(destination_database_id))
        .replace("__COLLISION_ID__", repr(collision_id))
        .replace("__SPEC__", repr(spec))
    )
    result = dojo_run(
        "dojo",
        "flask",
        input=invariant_script,
        check=False,
    )
    diagnostics = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode == 0, diagnostics
    assert "FINAL_IMPORT_TOPOLOGY_INVARIANT_OK" in result.stdout, diagnostics
    assert dojo_topology_database_state(source_dojo) == source_state
    assert dojo_topology_database_state(destination_dojo) == destination_state
    assert dojo_filesystem_state(source_dojo) == source_files
    assert dojo_filesystem_state(destination_dojo) == destination_files
    assert dojo_temporary_entries() == temporary_entries


def test_community_imports_reject_non_dojo_challenge_types(admin_session, random_user):
    user_name, _ = random_user
    user_id = get_user_id(user_name)

    for challenge_type in ("standard", "dynamic"):
        suffix = "".join(random.choices(string.ascii_lowercase, k=8))
        source_id = f"bad-src-{challenge_type}-{suffix}"
        destination_id = f"bad-dst-{challenge_type}-{suffix}"
        source_dojo = create_transfer_dojo(
            source_id,
            [{"id": "source"}],
            admin_session,
        )
        make_dojo_official(source_dojo, admin_session)
        destination_dojo = create_transfer_dojo(
            destination_id,
            [{"id": "keep"}],
            admin_session,
        )
        canonical_source_id = dojo_challenge_rows(source_dojo)["module:source"]
        collision_id = create_challenge_type_collision(
            source_dojo,
            ("module", "source"),
            challenge_type,
            user_id,
        )
        source_hex_id = source_dojo.rsplit("~", 1)[1]
        db_sql(
            "UPDATE dojo_challenges "
            f"SET challenge_id = {collision_id} "
            f"WHERE dojo_id = x'{source_hex_id}'::int AND id = 'source'"
        )
        assert dojo_logical_challenge_rows(source_dojo) == {
            "module:source": collision_id,
        }
        assert coordinate_challenge_rows(source_dojo, ("module", "source")) == {
            ("dojo", canonical_source_id),
            (challenge_type, collision_id),
        }

        individual_spec = transfer_dojo_spec(destination_id, [
            {"id": "keep"},
            {"id": "individual-import"},
        ])
        individual_spec["modules"][0]["resources"][1]["import"] = {
            "dojo": source_dojo,
            "module": "module",
            "challenge": "source",
        }
        module_spec = transfer_dojo_spec(destination_id, [{"id": "keep"}])
        module_spec["modules"].append({
            "id": "module-import",
            "name": "Module Import",
            "import": {
                "dojo": source_dojo,
                "module": "module",
            },
            "resources": [],
        })
        whole_dojo_spec = {
            "id": destination_id,
            "name": "Invalid Whole Dojo Import",
            "type": "public",
            "import": {"dojo": source_dojo},
        }

        source_state = dojo_topology_database_state(source_dojo)
        destination_state = dojo_topology_database_state(destination_dojo)
        source_files = dojo_filesystem_state(source_dojo)
        destination_files = dojo_filesystem_state(destination_dojo)
        temporary_entries = dojo_temporary_entries()

        for import_kind, spec in (
            ("individual", individual_spec),
            ("module", module_spec),
            ("whole-dojo", whole_dojo_spec),
        ):
            response = update_transfer_dojo(
                destination_dojo,
                spec,
                admin_session,
            )
            assert response.status_code == 400, (
                f"{challenge_type} {import_kind}: {response.text}"
            )
            assert response.json()["error"] == (
                "Dojo challenge association must reference a challenge of type `dojo`"
            )
            assert dojo_topology_database_state(source_dojo) == source_state
            assert dojo_topology_database_state(destination_dojo) == destination_state
            assert dojo_filesystem_state(source_dojo) == source_files
            assert dojo_filesystem_state(destination_dojo) == destination_files
            assert dojo_temporary_entries() == temporary_entries


def test_concurrent_community_import_alias_transfers_are_contained(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"import-source-{suffix}"
    source_dojo = create_transfer_dojo(source_id, [{"id": "source"}], admin_session)
    make_dojo_official(source_dojo, admin_session)
    source_rows = dojo_challenge_rows(source_dojo)
    source_challenge_id = source_rows["module:source"]
    source_flag_ids = challenge_flag_ids(source_challenge_id)
    user_name, user_session = random_user
    user_id = get_user_id(user_name)
    solve_id = int(db_sql(
        "INSERT INTO submissions "
        "(type, challenge_id, user_id, ip, provided, date) "
        f"VALUES ('correct', {source_challenge_id}, {user_id}, "
        "'127.0.0.1', 'test', NOW()) RETURNING id"
    ).strip())
    assert challenge_solve_ids(source_challenge_id) == (solve_id,)

    peer_ids = [f"import-peer-{index}-{suffix}" for index in range(2)]
    peer_dojos = []
    for peer_id in peer_ids:
        peer_spec = {
            "id": peer_id,
            "name": peer_id.replace("-", " ").title(),
            "type": "public",
            "modules": [{
                "id": "module",
                "name": "Module",
                "resources": [{
                    "type": "challenge",
                    "id": "alias",
                    "name": "Alias",
                    "import": {
                        "dojo": source_dojo,
                        "module": "module",
                        "challenge": "source",
                    },
                }],
            }],
        }
        peer_dojo = create_dojo_yml(
            yaml.safe_dump(peer_spec, sort_keys=False),
            session=admin_session,
        )
        grant_dojo_admin(peer_dojo, user_name, user_session, admin_session)
        peer_dojos.append(peer_dojo)

    expected_logical_rows = {"module:alias": source_challenge_id}
    assert all(dojo_challenge_rows(peer_dojo) == {} for peer_dojo in peer_dojos)
    assert all(
        dojo_logical_challenge_rows(peer_dojo) == expected_logical_rows
        for peer_dojo in peer_dojos
    )

    barrier = threading.Barrier(3)
    sessions = [clone_authenticated_session(user_session) for _ in peer_dojos]

    def transfer_alias(peer_id, peer_dojo, session):
        spec = transfer_dojo_spec(peer_id, [{
            "id": "moved",
            "transfer": {"challenge": "alias"},
        }])
        barrier.wait()
        return update_transfer_dojo(peer_dojo, spec, session)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(transfer_alias, peer_id, peer_dojo, session)
            for peer_id, peer_dojo, session in zip(peer_ids, peer_dojos, sessions)
        ]
        barrier.wait()
        responses = [future.result() for future in futures]
    for session in sessions:
        session.close()

    assert [response.status_code for response in responses] == [400, 400]
    assert dojo_challenge_rows(source_dojo) == source_rows
    assert challenge_flag_ids(source_challenge_id) == source_flag_ids
    assert challenge_solve_ids(source_challenge_id) == (solve_id,)
    assert challenge_transfer_provenance(source_challenge_id) is None
    assert all(dojo_challenge_rows(peer_dojo) == {} for peer_dojo in peer_dojos)
    assert all(
        dojo_logical_challenge_rows(peer_dojo) == expected_logical_rows
        for peer_dojo in peer_dojos
    )


def test_community_dojo_internal_transfer_supports_rename_and_swap(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"swap-{suffix}"
    renamed_dojo_id = f"renamed-{suffix}"
    dojo = create_transfer_dojo(
        dojo_id,
        [{"id": "alpha"}, {"id": "beta"}],
        admin_session,
    )
    user_name, user_session = random_user
    grant_dojo_admin(dojo, user_name, user_session, admin_session)
    original_rows = dojo_challenge_rows(dojo)

    swap_spec = transfer_dojo_spec(renamed_dojo_id, [
        {
            "id": "alpha",
            "transfer": {
                "dojo": dojo,
                "module": "module",
                "challenge": "beta",
            },
        },
        {
            "id": "beta",
            "transfer": {
                "dojo": dojo_id,
                "module": "module",
                "challenge": "alpha",
            },
        },
    ])
    response = update_transfer_dojo(dojo, swap_spec, user_session)
    assert response.status_code == 200, response.text

    renamed_dojo = f"{renamed_dojo_id}~{dojo.rsplit('~', 1)[1]}"
    expected_rows = {
        "module:alpha": original_rows["module:beta"],
        "module:beta": original_rows["module:alpha"],
    }
    assert dojo_challenge_rows(renamed_dojo) == expected_rows
    for _ in range(2):
        response = update_transfer_dojo(renamed_dojo, swap_spec, user_session)
        assert response.status_code == 200, response.text
        assert dojo_challenge_rows(renamed_dojo) == expected_rows


def test_community_dojo_admin_replays_durable_cross_transfer(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"replay-source-{suffix}"
    destination_id = f"replay-dest-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}, {"id": "other"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    source_rows = dojo_challenge_rows(source_dojo)
    transfer_spec = transfer_dojo_spec(destination_id, [{
        "id": "moved",
        "transfer": {
            "dojo": source_id,
            "module": "module",
            "challenge": "source",
        },
    }])
    destination_dojo = create_dojo_yml(
        yaml.safe_dump(transfer_spec, sort_keys=False),
        session=admin_session,
    )
    destination_hex_id = destination_dojo.rsplit("~", 1)[1]
    assert db_sql(
        "SELECT official FROM dojos "
        f"WHERE dojo_id = x'{destination_hex_id}'::int"
    ).strip() == "f"
    user_name, user_session = random_user
    grant_dojo_admin(destination_dojo, user_name, user_session, admin_session)
    user_id = get_user_id(user_name)
    assert db_sql(f"SELECT type FROM users WHERE id = {user_id}").strip() == "user"
    moved_id = source_rows["module:source"]
    solve_id = int(db_sql(
        "INSERT INTO submissions "
        "(type, challenge_id, user_id, ip, provided, date) "
        f"VALUES ('correct', {moved_id}, {user_id}, "
        "'127.0.0.1', 'durable-replay', NOW()) RETURNING id"
    ).strip())
    expected_destination_rows = {"module:moved": moved_id}
    expected_source_rows = {"module:other": source_rows["module:other"]}
    expected_flags = challenge_flag_ids(moved_id)
    expected_solves = challenge_solve_ids(moved_id)
    expected_state = challenge_database_state(moved_id)
    assert challenge_transfer_provenance(moved_id) == (
        "module", "moved", "1", "module", "source",
    )
    assert expected_flags
    assert solve_id in expected_solves
    assert dojo_challenge_rows(destination_dojo) == expected_destination_rows
    assert dojo_challenge_rows(source_dojo) == expected_source_rows

    marker = f"durable_replay_source_lock_{suffix}"
    source_lock = begin_pending_database_update(
        "SELECT dojo_id FROM dojos "
        f"WHERE dojo_id = x'{source_dojo.rsplit('~', 1)[1]}'::int FOR UPDATE",
        marker,
    )
    replay_session = clone_authenticated_session(user_session)
    replay_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        replay_future = replay_executor.submit(
            update_transfer_dojo,
            destination_dojo,
            transfer_spec,
            replay_session,
        )
        response = replay_future.result(timeout=10)
    finally:
        finish_database_transaction(source_lock, False)
        replay_executor.shutdown(wait=True, cancel_futures=True)
        replay_session.close()
    assert response.status_code == 200, response.text
    assert dojo_challenge_rows(destination_dojo) == expected_destination_rows
    assert dojo_challenge_rows(source_dojo) == expected_source_rows
    assert challenge_flag_ids(moved_id) == expected_flags
    assert challenge_solve_ids(moved_id) == expected_solves
    assert challenge_database_state(moved_id) == expected_state

    equivalent_spec = transfer_dojo_spec(destination_id, [{
        "id": "moved",
        "transfer": {
            "dojo": source_dojo,
            "module": "module",
            "challenge": "source",
        },
    }])
    response = update_transfer_dojo(
        destination_dojo,
        equivalent_spec,
        user_session,
    )
    assert response.status_code == 200, response.text
    assert dojo_challenge_rows(destination_dojo) == expected_destination_rows
    assert dojo_challenge_rows(source_dojo) == expected_source_rows
    assert challenge_flag_ids(moved_id) == expected_flags
    assert challenge_solve_ids(moved_id) == expected_solves
    assert challenge_database_state(moved_id) == expected_state

    conflicting_spec = transfer_dojo_spec(destination_id, [{
        "id": "moved",
        "transfer": {
            "dojo": source_dojo,
            "module": "module",
            "challenge": "other",
        },
    }])
    response = update_transfer_dojo(
        destination_dojo,
        conflicting_spec,
        user_session,
    )
    assert response.status_code == 400, response.text
    assert "conflicts with durable transfer provenance" in response.text
    assert dojo_challenge_rows(destination_dojo) == expected_destination_rows
    assert dojo_challenge_rows(source_dojo) == expected_source_rows
    assert challenge_flag_ids(moved_id) == expected_flags
    assert challenge_solve_ids(moved_id) == expected_solves
    assert challenge_database_state(moved_id) == expected_state

    conflicting_reference_spec = transfer_dojo_spec(destination_id, [{
        "id": "moved",
        "transfer": {
            "dojo": f"missing-{suffix}",
            "module": "module",
            "challenge": "source",
        },
    }])
    response = update_transfer_dojo(
        destination_dojo,
        conflicting_reference_spec,
        user_session,
    )
    assert response.status_code == 400, response.text
    assert "conflicts with durable transfer provenance" in response.text
    assert dojo_challenge_rows(destination_dojo) == expected_destination_rows
    assert dojo_challenge_rows(source_dojo) == expected_source_rows
    assert challenge_flag_ids(moved_id) == expected_flags
    assert challenge_solve_ids(moved_id) == expected_solves
    assert challenge_database_state(moved_id) == expected_state


def test_transfer_limits_reject_before_source_lookup(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    destination_id = f"limit-dest-{suffix}"
    destination_dojo = create_transfer_dojo(
        destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    oversized_spec = transfer_dojo_spec(
        destination_id,
        [
            {
                "id": f"moved-{index}",
                "transfer": {
                    "dojo": f"missing-{index}",
                    "module": "module",
                    "challenge": "source",
                },
            }
            for index in range(129)
        ],
    )
    original_rows = dojo_challenge_rows(destination_dojo)
    response = update_transfer_dojo(
        destination_dojo,
        oversized_spec,
        admin_session,
    )
    assert response.status_code == 400, response.text
    assert "Too many dojo references participate in one update" in response.text
    assert dojo_challenge_rows(destination_dojo) == original_rows

    destination_database_id = int.from_bytes(
        bytes.fromhex(destination_dojo.rsplit("~", 1)[1]),
        "big",
        signed=True,
    )
    lookup_script = f"""
from unittest.mock import patch
from sqlalchemy import event
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import Dojos
import CTFd.plugins.dojo_plugin.utils.dojo as dojo_utils

destination_id = {destination_database_id!r}
reference_spec = {oversized_spec!r}
request_spec = {{
    "id": "request-limit",
    "name": "Request Limit",
    "type": "public",
    "modules": [{{
        "id": "module",
        "name": "Module",
        "resources": [
            {{
                "type": "challenge",
                "id": f"moved-{{index}}",
                "name": f"Moved {{index}}",
                "image": "pwncollege-challenge",
                "transfer": {{
                    "dojo": "missing",
                    "module": "module",
                    "challenge": "source",
                }},
            }}
            for index in range(dojo_utils.MAX_TRANSFER_REQUESTS + 1)
        ],
    }}],
}}
reference_spec = dojo_utils.DOJO_SPEC.validate(reference_spec)
request_spec = dojo_utils.DOJO_SPEC.validate(request_spec)
statements = []

def record_statement(*args):
    statements.append(args[2])

def assert_rejected(spec, message):
    try:
        dojo_utils.transfer_lock_dojo_ids(spec, destination_id)
    except RuntimeError as error:
        assert str(error) == message
    else:
        raise AssertionError("Oversized transfer plan was accepted")

with patch.object(Dojos, "from_id", wraps=Dojos.from_id) as lookup, patch.object(
    dojo_utils,
    "transfer_reference_dojo_ids",
    wraps=dojo_utils.transfer_reference_dojo_ids,
) as resolver:
    event.listen(db.engine, "before_cursor_execute", record_statement)
    try:
        assert_rejected(
            reference_spec,
            "Too many dojo references participate in one update",
        )
        assert_rejected(
            request_spec,
            "Too many challenge transfers in one update",
        )
    finally:
        event.remove(db.engine, "before_cursor_execute", record_statement)
    lookup.assert_not_called()
    resolver.assert_not_called()

assert statements == []
print("TRANSFER_LIMITS_PRECEDE_LOOKUPS")
"""
    result = dojo_run("dojo", "flask", input=f"exec({lookup_script!r})\n")
    assert "TRANSFER_LIMITS_PRECEDE_LOOKUPS" in result.stdout


def test_community_dojo_cross_transfer_is_denied(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"source-{suffix}"
    destination_id = f"dest-{suffix}"
    source_dojo = create_transfer_dojo(source_id, [{"id": "source"}], admin_session)
    destination_dojo = create_transfer_dojo(destination_id, [{"id": "keep"}], admin_session)
    user_name, user_session = random_user
    grant_dojo_admin(source_dojo, user_name, user_session, admin_session)
    grant_dojo_admin(destination_dojo, user_name, user_session, admin_session)
    make_dojo_official(source_dojo, admin_session)
    source_rows = dojo_challenge_rows(source_dojo)
    destination_rows = dojo_challenge_rows(destination_dojo)

    transfer_spec = transfer_dojo_spec(destination_id, [
        {"id": "keep"},
        {
            "id": "moved",
            "transfer": {
                "dojo": source_id,
                "module": "module",
                "challenge": "source",
            },
        },
    ])
    marker = f"forbidden_transfer_source_lock_{suffix}"
    source_lock = begin_pending_database_update(
        "SELECT dojo_id FROM dojos "
        f"WHERE dojo_id = x'{source_dojo.rsplit('~', 1)[1]}'::int FOR UPDATE",
        marker,
    )
    denied_session = clone_authenticated_session(user_session)
    denied_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        denied_future = denied_executor.submit(
            update_transfer_dojo,
            destination_dojo,
            transfer_spec,
            denied_session,
        )
        response = denied_future.result(timeout=10)
    finally:
        finish_database_transaction(source_lock, False)
        denied_executor.shutdown(wait=True, cancel_futures=True)
        denied_session.close()
    assert response.status_code == 400, response.text
    assert dojo_challenge_rows(source_dojo) == source_rows
    assert dojo_challenge_rows(destination_dojo) == destination_rows

    make_dojo_official(destination_dojo, admin_session)
    response = update_transfer_dojo(destination_dojo, transfer_spec, user_session)
    assert response.status_code == 200, response.text
    assert dojo_challenge_rows(source_dojo) == {}
    assert dojo_challenge_rows(destination_dojo) == {
        "module:keep": destination_rows["module:keep"],
        "module:moved": source_rows["module:source"],
    }
    moved_id = source_rows["module:source"]
    moved_flag_ids = challenge_flag_ids(moved_id)

    replacement_response = update_transfer_dojo(
        source_dojo,
        transfer_dojo_spec(source_id, [{"id": "source"}]),
        user_session,
    )
    assert replacement_response.status_code == 200, replacement_response.text
    replacement_rows = dojo_challenge_rows(source_dojo)
    replacement_id = replacement_rows["module:source"]
    replacement_flag_ids = challenge_flag_ids(replacement_id)
    assert replacement_id != moved_id

    db_sql(
        "DELETE FROM dojo_challenge_transfer_provenances "
        f"WHERE challenge_id = {moved_id}"
    )
    assert challenge_transfer_provenance(moved_id) is None
    response = update_transfer_dojo(destination_dojo, transfer_spec, user_session)
    assert response.status_code == 200, response.text
    assert dojo_challenge_rows(source_dojo) == replacement_rows
    assert dojo_challenge_rows(destination_dojo) == {
        "module:keep": destination_rows["module:keep"],
        "module:moved": moved_id,
    }
    assert challenge_flag_ids(moved_id) == moved_flag_ids
    assert challenge_flag_ids(replacement_id) == replacement_flag_ids
    assert challenge_transfer_provenance(moved_id) == (
        "module", "moved", "1", "module", "source",
    )

    db_sql(
        "DELETE FROM dojo_challenge_transfer_provenances "
        f"WHERE challenge_id = {moved_id}"
    )
    delete_response = admin_session.post(
        f"{DOJO_URL}/dojo/{source_dojo}/delete/",
        json={"dojo": source_dojo},
    )
    assert delete_response.status_code == 200, delete_response.text
    assert challenge_transfer_provenance(moved_id) is None
    response = update_transfer_dojo(destination_dojo, transfer_spec, user_session)
    assert response.status_code == 200, response.text
    assert challenge_transfer_provenance(moved_id) == (
        "module", "moved", "1", "module", "source",
    )
    assert challenge_transfer_source_dojo_id(moved_id) == "NULL"
    response = update_transfer_dojo(destination_dojo, transfer_spec, user_session)
    assert response.status_code == 200, response.text


def test_global_admin_transfers_into_unique_community_dojo(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"global-source-{suffix}"
    destination_id = f"global-destination-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}],
        admin_session,
    )
    destination_dojo = create_transfer_dojo(
        destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    source_challenge_id = dojo_challenge_rows(source_dojo)["module:source"]
    transfer_spec = transfer_dojo_spec(destination_id, [
        {"id": "keep"},
        {
            "id": "moved",
            "transfer": {
                "dojo": source_id,
                "module": "module",
                "challenge": "source",
            },
        },
    ])

    marker = f"global_transfer_source_lock_{suffix}"
    source_lock = begin_pending_database_update(
        "SELECT dojo_id FROM dojos "
        f"WHERE dojo_id = x'{source_dojo.rsplit('~', 1)[1]}'::int FOR UPDATE",
        marker,
    )
    update_session = clone_authenticated_session(admin_session)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            update_transfer_dojo,
            destination_dojo,
            transfer_spec,
            update_session,
        )
        wait_for_update_database_lock(future, "dojos.dojo_id IN")
        finish_database_transaction(source_lock, False)
        response = future.result(timeout=10)
    finally:
        finish_database_transaction(source_lock, False)
        executor.shutdown(wait=True, cancel_futures=True)
        update_session.close()
    assert response.status_code == 200, response.text
    assert dojo_challenge_rows(destination_dojo)["module:moved"] == (
        source_challenge_id
    )


def test_official_twin_blocks_global_transfer_into_community_dojo(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"twin-source-{suffix}"
    destination_id = f"twin-destination-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}],
        admin_session,
    )
    destination_dojo = create_transfer_dojo(
        destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    official_twin = create_transfer_dojo(
        destination_id,
        [{"id": "twin"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    make_dojo_official(official_twin, admin_session)
    source_rows = dojo_challenge_rows(source_dojo)
    destination_rows = dojo_challenge_rows(destination_dojo)
    transfer_spec = transfer_dojo_spec(destination_id, [
        {"id": "keep"},
        {
            "id": "moved",
            "transfer": {
                "dojo": source_id,
                "module": "module",
                "challenge": "source",
            },
        },
    ])

    response = update_transfer_dojo(
        destination_dojo,
        transfer_spec,
        admin_session,
    )
    assert response.status_code == 400, response.text
    assert "Permission denied" in response.json()["error"]
    assert dojo_challenge_rows(source_dojo) == source_rows
    assert dojo_challenge_rows(destination_dojo) == destination_rows


def test_global_transfer_rename_to_official_twin_is_denied(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"rename-deny-source-{suffix}"
    old_destination_id = f"rename-old-{suffix}"
    proposed_destination_id = f"rename-twin-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}],
        admin_session,
    )
    destination_dojo = create_transfer_dojo(
        old_destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    official_twin = create_transfer_dojo(
        proposed_destination_id,
        [{"id": "twin"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    make_dojo_official(official_twin, admin_session)
    source_rows = dojo_challenge_rows(source_dojo)
    destination_rows = dojo_challenge_rows(destination_dojo)
    transfer_spec = transfer_dojo_spec(proposed_destination_id, [
        {"id": "keep"},
        {
            "id": "moved",
            "transfer": {
                "dojo": source_id,
                "module": "module",
                "challenge": "source",
            },
        },
    ])
    source_lock = begin_pending_database_update(
        "SELECT dojo_id FROM dojos "
        f"WHERE dojo_id = x'{source_dojo.rsplit('~', 1)[1]}'::int FOR UPDATE",
        f"rename_to_twin_source_probe_{suffix}",
    )
    update_session = clone_authenticated_session(admin_session)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            update_transfer_dojo,
            destination_dojo,
            transfer_spec,
            update_session,
        )
        response = future.result(timeout=10)
    finally:
        finish_database_transaction(source_lock, False)
        executor.shutdown(wait=True, cancel_futures=True)
        update_session.close()

    assert response.status_code == 400, response.text
    assert "Permission denied" in response.json()["error"]
    assert db_sql(
        "SELECT id FROM dojos "
        f"WHERE dojo_id = x'{destination_dojo.rsplit('~', 1)[1]}'::int"
    ).strip() == old_destination_id
    assert dojo_challenge_rows(source_dojo) == source_rows
    assert dojo_challenge_rows(destination_dojo) == destination_rows


def test_global_transfer_rename_away_from_official_twin_is_allowed(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"rename-allow-source-{suffix}"
    old_destination_id = f"rename-shared-{suffix}"
    proposed_destination_id = f"rename-unique-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}],
        admin_session,
    )
    destination_dojo = create_transfer_dojo(
        old_destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    official_twin = create_transfer_dojo(
        old_destination_id,
        [{"id": "twin"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    make_dojo_official(official_twin, admin_session)
    source_challenge_id = dojo_challenge_rows(source_dojo)["module:source"]
    transfer_spec = transfer_dojo_spec(proposed_destination_id, [
        {"id": "keep"},
        {
            "id": "moved",
            "transfer": {
                "dojo": source_id,
                "module": "module",
                "challenge": "source",
            },
        },
    ])
    source_lock = begin_pending_database_update(
        "SELECT dojo_id FROM dojos "
        f"WHERE dojo_id = x'{source_dojo.rsplit('~', 1)[1]}'::int FOR UPDATE",
        f"rename_from_twin_source_lock_{suffix}",
    )
    update_session = clone_authenticated_session(admin_session)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            update_transfer_dojo,
            destination_dojo,
            transfer_spec,
            update_session,
        )
        wait_for_update_database_lock(future, "dojos.dojo_id IN")
        finish_database_transaction(source_lock, False)
        response = future.result(timeout=10)
    finally:
        finish_database_transaction(source_lock, False)
        executor.shutdown(wait=True, cancel_futures=True)
        update_session.close()

    assert response.status_code == 200, response.text
    assert db_sql(
        "SELECT id FROM dojos "
        f"WHERE dojo_id = x'{destination_dojo.rsplit('~', 1)[1]}'::int"
    ).strip() == proposed_destination_id
    assert dojo_challenge_rows(destination_dojo)["module:moved"] == (
        source_challenge_id
    )


def test_global_transfer_serializes_with_same_id_promotion(
    admin_session,
    random_user,
):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"promotion-source-{suffix}"
    destination_id = f"promotion-dest-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}],
        admin_session,
    )
    destination_dojo = create_transfer_dojo(
        destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    promotion_dojo = create_transfer_dojo(
        destination_id,
        [{"id": "promotion"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    user_name, user_session = random_user
    user_id = get_user_id(user_name)
    promotion = admin_session.patch(
        f"{DOJO_URL}/api/v1/users/{user_id}",
        json={"type": "admin"},
    )
    assert promotion.status_code == 200, promotion.text
    source_rows = dojo_challenge_rows(source_dojo)
    destination_rows = dojo_challenge_rows(destination_dojo)
    transfer_spec = transfer_dojo_spec(destination_id, [
        {"id": "keep"},
        {
            "id": "moved",
            "transfer": {
                "dojo": source_id,
                "module": "module",
                "challenge": "source",
            },
        },
    ])
    promotion_row_lock = begin_pending_database_update(
        "SELECT dojo_id FROM dojos "
        f"WHERE dojo_id = x'{promotion_dojo.rsplit('~', 1)[1]}'::int FOR UPDATE",
        f"promotion_row_lock_{suffix}",
    )
    promotion_session = clone_authenticated_session(user_session)
    update_session = clone_authenticated_session(admin_session)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        promotion_future = executor.submit(
            promote_dojo_request,
            promotion_dojo,
            promotion_session,
        )
        wait_for_update_database_lock(
            promotion_future,
            "dojos.dojo_id IN",
        )
        update_future = executor.submit(
            update_transfer_dojo,
            destination_dojo,
            transfer_spec,
            update_session,
        )
        wait_for_advisory_database_lock(update_future)
        finish_database_transaction(promotion_row_lock, False)
        promotion_response = promotion_future.result(timeout=10)
        update_response = update_future.result(timeout=10)
    finally:
        finish_database_transaction(promotion_row_lock, False)
        executor.shutdown(wait=True, cancel_futures=True)
        promotion_session.close()
        update_session.close()
        restoration = admin_session.patch(
            f"{DOJO_URL}/api/v1/users/{user_id}",
            json={"type": "user"},
        )
        assert restoration.status_code == 200, restoration.text

    assert promotion_response.status_code == 200, promotion_response.text
    assert update_response.status_code == 400, update_response.text
    assert "Permission denied" in update_response.json()["error"]
    assert db_sql(
        "SELECT official FROM dojos "
        f"WHERE dojo_id = x'{promotion_dojo.rsplit('~', 1)[1]}'::int"
    ).strip() == "t"
    assert dojo_challenge_rows(source_dojo) == source_rows
    assert dojo_challenge_rows(destination_dojo) == destination_rows


def test_concurrent_community_dojo_internal_transfers_serialize(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"concurrent-{suffix}"
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    user_name, user_session = random_user
    grant_dojo_admin(dojo, user_name, user_session, admin_session)
    source_id = dojo_challenge_rows(dojo)["module:source"]
    barrier = threading.Barrier(3)
    sessions = [clone_authenticated_session(user_session) for _ in range(2)]

    def competing_update(session, destination):
        spec = transfer_dojo_spec(dojo_id, [{
            "id": destination,
            "transfer": {"challenge": "source"},
        }])
        barrier.wait()
        return destination, update_transfer_dojo(dojo, spec, session)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(competing_update, session, destination)
            for session, destination in zip(sessions, ["first", "second"])
        ]
        barrier.wait()
        results = [future.result() for future in futures]
    for session in sessions:
        session.close()

    assert sorted(response.status_code for _, response in results) == [200, 400]
    winner = next(
        destination
        for destination, response in results
        if response.status_code == 200
    )
    loser = next(
        destination
        for destination, response in results
        if response.status_code == 400
    )
    assert dojo_challenge_rows(dojo) == {f"module:{winner}": source_id}
    assert challenge_transfer_provenance(source_id) == (
        "module", winner, "1", "module", "source",
    )
    assert not db_sql(
        "SELECT id FROM challenges "
        f"WHERE category = '{dojo.rsplit('~', 1)[1]}' "
        f"AND (name LIKE '__move__%' OR name = 'module:{loser}')"
    ).strip()


def test_transfer_lock_refreshes_preloaded_dojo_topology(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"stale-topology-{suffix}"
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    source_id = dojo_challenge_rows(dojo)["module:source"]
    moved_spec = transfer_dojo_spec(dojo_id, [{
        "id": "moved",
        "transfer": {"challenge": "source"},
    }])
    moved_spec["modules"].append({
        "id": "extra",
        "name": "Extra",
        "resources": [],
    })
    dojo_database_id = int.from_bytes(
        bytes.fromhex(dojo.rsplit("~", 1)[1]),
        "big",
        signed=True,
    )
    concurrency_script = """
import threading
import time
from flask import current_app
from sqlalchemy import text
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import Dojos
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_spec

app = current_app._get_current_object()
dojo_id = __DOJO_ID__
source_id = __SOURCE_ID__
spec = __SPEC__
first_flushed = threading.Event()
release_first = threading.Event()
second_ready = threading.Event()
second_finished = threading.Event()
backend_pids = {}
topology = {}
errors = []

def challenge_topology(dojo):
    return tuple(
        (challenge.module.id, challenge.id, challenge.challenge_id)
        for challenge in dojo.challenges
    )

def first_update():
    with app.app_context():
        try:
            dojo = Dojos.query.filter_by(dojo_id=dojo_id).one()
            backend_pids["first"] = db.session.execute(
                text("SELECT pg_backend_pid()")
            ).scalar()
            dojo_from_spec(spec, dojo=dojo)
            db.session.flush()
            first_flushed.set()
            assert release_first.wait(10)
            db.session.commit()
        except BaseException as error:
            errors.append(("first", repr(error)))
            db.session.rollback()
            first_flushed.set()
            release_first.set()

def second_update():
    assert first_flushed.wait(10)
    with app.app_context():
        try:
            dojo = Dojos.query.filter_by(dojo_id=dojo_id).one()
            topology["stale_modules"] = tuple(module.id for module in dojo.modules)
            topology["stale_challenges"] = challenge_topology(dojo)
            assert topology["stale_modules"] == ("module",)
            assert topology["stale_challenges"] == (("module", "source", source_id),)
            backend_pids["second"] = db.session.execute(
                text("SELECT pg_backend_pid()")
            ).scalar()
            second_ready.set()
            locked_dojo = Dojos.lock_ids_for_update({dojo_id})[dojo_id]
            topology["fresh_modules"] = tuple(
                module.id for module in locked_dojo.modules
            )
            topology["fresh_challenges"] = challenge_topology(locked_dojo)
            db.session.rollback()
        except BaseException as error:
            errors.append(("second", repr(error)))
            db.session.rollback()
            second_ready.set()
        finally:
            second_finished.set()

first_thread = threading.Thread(target=first_update)
second_thread = threading.Thread(target=second_update)
first_thread.start()
assert first_flushed.wait(10), errors
second_thread.start()
assert second_ready.wait(10), errors
blocked = False
deadline = time.monotonic() + 10
while time.monotonic() < deadline and not second_finished.is_set():
    wait_event_type = db.session.execute(
        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
        {"pid": backend_pids["second"]},
    ).scalar()
    if wait_event_type == "Lock":
        blocked = True
        break
    time.sleep(0.05)
try:
    assert blocked, (errors, backend_pids, topology)
    assert not second_finished.is_set()
finally:
    release_first.set()
first_thread.join(10)
second_thread.join(10)
assert not first_thread.is_alive()
assert not second_thread.is_alive()
assert errors == []
assert backend_pids["first"] != backend_pids["second"]
assert topology["fresh_modules"] == ("module", "extra")
assert topology["fresh_challenges"] == (("module", "moved", source_id),)
print("TRANSFER_TOPOLOGY_REFRESHED")
"""
    concurrency_script = (
        concurrency_script
        .replace("__DOJO_ID__", repr(dojo_database_id))
        .replace("__SOURCE_ID__", repr(source_id))
        .replace("__SPEC__", repr(moved_spec))
    )
    result = dojo_run("dojo", "flask", input=concurrency_script)
    assert "TRANSFER_TOPOLOGY_REFRESHED" in result.stdout
    assert dojo_challenge_rows(dojo) == {"module:moved": source_id}


def test_dojo_update_revalidates_concurrent_admin_demotion(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    dojo_id = f"demotion-{suffix}"
    dojo = create_transfer_dojo(dojo_id, [{"id": "source"}], admin_session)
    user_name, user_session = random_user
    grant_dojo_admin(dojo, user_name, user_session, admin_session)
    user_id = get_user_id(user_name)
    original_rows = dojo_challenge_rows(dojo)
    marker = f"demotion_race_{suffix}"
    transaction = begin_pending_database_update(
        "UPDATE dojo_users SET type = 'member' "
        f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int "
        f"AND user_id = {user_id}",
        marker,
    )
    update_session = clone_authenticated_session(user_session)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        transfer_spec = transfer_dojo_spec(dojo_id, [{
            "id": "moved",
            "transfer": {"challenge": "source"},
        }])
        future = executor.submit(
            update_transfer_dojo,
            dojo,
            transfer_spec,
            update_session,
        )
        wait_for_update_database_lock(future, "dojo_users")
        finish_database_transaction(transaction, True)
        response = future.result(timeout=10)
        assert response.status_code == 403, response.text
    finally:
        finish_database_transaction(transaction, False)
        executor.shutdown(wait=True, cancel_futures=True)
        update_session.close()

    assert dojo_challenge_rows(dojo) == original_rows
    assert challenge_transfer_provenance(original_rows["module:source"]) is None
    assert db_sql(
        "SELECT type FROM dojo_users "
        f"WHERE dojo_id = x'{dojo.rsplit('~', 1)[1]}'::int "
        f"AND user_id = {user_id}"
    ).strip() == "member"


def test_dojo_update_revalidates_concurrent_global_admin_demotion(admin_session, random_user):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    source_id = f"global-demotion-source-{suffix}"
    destination_id = f"global-demotion-dest-{suffix}"
    source_dojo = create_transfer_dojo(
        source_id,
        [{"id": "source"}],
        admin_session,
    )
    destination_dojo = create_transfer_dojo(
        destination_id,
        [{"id": "keep"}],
        admin_session,
    )
    make_dojo_official(source_dojo, admin_session)
    user_name, user_session = random_user
    user_id = get_user_id(user_name)
    promotion = admin_session.patch(
        f"{DOJO_URL}/api/v1/users/{user_id}",
        json={"type": "admin"},
    )
    assert promotion.status_code == 200, promotion.text
    assert db_sql(f"SELECT type FROM users WHERE id = {user_id}").strip() == "admin"
    assert db_sql(
        "SELECT count(*) FROM dojo_users "
        f"WHERE dojo_id = x'{destination_dojo.rsplit('~', 1)[1]}'::int "
        f"AND user_id = {user_id}"
    ).strip() == "0"

    source_rows = dojo_challenge_rows(source_dojo)
    destination_rows = dojo_challenge_rows(destination_dojo)
    marker = f"global_demotion_race_{suffix}"
    transaction = None
    update_session = clone_authenticated_session(user_session)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = None
    try:
        transaction = begin_pending_database_update(
            f"UPDATE users SET type = 'user' WHERE id = {user_id}",
            marker,
        )
        transfer_spec = transfer_dojo_spec(destination_id, [
            {"id": "keep"},
            {
                "id": "moved",
                "transfer": {
                    "dojo": source_id,
                    "module": "module",
                    "challenge": "source",
                },
            },
        ])
        future = executor.submit(
            update_transfer_dojo,
            destination_dojo,
            transfer_spec,
            update_session,
        )
        wait_for_update_database_lock(future, "users.type", "dojo_users")
        source_probe = begin_pending_database_update(
            "SELECT dojo_id FROM dojos "
            f"WHERE dojo_id = x'{source_dojo.rsplit('~', 1)[1]}'::int FOR UPDATE",
            f"global_demotion_source_probe_{suffix}",
        )
        finish_database_transaction(source_probe, False)
        finish_database_transaction(transaction, True)
        response = future.result(timeout=10)
        assert response.status_code == 403, response.text
    finally:
        if transaction is not None:
            finish_database_transaction(transaction, False)
        executor.shutdown(wait=True, cancel_futures=True)
        update_session.close()
        restoration = admin_session.patch(
            f"{DOJO_URL}/api/v1/users/{user_id}",
            json={"type": "user"},
        )
        assert restoration.status_code == 200, restoration.text

    assert dojo_challenge_rows(source_dojo) == source_rows
    assert dojo_challenge_rows(destination_dojo) == destination_rows
    assert challenge_transfer_provenance(source_rows["module:source"]) is None
    assert db_sql(f"SELECT type FROM users WHERE id = {user_id}").strip() == "user"


def test_transfer_dojo_cases_leave_no_image_pull_backlog():
    regression_script = f"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from CTFd.plugins.dojo_plugin.utils.background_stats import get_redis_client
from CTFd.plugins.dojo_plugin.utils.image_pulls import IMAGE_PULL_STREAM_NAME, enqueue_dojo_image_pulls

image = {TRANSFER_TEST_IMAGE!r}
dojo = SimpleNamespace(
    modules=[SimpleNamespace(challenges=[SimpleNamespace(data={{"image": image}})])],
    reference_id="transfer-test",
)

with patch("CTFd.plugins.dojo_plugin.utils.image_pulls.publish_image_pull") as publish:
    enqueue_dojo_image_pulls(dojo)
    publish.assert_not_called()

queued_events = [
    json.loads(fields["data"])
    for _, fields in get_redis_client().xrange(IMAGE_PULL_STREAM_NAME)
]
assert not [event for event in queued_events if event.get("image") == image]
print("TRANSFER_IMAGE_QUEUE_EMPTY")
"""
    result = dojo_run("dojo", "flask", input=f"exec({regression_script!r})\n")
    assert "TRANSFER_IMAGE_QUEUE_EMPTY" in result.stdout


def test_create_dojo_pulls_image(admin_session):
    spec = {
        "id": "hello-world-pull",
        "type": "public",
        "modules": [
            {
                "id": "hello",
                "resources": [
                    {
                        "type": "challenge",
                        "id": "hello-world",
                        "name": "Hello World",
                        "image": "hello-world",
                    },
                ],
            },
        ],
    }
    dojo_reference_id = create_dojo_yml(
        yaml.safe_dump(spec, sort_keys=False),
        session=admin_session,
    )

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            start_challenge(dojo_reference_id, "hello", "hello-world", session=admin_session)
            return
        except AssertionError:
            time.sleep(2)
    raise AssertionError("Failed to start hello-world challenge within 60s")


def test_import(import_dojo, admin_session):
    assert admin_session.get(f"{DOJO_URL}/{import_dojo}/hello").status_code == 200

# this exists despite test_import because it doesn't re-run on re-test, but we still want to make sure our public example-import dojo passes
def test_create_import_dojo(example_import_dojo, admin_session):
    assert admin_session.get(f"{DOJO_URL}/{example_import_dojo}/").status_code == 200
    assert admin_session.get(f"{DOJO_URL}/{example_import_dojo}/").status_code == 200

def test_join_dojo(admin_session, guest_dojo_admin, example_dojo):
    random_user_name, random_session = guest_dojo_admin
    response = random_session.get(f"{DOJO_URL}/dojo/{example_dojo}/join/")
    assert response.status_code == 200
    response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert response.status_code == 200
    assert random_user_name in response.text and response.text.index("Members") < response.text.index(random_user_name)


def test_admin_page_shows_deploy_key(admin_session, example_dojo):
    if "~" in example_dojo:
        dojo_id_hex = example_dojo.split("~", 1)[1]
        public_key = db_sql(f"SELECT public_key FROM dojos WHERE dojo_id = x'{dojo_id_hex}'::int")
    else:
        public_key = db_sql(f"SELECT public_key FROM dojos WHERE id = '{example_dojo}' ORDER BY dojo_id DESC LIMIT 1")
    public_key = public_key.strip()

    response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert response.status_code == 200
    assert "Deploy Key" in response.text
    assert public_key in response.text


def test_promote_dojo_member(admin_session, guest_dojo_admin, example_dojo):
    random_user_name, _ = guest_dojo_admin
    random_user_id = get_user_id(random_user_name)
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/admins/promote", json={"user_id": random_user_id})
    assert response.status_code == 200
    response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert random_user_name in response.text and response.text.index("Members") > response.text.index(random_user_name)


def test_dojo_completion_emoji(simple_award_dojo, codepoints_award_dojo, completionist_user):
    user_name, session = completionist_user

    wait_for_background_worker(timeout=1)

    scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{codepoints_award_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 2
    assert len(us["badges"]) == 2

    scoreboard = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{simple_award_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 2
    assert len(us["badges"]) == 2


def test_no_practice(no_practice_challenge_dojo, no_practice_dojo, random_user_session):
    for dojo in [ no_practice_challenge_dojo, no_practice_dojo ]:
        response = random_user_session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
        assert response.status_code == 200
        response = random_user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker", json={
            "dojo": dojo,
            "module": "test",
            "challenge": "test",
            "practice": True
        })
        assert response.status_code == 200
        assert not response.json()["success"]
        assert "practice" in response.json()["error"]


def test_no_import(no_import_challenge_dojo, admin_session):
    try:
        create_dojo_yml(open(
            TEST_DOJOS_LOCATION / "forbidden_import.yml"
        ).read().replace("no-import-challenge", no_import_challenge_dojo), session=admin_session)
    except AssertionError as e:
        assert "Import disallowed" in str(e)
    else:
        raise AssertionError("forbidden-import dojo creation should have failed, but it succeeded")


def test_prune_dojo_emoji(simple_award_dojo, admin_session, completionist_user):
    user_name, _ = completionist_user
    db_sql(f"DELETE FROM submissions WHERE id IN (SELECT id FROM submissions WHERE user_id={get_user_id(user_name)} ORDER BY id LIMIT 1)")

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{simple_award_dojo}/awards/prune", json={})
    assert response.status_code == 200

    wait_for_background_worker(timeout=2)

    scoreboard = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{simple_award_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 1
    assert len(us["badges"]) == 2
    assert us["badges"][0]["stale"] == True


def test_dojo_removes_emoji(simple_award_dojo, admin_session, completionist_user):
    user_name, _ = completionist_user

    scoreboard = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{simple_award_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 2
    assert len(us["badges"]) == 2
    assert us["badges"][0]["stale"] == False

    dojo_id = simple_award_dojo.split("~")[1]
    db_sql(f"UPDATE dojos SET data = data - 'award' || jsonb_build_object('award', jsonb_build_object('belt', 'orange')) WHERE dojo_id = x'{dojo_id}'::int")

    scoreboard = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{simple_award_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == user_name)
    assert us["solves"] == 2
    assert len(us["badges"]) == 1


def test_lfs(lfs_dojo, random_user_name, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/dojo/{lfs_dojo}/join/").status_code == 200
    start_challenge(lfs_dojo, "test", "test", session=random_user_session)
    try:
        workspace_run("[ -f '/challenge/dojo.txt' ]", user=random_user_name)
    except subprocess.CalledProcessError:
        assert False, "LFS didn't create dojo.txt"


def test_import_override(import_override_dojo, random_user_name, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/dojo/{import_override_dojo}/join/").status_code == 200
    start_challenge(import_override_dojo, "test", "test", session=random_user_session)
    try:
        workspace_run("[ -f '/challenge/boom' ]", user=random_user_name)
        workspace_run("[ ! -f '/challenge/apple' ]", user=random_user_name)
    except subprocess.CalledProcessError:
        assert False, "dojo_initialize_files didn't create /challenge/boom"


def test_challenge_transfer(transfer_src_dojo, transfer_dst_dojo, random_user_name, random_user_session):
    assert random_user_session.get(f"{DOJO_URL}/dojo/{transfer_src_dojo}/join/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/dojo/{transfer_dst_dojo}/join/").status_code == 200
    start_challenge(transfer_dst_dojo, "dst-module", "dst-challenge", session=random_user_session)
    solve_challenge(transfer_dst_dojo, "dst-module", "dst-challenge", session=random_user_session, user=random_user_name)
    wait_for_background_worker()
    scoreboard = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{transfer_src_dojo}/_/0/1").json()
    us = next(u for u in scoreboard["standings"] if u["name"] == random_user_name)
    assert us["solves"] == 1


def test_hidden_challenges(admin_session, random_user_session, hidden_challenges_dojo):
    assert "CHALLENGE" in admin_session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text
    assert random_user_session.get(f"{DOJO_URL}/dojo/{hidden_challenges_dojo}/join/").status_code == 200
    assert random_user_session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").status_code == 200
    assert "CHALLENGE" not in random_user_session.get(f"{DOJO_URL}/{hidden_challenges_dojo}/module/").text


def test_dojo_solves_api(example_dojo, random_user_name, random_user_session):
    random_id = "".join(random.choices(string.ascii_lowercase, k=16))
    other_session = login(random_id, random_id, register=True)

    start_challenge(example_dojo, "hello", "apple", session=random_user_session)
    solve_challenge(example_dojo, "hello", "apple", session=random_user_session, user=random_user_name)

    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves")
    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    assert len(data["solves"]) == 1
    assert data["solves"][0]["challenge_id"] == "apple"

    response = other_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves", params={"username": random_user_name})
    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    assert len(data["solves"]) == 1
    assert data["solves"][0]["challenge_id"] == "apple"


def test_grant_award(admin_user, event_dojo):
    admin_name, admin_session = admin_user
    assert admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{event_dojo}/award/grant", json={"user_id": get_user_id(admin_name), "emoji": "🥈", "description": "This is a test emoji"}).status_code == 200


def test_no_award(admin_user, example_dojo):
    admin_name, admin_session = admin_user
    assert admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/award/grant", json={"user_id": get_user_id(admin_name), "emoji": "🥈", "description": "This is a test emoji"}).status_code == 403
