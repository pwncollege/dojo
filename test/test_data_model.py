import json
import random
import re
import string
import time
import uuid

import pytest
import yaml

from utils import (
    DOJO_URL,
    create_dojo_yml,
    db_sql,
    dojo_run,
    get_outer_container_for,
    get_user_id,
    login,
    make_dojo_official,
    solve_challenge,
    wait_for_background_worker,
)

IMAGE = "pwncollege/challenge-simple"
PAST = "2000-01-01T00:00:00Z"


def rand_suffix():
    return "".join(random.choices(string.ascii_lowercase, k=8))


def dojo_hex(dojo_reference_id):
    return dojo_reference_id.split("~")[1]


def dojo_id(dojo_reference_id):
    return int.from_bytes(bytes.fromhex(dojo_hex(dojo_reference_id)), "big", signed=True)


def create_dojo(spec, *, session):
    return create_dojo_yml(yaml.safe_dump(spec, sort_keys=False), session=session)


def update_dojo(dojo_reference_id, spec, *, session):
    return session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo_reference_id}/update", json=spec)


def challenge_entry(challenge_id, **kwargs):
    entry = {"type": "challenge", "id": challenge_id, "name": challenge_id.replace("-", " ").title()}
    entry.update(kwargs)
    return entry


def count(sql):
    return int(db_sql(sql).strip())


def solve_count_sql(challenge_db_id, user_id):
    return ("SELECT count(*) FROM submissions WHERE type = 'correct' "
            f"AND challenge_id = {challenge_db_id} AND user_id = {user_id}")


def challenge_id_of(dojo_reference_id, module_id, challenge_id):
    return int(db_sql(
        "SELECT dc.challenge_id FROM dojo_challenges dc "
        "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = {dojo_id(dojo_reference_id)} AND dm.id = '{module_id}' AND dc.id = '{challenge_id}'"
    ).strip())


def flag_for(user, challenge_db_id):
    """Derive a challenge flag the way the workspace does, for a specific challenges row."""
    return dojo_run(
        "docker", "exec", "ctfd", "python3", "-c",
        "import sys, os\n"
        "from itsdangerous.url_safe import URLSafeSerializer\n"
        "data = [int(sys.argv[1]), int(sys.argv[2])]\n"
        "print('pwn.college{' + URLSafeSerializer(os.environ['SECRET_KEY']).dumps(data)[::-1] + '}')",
        str(get_user_id(user)), str(challenge_db_id),
    ).stdout.strip()


def solve_offline(dojo_reference_id, module_id, challenge_id, *, session, user):
    flag = flag_for(user, challenge_id_of(dojo_reference_id, module_id, challenge_id))
    solve_challenge(dojo_reference_id, module_id, challenge_id, session=session, flag=flag)


def get_modules(session, dojo_reference_id):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo_reference_id}/modules")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    return response.json()["modules"]


def get_solves(session, dojo_reference_id):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo_reference_id}/solves")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    return response.json()["solves"]


def get_dojo_listing_entry(session, dojo_reference_id):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    return next((dojo for dojo in response.json()["dojos"] if dojo["id"] == dojo_reference_id), None)


def scoreboard_entry(session, dojo_reference_id, user_name, timeout=25):
    deadline = time.time() + timeout
    while True:
        response = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo_reference_id}/_/0/1")
        if response.status_code == 200:
            for entry in response.json().get("standings", []):
                if entry["name"] == user_name:
                    return entry
        if time.time() > deadline:
            return None
        time.sleep(1)


FLASK_EXEC_MARKER = "--- data model test output ---"


def flask_exec(code):
    """Run python inside CTFd's application context; unique script path so parallel runs don't collide."""
    script_path = f"/tmp/test-data-model-{uuid.uuid4().hex}.py"
    script = f"print({FLASK_EXEC_MARKER!r}, flush=True)\n{code}"
    dojo_run("docker", "exec", "-i", "ctfd", "sh", "-c", f"cat > {script_path}", input=script)
    result = dojo_run("docker", "exec", "ctfd", "flask", "shell", "--", script_path, check=False)
    dojo_run("docker", "exec", "ctfd", "rm", "-f", script_path, check=False)
    assert FLASK_EXEC_MARKER in result.stdout, f"flask exec produced no output: {result.stdout}\n{result.stderr}"
    return result.stdout.split(FLASK_EXEC_MARKER, 1)[1].lstrip("\n")


@pytest.fixture
def data_model_user():
    name = "dm" + rand_suffix()
    session = login(name, name, register=True)
    yield name, session


def test_dojo_delete_orphans_challenges_and_cascades_children(admin_session, data_model_user):
    user_name, user_session = data_model_user
    reference_id = create_dojo({
        "id": f"dm-delete-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{
            "id": "m",
            "visibility": {"start": PAST},
            "resources": [
                {"type": "markdown", "name": "Doc", "content": "a resource"},
                challenge_entry("c"),
            ],
        }],
    }, session=admin_session)
    db_id = dojo_id(reference_id)
    hex_id = dojo_hex(reference_id)
    challenge_db_id = challenge_id_of(reference_id, "m", "c")
    user_id = get_user_id(user_name)

    solve_offline(reference_id, "m", "c", session=user_session, user=user_name)

    for table in ["dojo_resources", "dojo_module_visibilities",
                  "dojo_challenge_visibilities", "dojo_resource_visibilities"]:
        assert count(f"SELECT count(*) FROM {table} WHERE dojo_id = {db_id}") > 0, \
            f"expected {table} rows for the dojo before deletion"

    activity_before = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/activity/{user_id}").json()

    response = admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={"dojo": reference_id})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 404, "deleted dojo is still reachable"

    for table in ["dojos", "dojo_modules", "dojo_challenges", "dojo_resources",
                  "dojo_module_visibilities", "dojo_challenge_visibilities", "dojo_resource_visibilities"]:
        assert count(f"SELECT count(*) FROM {table} WHERE dojo_id = {db_id}") == 0, \
            f"{table} rows survived the dojo deletion"

    assert count(f"SELECT count(*) FROM challenges WHERE id = {challenge_db_id} AND category = '{hex_id}'") == 1, \
        "the CTFd challenge row should be orphaned, not deleted"
    assert count(f"SELECT count(*) FROM flags WHERE challenge_id = {challenge_db_id}") == 1, \
        "the challenge flag should survive the dojo deletion"
    assert count(solve_count_sql(challenge_db_id, user_id)) == 1, \
        "solve history must survive the dojo deletion"

    activity_after = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/activity/{user_id}")
    assert activity_after.status_code == 200
    assert activity_after.json()["data"]["total_solves"] == activity_before["data"]["total_solves"], \
        "deleting a dojo must not change the user's solve history"


def test_challenge_row_delete_cascades_dojo_challenges(admin_session):
    suffix = rand_suffix()
    source = create_dojo({
        "id": f"dm-cascade-src-{suffix}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }, session=admin_session)
    importer = create_dojo({
        "id": f"dm-cascade-imp-{suffix}",
        "type": "public",
        "modules": [{"id": "m", "resources": [
            challenge_entry("c", **{"import": {"dojo": source, "module": "m", "challenge": "c"}}),
        ]}],
    }, session=admin_session)

    challenge_db_id = challenge_id_of(source, "m", "c")
    assert challenge_id_of(importer, "m", "c") == challenge_db_id, "import should reuse the source challenge row"
    assert count(f"SELECT count(*) FROM dojo_challenges WHERE challenge_id = {challenge_db_id}") == 2

    db_sql(f"DELETE FROM challenges WHERE id = {challenge_db_id}")

    assert count(f"SELECT count(*) FROM dojo_challenges WHERE challenge_id = {challenge_db_id}") == 0
    for reference_id in (source, importer):
        assert count(f"SELECT count(*) FROM dojo_challenges WHERE dojo_id = {dojo_id(reference_id)}") == 0, \
            "deleting the challenge row must cascade to every dojo_challenges row"
        modules = get_modules(admin_session, reference_id)
        assert len(modules) == 1
        assert modules[0]["challenges"] == [], "the deleted challenge must not be listed anymore"


def test_survey_responses_survive_dojo_and_user_deletion(admin_session):
    user_name = "dm" + rand_suffix()
    user_session = login(user_name, user_name, register=True)
    user_id = get_user_id(user_name)

    reference_id = create_dojo({
        "id": f"dm-survey-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [
            challenge_entry("c", survey={"prompt": "How was it?", "data": "<div>survey</div>"}),
        ]}],
    }, session=admin_session)
    db_id = dojo_id(reference_id)

    survey_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/m/c/surveys"
    response = user_session.get(survey_url)
    assert response.status_code == 200 and response.json()["type"] == "user-specified"

    response = user_session.post(survey_url, json={"response": "great"})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"]
    assert count(f"SELECT count(*) FROM survey_responses WHERE dojo_id = {db_id} AND user_id = {user_id}") == 1

    response = admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={"dojo": reference_id})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    response = admin_session.delete(f"{DOJO_URL}/api/v1/users/{user_id}", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert count(f"SELECT count(*) FROM users WHERE id = {user_id}") == 0

    assert count(f"SELECT count(*) FROM survey_responses WHERE dojo_id = {db_id} AND user_id = {user_id}") == 1, \
        "survey responses have no foreign keys, so they must survive as orphans"
    assert admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos").status_code == 200, \
        "orphaned survey rows must not break the dojo listing"


def test_user_delete_cascades_dojo_memberships(admin_session):
    user_name = "dm" + rand_suffix()
    user_session = login(user_name, user_name, register=True)
    user_id = get_user_id(user_name)
    suffix = rand_suffix()

    member_dojo = create_dojo({"id": f"dm-member-{suffix}", "type": "public"}, session=admin_session)
    admin_dojo = create_dojo({"id": f"dm-admin-{suffix}", "type": "public"}, session=admin_session)

    for reference_id in (member_dojo, admin_dojo):
        assert user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200

    response = admin_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{admin_dojo}/admins/promote", json={"user_id": user_id})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    db_sql(f"DELETE FROM dojo_users WHERE dojo_id = {dojo_id(admin_dojo)} AND user_id = {get_user_id('admin')}")

    assert count(f"SELECT count(*) FROM dojo_users WHERE user_id = {user_id}") == 2
    assert count(f"SELECT count(*) FROM dojo_users WHERE dojo_id = {dojo_id(admin_dojo)} AND type = 'admin'") == 1

    response = admin_session.delete(f"{DOJO_URL}/api/v1/users/{user_id}", json={})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"

    assert count(f"SELECT count(*) FROM dojo_users WHERE user_id = {user_id}") == 0, \
        "dojo memberships must cascade away with the user"
    assert count(f"SELECT count(*) FROM dojo_users WHERE dojo_id = {dojo_id(admin_dojo)}") == 0
    for reference_id in (member_dojo, admin_dojo):
        assert count(f"SELECT count(*) FROM dojos WHERE dojo_id = {dojo_id(reference_id)}") == 1, \
            "deleting a user must not delete their dojos"
        assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
    assert admin_session.get(f"{DOJO_URL}/dojo/{admin_dojo}/admin/").status_code == 200, \
        "an adminless dojo must still be manageable by a site admin"


def test_update_shrinking_spec_deletes_orphan_children(admin_session):
    dojo_spec_id = f"dm-shrink-{rand_suffix()}"
    spec = {
        "id": dojo_spec_id,
        "type": "public",
        "image": IMAGE,
        "modules": [
            {
                "id": module_id,
                "visibility": {"start": PAST},
                "resources": [
                    {"type": "markdown", "name": f"Doc {module_id}", "content": "content"},
                    challenge_entry(f"{module_id}-a"),
                    challenge_entry(f"{module_id}-b"),
                ],
            }
            for module_id in ["m0", "m1", "m2"]
        ],
    }
    reference_id = create_dojo(spec, session=admin_session)
    db_id = dojo_id(reference_id)

    assert count(f"SELECT count(*) FROM dojo_modules WHERE dojo_id = {db_id}") == 3
    assert count(f"SELECT count(*) FROM dojo_challenges WHERE dojo_id = {db_id}") == 6
    assert count(f"SELECT count(*) FROM dojo_resources WHERE dojo_id = {db_id}") == 3

    shrunk = dict(spec, modules=[{
        "id": "m0",
        "visibility": {"start": PAST},
        "resources": [
            {"type": "markdown", "name": "Doc m0", "content": "content"},
            challenge_entry("m0-a"),
        ],
    }])
    response = update_dojo(reference_id, shrunk, session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    assert count(f"SELECT count(*) FROM dojo_modules WHERE dojo_id = {db_id}") == 1
    assert count(f"SELECT count(*) FROM dojo_challenges WHERE dojo_id = {db_id}") == 1
    assert count(f"SELECT count(*) FROM dojo_resources WHERE dojo_id = {db_id}") == 1
    for table in ["dojo_challenges", "dojo_resources", "dojo_module_visibilities",
                  "dojo_challenge_visibilities", "dojo_resource_visibilities"]:
        assert count(f"SELECT count(*) FROM {table} WHERE dojo_id = {db_id} AND module_index >= 1") == 0, \
            f"{table} rows of dropped modules survived the update"

    modules = get_modules(admin_session, reference_id)
    assert [module["id"] for module in modules] == ["m0"]
    assert [challenge["id"] for challenge in modules[0]["challenges"]] == ["m0-a"]


def test_module_and_challenge_reordering_preserves_identity(admin_session, data_model_user):
    user_name, user_session = data_model_user
    dojo_spec_id = f"dm-order-{rand_suffix()}"
    spec = {
        "id": dojo_spec_id,
        "type": "public",
        "image": IMAGE,
        "modules": [
            {"id": "zulu", "resources": [challenge_entry("z1"), challenge_entry("z2")]},
            {"id": "alpha", "resources": [challenge_entry("a1")]},
            {"id": "mike", "resources": [challenge_entry("m1")]},
        ],
    }
    reference_id = create_dojo(spec, session=admin_session)
    db_id = dojo_id(reference_id)

    indexes = dict(
        line.split("|") for line in
        db_sql(f"SELECT id, module_index FROM dojo_modules WHERE dojo_id = {db_id}").strip().splitlines()
    )
    assert indexes == {"zulu": "0", "alpha": "1", "mike": "2"}, "module_index must follow spec order"
    assert [module["id"] for module in get_modules(admin_session, reference_id)] == ["zulu", "alpha", "mike"]
    assert count(f"SELECT count(*) FROM dojo_challenges WHERE dojo_id = {db_id} AND module_index = 0") == 2
    assert count(f"SELECT count(*) FROM dojo_challenges WHERE dojo_id = {db_id} AND module_index = 2 AND id = 'm1'") == 1

    original_ids = {
        (module_id, challenge_id): challenge_id_of(reference_id, module_id, challenge_id)
        for module_id, challenge_id in [("zulu", "z1"), ("zulu", "z2"), ("alpha", "a1"), ("mike", "m1")]
    }
    solve_offline(reference_id, "zulu", "z1", session=user_session, user=user_name)
    solve_offline(reference_id, "mike", "m1", session=user_session, user=user_name)

    reordered = dict(spec, modules=[
        {"id": "mike", "resources": [challenge_entry("m1")]},
        {"id": "zulu", "resources": [challenge_entry("z2"), challenge_entry("z1")]},
        {"id": "alpha", "resources": [challenge_entry("a1")]},
    ])
    response = update_dojo(reference_id, reordered, session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    indexes = dict(
        line.split("|") for line in
        db_sql(f"SELECT id, module_index FROM dojo_modules WHERE dojo_id = {db_id}").strip().splitlines()
    )
    assert indexes == {"mike": "0", "zulu": "1", "alpha": "2"}, "reordering must renumber module_index"
    assert [module["id"] for module in get_modules(admin_session, reference_id)] == ["mike", "zulu", "alpha"]
    zulu_challenges = db_sql(
        f"SELECT id FROM dojo_challenges WHERE dojo_id = {db_id} AND module_index = 1 ORDER BY challenge_index"
    ).split()
    assert zulu_challenges == ["z2", "z1"], "challenge_index must follow the new spec order"

    for (module_id, challenge_id), challenge_db_id in original_ids.items():
        assert challenge_id_of(reference_id, module_id, challenge_id) == challenge_db_id, \
            f"{module_id}/{challenge_id} must keep its challenge row across a reorder"

    solves = get_solves(user_session, reference_id)
    assert sorted((solve["module_id"], solve["challenge_id"]) for solve in solves) == \
        [("mike", "m1"), ("zulu", "z1")], "reordering must not lose solves"


def test_duplicate_module_id_rejected_at_create(admin_session):
    dojo_spec_id = f"dm-dupmod-{rand_suffix()}"
    spec = {
        "id": dojo_spec_id,
        "image": IMAGE,
        "modules": [
            {"id": "dup", "resources": [challenge_entry("a")]},
            {"id": "dup", "resources": [challenge_entry("b")]},
        ],
    }
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create",
                                  json={"spec": yaml.safe_dump(spec, sort_keys=False)})
    assert count(f"SELECT count(*) FROM dojos WHERE id = '{dojo_spec_id}'") == 0, \
        "a rejected spec must not leave a dojo row behind"
    assert response.status_code == 400, f"Expected status code 400, but got {response.status_code}"


def test_duplicate_module_id_rejected_at_update(admin_session):
    dojo_spec_id = f"dm-dupupd-{rand_suffix()}"
    spec = {
        "id": dojo_spec_id,
        "type": "public",
        "image": IMAGE,
        "modules": [
            {"id": "one", "resources": [challenge_entry("a")]},
            {"id": "two", "resources": [challenge_entry("b")]},
        ],
    }
    reference_id = create_dojo(spec, session=admin_session)
    original_ids = {
        challenge_id: challenge_id_of(reference_id, module_id, challenge_id)
        for module_id, challenge_id in [("one", "a"), ("two", "b")]
    }

    broken = dict(spec, modules=[
        {"id": "dup", "resources": [challenge_entry("a")]},
        {"id": "dup", "resources": [challenge_entry("b")]},
    ])
    response = update_dojo(reference_id, broken, session=admin_session)
    assert response.status_code == 400, f"Expected status code 400, but got {response.status_code}"
    assert not response.json()["success"]

    modules = get_modules(admin_session, reference_id)
    assert [module["id"] for module in modules] == ["one", "two"], "a failed update must roll back"
    for challenge_id, challenge_db_id in original_ids.items():
        module_id = "one" if challenge_id == "a" else "two"
        assert challenge_id_of(reference_id, module_id, challenge_id) == challenge_db_id


def test_challenge_id_unique_per_module_not_per_dojo(admin_session, data_model_user):
    user_name, user_session = data_model_user
    reference_id = create_dojo({
        "id": f"dm-samechal-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [
            {"id": "m1", "resources": [challenge_entry("same")]},
            {"id": "m2", "resources": [challenge_entry("same")]},
        ],
    }, session=admin_session)
    hex_id = dojo_hex(reference_id)

    modules = get_modules(admin_session, reference_id)
    assert [(module["id"], module["challenges"][0]["id"]) for module in modules] == \
        [("m1", "same"), ("m2", "same")]

    first = challenge_id_of(reference_id, "m1", "same")
    second = challenge_id_of(reference_id, "m2", "same")
    assert first != second, "the same challenge id in two modules must get its own challenge row"
    names = db_sql(f"SELECT name FROM challenges WHERE category = '{hex_id}' ORDER BY name").split()
    assert names == ["m1:same", "m2:same"]

    solve_offline(reference_id, "m1", "same", session=user_session, user=user_name)
    solves = get_solves(user_session, reference_id)
    assert [(solve["module_id"], solve["challenge_id"]) for solve in solves] == [("m1", "same")], \
        "solving one module's challenge must not credit the other module's"

    solve_offline(reference_id, "m2", "same", session=user_session, user=user_name)
    solves = get_solves(user_session, reference_id)
    assert sorted(solve["module_id"] for solve in solves) == ["m1", "m2"]


def test_duplicate_dojo_id_across_dojos(admin_session, data_model_user):
    _, user_session = data_model_user
    shared_id = f"dm-dup-id-{rand_suffix()}"
    first = create_dojo({"id": shared_id, "name": "Alpha Duplicate", "type": "public",
                         "modules": [{"id": "first-module"}]}, session=admin_session)
    second = create_dojo({"id": shared_id, "name": "Zulu Duplicate", "type": "public",
                          "modules": [{"id": "second-module"}]}, session=admin_session)

    assert first != second and dojo_hex(first) != dojo_hex(second), "each dojo needs its own unique reference"
    assert count(f"SELECT count(*) FROM dojos WHERE id = '{shared_id}'") == 2
    assert [module["id"] for module in get_modules(user_session, first)] == ["first-module"]
    assert [module["id"] for module in get_modules(user_session, second)] == ["second-module"]

    make_dojo_official(first, admin_session)
    make_dojo_official(second, admin_session)

    assert user_session.get(f"{DOJO_URL}/{shared_id}/").status_code == 200
    resolutions = [tuple(module["id"] for module in get_modules(user_session, shared_id)) for _ in range(3)]
    assert len(set(resolutions)) == 1, f"bare id resolution must be deterministic, got {resolutions}"
    assert resolutions[0] in [("first-module",), ("second-module",)]

    for reference_id, module_id in [(first, "first-module"), (second, "second-module")]:
        assert [module["id"] for module in get_modules(user_session, reference_id)] == [module_id], \
            "each dojo stays individually addressable by its unique reference"


def test_spec_dojos_coexist_with_null_unique_columns(admin_session):
    suffix = rand_suffix()
    references = [create_dojo({"id": f"dm-null-{suffix}-{index}"}, session=admin_session) for index in range(3)]
    db_ids = [dojo_id(reference_id) for reference_id in references]
    assert len(set(db_ids)) == 3, "each dojo must get its own dojo_id"

    rows = db_sql(
        "SELECT repository IS NULL, public_key IS NULL, private_key IS NULL, update_code "
        f"FROM dojos WHERE dojo_id IN ({', '.join(str(db_id) for db_id in db_ids)})"
    ).strip().splitlines()
    assert len(rows) == 3
    update_codes = set()
    for row in rows:
        repository_null, public_null, private_null, update_code = row.split("|")
        assert (repository_null, public_null, private_null) == ("t", "t", "t"), \
            "spec dojos leave the unique repository/key columns NULL"
        assert update_code, "every dojo gets a generated update code"
        update_codes.add(update_code)
    assert len(update_codes) == 3

    assert count("SELECT count(*) - count(DISTINCT update_code) FROM dojos WHERE update_code IS NOT NULL") == 0, \
        "update codes must be unique across all dojos"


def test_dojo_id_hex_roundtrip_signed(admin_session):
    suffix = rand_suffix()
    reference_id = None
    for attempt in range(12):
        candidate = create_dojo({"id": f"dm-signed-{suffix}-{attempt}", "type": "public",
                                 "modules": [{"id": f"mod-{attempt}"}]}, session=admin_session)
        if dojo_id(candidate) < 0:
            reference_id = candidate
            break
    assert reference_id is not None, "failed to generate a dojo with a negative dojo_id in 12 attempts"

    dojo_spec_id, hex_id = reference_id.split("~")
    assert re.fullmatch(r"[0-9a-f]{8}", hex_id), f"hex suffix must be 8 lowercase hex chars, got {hex_id}"
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
    assert get_modules(admin_session, reference_id)

    stored = int(db_sql(f"SELECT dojo_id FROM dojos WHERE id = '{dojo_spec_id}'").strip())
    assert stored < 0
    assert int.from_bytes(bytes.fromhex(hex_id), "big", signed=True) == stored, \
        "the hex suffix must round-trip back to the signed dojo_id"
    entry = get_dojo_listing_entry(admin_session, reference_id)
    assert entry is not None and entry["hex_id"] == hex_id


def test_hex_reference_id_zero_padding_tolerant(admin_session):
    dojo_spec_id = f"dm-pad-{rand_suffix()}"
    reference_id = create_dojo({"id": dojo_spec_id, "type": "public",
                                "modules": [{"id": "padded-module"}]}, session=admin_session)
    original_db_id = dojo_id(reference_id)

    padded_db_id = random.randrange(0x01000000, 0x0fffffff)
    while count(f"SELECT count(*) FROM dojos WHERE dojo_id = {padded_db_id}"):
        padded_db_id = random.randrange(0x01000000, 0x0fffffff)
    db_sql(f"DELETE FROM dojo_modules WHERE dojo_id = {original_db_id}")
    db_sql(f"DELETE FROM dojo_users WHERE dojo_id = {original_db_id}")
    db_sql(f"UPDATE dojos SET dojo_id = {padded_db_id} WHERE dojo_id = {original_db_id}")

    canonical = f"{padded_db_id:08x}"
    assert canonical.startswith("0")
    stripped = canonical.lstrip("0")

    for hex_suffix in (canonical, stripped, f"00{canonical}"):
        response = admin_session.get(f"{DOJO_URL}/{dojo_spec_id}~{hex_suffix}/")
        assert response.status_code == 200, \
            f"reference id {dojo_spec_id}~{hex_suffix} should resolve, got {response.status_code}"
        assert get_modules(admin_session, f"{dojo_spec_id}~{hex_suffix}") == \
            get_modules(admin_session, f"{dojo_spec_id}~{canonical}"), \
            f"{hex_suffix} must resolve to the same dojo as {canonical}"

    entry = get_dojo_listing_entry(admin_session, f"{dojo_spec_id}~{canonical}")
    assert entry is not None and entry["hex_id"] == canonical, \
        "the canonical 8-character hex is the one that is published"
    response = admin_session.get(f"{DOJO_URL}/{dojo_spec_id}~{canonical}00/")
    assert response.status_code == 404, "trailing hex digits change the dojo_id and must not resolve"


def test_malformed_reference_id_is_not_found(admin_session):
    dojo_spec_id = f"dm-badref-{rand_suffix()}"
    reference_id = create_dojo({"id": dojo_spec_id, "type": "public"}, session=admin_session)
    assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200

    response = admin_session.get(f"{DOJO_URL}/{dojo_spec_id}~zzzzzzzz/")
    assert response.status_code == 404, \
        f"a malformed hex suffix should 404, but got {response.status_code}"


def test_official_dojo_addressable_by_both_reference_forms(admin_session, data_model_user):
    _, user_session = data_model_user
    dojo_spec_id = f"dm-official-{rand_suffix()}"
    reference_id = create_dojo({
        "id": dojo_spec_id,
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c", allow_privileged=False)]}],
    }, session=admin_session)

    def start(dojo):
        response = user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker",
                                     json={"dojo": dojo, "module": "m", "challenge": "c", "practice": True})
        assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
        return response.json()

    assert user_session.get(f"{DOJO_URL}/{dojo_spec_id}/").status_code == 404, \
        "an unofficial dojo must not be reachable by its bare id"
    assert user_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
    assert start(dojo_spec_id)["error"] == "Invalid dojo"
    assert "practice" in start(reference_id)["error"], "the unique reference must resolve to the challenge"

    make_dojo_official(reference_id, admin_session)

    assert user_session.get(f"{DOJO_URL}/{dojo_spec_id}/").status_code == 200
    assert user_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
    for dojo in (dojo_spec_id, reference_id):
        assert "practice" in start(dojo)["error"], f"official dojo must resolve through {dojo}"
    entry = get_dojo_listing_entry(user_session, dojo_spec_id)
    assert entry is not None and entry["hex_id"] == dojo_hex(reference_id), \
        "an official dojo is listed under its bare id"


def test_update_preserves_identity_and_out_of_band_data(admin_session):
    dojo_spec_id = f"dm-identity-{rand_suffix()}"
    spec = {
        "id": dojo_spec_id,
        "type": "public",
        "image": IMAGE,
        "name": "Identity Original",
        "description": "original description",
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }
    reference_id = create_dojo(spec, session=admin_session)
    db_id = dojo_id(reference_id)
    hex_id = dojo_hex(reference_id)
    challenge_db_id = challenge_id_of(reference_id, "m", "c")

    custom_js = "console.log(42);"
    data = json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id = {db_id}"))
    data["permissions"] = ["grant_awards"]
    data["custom_js"] = custom_js
    db_sql(f"UPDATE dojos SET data = '{json.dumps(data)}' WHERE dojo_id = {db_id}")

    make_dojo_official(reference_id, admin_session)
    update_code = db_sql(f"SELECT update_code FROM dojos WHERE dojo_id = {db_id}").strip()

    grant = dict(user_id=get_user_id("admin"), emoji="🥈", description="before update")
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/award/grant", json=grant)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"

    updated = dict(spec, name="Identity Updated", description="updated description")
    response = update_dojo(reference_id, updated, session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    row = db_sql(
        f"SELECT dojo_id, update_code, official, id FROM dojos WHERE dojo_id = {db_id}"
    ).strip().split("|")
    assert row == [str(db_id), update_code, "t", dojo_spec_id], "update must not touch dojo identity columns"
    assert challenge_id_of(reference_id, "m", "c") == challenge_db_id, "the challenge row must survive an update"
    assert db_sql(f"SELECT category FROM challenges WHERE id = {challenge_db_id}").strip() == hex_id

    data = json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id = {db_id}"))
    assert data["permissions"] == ["grant_awards"], "administratively granted permissions must survive an update"
    assert data["custom_js"] == custom_js, "custom_js must survive an update"

    grant = dict(user_id=get_user_id("admin"), emoji="🥉", description="after update")
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/award/grant", json=grant)
    assert response.status_code == 200, f"award granting broke after the update ({response.status_code})"

    entry = get_dojo_listing_entry(admin_session, dojo_spec_id)
    assert entry is not None and entry["name"] == "Identity Updated"
    assert entry["description"] == "updated description"


def test_repeated_updates_do_not_duplicate_challenge_or_flag_rows(admin_session, data_model_user):
    user_name, user_session = data_model_user
    spec = {
        "id": f"dm-repeat-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c1"), challenge_entry("c2")]}],
    }
    reference_id = create_dojo(spec, session=admin_session)
    hex_id = dojo_hex(reference_id)
    challenge_ids = {
        challenge_id: challenge_id_of(reference_id, "m", challenge_id) for challenge_id in ["c1", "c2"]
    }
    flags = {challenge_id: flag_for(user_name, db_id) for challenge_id, db_id in challenge_ids.items()}
    solve_challenge(reference_id, "m", "c1", session=user_session, flag=flags["c1"])

    for iteration in range(3):
        response = update_dojo(reference_id, spec, session=admin_session)
        assert response.status_code == 200, \
            f"update {iteration} failed: {response.status_code} - {response.text}"
        for challenge_id, db_id in challenge_ids.items():
            assert challenge_id_of(reference_id, "m", challenge_id) == db_id, \
                f"{challenge_id} was re-minted by update {iteration}"
            assert count(f"SELECT count(*) FROM flags WHERE challenge_id = {db_id}") == 1, \
                f"{challenge_id} accumulated flags after update {iteration}"
        assert count(f"SELECT count(*) FROM challenges WHERE category = '{hex_id}'") == 2, \
            f"update {iteration} duplicated challenge rows"

    response = user_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/m/c1/solve",
                                 json={"submission": flags["c1"]})
    assert response.status_code == 200 and response.json()["status"] == "already_solved"
    response = user_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/m/c2/solve",
                                 json={"submission": flags["c2"]})
    assert response.status_code == 200 and response.json()["status"] == "solved", \
        "flags derived before the updates must still validate"
    assert sorted(solve["challenge_id"] for solve in get_solves(user_session, reference_id)) == ["c1", "c2"]


def test_update_drops_award_when_spec_omits_it(admin_session, data_model_user):
    user_name, user_session = data_model_user
    spec = {
        "id": f"dm-award-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "award": {"emoji": "🧪"},
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }
    reference_id = create_dojo(spec, session=admin_session)
    db_id = dojo_id(reference_id)
    hex_id = dojo_hex(reference_id)
    user_id = get_user_id(user_name)

    solve_offline(reference_id, "m", "c", session=user_session, user=user_name)
    assert count(f"SELECT count(*) FROM awards WHERE category = '{hex_id}' AND user_id = {user_id}") == 1, \
        "completing the dojo must grant the emoji award"

    wait_for_background_worker(timeout=5)
    entry = scoreboard_entry(user_session, reference_id, user_name)
    assert entry is not None, "the solver should appear on the dojo scoreboard"
    assert any(badge["category"] == hex_id for badge in entry["badges"]), "the award badge should be shown"

    response = update_dojo(reference_id, {key: value for key, value in spec.items() if key != "award"},
                           session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    assert db_sql(f"SELECT data->>'award' IS NULL FROM dojos WHERE dojo_id = {db_id}").strip() == "t", \
        "an update whose spec omits award must clear it"
    assert count(f"SELECT count(*) FROM awards WHERE category = '{hex_id}' AND user_id = {user_id}") == 1, \
        "the granted award row must survive"

    entry = scoreboard_entry(user_session, reference_id, user_name)
    assert entry is not None
    assert not any(badge["category"] == hex_id for badge in entry["badges"]), \
        "the badge must stop rendering once the dojo has no award"


def test_update_module_rename_forks_challenge_identity(admin_session, data_model_user):
    user_name, user_session = data_model_user
    spec = {
        "id": f"dm-rename-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "old", "resources": [challenge_entry("c")]}],
    }
    reference_id = create_dojo(spec, session=admin_session)
    hex_id = dojo_hex(reference_id)
    user_id = get_user_id(user_name)
    before = challenge_id_of(reference_id, "old", "c")
    solve_offline(reference_id, "old", "c", session=user_session, user=user_name)

    renamed = dict(spec, modules=[{"id": "new", "resources": [challenge_entry("c")]}])
    response = update_dojo(reference_id, renamed, session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    after = challenge_id_of(reference_id, "new", "c")
    assert after != before, "renaming a module forks the challenge identity"
    assert count(f"SELECT count(*) FROM flags WHERE challenge_id = {after}") == 1
    assert db_sql(f"SELECT name FROM challenges WHERE id = {after}").strip() == "new:c"
    assert get_solves(user_session, reference_id) == [], "the fork orphans the previous solves"

    row = db_sql(f"SELECT category, name FROM challenges WHERE id = {before}").strip()
    assert row == f"{hex_id}|old:c", "the old challenge row is orphaned, not deleted"
    assert count(solve_count_sql(before, user_id)) == 1, "the orphaned row keeps the solve"


def test_challenge_identity_is_category_plus_name(admin_session, data_model_user):
    user_name, user_session = data_model_user
    suffix = rand_suffix()
    first = create_dojo({"id": f"dm-ident-a-{suffix}", "type": "public", "image": IMAGE,
                         "modules": [{"id": "m", "resources": [challenge_entry("c")]}]}, session=admin_session)
    second = create_dojo({"id": f"dm-ident-b-{suffix}", "type": "public", "image": IMAGE,
                          "modules": [{"id": "m", "resources": [challenge_entry("c")]}]}, session=admin_session)

    first_challenge = challenge_id_of(first, "m", "c")
    second_challenge = challenge_id_of(second, "m", "c")
    assert first_challenge != second_challenge, "two dojos must not share a challenge row"
    for reference_id, challenge_db_id in [(first, first_challenge), (second, second_challenge)]:
        row = db_sql(f"SELECT category, name FROM challenges WHERE id = {challenge_db_id}").strip()
        assert row == f"{dojo_hex(reference_id)}|m:c"

    solve_offline(first, "m", "c", session=user_session, user=user_name)
    assert [solve["challenge_id"] for solve in get_solves(user_session, first)] == ["c"]
    assert get_solves(user_session, second) == [], "solving one dojo's challenge must not credit the other's"


def test_module_import_forces_required_true(admin_session, data_model_user):
    user_name, user_session = data_model_user
    suffix = rand_suffix()
    source = create_dojo({
        "id": f"dm-req-src-{suffix}",
        "type": "public",
        "image": IMAGE,
        "award": {"emoji": "🧪"},
        "modules": [{"id": "m", "resources": [challenge_entry("c1"), challenge_entry("c2", required=False)]}],
    }, session=admin_session)
    importer = create_dojo({
        "id": f"dm-req-imp-{suffix}",
        "type": "public",
        "award": {"emoji": "🧪"},
        "modules": [{"id": "m", "import": {"dojo": source, "module": "m"}}],
    }, session=admin_session)
    user_id = get_user_id(user_name)

    assert db_sql(
        f"SELECT required FROM dojo_challenges WHERE dojo_id = {dojo_id(source)} AND id = 'c2'").strip() == "f"
    assert db_sql(
        f"SELECT required FROM dojo_challenges WHERE dojo_id = {dojo_id(importer)} AND id = 'c2'").strip() == "t", \
        "a module import forces required=True on the imported challenges"

    assert get_dojo_listing_entry(admin_session, source)["challenges_count"] == 1
    assert get_dojo_listing_entry(admin_session, importer)["challenges_count"] == 2

    source_challenges = {c["id"]: c["required"] for c in get_modules(admin_session, source)[0]["challenges"]}
    importer_challenges = {c["id"]: c["required"] for c in get_modules(admin_session, importer)[0]["challenges"]}
    assert source_challenges == {"c1": True, "c2": False}
    assert importer_challenges == {"c1": True, "c2": True}

    solve_offline(source, "m", "c1", session=user_session, user=user_name)
    assert count(
        f"SELECT count(*) FROM awards WHERE category = '{dojo_hex(source)}' AND user_id = {user_id}") == 1, \
        "solving the only required challenge completes the source dojo"
    assert count(
        f"SELECT count(*) FROM awards WHERE category = '{dojo_hex(importer)}' AND user_id = {user_id}") == 0, \
        "the importing dojo requires both challenges, so it is not complete"


def test_import_does_not_copy_behavior_flags(admin_session, data_model_user):
    user_name, user_session = data_model_user
    suffix = rand_suffix()
    source = create_dojo({
        "id": f"dm-flags-src-{suffix}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [
            challenge_entry("c1"),
            challenge_entry("c2", allow_privileged=False, progression_locked=True,
                            survey={"prompt": "source survey", "data": "<div>s</div>"}),
        ]}],
    }, session=admin_session)
    importer = create_dojo({
        "id": f"dm-flags-imp-{suffix}",
        "type": "public",
        "modules": [{"id": "m", "import": {"dojo": source, "module": "m"}}],
    }, session=admin_session)

    assert challenge_id_of(importer, "m", "c2") == challenge_id_of(source, "m", "c2"), \
        "the import must reuse the source challenge row"
    assert db_sql(
        f"SELECT data->>'image' FROM dojo_challenges WHERE dojo_id = {dojo_id(importer)} AND id = 'c2'"
    ).strip() == IMAGE, "the import copies the source image"
    assert db_sql(
        f"SELECT data->>'allow_privileged' FROM dojo_challenges WHERE dojo_id = {dojo_id(source)} AND id = 'c2'"
    ).strip() == "false"
    assert db_sql(
        f"SELECT coalesce(data->>'allow_privileged', 'unset') FROM dojo_challenges "
        f"WHERE dojo_id = {dojo_id(importer)} AND id = 'c2'"
    ).strip() != "false", "allow_privileged must not be inherited by the importing dojo"

    def survey_type(reference_id):
        response = user_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/m/c2/surveys")
        assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
        return response.json()["type"]

    assert survey_type(source) == "user-specified"
    assert survey_type(importer) == "none", "surveys must not be inherited by the importing dojo"

    def description_status(reference_id):
        return user_session.get(
            f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/m/c2/description").status_code

    assert description_status(source) == 403, "the source challenge is progression locked"
    assert description_status(importer) == 200, "progression locks must not be inherited by the importing dojo"

    response = user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker",
                                 json={"dojo": source, "module": "m", "challenge": "c2", "practice": True})
    assert response.status_code == 200
    assert "practice" in response.json()["error"], "the source challenge disallows practice mode"


def test_resource_index_numbering_includes_challenge_entries(admin_session):
    spec = {
        "id": f"dm-residx-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [
            {"type": "markdown", "name": "Doc A", "content": "alpha"},
            challenge_entry("x"),
            {"type": "markdown", "name": "Doc B", "content": "beta"},
            challenge_entry("y"),
        ]}],
    }
    reference_id = create_dojo(spec, session=admin_session)
    db_id = dojo_id(reference_id)

    assert db_sql(
        f"SELECT resource_index FROM dojo_resources WHERE dojo_id = {db_id} ORDER BY resource_index"
    ).split() == ["0", "2"], "resource_index counts challenge entries too"
    assert db_sql(
        f"SELECT data->>'unified_index' FROM dojo_challenges WHERE dojo_id = {db_id} ORDER BY challenge_index"
    ).split() == ["1", "3"]

    module = get_modules(admin_session, reference_id)[0]
    assert [resource["id"] for resource in module["resources"]] == ["resource-0", "resource-2"]
    assert [(item["item_type"], item["name"]) for item in module["unified_items"]] == [
        ("resource", "Doc A"), ("challenge", "X"), ("resource", "Doc B"), ("challenge", "Y")
    ]

    shrunk = dict(spec, modules=[{"id": "m", "resources": [
        {"type": "markdown", "name": "Doc A", "content": "alpha"},
        {"type": "markdown", "name": "Doc B", "content": "beta"},
        challenge_entry("y"),
    ]}])
    response = update_dojo(reference_id, shrunk, session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    assert db_sql(
        f"SELECT resource_index FROM dojo_resources WHERE dojo_id = {db_id} ORDER BY resource_index"
    ).split() == ["0", "1"], "resources must be renumbered without leaving stale rows"
    assert db_sql(
        f"SELECT data->>'unified_index' FROM dojo_challenges WHERE dojo_id = {db_id}"
    ).split() == ["2"]
    module = get_modules(admin_session, reference_id)[0]
    assert [(item["item_type"], item["name"]) for item in module["unified_items"]] == [
        ("resource", "Doc A"), ("resource", "Doc B"), ("challenge", "Y")
    ]


def test_data_field_assignment_persists_only_on_dojos(admin_session):
    reference_id = create_dojo({
        "id": f"dm-datafield-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }, session=admin_session)
    db_id = dojo_id(reference_id)

    output = flask_exec(f"""
from CTFd.models import db
from sqlalchemy.orm.attributes import flag_modified
from CTFd.plugins.dojo_plugin.models import Dojos

def reload():
    db.session.expire_all()
    return Dojos.query.filter_by(dojo_id={db_id}).first()

dojo = reload()
dojo.show_scoreboard = False
db.session.commit()
print("DOJO", reload().data.get("show_scoreboard"))

dojo = reload()
module = dojo.modules[0]
challenge = module.challenges[0]
module.show_challenges = False
challenge.progression_locked = True
db.session.commit()
module = reload().modules[0]
print("MODULE", module.data.get("show_challenges"))
print("CHALLENGE", module.challenges[0].data.get("progression_locked"))

module = reload().modules[0]
module.data["show_challenges"] = False
flag_modified(module, "data")
db.session.commit()
print("MODULE_FLAGGED", reload().modules[0].data.get("show_challenges"))
""")

    assert "DOJO False" in output, f"Dojos.__setattr__ must persist data fields: {output}"
    assert "MODULE True" in output, f"module data field assignment must be dropped: {output}"
    assert "CHALLENGE None" in output, f"challenge data field assignment must be dropped: {output}"
    assert "MODULE_FLAGGED False" in output, f"flag_modified writes must persist: {output}"
    assert db_sql(
        f"SELECT data->>'show_scoreboard' FROM dojos WHERE dojo_id = {db_id}").strip() == "false"


def test_duplicate_challenge_in_one_dojo_double_counts_solves(admin_session, data_model_user):
    user_name, user_session = data_model_user
    suffix = rand_suffix()
    source = create_dojo({
        "id": f"dm-double-src-{suffix}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }, session=admin_session)
    imported = {"import": {"dojo": source, "module": "m", "challenge": "c"}}
    duplicate = create_dojo({
        "id": f"dm-double-dup-{suffix}",
        "type": "public",
        "award": {"emoji": "🧪"},
        "modules": [
            {"id": "one", "resources": [challenge_entry("c", **imported)]},
            {"id": "two", "resources": [challenge_entry("c", **imported)]},
        ],
    }, session=admin_session)
    user_id = get_user_id(user_name)

    challenge_db_id = challenge_id_of(source, "m", "c")
    assert challenge_id_of(duplicate, "one", "c") == challenge_db_id
    assert challenge_id_of(duplicate, "two", "c") == challenge_db_id

    solve_offline(duplicate, "one", "c", session=user_session, user=user_name)
    assert count(solve_count_sql(challenge_db_id, user_id)) == 1, \
        "the user solved exactly one challenge row"

    solves = get_solves(user_session, duplicate)
    assert sorted(solve["module_id"] for solve in solves) == ["one", "two"], \
        "a challenge included twice counts its single solve twice"
    assert count(
        f"SELECT count(*) FROM awards WHERE category = '{dojo_hex(duplicate)}' AND user_id = {user_id}") == 1, \
        "the double counted solve reaches the two-challenge completion threshold"


def test_imported_challenge_dangles_when_source_deleted(admin_session, data_model_user):
    user_name, user_session = data_model_user
    suffix = rand_suffix()
    source = create_dojo({
        "id": f"dm-dangle-src-{suffix}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }, session=admin_session)
    importer = create_dojo({
        "id": f"dm-dangle-imp-{suffix}",
        "type": "public",
        "modules": [{"id": "m", "resources": [
            challenge_entry("c", **{"import": {"dojo": source, "module": "m", "challenge": "c"}}),
        ]}],
    }, session=admin_session)

    response = admin_session.post(f"{DOJO_URL}/dojo/{source}/delete/", json={"dojo": source})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"

    assert user_session.get(f"{DOJO_URL}/{importer}/").status_code == 200, \
        "the importing dojo must still render"
    modules = get_modules(user_session, importer)
    assert [challenge["id"] for challenge in modules[0]["challenges"]] == ["c"]

    response = user_session.post(f"{DOJO_URL}/pwncollege_api/v1/docker",
                                 json={"dojo": importer, "module": "m", "challenge": "c"})
    assert response.status_code == 200, f"Expected a JSON error, but got {response.status_code}"
    assert not response.json()["success"], "a dangling import must not report a successful start"
    with pytest.raises(RuntimeError):
        get_outer_container_for(f"user_{get_user_id(user_name)}")


def test_transfer_ignored_when_destination_id_exists(admin_session, data_model_user):
    user_name, user_session = data_model_user
    spec = {
        "id": f"dm-noopxfer-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("old"), challenge_entry("new")]}],
    }
    reference_id = create_dojo(spec, session=admin_session)
    original = {
        challenge_id: challenge_id_of(reference_id, "m", challenge_id) for challenge_id in ["old", "new"]
    }
    for challenge_id in ["old", "new"]:
        solve_offline(reference_id, "m", challenge_id, session=user_session, user=user_name)

    transferring = dict(spec, modules=[{"id": "m", "resources": [
        challenge_entry("old"),
        challenge_entry("new", transfer={"challenge": "old"}),
    ]}])
    response = update_dojo(reference_id, transferring, session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    for challenge_id, challenge_db_id in original.items():
        assert challenge_id_of(reference_id, "m", challenge_id) == challenge_db_id, \
            f"transfer aimed at an existing id must be a no-op for {challenge_id}"
        assert db_sql(f"SELECT name FROM challenges WHERE id = {challenge_db_id}").strip() == f"m:{challenge_id}"
    assert sorted(solve["challenge_id"] for solve in get_solves(user_session, reference_id)) == ["new", "old"]


def test_transfer_ignored_when_entry_also_imports(admin_session):
    suffix = rand_suffix()
    import_source = create_dojo({
        "id": f"dm-both-import-{suffix}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }, session=admin_session)
    transfer_source = create_dojo({
        "id": f"dm-both-transfer-{suffix}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("t")]}],
    }, session=admin_session)
    imported_challenge = challenge_id_of(import_source, "m", "c")
    transfer_challenge = challenge_id_of(transfer_source, "m", "t")

    combined = create_dojo({
        "id": f"dm-both-{suffix}",
        "type": "public",
        "modules": [{"id": "m", "resources": [challenge_entry("x", **{
            "import": {"dojo": import_source, "module": "m", "challenge": "c"},
            "transfer": {"dojo": transfer_source, "module": "m", "challenge": "t"},
        })]}]},
        session=admin_session)

    assert challenge_id_of(combined, "m", "x") == imported_challenge, "import wins over transfer"
    row = db_sql(f"SELECT category, name FROM challenges WHERE id = {transfer_challenge}").strip()
    assert row == f"{dojo_hex(transfer_source)}|m:t", "the transfer source must be left untouched"
    assert challenge_id_of(transfer_source, "m", "t") == transfer_challenge


def test_transfer_moves_challenge_row_and_source_keeps_referencing_it(admin_session, data_model_user):
    user_name, user_session = data_model_user
    suffix = rand_suffix()
    source_spec = {
        "id": f"dm-xfer-src-{suffix}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }
    source = create_dojo(source_spec, session=admin_session)
    challenge_db_id = challenge_id_of(source, "m", "c")
    solve_offline(source, "m", "c", session=user_session, user=user_name)

    destination = create_dojo({
        "id": f"dm-xfer-dst-{suffix}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "dm", "resources": [challenge_entry("dc", transfer={
            "dojo": source, "module": "m", "challenge": "c"})]}],
    }, session=admin_session)

    row = db_sql(f"SELECT category, name FROM challenges WHERE id = {challenge_db_id}").strip()
    assert row == f"{dojo_hex(destination)}|dm:dc", "a transfer rewrites the challenge row in place"
    assert challenge_id_of(source, "m", "c") == challenge_db_id, \
        "the source dojo still references the moved challenge"
    assert challenge_id_of(destination, "dm", "dc") == challenge_db_id

    response = update_dojo(source, source_spec, session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    assert challenge_id_of(source, "m", "c") == challenge_db_id, \
        "re-applying the source spec reuses the moved row rather than minting a new one"
    assert count(f"SELECT count(*) FROM challenges WHERE category = '{dojo_hex(source)}'") == 0
    assert count(f"SELECT count(*) FROM flags WHERE challenge_id = {challenge_db_id}") == 1
    assert [solve["challenge_id"] for solve in get_solves(user_session, source)] == ["c"]
    assert [solve["challenge_id"] for solve in get_solves(user_session, destination)] == ["dc"]


def test_dojo_membership_is_one_polymorphic_row(admin_session):
    user_name = "dm" + rand_suffix()
    user_session = login(user_name, user_name, register=True)
    user_id = get_user_id(user_name)

    reference_id = create_dojo({
        "id": f"dm-course-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }, session=admin_session)
    db_id = dojo_id(reference_id)
    token = f"student-{rand_suffix()}"
    course = json.dumps({"students": [token]})
    db_sql(f"UPDATE dojos SET data = jsonb_set(data, '{{course}}', '{course}'::jsonb) WHERE dojo_id = {db_id}")

    membership_sql = f"SELECT type, coalesce(token, '') FROM dojo_users WHERE dojo_id = {db_id} AND user_id = {user_id}"

    assert user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
    assert db_sql(membership_sql).strip() == "member|"

    response = user_session.patch(f"{DOJO_URL}/dojo/{reference_id}/course/identity", json={"identity": token})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], response.text
    assert db_sql(membership_sql).strip() == f"student|{token}", \
        "identifying converts the single membership row to a student"

    assert user_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
    assert db_sql(membership_sql).strip() == f"student|{token}", "joining twice must not add a row"

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{reference_id}/admins/promote",
                                  json={"user_id": user_id})
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert db_sql(membership_sql).strip() == f"admin|{token}", \
        "promotion mutates the same row and keeps the student token"

    assert user_session.get(f"{DOJO_URL}/dojo/{reference_id}/admin/").status_code == 200
    response = user_session.patch(f"{DOJO_URL}/dojo/{reference_id}/course/identity", json={"identity": token})
    assert response.json() == {"success": False, "error": "Cannot identify admin"}


def test_dojo_hash_renders_for_spec_created_dojo(admin_session):
    reference_id = create_dojo({
        "id": f"dm-hash-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "resources": [challenge_entry("c")]}],
    }, session=admin_session)
    assert db_sql(f"SELECT private_key IS NULL FROM dojos WHERE dojo_id = {dojo_id(reference_id)}").strip() == "t"

    response = admin_session.get(f"{DOJO_URL}/dojo/{reference_id}/admin/")
    assert response.status_code == 200, \
        f"the admin page of a keyless spec dojo must render, got {response.status_code}"
    assert admin_session.get(f"{DOJO_URL}/admin/dojos").status_code == 200, \
        "the site-wide dojo listing must render dojos without a deploy key"

    output = flask_exec(f"""
from CTFd.plugins.dojo_plugin.models import Dojos
dojo = Dojos.query.filter_by(dojo_id={dojo_id(reference_id)}).first()
try:
    print("HASH", repr(dojo.hash))
except Exception as error:
    print("HASH_ERROR", type(error).__name__)
""")
    assert "HASH ''" in output, f"a keyless dojo's hash must degrade to an empty string: {output}"


def test_dojo_hash_reports_the_commit_of_a_repository_dojo(admin_session, example_dojo):
    output = flask_exec(f"""
from CTFd.plugins.dojo_plugin.models import Dojos
dojo = Dojos.from_id({example_dojo!r}).first()
print("HASH", dojo.hash)
""")
    commit_hash = next(
        (line.split(maxsplit=1)[1] for line in output.splitlines() if line.startswith("HASH ")), "")
    assert re.fullmatch(r"[0-9a-f]{40}", commit_hash), \
        f"a repository dojo must report its git commit, got {commit_hash!r}"

    response = admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/")
    assert response.status_code == 200
    assert commit_hash[:8] in response.text, "the dojo admin page shows the deployed commit"


def test_update_with_challenges_shorthand_preserves_challenges(admin_session, data_model_user):
    user_name, user_session = data_model_user
    spec = {
        "id": f"dm-chalkey-{rand_suffix()}",
        "type": "public",
        "image": IMAGE,
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
    }
    reference_id = create_dojo(spec, session=admin_session)
    challenge_db_id = challenge_id_of(reference_id, "m", "c")
    solve_offline(reference_id, "m", "c", session=user_session, user=user_name)

    response = update_dojo(reference_id, dict(spec, name="Renamed"), session=admin_session)
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code} - {response.text}"

    assert count(f"SELECT count(*) FROM dojo_challenges WHERE dojo_id = {dojo_id(reference_id)}") == 1, \
        "re-applying the creating spec must not delete the dojo's challenges"
    assert challenge_id_of(reference_id, "m", "c") == challenge_db_id
    assert [solve["challenge_id"] for solve in get_solves(user_session, reference_id)] == ["c"]
