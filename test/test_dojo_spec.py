import json
import random
import string

import pytest
import yaml

from utils import (
    DOJO_URL,
    challenge_db_id,
    db_sql,
    dojo_db_id,
    dojo_run,
    flask_exec,
    get_user_id,
    login,
    make_dojo_official,
    solve_challenge_offline,
    wait_for_background_worker,
)


CHALLENGE_SOURCE = "#!/opt/pwn.college/bash\ncat /flag\n"


def spec_id(prefix):
    return f"{prefix}-{''.join(random.choices(string.ascii_lowercase, k=8))}"


def challenge_file(path):
    return {"type": "text", "path": path, "content": CHALLENGE_SOURCE}


def text_file(path, content):
    return {"type": "text", "path": path, "content": content}


def post_spec(session, spec):
    """POST a spec at the create API directly; create_dojo_yml retries, which is wrong for negative tests."""
    body = spec if isinstance(spec, str) else yaml.safe_dump(spec, sort_keys=False)
    return session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/create", json={"spec": body})


def create_dojo_spec(session, spec):
    response = post_spec(session, spec)
    assert response.status_code == 200, f"Expected dojo creation to succeed, got {response.status_code} - {response.text[:400]}"
    return response.json()["dojo"]


def reject_dojo_spec(session, spec):
    response = post_spec(session, spec)
    assert response.status_code == 400, f"Expected dojo creation to be rejected with 400, got {response.status_code} - {response.text[:400]}"
    return response.json()["error"]


def dojos_named(dojo_id):
    return int(db_sql(f"SELECT count(*) FROM dojos WHERE id = '{dojo_id}'"))


def dojo_data(dojo):
    return json.loads(db_sql(f"SELECT data FROM dojos WHERE dojo_id = {dojo_db_id(dojo)}"))


def module_data(dojo, module):
    return json.loads(db_sql(
        f"SELECT data FROM dojo_modules WHERE dojo_id = {dojo_db_id(dojo)} AND id = '{module}'"
    ))


def challenge_data(dojo, module, challenge):
    return json.loads(db_sql(
        "SELECT dc.data FROM dojo_challenges dc "
        "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = {dojo_db_id(dojo)} AND dm.id = '{module}' AND dc.id = '{challenge}'"
    ))


def challenge_ids(dojo):
    output = db_sql(
        "SELECT dm.id || '/' || dc.id FROM dojo_challenges dc "
        "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = {dojo_db_id(dojo)} ORDER BY dc.module_index, dc.challenge_index"
    )
    return output.split()


def module_indices(dojo):
    output = db_sql(
        f"SELECT module_index || '/' || id FROM dojo_modules WHERE dojo_id = {dojo_db_id(dojo)} "
        "ORDER BY module_index"
    )
    return output.split()


def get_modules(session, dojo):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/modules")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    return response.json()["modules"]


def get_module(session, dojo, module_id):
    modules = get_modules(session, dojo)
    matching = [module for module in modules if module["id"] == module_id]
    assert matching, f"Module {module_id} not present in {[module['id'] for module in modules]}"
    return matching[0]


def request_container(session, dojo, module, challenge, practice=False):
    response = session.post(f"{DOJO_URL}/pwncollege_api/v1/docker",
                            json=dict(dojo=dojo, module=module, challenge=challenge, practice=practice))
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    return response.json()


def ctfd_path_exists(path):
    return dojo_run("docker", "exec", "ctfd", "test", "-e", path, check=False).returncode == 0


@pytest.fixture(scope="module")
def spec_user():
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    return name, login(name, name, register=True)


@pytest.fixture(scope="module")
def spec_outsider():
    name = "".join(random.choices(string.ascii_lowercase, k=16))
    return name, login(name, name, register=True)


def test_dojo_id_is_required_and_validated(admin_session):
    error = reject_dojo_spec(admin_session, "name: No Id\n")
    assert "Dojo id must be defined" in error, f"Unexpected error for missing id: {error}"

    for bad_id in ["Bad-Id", "bad_id", "x" * 33, "has space"]:
        error = reject_dojo_spec(admin_session, {"id": bad_id})
        assert "id" in error and "^[a-z0-9-]{1,32}$" in error, f"Unexpected error for id {bad_id!r}: {error[:300]}"

    assert dojos_named("Bad-Id") == 0, "Rejected dojo id should not create a dojos row"
    assert dojos_named("bad_id") == 0, "Rejected dojo id should not create a dojos row"


def test_unknown_spec_keys_are_rejected(admin_session):
    cases = [
        {"id": spec_id("bogus"), "modulez": []},
        {"id": spec_id("bogus"), "modules": [{"id": "m", "resources": [
            {"type": "challenge", "id": "c", "name": "C", "bogus": 1}]}]},
        {"id": spec_id("bogus"), "modules": [{"id": "m", "resources": [
            {"type": "markdown", "name": "x", "content": "y", "bogus": 1}]}]},
    ]
    for spec in cases:
        error = reject_dojo_spec(admin_session, spec)
        assert "bogus" in error, f"Error should name the unknown key: {error[:300]}"
        assert dojos_named(spec["id"]) == 0, f"Rejected spec created a dojos row for {spec['id']}"


def test_auxiliary_is_accepted_and_not_persisted(admin_session):
    dojo_id = spec_id("aux")
    dojo = create_dojo_spec(admin_session, {
        "id": dojo_id,
        "auxiliary": {"anything": {"deeply": [1, 2, 3]}},
        "modules": [{
            "id": "m",
            "auxiliary": {"module_level": True},
            "resources": [{"type": "challenge", "id": "c", "name": "C", "auxiliary": {"challenge_level": True}}],
        }],
        "files": [challenge_file("m/c/src")],
    })

    module = get_module(admin_session, dojo, "m")
    assert [challenge["id"] for challenge in module["challenges"]] == ["c"]
    assert "auxiliary" not in dojo_data(dojo), "auxiliary must not be stored on the dojo"
    assert "auxiliary" not in module_data(dojo, "m"), "auxiliary must not be stored on the module"
    assert "auxiliary" not in challenge_data(dojo, "m", "c"), "auxiliary must not be stored on the challenge"


def test_names_autofill_from_ids(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("autoname"),
        "modules": [{"id": "hello-there", "challenges": [{"id": "big-apple"}]}],
        "files": [challenge_file("hello-there/big-apple/src")],
    })

    module = get_module(admin_session, dojo, "hello-there")
    assert module["name"] == "Hello There", f"Expected auto-filled module name, got {module['name']!r}"
    assert module["challenges"][0]["name"] == "Big Apple", f"Expected auto-filled challenge name, got {module['challenges'][0]['name']!r}"

    name = db_sql(f"SELECT coalesce(name, '<NULL>') FROM dojos WHERE dojo_id = {dojo_db_id(dojo)}").strip()
    assert name == "<NULL>", f"Dojos must not get an auto-filled name, got {name!r}"


def test_module_ordering_follows_spec_order(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("ordering"),
        "type": "public",
        "modules": [
            {"id": "zeta", "challenges": [{"id": "zed"}, {"id": "alpha"}]},
            {"id": "alpha", "challenges": [{"id": "one"}]},
        ],
        "files": [challenge_file("zeta/zed/src"), challenge_file("zeta/alpha/src"), challenge_file("alpha/one/src")],
    })

    assert module_indices(dojo) == ["0/zeta", "1/alpha"], "module_index must follow spec order, not sort order"
    assert challenge_ids(dojo) == ["zeta/zed", "zeta/alpha", "alpha/one"], "challenge_index must follow spec order"
    assert [module["id"] for module in get_modules(admin_session, dojo)] == ["zeta", "alpha"]


def test_dojo_directory_fills_in_names_descriptions_and_subyamls(admin_session, example_dojo):
    modules = get_modules(admin_session, example_dojo)
    by_id = {module["id"]: module for module in modules}

    assert "The first module in this example dojo." in by_id["hello"]["description"]
    assert by_id["hello"]["name"] == "Hello", "module.yml should supply the module name"
    assert [challenge["id"] for challenge in by_id["hello"]["challenges"]] == ["apple", "banana"]
    assert [challenge["id"] for challenge in by_id["world"]["challenges"]] == ["earth", "mars", "venus"]

    apple = next(challenge for challenge in by_id["hello"]["challenges"] if challenge["id"] == "apple")
    assert "This is apple." in apple["description"], "challenge DESCRIPTION.md should populate the description"

    assert "example dojo" in db_sql("SELECT description FROM dojos WHERE id = 'example' AND official")

    lecture_resources = [resource for resource in by_id["lectures"]["resources"] if resource["type"] == "lecture"]
    assert [resource["name"] for resource in lecture_resources] == ["Ungraded Lecture"]
    assert [challenge["id"] for challenge in by_id["lectures"]["challenges"]] == ["graded-lecture"]
    assert challenge_data("example", "lectures", "graded-lecture")["image"] == "pwncollege/challenge-lecture"


def test_subyaml_precedence_and_survey_src_from_directory():
    tag = "".join(random.choices(string.ascii_lowercase, k=8))
    output = flask_exec(f'''
import json, pathlib, shutil
from CTFd.models import db
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_dir

root = pathlib.Path("/tmp/dojo-spec-test-{tag}")
shutil.rmtree(root, ignore_errors=True)
(root / "m" / "c").mkdir(parents=True)
(root / "surveys").mkdir(parents=True)
(root / "dojo.yml").write_text("""
id: subyaml-{tag}
survey-sources: surveys
modules:
  - id: m
    name: Top Name
    challenges:
      - id: c
        name: Top Chal
        survey:
          prompt: P
          src: s.html
""")
(root / "DESCRIPTION.md").write_text("dojo-md-desc")
(root / "surveys" / "s.html").write_text("<div>from file</div>")
(root / "m" / "module.yml").write_text("name: Sub Name\\ndescription: sub-module-desc\\n")
(root / "m" / "DESCRIPTION.md").write_text("module-md-desc")
(root / "m" / "c" / "challenge.yml").write_text(
    "name: Sub Chal\\ndescription: sub-chal-desc\\nimage: pwncollege/challenge-simple\\n")
(root / "m" / "c" / "src").write_text("x")

dojo = dojo_from_dir(root)
module = dojo.modules[0]
challenge = module.challenges[0]
result = dict(dojo_description=dojo.description,
              module_name=module.name,
              module_description=module.description,
              challenge_name=challenge.name,
              challenge_description=challenge.description,
              image=challenge.data.get("image"),
              survey=challenge.data.get("survey"))
db.session.rollback()
shutil.rmtree(root, ignore_errors=True)
print("RESULT " + json.dumps(result))
''')
    result = json.loads(next(line for line in output.splitlines() if line.startswith("RESULT "))[len("RESULT "):])

    assert result["module_name"] == "Top Name", "dojo.yml must win over module.yml"
    assert result["challenge_name"] == "Top Chal", "dojo.yml must win over challenge.yml"
    assert result["module_description"] == "sub-module-desc", "module.yml must fill in an unset description"
    assert result["challenge_description"] == "sub-chal-desc", "challenge.yml must fill in an unset description"
    assert result["dojo_description"] == "dojo-md-desc", "DESCRIPTION.md must fill in the dojo description"
    assert result["image"] == "pwncollege/challenge-simple", "challenge.yml must supply the image"
    assert result["survey"] == {"prompt": "P", "data": "<div>from file</div>"}, \
        f"survey-sources src should load the survey body, got {result['survey']}"


def test_dojo_level_import_inherits_source_fields(admin_session, example_dojo):
    dojo_id = spec_id("dojoimport")
    dojo = create_dojo_spec(admin_session, {"id": dojo_id, "import": {"dojo": "example"}})

    source_name = db_sql("SELECT name FROM dojos WHERE id = 'example' AND official").strip()
    assert db_sql(f"SELECT name FROM dojos WHERE dojo_id = {dojo_db_id(dojo)}").strip() == source_name
    assert dojo_data(dojo)["award"] == json.loads(db_sql("SELECT data->'award' FROM dojos WHERE id = 'example' AND official"))


def test_missing_import_targets_are_reported(admin_session, example_dojo):
    error = reject_dojo_spec(admin_session, {"id": spec_id("impchal"), "modules": [{"id": "m", "challenges": [
        {"id": "c", "import": {"dojo": "example", "module": "hello", "challenge": "durian"}}]}]})
    assert "Import challenge" in error and "durian" in error, f"Unexpected error: {error[:300]}"

    error = reject_dojo_spec(admin_session, {"id": spec_id("impdojo"), "modules": [{"id": "m", "challenges": [
        {"id": "c", "import": {"dojo": "nonexistent-dojo-xyz", "module": "hello", "challenge": "apple"}}]}]})
    assert "does not exist" in error, f"Unexpected error: {error[:300]}"

    error = reject_dojo_spec(admin_session, {"id": spec_id("impmod"), "modules": [
        {"import": {"dojo": "example", "module": "nomodule"}}]})
    assert "Import module" in error and "nomodule" in error, f"Unexpected error: {error[:300]}"

    error = reject_dojo_spec(admin_session, {"id": spec_id("imptop"), "import": {"dojo": "nonexistent-dojo-xyz"}})
    assert "does not exist" in error, f"Unexpected error: {error[:300]}"


def test_import_source_must_be_official_or_referenced_by_unique_id(admin_session):
    source_id = spec_id("importsrc")
    source = create_dojo_spec(admin_session, {
        "id": source_id,
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })
    assert "~" in source, "an unofficial dojo's reference id must carry its unique suffix"

    error = reject_dojo_spec(admin_session, {"id": spec_id("importbare"), "modules": [{"id": "m", "challenges": [
        {"id": "c", "import": {"dojo": source_id, "module": "m", "challenge": "c"}}]}]})
    assert "does not exist" in error, f"Bare id of an unofficial dojo must not resolve: {error[:300]}"

    importer = create_dojo_spec(admin_session, {"id": spec_id("importref"), "modules": [{"id": "m2", "challenges": [
        {"id": "c2", "import": {"dojo": source, "module": "m", "challenge": "c"}}]}]})
    assert challenge_db_id(importer, "m2", "c2") == challenge_db_id(source, "m", "c"), \
        "an imported challenge must reuse the source Challenges row"


def test_importable_false_blocks_imports(admin_session):
    source_id = spec_id("noimport")
    source = create_dojo_spec(admin_session, {
        "id": source_id,
        "modules": [
            {"id": "blocked", "importable": False, "challenges": [{"id": "c"}]},
            {"id": "open", "challenges": [{"id": "c"}]},
        ],
        "files": [challenge_file("blocked/c/src"), challenge_file("open/c/src")],
    })
    make_dojo_official(source, admin_session)

    error = reject_dojo_spec(admin_session, {"id": spec_id("importer"), "modules": [
        {"import": {"dojo": source_id, "module": "blocked"}}]})
    assert "Import disallowed" in error, f"Unexpected error: {error[:300]}"

    create_dojo_spec(admin_session, {"id": spec_id("importer"), "modules": [
        {"import": {"dojo": source_id, "module": "open"}}]})


def test_dojo_level_importable_false_shadows_challenges_only(admin_session):
    source_id = spec_id("noimpdojo")
    source = create_dojo_spec(admin_session, {
        "id": source_id,
        "importable": False,
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })
    make_dojo_official(source, admin_session)

    assert "importable" not in dojo_data(source), "dojo-level importable is not stored on the dojos row"
    assert challenge_data(source, "m", "c")["importable"] is False, "dojo-level importable must shadow onto challenges"

    error = reject_dojo_spec(admin_session, {"id": spec_id("importer"), "modules": [{"id": "x", "challenges": [
        {"id": "c", "import": {"dojo": source_id, "module": "m", "challenge": "c"}}]}]})
    assert "Import disallowed" in error, f"Unexpected error: {error[:300]}"


def test_imported_challenge_shares_solves_with_source(admin_session, example_dojo, random_user):
    name, session = random_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("shared"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [
            {"id": "c", "import": {"dojo": "example", "module": "hello", "challenge": "apple"}}]}],
    })
    assert challenge_db_id(dojo, "m", "c") == challenge_db_id("example", "hello", "apple")

    solve_challenge_offline(dojo, "m", "c", session=session, user=name)

    solves = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/solves").json()["solves"]
    assert [solve["challenge_id"] for solve in solves] == ["apple"], \
        f"solving an imported challenge must register in the source dojo, got {solves}"


def test_imported_challenge_field_overrides(admin_session, example_import_dojo):
    modules = get_modules(admin_session, example_import_dojo)
    by_id = {module["id"]: module for module in modules}

    assert by_id["hello"]["name"] == "Hello", "an imported module inherits its source name"
    assert [challenge["id"] for challenge in by_id["hello"]["challenges"]] == ["apple", "banana"]

    planet = {challenge["id"]: challenge for challenge in by_id["planet"]["challenges"]}
    assert planet["mars"]["name"] == "Martian Planet", "the importing entry must override the name"
    assert "martian" in planet["mars"]["description"], "the importing entry must override the description"
    assert planet["earth"]["name"] == "Earth", "unspecified fields fall back to the source challenge"
    assert "earth" in planet["earth"]["description"].lower(), "unspecified description falls back to the source"


def test_imported_challenge_path_override_prefers_official_local_files(admin_session, example_dojo):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("pathovr"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [
            {"id": "apple", "import": {"dojo": "example", "module": "hello", "challenge": "apple"}}]}],
        "files": [challenge_file("m/apple/boom")],
    })

    source_path = db_sql(
        f"SELECT dc.data->>'path_override' FROM dojo_challenges dc WHERE dc.dojo_id = {dojo_db_id(dojo)}"
    ).strip()
    assert source_path.endswith("/hello/apple"), f"path_override should point at the source challenge, got {source_path!r}"

    probe = f'''
from CTFd.plugins.dojo_plugin.models import DojoChallenges
challenge = DojoChallenges.from_id({dojo!r}, "m", "apple").first()
print("PATH " + str(challenge.path))
'''
    unofficial_path = flask_exec(probe).strip().split("PATH ", 1)[1].strip()
    assert unofficial_path == source_path, "an unofficial dojo must not override imported challenge files"

    make_dojo_official(dojo, admin_session)
    official_path = flask_exec(probe).strip().split("PATH ", 1)[1].strip()
    assert official_path.endswith("/m/apple") and official_path != source_path, \
        f"an official dojo shipping its own directory must override, got {official_path!r}"


def test_transfer_with_missing_source_is_rejected(admin_session):
    dojo_id = spec_id("transfer")
    reject_dojo_spec(admin_session, {
        "id": dojo_id,
        "modules": [{"id": "m", "resources": [
            {"type": "challenge", "id": "c", "name": "C", "transfer": {"challenge": "does-not-exist"}}]}],
        "files": [challenge_file("m/c/src")],
    })
    assert dojos_named(dojo_id) == 0, "a failed transfer must not leave a dojos row"

    spec = {
        "id": spec_id("transfer"),
        "type": "public",
        "modules": [{"id": "m", "resources": [{"type": "challenge", "id": "c", "name": "C"}]}],
        "files": [challenge_file("m/c/src")],
    }
    dojo = create_dojo_spec(admin_session, spec)
    original_challenge_id = challenge_db_id(dojo, "m", "c")

    broken = json.loads(json.dumps(spec))
    broken["modules"][0]["resources"] = [
        {"type": "challenge", "id": "new", "name": "New", "transfer": {"challenge": "does-not-exist"}}]
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update", json=broken)
    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    assert "unable to find source" in response.json()["error"], f"Unexpected error: {response.json()['error'][:300]}"

    broken["modules"][0]["resources"] = [
        {"type": "challenge", "id": "new", "name": "New",
         "transfer": {"dojo": "nonexistent-dojo-xyz~00000000", "module": "m", "challenge": "c"}}]
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update", json=broken)
    assert response.status_code == 400, f"Expected 400, got {response.status_code}"

    assert challenge_ids(dojo) == ["m/c"], "a failed transfer must leave the existing challenges intact"
    assert challenge_db_id(dojo, "m", "c") == original_challenge_id


def test_password_gates_join_and_visibility(admin_session, spec_user):
    name, session = spec_user

    error = reject_dojo_spec(admin_session, {"id": spec_id("shortpw"), "password": "short1"})
    assert "password" in error, f"Unexpected error: {error[:300]}"

    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("password"),
        "type": "topic",
        "password": "hunter2hunter2",
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })
    user_id = get_user_id(name)
    membership = f"SELECT count(*) FROM dojo_users WHERE dojo_id = {dojo_db_id(dojo)} AND user_id = {user_id}"

    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 403, "joining without the password must be forbidden"
    assert int(db_sql(membership)) == 0, "a forbidden join must not create a membership"

    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/hunter2hunter2").status_code == 200
    assert int(db_sql(membership)) == 1, "joining with the password must create a membership"
    assert session.get(f"{DOJO_URL}/{dojo}/").status_code == 200


def test_password_excludes_public_dojo_from_viewable(admin_session, spec_user):
    name, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("pubpw"),
        "type": "public",
        "password": "longenough123",
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })

    assert session.get(f"{DOJO_URL}/{dojo}/").status_code == 404, "a password-protected public dojo is not viewable"
    result = request_container(session, dojo, "m", "c")
    assert result["success"] is False and result["error"] == "Invalid dojo", f"Unexpected result: {result}"

    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/longenough123").status_code == 200
    assert session.get(f"{DOJO_URL}/{dojo}/").status_code == 200


def test_public_dojo_is_open_without_joining(admin_session, spec_user):
    name, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("public"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })

    assert session.get(f"{DOJO_URL}/{dojo}/").status_code == 200
    solve_challenge_offline(dojo, "m", "c", session=session, user=name)

    solves = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/solves").json()["solves"]
    assert [solve["challenge_id"] for solve in solves] == ["c"], f"Unexpected solves: {solves}"
    membership = int(db_sql(
        f"SELECT count(*) FROM dojo_users WHERE dojo_id = {dojo_db_id(dojo)} AND user_id = {get_user_id(name)}"))
    assert membership == 0, "a public dojo must be usable without a membership row"


def test_private_dojo_requires_membership_and_unique_reference_id(admin_session, spec_user, spec_outsider):
    name, session = spec_user
    _, outsider_session = spec_outsider
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("private"),
        "type": "topic",
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })
    bare_id = dojo.split("~")[0]

    assert session.get(f"{DOJO_URL}/{dojo}/").status_code == 404, "non-members must not see a private dojo"
    assert session.get(f"{DOJO_URL}/{bare_id}/").status_code == 404, "the bare id must not resolve for unofficial dojos"
    assert admin_session.get(f"{DOJO_URL}/{dojo}/").status_code == 200, "site admins can always view"

    assert session.get(f"{DOJO_URL}/dojo/{dojo}/join/").status_code == 200
    assert session.get(f"{DOJO_URL}/{dojo}/").status_code == 200

    make_dojo_official(dojo, admin_session)
    assert outsider_session.get(f"{DOJO_URL}/{bare_id}/").status_code == 200, \
        "an official dojo resolves by its bare id, even for a non-member"


def test_hidden_dojo_is_not_listed(admin_session, spec_user):
    _, session = spec_user
    hidden = create_dojo_spec(admin_session, {"id": spec_id("hidden"), "type": "hidden"})
    public = create_dojo_spec(admin_session, {"id": spec_id("shown"), "type": "public"})

    listing = session.get(f"{DOJO_URL}/dojos")
    assert listing.status_code == 200
    assert public in listing.text, "a public dojo should be listed in the catalog"
    assert hidden not in listing.text, "a hidden dojo must not be listed in the catalog"
    assert admin_session.get(f"{DOJO_URL}/{hidden}/").status_code == 200, "a hidden dojo stays directly accessible"


def test_award_emoji_validation_and_belt_award(admin_session, random_user):
    name, session = random_user

    error = reject_dojo_spec(admin_session, {"id": spec_id("award"), "award": {"emoji": ":)"}})
    assert "emoji" in error, f"Unexpected error: {error[:300]}"
    create_dojo_spec(admin_session, {"id": spec_id("award"), "award": {"emoji": "\U0001f43b‍❄️"}})

    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("belt"),
        "type": "public",
        "award": {"belt": "orange"},
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })
    assert dojo_data(dojo)["award"] == {"belt": "orange"}

    solve_challenge_offline(dojo, "m", "c", session=session, user=name)
    wait_for_background_worker()

    hex_id = dojo.split("~")[1]
    emojis = int(db_sql(f"SELECT count(*) FROM awards WHERE category = '{hex_id}'"))
    assert emojis == 0, "a belt-award dojo must not grant a completion emoji"


def test_image_shadowing(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("image"),
        "image": "pwncollege/challenge-simple",
        "modules": [
            {"id": "a", "challenges": [{"id": "inherit"}, {"id": "override", "image": "pwncollege/challenge-lecture"}]},
            {"id": "b", "image": "pwncollege/challenge-legacy", "challenges": [{"id": "moduleimage"}]},
        ],
        "files": [challenge_file("a/inherit/src"), challenge_file("a/override/src"), challenge_file("b/moduleimage/src")],
    })

    assert challenge_data(dojo, "a", "inherit")["image"] == "pwncollege/challenge-simple"
    assert challenge_data(dojo, "a", "override")["image"] == "pwncollege/challenge-lecture"
    assert challenge_data(dojo, "b", "moduleimage")["image"] == "pwncollege/challenge-legacy"

    imageless = create_dojo_spec(admin_session, {
        "id": spec_id("noimage"),
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })
    assert challenge_data(imageless, "m", "c")["image"] is None, "no image anywhere means no stored image"


def test_interfaces_validation_and_shadowing(admin_session):
    reject_dojo_spec(admin_session, {"id": spec_id("iface"), "interfaces": [{"name": "Web"}]})
    reject_dojo_spec(admin_session, {"id": spec_id("iface"), "interfaces": [{"name": "1bad", "port": 80}]})
    create_dojo_spec(admin_session, {"id": spec_id("iface"), "interfaces": [{"name": "SSH"}]})

    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("iface"),
        "interfaces": [{"name": "SSH"}],
        "modules": [
            {"id": "a", "challenges": [{"id": "inherit"}]},
            {"id": "b", "interfaces": [{"name": "Code", "port": 8080}], "challenges": [
                {"id": "moduleiface"},
                {"id": "chaliface", "interfaces": [{"name": "Terminal", "port": 7681}]},
            ]},
        ],
        "files": [challenge_file("a/inherit/src"), challenge_file("b/moduleiface/src"), challenge_file("b/chaliface/src")],
    })

    assert challenge_data(dojo, "a", "inherit")["interfaces"] == [{"name": "SSH"}]
    assert challenge_data(dojo, "b", "moduleiface")["interfaces"] == [{"name": "Code", "port": 8080}]
    assert challenge_data(dojo, "b", "chaliface")["interfaces"] == [{"name": "Terminal", "port": 7681}]

    default = create_dojo_spec(admin_session, {
        "id": spec_id("iface"),
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")],
    })
    names = [interface["name"] for interface in challenge_data(default, "m", "c")["interfaces"]]
    assert names == ["Terminal", "Code", "Desktop", "SSH"], f"Unexpected default interfaces: {names}"


def test_privileged_and_allow_privileged_shadowing(admin_session, spec_user):
    _, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("priv"),
        "type": "public",
        "privileged": True,
        "image": "pwncollege/challenge-simple",
        "modules": [
            {"id": "blocked", "allow_privileged": False, "challenges": [
                {"id": "c"},
                {"id": "reenabled", "allow_privileged": True},
            ]},
            {"id": "open", "privileged": False, "challenges": [{"id": "c"}]},
        ],
        "files": [challenge_file("blocked/c/src"), challenge_file("blocked/reenabled/src"), challenge_file("open/c/src")],
    })

    assert "privileged" not in dojo_data(dojo), "dojo-level privileged is not stored on the dojos row"
    assert challenge_data(dojo, "blocked", "c")["privileged"] is True, "dojo-level privileged shadows onto challenges"
    assert challenge_data(dojo, "open", "c")["privileged"] is False, "module-level privileged wins over dojo-level"
    assert challenge_data(dojo, "blocked", "c")["allow_privileged"] is False
    assert challenge_data(dojo, "blocked", "reenabled")["allow_privileged"] is True
    assert challenge_data(dojo, "open", "c")["allow_privileged"] is True

    result = request_container(session, dojo, "blocked", "c", practice=True)
    assert result["success"] is False and "practice" in result["error"], f"Unexpected result: {result}"


def test_show_challenges_is_module_level_and_presentation_only(admin_session, spec_user):
    _, session = spec_user

    error = reject_dojo_spec(admin_session, {"id": spec_id("showchal"), "show_challenges": False})
    assert "show_challenges" in error, f"show_challenges is not a dojo-level key: {error[:300]}"

    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("showchal"),
        "type": "public",
        "modules": [
            {"id": "quiet", "show_challenges": False, "challenges": [{"id": "c"}]},
            {"id": "loud", "challenges": [{"id": "c"}]},
        ],
        "files": [challenge_file("quiet/c/src"), challenge_file("loud/c/src")],
    })

    assert module_data(dojo, "quiet")["show_challenges"] is False
    assert module_data(dojo, "loud")["show_challenges"] is True

    module = get_module(session, dojo, "quiet")
    assert [challenge["id"] for challenge in module["challenges"]] == ["c"], \
        "show_challenges is presentation-only: the modules API still lists the challenge"


def test_show_scoreboard_shadowing(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("scoreboard"),
        "show_scoreboard": False,
        "modules": [
            {"id": "a", "challenges": [{"id": "c"}]},
            {"id": "b", "show_scoreboard": True, "challenges": [{"id": "c"}]},
        ],
        "files": [challenge_file("a/c/src"), challenge_file("b/c/src")],
    })

    assert module_data(dojo, "a")["show_scoreboard"] is False, "dojo-level show_scoreboard shadows onto modules"
    assert module_data(dojo, "b")["show_scoreboard"] is True, "module-level show_scoreboard wins"
    assert "show_scoreboard" not in dojo_data(dojo), "dojo-level show_scoreboard is not stored on the dojos row"


def test_progression_lock_gates_description(admin_session, spec_user):
    name, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("progression"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [
            {"id": "first", "progression_locked": True, "description": "first desc"},
            {"id": "second", "progression_locked": True, "description": "second desc"},
        ]}],
        "files": [challenge_file("m/first/src"), challenge_file("m/second/src")],
    })
    description_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/m/second/description"

    response = session.get(description_url)
    assert response.status_code == 403, f"Expected 403 for a locked challenge, got {response.status_code}"
    assert "locked" in response.json()["error"]

    assert admin_session.get(description_url).status_code == 200, "dojo admins bypass progression locks"

    solve_challenge_offline(dojo, "m", "first", session=session, user=name)

    response = session.get(description_url)
    assert response.status_code == 200, f"Expected 200 after unlocking, got {response.status_code}"
    assert "second desc" in response.json()["description"]


def test_required_false_is_excluded_from_completion(admin_session, random_user):
    name, session = random_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("required"),
        "type": "public",
        "award": {"emoji": "\U0001f9ea"},
        "modules": [{"id": "m", "challenges": [{"id": "req"}, {"id": "opt", "required": False}]}],
        "files": [challenge_file("m/req/src"), challenge_file("m/opt/src")],
    })

    module = get_module(session, dojo, "m")
    required = {challenge["id"]: challenge["required"] for challenge in module["challenges"]}
    assert required == {"req": True, "opt": False}, f"Unexpected required flags: {required}"

    listed = next(entry for entry in session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos").json()["dojos"]
                  if entry["id"] == dojo)
    assert listed["challenges_count"] == 1, "only required challenges count towards the dojo total"

    solve_challenge_offline(dojo, "m", "req", session=session, user=name)
    wait_for_background_worker()

    standings = session.get(f"{DOJO_URL}/pwncollege_api/v1/scoreboard/{dojo}/_/0/1").json()["standings"]
    us = next(entry for entry in standings if entry["name"] == name)
    assert [badge["emoji"] for badge in us["badges"]] == ["\U0001f9ea"], \
        f"the award should be granted once all required challenges are solved, got {us['badges']}"


def test_visibility_is_inherited_from_the_dojo_level(admin_session, spec_user):
    _, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("visibility"),
        "type": "public",
        "visibility": {"start": "2099-01-01T00:00:00Z"},
        "modules": [
            {"id": "past", "visibility": {"start": "2000-01-01T00:00:00Z"}, "challenges": [
                {"id": "shown"},
                {"id": "hidden", "visibility": {"start": "2099-01-01T00:00:00Z"}},
            ]},
            {"id": "future", "challenges": [{"id": "later"}]},
        ],
        "files": [challenge_file("past/shown/src"), challenge_file("past/hidden/src"), challenge_file("future/later/src")],
    })

    visible = [(module["id"], [challenge["id"] for challenge in module["challenges"]])
               for module in get_modules(session, dojo)]
    assert visible == [("past", ["shown"])], f"Unexpected visible modules: {visible}"

    for module_id, challenge_id in [("future", "later"), ("past", "hidden")]:
        result = request_container(session, dojo, module_id, challenge_id)
        assert result["success"] is False and result["error"] == "Invalid challenge", \
            f"Expected {module_id}/{challenge_id} to be unstartable, got {result}"

    as_admin = [(module["id"], [challenge["id"] for challenge in module["challenges"]])
                for module in get_modules(admin_session, dojo)]
    assert as_admin == [("past", ["shown", "hidden"]), ("future", ["later"])], f"Admins see everything: {as_admin}"


def test_visibility_stop_in_the_past_hides_challenge(admin_session, spec_user):
    _, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("expired"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [
            {"id": "expired", "visibility": {"stop": "2000-01-01T00:00:00Z"}},
            {"id": "control"},
        ]}],
        "files": [challenge_file("m/expired/src"), challenge_file("m/control/src")],
    })

    module = get_module(session, dojo, "m")
    assert [challenge["id"] for challenge in module["challenges"]] == ["control"]

    result = request_container(session, dojo, "m", "expired")
    assert result["success"] is False and result["error"] == "Invalid challenge", f"Unexpected result: {result}"

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/m/expired/solve",
                                  json={"submission": "pwn.college{nope}"})
    assert response.status_code == 404, f"the solve route has no admin bypass, got {response.status_code}"
    assert response.json()["error"] == "Challenge not found"


def test_resource_visibility_hides_resource_from_members(admin_session, spec_user):
    _, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("resvis"),
        "type": "public",
        "modules": [{"id": "m", "resources": [
            {"type": "markdown", "name": "Now Res", "content": "now"},
            {"type": "markdown", "name": "Future Res", "content": "future",
             "visibility": {"start": "2099-01-01T00:00:00Z"}},
        ]}],
    })

    member_resources = [resource["name"] for resource in get_module(session, dojo, "m")["resources"]]
    assert member_resources == ["Now Res"], f"Unexpected member-visible resources: {member_resources}"

    admin_resources = [resource["name"] for resource in get_module(admin_session, dojo, "m")["resources"]]
    assert admin_resources == ["Now Res", "Future Res"], f"Dojo admins see all resources: {admin_resources}"


def test_resource_visibility_applies_to_unified_items(admin_session, spec_user):
    _, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("resvis"),
        "type": "public",
        "modules": [{"id": "m", "resources": [
            {"type": "markdown", "name": "Now Res", "content": "now"},
            {"type": "markdown", "name": "Future Res", "content": "FUTURE_MARKER",
             "visibility": {"start": "2099-01-01T00:00:00Z"}},
        ]}],
    })

    items = [item["name"] for item in get_module(session, dojo, "m")["unified_items"]]
    assert items == ["Now Res"], f"an invisible resource must not appear in unified_items, got {items}"
    assert "FUTURE_MARKER" not in session.get(f"{DOJO_URL}/{dojo}/m/").text, \
        "an invisible resource's content must not be rendered on the module page"


def test_resource_types_expose_their_fields(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("resource"),
        "type": "public",
        "modules": [{"id": "m", "resources": [
            {"type": "markdown", "name": "Inline", "content": "TESTB123"},
            {"type": "markdown", "name": "Flat", "content": "flat", "expandable": False},
            {"type": "lecture", "name": "Lecture", "video": "vid1", "playlist": "pl1", "slides": "sl1"},
            {"type": "lecture", "name": "Bare Lecture"},
            {"type": "header", "content": "Advanced Section"},
        ]}],
    })
    module = get_module(admin_session, dojo, "m")
    resources = {resource["name"]: resource for resource in module["resources"]}

    assert resources["Inline"]["type"] == "markdown"
    assert resources["Inline"]["content"] == "TESTB123"
    assert resources["Inline"]["expandable"] is True
    assert resources["Flat"]["expandable"] is False

    lecture = resources["Lecture"]
    assert (lecture["video"], lecture["playlist"], lecture["slides"]) == ("vid1", "pl1", "sl1")
    assert lecture["content"] is None, "lecture resources carry no markdown content"

    header = next(resource for resource in module["resources"] if resource["type"] == "header")
    assert header["name"] is None, "header resources have no name"
    header_item = next(item for item in module["unified_items"] if item["type"] == "header")
    assert header_item["content"] == "Advanced Section"

    reject_dojo_spec(admin_session, {"id": spec_id("resource"), "modules": [{"id": "m", "resources": [
        {"type": "video", "name": "x"}]}]})
    reject_dojo_spec(admin_session, {"id": spec_id("resource"), "modules": [{"id": "m", "resources": [
        {"type": "markdown", "content": "x"}]}]})
    reject_dojo_spec(admin_session, {"id": spec_id("resource"), "modules": [{"id": "m", "resources": [
        {"type": "header"}]}]})


def test_markdown_resource_file_loading(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("mdfile"),
        "type": "public",
        "modules": [{"id": "m", "resources": [{"type": "markdown", "name": "From File", "file": "content.md"}]}],
        "files": [text_file("m/content.md", "FILE_CONTENT_123")],
    })
    resource = get_module(admin_session, dojo, "m")["resources"][0]
    assert resource["content"] == "FILE_CONTENT_123", f"Unexpected resource content: {resource['content']!r}"

    missing_id = spec_id("mdfile")
    error = reject_dojo_spec(admin_session, {"id": missing_id, "modules": [{"id": "m", "resources": [
        {"type": "markdown", "name": "x", "file": "missing.md"}]}]})
    assert "not found" in error, f"Unexpected error: {error[:300]}"
    assert dojos_named(missing_id) == 0

    escaping_id = spec_id("mdfile")
    error = reject_dojo_spec(admin_session, {"id": escaping_id, "modules": [{"id": "m", "resources": [
        {"type": "markdown", "name": "x", "file": "sub/../../../../etc/passwd"}]}]})
    assert "outside dojo directory" in error, f"Unexpected error: {error[:300]}"
    assert dojos_named(escaping_id) == 0


def test_challenges_key_appends_a_challenges_header(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("header"),
        "type": "public",
        "modules": [
            {"id": "a",
             "resources": [{"type": "markdown", "name": "R1", "content": "r1"}],
             "challenges": [{"id": "c1"}, {"id": "c2"}]},
            {"id": "b", "resources": [
                {"type": "markdown", "name": "B1", "content": "b1"},
                {"type": "challenge", "id": "bc", "name": "BC"},
                {"type": "markdown", "name": "B2", "content": "b2"},
            ]},
        ],
        "files": [challenge_file("a/c1/src"), challenge_file("a/c2/src"), challenge_file("b/bc/src")],
    })

    module_a = get_module(admin_session, dojo, "a")
    assert [item["name"] or item["content"] for item in module_a["unified_items"]] == \
        ["R1", "Challenges", "C1", "C2"], f"Unexpected order: {module_a['unified_items']}"
    assert [resource["type"] for resource in module_a["resources"]] == ["markdown", "header"]

    module_b = get_module(admin_session, dojo, "b")
    assert [item["name"] for item in module_b["unified_items"]] == ["B1", "BC", "B2"], \
        "inline challenge resources keep their spec position and add no header"
    assert all(resource["type"] != "header" for resource in module_b["resources"]), \
        "modules without a challenges key get no Challenges header"


def test_survey_probability_and_absence(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("survey"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [
            {"id": "p", "survey": {"prompt": "P", "data": "<div>p</div>", "probability": 0.25}},
            {"id": "q", "survey": {"prompt": "Q", "data": "<div>q</div>"}},
            {"id": "r"},
        ]}],
        "files": [challenge_file("m/p/src"), challenge_file("m/q/src"), challenge_file("m/r/src")],
    })

    def survey(challenge):
        return admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/m/{challenge}/surveys").json()

    assert survey("p")["probability"] == 0.25
    assert survey("p")["type"] == "user-specified"
    assert survey("q")["probability"] == 1.0, "probability defaults to 1.0"
    assert survey("r") == {"success": True, "type": "none"}


def test_survey_data_is_sanitized(admin_session):
    payload = ('<script>alert(1)</script><div onclick="alert(2)">'
               '<input type="radio" name="a" value="1"><label for="a">Hi</label>'
               '<img src=x onerror=alert(3)></div>')
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("sanitize"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [{"id": "c", "survey": {"prompt": "P", "data": payload}}]}],
        "files": [challenge_file("m/c/src")],
    })

    data = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/m/c/surveys").json()["data"]
    assert "<script>" not in data, f"script tags must be neutralized: {data}"
    assert "onclick" not in data, f"event handlers must be stripped: {data}"
    assert "<img" not in data, f"img tags must be neutralized: {data}"
    assert '<input type="radio" name="a" value="1">' in data, f"form controls must survive: {data}"
    assert '<label for="a">Hi</label>' in data, f"labels must survive: {data}"


def test_survey_src_path_validation(admin_session):
    escaping_id = spec_id("surveysrc")
    error = reject_dojo_spec(admin_session, {
        "id": escaping_id,
        "survey-sources": "surveys",
        "modules": [{"id": "m", "challenges": [{"id": "c", "survey": {"prompt": "P", "src": "../../../etc/passwd"}}]}],
        "files": [challenge_file("m/c/src")],
    })
    assert "references path outside of the dojo" in error, f"Unexpected error: {error[:300]}"
    assert dojos_named(escaping_id) == 0

    missing_id = spec_id("surveysrc")
    error = reject_dojo_spec(admin_session, {
        "id": missing_id,
        "survey-sources": "surveys",
        "modules": [{"id": "m", "challenges": [{"id": "c", "survey": {"prompt": "P", "src": "missing.html"}}]}],
        "files": [challenge_file("m/c/src")],
    })
    assert "Missing key" in error and "data" in error, \
        f"an unresolved src leaves the survey without data and fails validation: {error[:300]}"
    assert dojos_named(missing_id) == 0


def test_files_first_entry_wins(admin_session, spec_user):
    _, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("files"),
        "type": "public",
        "pages": ["notes"],
        "files": [text_file("notes.md", "FIRST_CONTENT"), text_file("notes.md", "SECOND_CONTENT")],
    })

    page = session.get(f"{DOJO_URL}/{dojo}/notes")
    assert page.status_code == 200
    assert "FIRST_CONTENT" in page.text, "the first files entry for a path wins"
    assert "SECOND_CONTENT" not in page.text, "an existing path is never overwritten"


def test_files_path_and_url_validation(admin_session):
    escaping_id = spec_id("filepath")
    error = reject_dojo_spec(admin_session, {"id": escaping_id, "files": [text_file("../escape", "x")]})
    assert "path" in error, f"Unexpected error: {error[:300]}"
    assert dojos_named(escaping_id) == 0

    download_id = spec_id("filesurl")
    reject_dojo_spec(admin_session, {"id": download_id, "files": [
        {"type": "download", "path": "a.bin", "url": "https://example.invalid/file.bin"}]})
    assert dojos_named(download_id) == 0, "a non-dropbox download url must not produce a dojo"


def test_files_outside_the_dojo_directory_are_not_written(admin_session):
    marker = "".join(random.choices(string.ascii_lowercase, k=12))

    post_spec(admin_session, {"id": spec_id("filepath"), "files": [text_file(f"../{marker}", "x")]})
    assert not ctfd_path_exists(f"/var/dojos/tmp/{marker}"), \
        "a files entry rejected by FILE_PATH_REGEX must not be written outside the dojo directory"

    post_spec(admin_session, {"id": spec_id("filepath"), "files": [
        text_file(f"a/../../../../../../tmp/{marker}", "x")]})
    assert not ctfd_path_exists(f"/tmp/{marker}"), \
        "a files entry must not be able to traverse out of the dojo directory"


def test_missing_challenge_path_is_rejected(admin_session):
    error = reject_dojo_spec(admin_session, {
        "id": spec_id("path"), "modules": [{"id": "m", "challenges": [{"id": "c"}]}]})
    assert "Missing challenge path: m/c" in error, f"Unexpected error: {error[:300]}"

    create_dojo_spec(admin_session, {
        "id": spec_id("path"), "modules": [{"id": "m", "challenges": [{"id": "c", "image": "hello-world"}]}]})
    create_dojo_spec(admin_session, {
        "id": spec_id("path"), "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src")]})


def test_pages_render_markdown(admin_session, spec_user):
    _, session = spec_user
    marker = f"PAGE_MARKER_{''.join(random.choices(string.ascii_uppercase, k=6))}"
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("pages"),
        "type": "public",
        "pages": ["about", "../../etc"],
        "files": [text_file("about.md", f"# {marker}\n")],
    })

    page = session.get(f"{DOJO_URL}/{dojo}/about")
    assert page.status_code == 200
    assert marker in page.text, "a listed page renders its markdown file"

    assert session.get(f"{DOJO_URL}/{dojo}/notlisted").status_code == 404, "unlisted page names 404"

    escaping = session.get(f"{DOJO_URL}/{dojo}/..%2f..%2fetc")
    assert escaping.status_code != 200, f"a listed page resolving outside the dojo must not be served: {escaping.status_code}"
    assert dojo_data(dojo)["pages"] == ["about", "../../etc"]


def test_pages_raw_file_requires_official(admin_session):
    marker = f"RAW_BYTES_{''.join(random.choices(string.ascii_uppercase, k=6))}"
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("rawpage"),
        "pages": ["blob"],
        "files": [text_file("blob", marker)],
    })

    response = admin_session.get(f"{DOJO_URL}/{dojo}/blob")
    assert response.status_code != 200 and marker not in response.text, \
        "an unofficial dojo must not serve raw (non-markdown) page files"

    make_dojo_official(dojo, admin_session)
    response = admin_session.get(f"{DOJO_URL}/{dojo}/blob")
    assert response.status_code == 200 and marker in response.text, \
        "an official dojo serves raw page files verbatim"


def test_pages_directory_serves_per_user_then_default_markdown(admin_session, spec_user):
    name, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("dirpage"),
        "type": "public",
        "pages": ["notes"],
        "files": [text_file("notes/default.md", "DEFAULT_NOTES")],
    })

    response = session.get(f"{DOJO_URL}/{dojo}/notes")
    assert response.status_code == 200 and "DEFAULT_NOTES" in response.text

    hex_id = dojo.split("~")[1]
    dojo_run("docker", "exec", "ctfd", "bash", "-c",
             f"echo USER_NOTES > /var/dojos/{hex_id}/notes/{get_user_id(name)}.md")

    response = session.get(f"{DOJO_URL}/{dojo}/notes")
    assert response.status_code == 200 and "USER_NOTES" in response.text, \
        "a per-user markdown file takes precedence for that user"
    assert "DEFAULT_NOTES" in admin_session.get(f"{DOJO_URL}/{dojo}/notes").text, \
        "other users still get default.md"


def test_custom_js_requires_permission(admin_session, spec_user):
    _, session = spec_user
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("customjs"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [challenge_file("m/c/src"), text_file("custom.js", "window.CUSTOM_JS_MARKER=1")],
    })

    assert dojo_data(dojo).get("custom_js") is None, "custom.js is ignored without the custom_js permission"
    page = session.get(f"{DOJO_URL}/{dojo}/m/")
    assert page.status_code == 200
    assert "CUSTOM_JS_MARKER" not in page.text, "no dojo-supplied script may be attached without the permission"


def test_course_yml_loading(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("course"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [{"id": "c"}]}],
        "files": [
            challenge_file("m/c/src"),
            text_file("course.yml", "student_id: ASURITE\n"),
            text_file("students.yml", "- tok1\n- tok2\n"),
            text_file("SYLLABUS.md", "SYLLABUS_MARKER"),
            text_file("grade.py", "GRADE_MARKER = 1\n"),
        ],
    })

    course = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/course").json()["course"]
    assert "SYLLABUS_MARKER" in course["syllabus"], "SYLLABUS.md populates course.syllabus"
    assert "GRADE_MARKER" in course["scripts"]["grade"], "grade.py populates course.scripts.grade"

    students = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/course/students").json()["students"]
    assert set(students) == {"tok1", "tok2"}, f"a bare students.yml list becomes a token dict: {students}"
    assert all(student["user_id"] is None for student in students.values())

    assert admin_session.get(f"{DOJO_URL}/dojo/{dojo}/course").status_code == 200


def test_course_discord_role_requires_official(admin_session):
    dojo_id = spec_id("discord")
    error = reject_dojo_spec(admin_session, {
        "id": dojo_id, "files": [text_file("course.yml", "discord_role: SomeRole\n")]})
    assert "Unofficial dojos cannot have a discord role" in error, f"Unexpected error: {error[:300]}"
    assert dojos_named(dojo_id) == 0


def test_course_endpoints_absent_without_course_yml(admin_session, example_dojo):
    assert admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/course").status_code == 404

    response = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{example_dojo}/course")
    assert response.status_code == 404, f"Expected a clean 404, got {response.status_code}"
    assert response.json()["success"] is False


def test_update_removes_and_restores_challenges(admin_session, spec_user):
    name, session = spec_user
    spec = {
        "id": spec_id("update"),
        "type": "public",
        "modules": [{"id": "m", "resources": [
            {"type": "challenge", "id": "a", "name": "A"},
            {"type": "challenge", "id": "b", "name": "B"},
        ]}],
        "files": [challenge_file("m/a/src"), challenge_file("m/b/src")],
    }
    dojo = create_dojo_spec(admin_session, spec)
    original_challenge_id = challenge_db_id(dojo, "m", "a")
    user_id = get_user_id(name)
    solve_challenge_offline(dojo, "m", "a", session=session, user=name)

    def solved_challenge_ids():
        return [solve["challenge_id"]
                for solve in session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/solves").json()["solves"]]

    assert solved_challenge_ids() == ["a"]

    without_a = json.loads(json.dumps(spec))
    without_a["modules"][0]["resources"] = [{"type": "challenge", "id": "b", "name": "B"}]
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update", json=without_a)
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"

    assert challenge_ids(dojo) == ["m/b"], "a challenge dropped from the spec loses its dojo_challenges row"
    assert solved_challenge_ids() == [], "a dropped challenge's solve disappears from the dojo solves API"
    submissions = int(db_sql(
        f"SELECT count(*) FROM submissions WHERE challenge_id = {original_challenge_id} "
        f"AND user_id = {user_id} AND type = 'correct'"))
    assert submissions == 1, "the underlying Challenges row and its solve must survive"

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update", json=spec)
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"
    assert challenge_ids(dojo) == ["m/a", "m/b"]

    restored_challenge_id = int(db_sql(
        "SELECT dc.challenge_id FROM dojo_challenges dc "
        "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = {dojo_db_id(dojo)} AND dm.id = 'm' AND dc.id = 'a'"))
    assert restored_challenge_id == original_challenge_id, "re-adding a challenge reattaches the original Challenges row"
    assert solved_challenge_ids() == ["a"], "the solve is visible again once the challenge is restored"


def test_update_rejects_duplicate_challenge_ids(admin_session):
    spec = {
        "id": spec_id("dupupdate"),
        "type": "public",
        "modules": [{"id": "m", "resources": [{"type": "challenge", "id": "a", "name": "A"}]}],
        "files": [challenge_file("m/a/src")],
    }
    dojo = create_dojo_spec(admin_session, spec)
    original_challenge_id = challenge_db_id(dojo, "m", "a")

    duplicated = json.loads(json.dumps(spec))
    duplicated["modules"][0]["resources"] = [
        {"type": "challenge", "id": "a", "name": "A"},
        {"type": "challenge", "id": "a", "name": "A2"},
    ]
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update", json=duplicated)
    assert response.status_code == 400, f"Expected 400, got {response.status_code}"

    assert admin_session.get(f"{DOJO_URL}/{dojo}/").status_code == 200, "the dojo survives a rejected update"
    assert challenge_ids(dojo) == ["m/a"]
    assert int(db_sql(
        "SELECT dc.challenge_id FROM dojo_challenges dc "
        "JOIN dojo_modules dm ON dm.dojo_id = dc.dojo_id AND dm.module_index = dc.module_index "
        f"WHERE dc.dojo_id = {dojo_db_id(dojo)} AND dm.id = 'm' AND dc.id = 'a'")) == original_challenge_id


def test_duplicate_ids_in_a_creation_spec_are_rejected_cleanly(admin_session):
    duplicate_challenge = spec_id("dupcreate")
    reject_dojo_spec(admin_session, {
        "id": duplicate_challenge,
        "modules": [{"id": "m", "challenges": [{"id": "a"}, {"id": "a"}]}],
        "files": [challenge_file("m/a/src")],
    })
    assert dojos_named(duplicate_challenge) == 0

    duplicate_module = spec_id("dupcreate")
    reject_dojo_spec(admin_session, {
        "id": duplicate_module,
        "modules": [{"id": "m", "challenges": [{"id": "a"}]}, {"id": "m", "challenges": [{"id": "b"}]}],
        "files": [challenge_file("m/a/src"), challenge_file("m/b/src")],
    })
    assert dojos_named(duplicate_module) == 0


def test_update_honours_the_challenges_key(admin_session):
    spec = {
        "id": spec_id("updatechals"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [{"id": "a"}, {"id": "b"}]}],
        "files": [challenge_file("m/a/src"), challenge_file("m/b/src")],
    }
    dojo = create_dojo_spec(admin_session, spec)
    assert challenge_ids(dojo) == ["m/a", "m/b"]

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update", json=spec)
    assert response.status_code == 200, f"Expected 200, got {response.status_code} - {response.text[:300]}"
    assert challenge_ids(dojo) == ["m/a", "m/b"], "re-applying the creation spec must not drop the challenges"


def test_challenge_import_without_id(admin_session, example_dojo):
    spec = {
        "id": spec_id("noid"),
        "type": "public",
        "modules": [{"id": "m", "challenges": [
            {"import": {"dojo": "example", "module": "hello", "challenge": "apple"}}]}],
    }
    dojo = create_dojo_spec(admin_session, spec)

    module = get_module(admin_session, dojo, "m")
    assert [(challenge["id"], challenge["name"]) for challenge in module["challenges"]] == [("apple", "Apple")], \
        "the create path fills the id and name in from the import"

    update_spec = json.loads(json.dumps(spec))
    update_spec["modules"][0].pop("challenges")
    update_spec["modules"][0]["resources"] = [
        {"type": "challenge", "import": {"dojo": "example", "module": "hello", "challenge": "apple"}}]
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update", json=update_spec)
    assert response.status_code == 200, \
        f"the update path fills the id in from the import too, got {response.status_code} - {response.text[:300]}"
    assert challenge_ids(dojo) == ["m/apple"], "the imported challenge must survive the update"


def test_spec_creation_requires_admin(admin_session, spec_user):
    _, session = spec_user
    for key in dojo_run("docker", "exec", "cache", "redis-cli", "--scan",
                        "--pattern", "flask_cache_rl:*:pwncollege_api.dojos_create_dojo").stdout.split():
        dojo_run("docker", "exec", "cache", "redis-cli", "DEL", key)

    dojo_id = spec_id("nonadmin")
    response = post_spec(session, {"id": dojo_id})
    assert response.status_code == 400, f"Expected 400, got {response.status_code} - {response.text[:200]}"
    assert "admin" in response.json()["error"], f"Unexpected error: {response.json()['error']}"
    assert dojos_named(dojo_id) == 0

    create_dojo_spec(admin_session, {"id": spec_id("admincreate")})
    create_dojo_spec(admin_session, {"id": spec_id("admincreate")})


def test_dojo_delete_cascades(admin_session):
    dojo = create_dojo_spec(admin_session, {
        "id": spec_id("delete"),
        "type": "public",
        "modules": [{"id": "m",
                     "resources": [{"type": "markdown", "name": "R", "content": "x"}],
                     "challenges": [{"id": "c", "visibility": {"stop": "2099-01-01T00:00:00Z"}}]}],
        "files": [challenge_file("m/c/src")],
    })
    dojo_id = dojo_db_id(dojo)
    tables = ["dojo_modules", "dojo_challenges", "dojo_resources", "dojo_challenge_visibilities"]

    before = [int(db_sql(f"SELECT count(*) FROM {table} WHERE dojo_id = {dojo_id}")) for table in tables]
    assert all(count > 0 for count in before), f"Expected rows in every table, got {dict(zip(tables, before))}"

    response = admin_session.post(f"{DOJO_URL}/dojo/{dojo}/delete/", json={"dojo": dojo})
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"

    after = [int(db_sql(f"SELECT count(*) FROM {table} WHERE dojo_id = {dojo_id}")) for table in tables]
    assert after == [0, 0, 0, 0], f"Deleting a dojo must cascade, got {dict(zip(tables, after))}"
    assert admin_session.get(f"{DOJO_URL}/{dojo}/").status_code == 404
