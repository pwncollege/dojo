import datetime
import json
import random
import string
import time

import pytest
import requests

from utils import (
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    challenge_db_id,
    challenge_flag,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    flask_exec,
    get_outer_container_for,
    get_user_id,
    login,
    make_dojo_official,
    remove_workspace_container,
    solve_challenge_offline,
    wait_for_background_worker,
    workspace_run,
)

API = f"{DOJO_URL}/pwncollege_api/v1"
SYLLABUS = "# Syllabus body"
PRIVATE_TOKEN = "private-course-token"
FUTURE_ASSESSMENT = {"id": "hello", "type": "checkpoint", "date": "2099-01-01T00:00:00-07:00"}

GRADE_PY_BODY = '''\
import datetime


def credit_for(solved_at, deadline, extra_late_date):
    if solved_at is None:
        return 0.0
    if solved_at <= deadline:
        return 1.0
    if extra_late_date and solved_at <= extra_late_date:
        return 0.5
    return 0.0


def grade(data):
    modules = {module["id"]: module for module in data["modules"]}
    solves = data["solves"]

    assignments = []
    total_credit = 0.0
    total_weight = 0.0

    for assessment in ASSESSMENTS:
        module = modules.get(assessment["id"], {})
        required = [c["id"] for c in module.get("challenges", []) if c.get("required")]
        deadline = datetime.datetime.fromisoformat(assessment["date"])
        extra_late_date = assessment.get("extra_late_date")
        if extra_late_date:
            extra_late_date = datetime.datetime.fromisoformat(extra_late_date)

        earned = 0.0
        for challenge_id in required:
            timestamps = [datetime.datetime.fromisoformat(solve["timestamp"])
                          for solve in solves
                          if solve["module_id"] == assessment["id"] and solve["challenge_id"] == challenge_id]
            earned += credit_for(min(timestamps) if timestamps else None, deadline, extra_late_date)
        credit = earned / len(required) if required else 0.0

        weight = assessment.get("weight", 1)
        assignments.append({"id": assessment["id"], "type": assessment["type"], "credit": credit, "weight": weight})
        total_credit += credit * weight
        if not assessment.get("extra_credit"):
            total_weight += weight

    overall = total_credit / total_weight if total_weight else 0.0
    letter = next(letter for threshold, letter in [(0.9, "A"), (0.8, "B"), (0.7, "C"), (0.6, "D"), (0.0, "F")]
                  if overall >= threshold)
    return {"student": (data["course"].get("student") or {}).get("token"),
            "assignments": assignments, "overall": overall, "letter": letter}
'''

REMOVE = object()


def grade_script(assessments):
    """A grade script shaped like a real one: it carries its own deadlines and reads the API payload."""
    return f"ASSESSMENTS = {assessments!r}\n\n\n{GRADE_PY_BODY}"


GRADE_PY = grade_script([{"id": "hello", "type": "checkpoint", "date": "2099-01-01T00:00:00-07:00"}])


def rand(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def new_user():
    name = rand(16)
    return name, login(name, name, register=True)


def set_course(dojo, course):
    db_sql(f"UPDATE dojos SET data = jsonb_set(data, '{{course}}', "
           f"$JSON${json.dumps(course)}$JSON$::jsonb) WHERE dojo_id = {dojo_db_id(dojo)};")


def dojo_user_rows(dojo, user_id):
    return db_sql(f"SELECT type, coalesce(token, '<null>') FROM dojo_users "
                  f"WHERE dojo_id = {dojo_db_id(dojo)} AND user_id = {user_id}").strip()


def clear_identity_ratelimit():
    """The identity endpoint allows 10 PATCHes per minute per IP, and the whole suite shares one IP."""
    scan = dojo_run("docker", "exec", "cache", "redis-cli", "--scan", "--pattern",
                    "flask_cache_rl:*:course.update_identity", check=False)
    keys = [key for key in scan.stdout.split() if key]
    if keys:
        dojo_run("docker", "exec", "cache", "redis-cli", "DEL", *keys, check=False)


def patch_identity(session, dojo, identity=REMOVE):
    body = {} if identity is REMOVE else {"identity": identity}
    return session.patch(f"{DOJO_URL}/dojo/{dojo}/course/identity", json=body)


def join(session, dojo):
    response = session.get(f"{DOJO_URL}/dojo/{dojo}/join/")
    assert response.status_code == 200, f"Expected to join {dojo}, got {response.status_code}"


def promote_dojo_admin(admin_session, dojo, user_id):
    response = admin_session.post(f"{API}/dojos/{dojo}/admins/promote", json={"user_id": user_id})
    assert response.status_code == 200 and response.json()["success"], response.text[:200]


def set_solve_date(dojo, module, challenge, user_id, date):
    updated = db_sql(f"UPDATE submissions SET date = '{date}' WHERE type = 'correct' AND user_id = {user_id} "
                     f"AND challenge_id = {challenge_db_id(dojo, module, challenge)} RETURNING id;")
    assert updated.strip(), f"no solve of {module}/{challenge} by user {user_id} to re-date"


class CourseFixture:
    def __init__(self, dojo):
        self.dojo = dojo
        self.a = f"tok-a-{rand()}"
        self.b = f"tok-b-{rand()}"
        self.ghost = f"ghost-{rand()}"

    def install(self, **overrides):
        course = {
            "student_id": "Student ID",
            "students": {self.a: {"name": "Alice"}, self.b: {"name": "Bob"}},
            "syllabus": SYLLABUS,
            "scripts": {"grade": GRADE_PY},
            "assessments": [dict(FUTURE_ASSESSMENT)],
        }
        course.update(overrides)
        for key in [key for key, value in course.items() if value is REMOVE]:
            del course[key]
        set_course(self.dojo, course)
        return course


@pytest.fixture(scope="module")
def course_dojo(admin_session, example_dojo):
    spec = (TEST_DOJOS_LOCATION / "course_test.yml").read_text().replace("dojotag", rand())
    reference_id = create_dojo_yml(spec, session=admin_session)
    make_dojo_official(reference_id, admin_session)
    return reference_id


@pytest.fixture(scope="module")
def private_course_dojo(admin_session, example_dojo):
    spec = (TEST_DOJOS_LOCATION / "course_test.yml").read_text().replace("dojotag", rand())
    reference_id = create_dojo_yml(spec, session=admin_session)
    set_course(reference_id, {"student_id": "Student ID",
                              "students": {PRIVATE_TOKEN: {"name": "Private"}},
                              "syllabus": SYLLABUS,
                              "scripts": {"grade": GRADE_PY}})
    return reference_id


@pytest.fixture
def course(course_dojo):
    fixture = CourseFixture(course_dojo)
    fixture.install()
    return fixture


@pytest.fixture
def identity_budget():
    clear_identity_ratelimit()


@pytest.fixture(scope="module")
def ingestion_results():
    """Ingest several course directories through the real dojo_from_dir path, without persisting them."""
    tag = rand()
    script = f'''
import json, pathlib, shutil
from CTFd.models import db
from CTFd.plugins.dojo_plugin.models import Dojos
from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_dir

root = pathlib.Path("/tmp/course-ingest-{tag}")
results = dict()
GRADE_PY = {GRADE_PY!r}
DOJO_YML = "id: course-ingest-{tag}\\n"

def ingest(name, files, official=False):
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for path, content in [("dojo.yml", DOJO_YML)] + files:
        (root / path).write_text(content)
    dojo = Dojos(id="course-ingest-{tag}", official=official)
    try:
        dojo_from_dir(root, dojo=dojo)
        results[name] = dict(ok=True, course=dojo.course)
    except Exception as e:
        results[name] = dict(ok=False, error=str(e))
    db.session.rollback()

COURSE_YML = (
    "student_id: Student ID\\n"
    "assessments:\\n"
    "  - id: hello\\n"
    "    type: checkpoint\\n"
    "    date: \\"2099-01-01T00:00:00-07:00\\"\\n"
)

ingest("files", [
    ("course.yml", COURSE_YML),
    ("students.yml", "- token-a\\n- token-b\\n"),
    ("SYLLABUS.md", "# Syllabus body\\n"),
    ("grade.py", GRADE_PY),
])
ingest("students_mapping", [
    ("course.yml", COURSE_YML),
    ("students.yml", "token-a:\\n  name: Alice\\n"),
])
ingest("students_precedence", [
    ("course.yml", COURSE_YML + "students:\\n  yml-token: {{}}\\n"),
    ("students.yml", "- file-token\\n"),
])
ingest("overrides", [
    ("course.yml", COURSE_YML + "syllabus: overridden\\nscripts:\\n  grade: inline-grade\\n"),
    ("SYLLABUS.md", "# Syllabus body\\n"),
    ("grade.py", GRADE_PY),
])
ingest("no_scripts", [("course.yml", COURSE_YML)])
ingest("discord_unofficial", [("course.yml", COURSE_YML + "discord_role: Test Role\\n")])
ingest("discord_official", [("course.yml", COURSE_YML + "discord_role: Test Role\\n")], official=True)

shutil.rmtree(root, ignore_errors=True)
print("RESULT " + json.dumps(results))
'''
    output = flask_exec(script)
    line = next((line for line in output.splitlines() if line.startswith("RESULT ")), None)
    assert line, f"course ingestion probe produced no result: {output[-2000:]}"
    return json.loads(line[len("RESULT "):])


def test_course_yml_ingestion(ingestion_results):
    result = ingestion_results["files"]
    assert result["ok"], result
    course = result["course"]
    assert course["student_id"] == "Student ID", course
    assert course["assessments"] == [{"id": "hello", "type": "checkpoint", "date": "2099-01-01T00:00:00-07:00"}], \
        f"course.yml assessments must be stored verbatim: {course.get('assessments')}"
    assert course["students"] == {"token-a": {}, "token-b": {}}, \
        f"a bare students.yml list becomes a roster dict: {course.get('students')}"
    assert course["syllabus"] == "# Syllabus body\n", f"SYLLABUS.md becomes course.syllabus: {course.get('syllabus')!r}"
    assert course["scripts"]["grade"] == GRADE_PY, "grade.py becomes course.scripts.grade verbatim"

    mapping = ingestion_results["students_mapping"]
    assert mapping["ok"], mapping
    assert mapping["course"]["students"] == {"token-a": {"name": "Alice"}}, \
        f"a students.yml mapping is stored as-is: {mapping['course'].get('students')}"

    precedence = ingestion_results["students_precedence"]
    assert precedence["ok"], precedence
    assert precedence["course"]["students"] == {"yml-token": {}}, \
        f"a students key in course.yml wins over students.yml: {precedence['course'].get('students')}"

    overrides = ingestion_results["overrides"]
    assert overrides["ok"], overrides
    assert overrides["course"]["syllabus"] == "overridden", "course.yml syllabus wins over SYLLABUS.md"

    no_scripts = ingestion_results["no_scripts"]
    assert no_scripts["ok"], no_scripts
    assert no_scripts["course"]["scripts"] == {}, \
        f"course.scripts always exists after ingestion: {no_scripts['course'].get('scripts')}"


def test_course_yml_grade_script_wins_over_grade_py(ingestion_results):
    overrides = ingestion_results["overrides"]
    assert overrides["ok"], overrides
    assert overrides["course"]["scripts"]["grade"] == "inline-grade", \
        "course.yml scripts.grade must win over grade.py, like syllabus and students do"


def test_ingest_discord_role_requires_official_dojo(ingestion_results):
    unofficial = ingestion_results["discord_unofficial"]
    assert not unofficial["ok"], f"an unofficial dojo must not accept a discord role: {unofficial}"
    assert "Unofficial dojos cannot have a discord role" in unofficial["error"], unofficial["error"]

    official = ingestion_results["discord_official"]
    assert official["ok"], official
    assert official["course"]["discord_role"] == "Test Role", official["course"]


def test_identity_links_and_relinks_roster_token(course, random_user, identity_budget, admin_session):
    name, session = random_user
    user_id = get_user_id(name)

    response = patch_identity(session, course.dojo, f"  {course.a}\n")
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert body["success"] is True and "warning" not in body, \
        f"a whitespace-padded roster token must link cleanly: {body}"
    assert dojo_user_rows(course.dojo, user_id) == f"student|{course.a}", \
        f"the stored token must be stripped: {dojo_user_rows(course.dojo, user_id)!r}"

    response = patch_identity(session, course.dojo, course.b)
    assert response.status_code == 200 and response.json() == {"success": True}, response.text[:200]
    assert dojo_user_rows(course.dojo, user_id) == f"student|{course.b}", \
        f"re-identifying replaces the token in place: {dojo_user_rows(course.dojo, user_id)!r}"

    students = admin_session.get(f"{API}/dojos/{course.dojo}/course/students").json()["students"]
    assert students[course.b]["user_id"] == user_id, students[course.b]
    assert students[course.a]["user_id"] is None and students[course.a]["token"] is None, \
        f"the abandoned token is reported unlinked: {students[course.a]}"


def test_identity_off_roster_and_empty_values_warn(course, random_user, identity_budget, admin_session):
    name, session = random_user
    user_id = get_user_id(name)

    response = patch_identity(session, course.dojo, course.ghost)
    assert response.status_code == 200, response.text[:200]
    body = response.json()
    assert body["success"] is True, body
    assert body["warning"] == "Your Student ID is not on the official student roster", body
    assert dojo_user_rows(course.dojo, user_id) == f"student|{course.ghost}", dojo_user_rows(course.dojo, user_id)

    for identity in ["", REMOVE]:
        response = patch_identity(session, course.dojo, identity)
        assert response.status_code == 200, response.text[:200]
        body = response.json()
        assert body["success"] is True and "warning" in body, \
            f"an empty identity is a warning, not an error: {body}"
        assert dojo_user_rows(course.dojo, user_id) == "student|", \
            f"an empty identity stores an empty token: {dojo_user_rows(course.dojo, user_id)!r}"

    course.install(student_id=REMOVE)
    response = patch_identity(session, course.dojo, course.ghost)
    assert response.status_code == 200, response.text[:200]
    assert response.json()["warning"] == "Your Identity is not on the official student roster", response.json()


def test_identity_converts_member_to_student(course, random_user, identity_budget):
    name, session = random_user
    user_id = get_user_id(name)

    join(session, course.dojo)
    assert dojo_user_rows(course.dojo, user_id) == "member|<null>", dojo_user_rows(course.dojo, user_id)

    response = patch_identity(session, course.dojo, course.a)
    assert response.status_code == 200 and response.json() == {"success": True}, response.text[:200]
    assert dojo_user_rows(course.dojo, user_id) == f"student|{course.a}", \
        f"a member becomes exactly one student row: {dojo_user_rows(course.dojo, user_id)!r}"


def test_identity_rejects_dojo_admins(course, admin_session, identity_budget):
    admin_id = get_user_id("admin")
    response = patch_identity(admin_session, course.dojo, course.a)
    assert response.status_code == 200, response.text[:200]
    assert response.json() == {"success": False, "error": "Cannot identify admin"}, response.json()
    assert dojo_user_rows(course.dojo, admin_id) == "admin|<null>", dojo_user_rows(course.dojo, admin_id)

    name, session = new_user()
    user_id = get_user_id(name)
    join(session, course.dojo)
    promote_dojo_admin(admin_session, course.dojo, user_id)

    response = patch_identity(session, course.dojo, course.a)
    assert response.status_code == 200, response.text[:200]
    assert response.json() == {"success": False, "error": "Cannot identify admin"}, response.json()
    assert dojo_user_rows(course.dojo, user_id) == "admin|<null>", dojo_user_rows(course.dojo, user_id)


def test_identity_requires_a_course_and_authentication(course, example_dojo, random_user, identity_budget):
    name, session = random_user
    user_id = get_user_id(name)

    response = patch_identity(session, example_dojo, "x")
    assert response.status_code == 404, f"a dojo without a course has no identity endpoint: {response.status_code}"
    assert dojo_user_rows(example_dojo, user_id) == "", "no dojo_users row may be created for a non-course dojo"

    anonymous = requests.Session()
    response = patch_identity(anonymous, course.dojo, course.a)
    assert response.status_code == 403, f"expected 403 for an unauthenticated json PATCH, got {response.status_code}"
    assert db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id = {dojo_db_id(course.dojo)} "
                  f"AND token = '{course.a}'").strip() == "0", "an anonymous PATCH must not link anyone"


def test_identity_private_dojo_requires_membership(private_course_dojo, random_user, identity_budget):
    name, session = random_user

    assert patch_identity(session, private_course_dojo, PRIVATE_TOKEN).status_code == 404, \
        "a private course dojo must not be identifiable by a non-member"
    assert session.get(f"{DOJO_URL}/dojo/{private_course_dojo}/course").status_code == 404
    assert session.get(f"{API}/dojos/{private_course_dojo}/course").status_code == 404

    join(session, private_course_dojo)
    response = patch_identity(session, private_course_dojo, PRIVATE_TOKEN)
    assert response.status_code == 200 and response.json() == {"success": True}, response.text[:200]


def test_identity_is_scoped_per_dojo(course, private_course_dojo, random_user, identity_budget):
    name, session = random_user
    user_id = get_user_id(name)
    join(session, private_course_dojo)

    assert patch_identity(session, course.dojo, course.a).json()["success"] is True

    first = session.get(f"{API}/dojos/{course.dojo}/course").json()["course"]
    assert first["student"] == {"name": "Alice", "token": course.a, "user_id": user_id}, first["student"]
    second = session.get(f"{API}/dojos/{private_course_dojo}/course").json()["course"]
    assert "student" not in second, f"an identity in one course must not leak into another: {second}"

    assert patch_identity(session, private_course_dojo, PRIVATE_TOKEN).json()["success"] is True
    again = session.get(f"{API}/dojos/{course.dojo}/course").json()["course"]
    assert again["student"]["token"] == course.a, again["student"]


def test_identity_discord_warnings(course, random_user, identity_budget):
    name, session = random_user
    user_id = get_user_id(name)
    course.install(discord_role="Test Role")

    response = patch_identity(session, course.dojo, course.a)
    assert response.status_code == 200, response.text[:200]
    assert response.json() == {"success": True, "warning": "Your Discord account is not linked"}, response.json()
    assert dojo_user_rows(course.dojo, user_id) == f"student|{course.a}", dojo_user_rows(course.dojo, user_id)

    discord_id = random.randrange(10**17, 10**18)
    db_sql(f"INSERT INTO discord_users (user_id, discord_id) VALUES ({user_id}, {discord_id});")
    try:
        response = patch_identity(session, course.dojo, course.a)
        assert response.status_code == 200, response.text[:200]
        assert response.json() == {
            "success": True,
            "warning": "Your Discord account has not joined the official Discord server",
        }, response.json()
    finally:
        db_sql(f"DELETE FROM discord_users WHERE user_id = {user_id};")


def test_course_page_identity_and_setup_status(course, random_user, identity_budget):
    name, session = random_user

    response = session.get(f"{DOJO_URL}/dojo/{course.dojo}/course")
    assert response.status_code == 200, response.status_code
    assert "Student ID" in response.text, "the course page shows the configured identity label"
    assert course.a not in response.text and course.b not in response.text, \
        "the roster must not be exposed to a student who has not linked"
    assert "Setup incomplete." in response.text, "a user with no identity has an incomplete setup"

    assert patch_identity(session, course.dojo, course.ghost).json()["success"] is True
    response = session.get(f"{DOJO_URL}/dojo/{course.dojo}/course")
    assert course.ghost in response.text, "the course page shows the student their own identity"
    assert "Setup incomplete." in response.text, "an off-roster identity does not complete setup"

    assert patch_identity(session, course.dojo, course.a).json()["success"] is True
    response = session.get(f"{DOJO_URL}/dojo/{course.dojo}/course")
    assert course.a in response.text, "the course page shows the linked roster token"
    assert "Setup complete!" in response.text, "an on-roster identity completes setup"


def test_course_page_admin_view_of_another_user(course, admin_session, identity_budget):
    student_name, student_session = new_user()
    student_id = get_user_id(student_name)
    assert patch_identity(student_session, course.dojo, course.a).json()["success"] is True

    other_name, other_session = new_user()
    response = other_session.get(f"{DOJO_URL}/dojo/{course.dojo}/course?user={student_id}")
    assert response.status_code == 403, f"only dojo admins may view another user's course page: {response.status_code}"
    assert course.a not in response.text, "a rejected request must not leak the student's identity"

    response = admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/course?user={student_id}")
    assert response.status_code == 200, response.status_code
    assert course.a in response.text, "a dojo admin sees the target student's identity"
    assert "Student ID" in response.text, "the course's identity label is shown alongside it"

    join(other_session, course.dojo)
    promote_dojo_admin(admin_session, course.dojo, get_user_id(other_name))
    response = other_session.get(f"{DOJO_URL}/dojo/{course.dojo}/course?user={student_id}")
    assert response.status_code == 200, f"a promoted dojo admin may view course pages: {response.status_code}"
    assert course.a in response.text, response.status_code

    assert admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/course?user=99999999").status_code == 404
    assert admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/course?user=notanumber").status_code == 404


def test_course_page_anonymous_and_resource_deeplinks(course, random_user):
    dojo_id = dojo_db_id(course.dojo)
    before = db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id = {dojo_id};").strip()

    anonymous = requests.Session()
    response = anonymous.get(f"{DOJO_URL}/dojo/{course.dojo}/course")
    assert response.status_code == 200, response.status_code
    assert "Syllabus body" in response.text, "the syllabus of an official course is publicly readable"
    assert course.a not in response.text and course.b not in response.text, "the roster is never rendered"
    assert db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id = {dojo_id};").strip() == before, \
        "viewing the course page must not create a dojo_users row"

    _, session = random_user
    for resource in ["", "/syllabus", "/identity", "/grades", "/setup"]:
        response = session.get(f"{DOJO_URL}/dojo/{course.dojo}/course{resource}")
        assert response.status_code == 200, f"course{resource} should serve the course page, got {response.status_code}"
        assert "Syllabus body" in response.text, f"course{resource} serves the same course page"


def test_course_endpoints_absent_without_a_course(example_dojo, admin_session, random_user):
    name, session = random_user
    user_id = get_user_id(name)

    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/course").status_code == 404
    assert session.get(f"{DOJO_URL}/dojo/{example_dojo}/course/identity").status_code == 404
    assert admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/grades").status_code == 404
    assert admin_session.get(f"{DOJO_URL}/dojo/{example_dojo}/admin/users/{user_id}").status_code == 404, \
        "a dojo with no course has no per-user course page, even for admins"

    for endpoint in ["course", "course/students", "course/solves"]:
        response = admin_session.get(f"{API}/dojos/{example_dojo}/{endpoint}")
        assert response.status_code == 404, f"{endpoint} on a non-course dojo should 404, got {response.status_code}"
        assert response.json()["success"] is False, response.text[:200]


def test_admin_grades_page_authorization(course, admin_session):
    name, session = new_user()
    assert session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/grades").status_code == 403

    anonymous = requests.Session()
    response = anonymous.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/grades", allow_redirects=False)
    assert response.status_code == 302 and "/login" in response.headers["Location"], \
        f"anonymous visitors are sent to login: {response.status_code} {response.headers.get('Location')}"

    assert admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/grades").status_code == 200

    join(session, course.dojo)
    promote_dojo_admin(admin_session, course.dojo, get_user_id(name))
    assert session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/grades").status_code == 200


def test_admin_grades_page_requires_a_grade_script(course, admin_session):
    course.install(scripts={})
    assert admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/grades").status_code == 404, \
        "a course with no grade script has no grades page"

    course.install(scripts=REMOVE)
    assert admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/grades").status_code == 404, \
        "a course dict without a scripts key must 404 rather than error"


def test_admin_user_info_page(course, admin_session, identity_budget):
    student_name, student_session = new_user()
    student_id = get_user_id(student_name)
    assert patch_identity(student_session, course.dojo, course.a).json()["success"] is True

    other_name, other_session = new_user()
    other_id = get_user_id(other_name)

    response = other_session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/users/{student_id}")
    assert response.status_code == 403, f"non-admins may not view a student's info page: {response.status_code}"
    assert course.a not in response.text, "the rejected page must not leak the identity"

    response = admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/users/{student_id}")
    assert response.status_code == 200, response.status_code
    assert student_name in response.text and course.a in response.text and "Student ID" in response.text, \
        "the admin user page shows the student, their identity label and their token"

    response = admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/users/{other_id}")
    assert response.status_code == 200, "a user who never linked an identity still renders"
    assert other_name in response.text and course.a not in response.text, response.status_code

    assert admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/users/99999999").status_code == 404
    assert admin_session.get(f"{DOJO_URL}/dojo/{course.dojo}/admin/users/abc").status_code == 404


def test_course_api_payload_and_student_block(course, random_user, identity_budget):
    name, session = random_user
    user_id = get_user_id(name)

    response = session.get(f"{API}/dojos/{course.dojo}/course")
    assert response.status_code == 200, response.status_code
    body = response.json()
    assert body["success"] is True, body
    assert body["course"]["syllabus"] == SYLLABUS, body["course"]["syllabus"]
    assert body["course"]["scripts"]["grade"] == GRADE_PY, "the grade script is served verbatim"
    assert "students" not in body["course"] and "student" not in body["course"], \
        f"the roster is never exposed through the course API: {body['course'].keys()}"
    assert course.a not in response.text and "Alice" not in response.text, "no roster data may leak"

    assert patch_identity(session, course.dojo, course.a).json()["success"] is True
    body = session.get(f"{API}/dojos/{course.dojo}/course").json()
    assert body["course"]["student"] == {"name": "Alice", "token": course.a, "user_id": user_id}, \
        body["course"]["student"]

    ghost_name, ghost_session = new_user()
    ghost_id = get_user_id(ghost_name)
    assert patch_identity(ghost_session, course.dojo, course.ghost).json()["success"] is True
    body = ghost_session.get(f"{API}/dojos/{course.dojo}/course").json()
    assert body["course"]["student"] == {"token": course.ghost, "user_id": ghost_id}, \
        f"an off-roster student gets no roster fields: {body['course']['student']}"

    course.install(students={course.a: {"name": "Alice"}, course.ghost: {"name": "Ghost"}})
    body = ghost_session.get(f"{API}/dojos/{course.dojo}/course").json()
    assert body["course"]["student"]["name"] == "Ghost", \
        f"roster changes are reflected without re-linking: {body['course']['student']}"


def test_course_api_visibility(course, private_course_dojo, random_user):
    name, session = random_user
    anonymous = requests.Session()

    assert anonymous.get(f"{API}/dojos/{private_course_dojo}/course").status_code == 404
    assert session.get(f"{API}/dojos/{private_course_dojo}/course").status_code == 404

    join(session, private_course_dojo)
    response = session.get(f"{API}/dojos/{private_course_dojo}/course")
    assert response.status_code == 200 and response.json()["course"]["syllabus"] == SYLLABUS, response.text[:200]

    response = anonymous.get(f"{API}/dojos/{course.dojo}/course")
    assert response.status_code == 200, response.status_code
    body = response.json()["course"]
    assert body["syllabus"] == SYLLABUS and body["scripts"]["grade"] == GRADE_PY, body.keys()
    assert "student" not in body, f"an anonymous request has no student block: {body}"


def test_students_api_roster_view(course, admin_session, identity_budget):
    linked_name, linked_session = new_user()
    linked_id = get_user_id(linked_name)
    assert patch_identity(linked_session, course.dojo, course.a).json()["success"] is True

    ghost_name, ghost_session = new_user()
    ghost_id = get_user_id(ghost_name)
    assert patch_identity(ghost_session, course.dojo, course.ghost).json()["success"] is True

    duplicate_name, duplicate_session = new_user()
    duplicate_id = get_user_id(duplicate_name)
    assert patch_identity(duplicate_session, course.dojo, course.a).json()["success"] is True

    response = admin_session.get(f"{API}/dojos/{course.dojo}/course/students")
    assert response.status_code == 200, response.status_code
    students = response.json()["students"]
    assert set(students) == {course.a, course.b}, f"the listing is roster-driven: {set(students)}"
    assert students[course.b] == {"name": "Bob", "token": None, "user_id": None}, \
        f"an unclaimed roster entry is reported unlinked: {students[course.b]}"
    assert students[course.a] == {"name": "Alice", "token": course.a, "user_id": max(linked_id, duplicate_id)}, \
        f"a duplicate token claim resolves to the highest user id: {students[course.a]}"
    assert course.ghost not in response.text and str(ghost_id) not in json.dumps(students), \
        "off-roster students are not listed"
    assert db_sql(f"SELECT count(*) FROM dojo_users WHERE dojo_id = {dojo_db_id(course.dojo)} "
                  f"AND token = '{course.a}';").strip() == "2", "duplicate claims are stored, not rejected"

    course.install(students=REMOVE)
    response = admin_session.get(f"{API}/dojos/{course.dojo}/course/students")
    assert response.status_code == 200 and response.json()["students"] == {}, \
        f"a course with no roster lists no students: {response.text[:200]}"


def test_students_api_authorization(course, private_course_dojo, admin_session, random_user, identity_budget):
    name, session = random_user
    url = f"{API}/dojos/{course.dojo}/course/students"

    response = session.get(url)
    assert response.status_code == 403, response.status_code
    assert course.a not in response.text and "Alice" not in response.text, "no roster data in a rejected response"

    assert patch_identity(session, course.dojo, course.a).json()["success"] is True
    assert session.get(url).status_code == 403, "being a student does not grant roster access"
    assert requests.get(url).status_code == 403, "anonymous roster access is rejected"
    assert admin_session.get(url).status_code == 200

    assert session.get(f"{API}/dojos/{private_course_dojo}/course/students").status_code == 404, \
        "a private dojo's existence is not disclosed to non-members"


@pytest.fixture
def solving_student(course, identity_budget):
    name, session = new_user()
    user_id = get_user_id(name)
    assert patch_identity(session, course.dojo, course.a).json()["success"] is True
    for challenge in ["apple", "banana", "optional-c"]:
        solve_challenge_offline(course.dojo, "hello", challenge, session=session, user=name)
    return name, session, user_id


def test_course_solves_api_shape_order_and_filters(course, solving_student, admin_session):
    name, session, user_id = solving_student

    response = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves")
    assert response.status_code == 200, response.status_code
    body = response.json()
    assert body["success"] is True, body
    solves = [solve for solve in body["solves"] if solve["user_id"] == user_id]
    assert [solve["challenge_id"] for solve in solves] == ["apple", "banana"], \
        f"only required challenges are reported, in solve order: {solves}"
    for solve in solves:
        assert solve["student_token"] == course.a and solve["module_id"] == "hello", solve
        assert set(solve) == {"timestamp", "student_token", "user_id", "module_id", "challenge_id"}, solve
        parsed = datetime.datetime.fromisoformat(solve["timestamp"])
        assert parsed.tzinfo is not None and parsed.utcoffset() == datetime.timedelta(0), \
            f"timestamps are ISO-8601 UTC: {solve['timestamp']}"
    timestamps = [solve["timestamp"] for solve in solves]
    assert timestamps == sorted(timestamps), f"solves are ordered by date ascending: {timestamps}"

    response = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves", params={"after": timestamps[0]})
    later = [solve for solve in response.json()["solves"] if solve["user_id"] == user_id]
    assert [solve["challenge_id"] for solve in later] == ["banana"], \
        f"?after is a strict lower bound: {later}"

    response = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves", params={"after": timestamps[-1]})
    assert [solve for solve in response.json()["solves"] if solve["user_id"] == user_id] == [], \
        "nothing is returned after the last solve"

    naive = timestamps[0].replace("+00:00", "")
    response = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves", params={"after": naive})
    assert response.status_code == 200 and response.json()["success"] is True, \
        f"a naive ISO timestamp is accepted: {response.text[:200]}"

    response = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves", params={"after": "not-a-date"})
    assert response.status_code == 400, response.status_code
    assert response.json() == {"success": False, "error": "Invalid after date format"}, response.json()

    response = session.get(f"{API}/dojos/{course.dojo}/solves")
    assert [solve["challenge_id"] for solve in response.json()["solves"]] == ["apple", "banana"], \
        "the per-user solves API also reports required challenges only"


def test_course_solves_api_roster_filtering(course, solving_student, admin_session, identity_budget):
    linked_name, linked_session, linked_id = solving_student

    ghost_name, ghost_session = new_user()
    ghost_id = get_user_id(ghost_name)
    assert patch_identity(ghost_session, course.dojo, course.ghost).json()["success"] is True
    solve_challenge_offline(course.dojo, "hello", "apple", session=ghost_session, user=ghost_name)

    plain_name, plain_session = new_user()
    plain_id = get_user_id(plain_name)
    solve_challenge_offline(course.dojo, "hello", "apple", session=plain_session, user=plain_name)

    solves = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves").json()["solves"]
    reported = {solve["user_id"] for solve in solves}
    assert linked_id in reported, "a roster student's solves are reported"
    assert ghost_id not in reported and plain_id not in reported, \
        f"only roster students are reported when a roster exists: {reported}"
    assert all(solve["student_token"] is not None for solve in solves), solves

    course.install(students=REMOVE)
    solves = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves").json()["solves"]
    by_user = {solve["user_id"]: solve for solve in solves}
    assert {linked_id, ghost_id} <= set(by_user), \
        f"with no roster, off-roster students are reported too: {set(by_user)}"
    assert by_user[ghost_id]["student_token"] == course.ghost, by_user[ghost_id]


def test_course_solves_api_without_a_roster_includes_everyone(course, admin_session):
    plain_name, plain_session = new_user()
    plain_id = get_user_id(plain_name)
    solve_challenge_offline(course.dojo, "hello", "apple", session=plain_session, user=plain_name)

    course.install(students=REMOVE)
    solves = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves").json()["solves"]
    by_user = {solve["user_id"]: solve for solve in solves}
    assert plain_id in by_user, \
        f"a course with no roster exports every solve, not just students': {set(by_user)}"
    assert by_user[plain_id]["student_token"] is None, by_user[plain_id]


def test_course_solves_api_authorization(course, private_course_dojo, solving_student, admin_session):
    name, session, user_id = solving_student
    url = f"{API}/dojos/{course.dojo}/course/solves"

    response = session.get(url)
    assert response.status_code == 403, "a student may not read the course-wide solve export"
    assert course.a not in response.text, "no solve data leaks in the rejection"

    other_name, other_session = new_user()
    assert other_session.get(url).status_code == 403
    assert requests.get(url).status_code == 403
    assert admin_session.get(url).status_code == 200

    assert other_session.get(f"{API}/dojos/{private_course_dojo}/course/solves").status_code == 404


def test_user_solves_api_self_and_other(course, solving_student, random_user):
    name, session, user_id = solving_student
    other_name, other_session = random_user

    response = session.get(f"{API}/dojos/{course.dojo}/solves")
    assert response.status_code == 200, response.status_code
    solves = response.json()["solves"]
    assert [solve["challenge_id"] for solve in solves] == ["apple", "banana"], solves
    assert all(set(solve) == {"timestamp", "module_id", "challenge_id"} for solve in solves), solves

    response = other_session.get(f"{API}/dojos/{course.dojo}/solves", params={"username": name})
    assert response.status_code == 200 and response.json()["solves"] == solves, \
        "another user's solves are readable by username"

    response = other_session.get(f"{API}/dojos/{course.dojo}/solves", params={"username": "definitely-not-a-user"})
    assert response.status_code == 400 and "User not found" in response.text, response.text[:200]

    db_sql(f"UPDATE users SET hidden = true WHERE id = {user_id};")
    try:
        response = other_session.get(f"{API}/dojos/{course.dojo}/solves", params={"username": name})
        assert response.status_code == 400 and "User not found" in response.text, \
            f"hidden users are not exposed: {response.status_code} {response.text[:200]}"
    finally:
        db_sql(f"UPDATE users SET hidden = false WHERE id = {user_id};")

    assert requests.get(f"{API}/dojos/{course.dojo}/solves").status_code == 400, \
        "an anonymous request with no username has no user"

    timestamps = [solve["timestamp"] for solve in solves]
    assert timestamps == sorted(timestamps), timestamps
    response = session.get(f"{API}/dojos/{course.dojo}/solves", params={"after": timestamps[0]})
    assert [solve["challenge_id"] for solve in response.json()["solves"]] == ["banana"], response.json()
    response = session.get(f"{API}/dojos/{course.dojo}/solves", params={"after": "garbage"})
    assert response.status_code == 400, response.status_code
    assert response.json() == {"success": False, "error": "Invalid after date format"}, response.json()


def test_grades_pipeline_groups_solves_per_student(course, solving_student, admin_session, identity_budget):
    linked_name, linked_session, linked_id = solving_student

    idle_name, idle_session = new_user()
    idle_id = get_user_id(idle_name)
    assert patch_identity(idle_session, course.dojo, course.b).json()["success"] is True

    students = admin_session.get(f"{API}/dojos/{course.dojo}/course/students").json()["students"]
    solves = admin_session.get(f"{API}/dojos/{course.dojo}/course/solves").json()["solves"]

    groups = {token: [solve for solve in solves if solve["student_token"] == token] for token in students}
    assert len(groups[course.a]) == 2 and all(solve["user_id"] == linked_id for solve in groups[course.a]), \
        f"every solve of a roster student is attributable to their token: {groups[course.a]}"
    assert groups[course.b] == [], "a roster student with no solves still gets an (empty) group"
    assert sum(len(group) for group in groups.values()) == len(solves), \
        "no solve in the export is unattributable to a roster token"


def test_grade_script_over_api_payload(course, solving_student):
    name, session, user_id = solving_student
    set_solve_date(course.dojo, "hello", "apple", user_id, "2019-01-01 00:00:00")
    set_solve_date(course.dojo, "hello", "banana", user_id, "2019-01-02 00:00:00")

    modules = session.get(f"{API}/dojos/{course.dojo}/modules").json()["modules"]

    def run(assessments, grading_session=None):
        grading_session = grading_session or session
        course.install(scripts={"grade": grade_script(assessments)})
        course_payload = grading_session.get(f"{API}/dojos/{course.dojo}/course").json()["course"]
        solves = grading_session.get(f"{API}/dojos/{course.dojo}/solves").json()["solves"]
        namespace = {}
        exec(course_payload["scripts"]["grade"], namespace)
        return solves, namespace["grade"](dict(course=course_payload, modules=modules, solves=solves))

    on_time = {"id": "hello", "type": "checkpoint", "date": "2020-01-01T00:00:00+00:00",
               "extra_late_date": "2030-01-01T00:00:00+00:00"}

    solves, result = run([dict(on_time)])
    assert result["student"] == course.a, f"the grade script sees the student's identity: {result}"
    assert result["assignments"][0]["credit"] == 1.0 and result["overall"] == 1.0, result
    assert result["letter"] == "A", result

    set_solve_date(course.dojo, "hello", "banana", user_id, "2025-01-01 00:00:00")
    _, result = run([dict(on_time)])
    assert result["assignments"][0]["credit"] == 0.75, f"a late solve inside the extension is half credit: {result}"
    assert result["letter"] == "C", result

    empty_name, empty_session = new_user()
    solves, result = run([dict(on_time)], grading_session=empty_session)
    assert solves == [], "a student with no solves gets an empty solve list"
    assert result["student"] is None and result["overall"] == 0.0 and result["letter"] == "F", result

    set_solve_date(course.dojo, "hello", "banana", user_id, "2019-01-02 00:00:00")
    _, result = run([dict(on_time), dict(on_time, type="bonus", extra_credit=True)])
    assert result["overall"] == 2.0, f"extra credit adds credit without adding weight: {result}"

    _, result = run([dict(on_time, weight=1),
                     dict(on_time, type="exam", weight=3, date="1990-01-01T00:00:00+00:00",
                          extra_late_date=None)])
    credits = [assignment["credit"] for assignment in result["assignments"]]
    assert credits == [1.0, 0.0], credits
    assert result["overall"] == (1 * credits[0] + 3 * credits[1]) / 4 == 0.25, \
        f"assessment weights are honored: {result}"


def test_module_page_assessments_are_for_students_and_admins(course, admin_session, random_user, identity_budget):
    name, session = random_user
    course.install(assessments=[
        {"id": "hello", "type": "checkpoint", "date": "2099-01-01T00:00:00-07:00"},
        {"id": "hello", "type": "exam", "date": "2000-01-01T00:00:00-07:00"},
        {"id": "elsewhere", "type": "quiz", "date": "2098-01-01T00:00:00-07:00"},
    ])
    url = f"{DOJO_URL}/{course.dojo}/hello/"

    response = session.get(url)
    assert response.status_code == 200, response.status_code
    assert "2099-01-01" not in response.text, "deadlines are not shown to users who are not students"

    assert patch_identity(session, course.dojo, course.a).json()["success"] is True
    response = session.get(url)
    assert "2099-01-01" in response.text and "Checkpoint" in response.text, \
        "an upcoming deadline is shown to a linked student"
    assert "2000-01-01" not in response.text, "past assessments are not shown"
    assert "2098-01-01" not in response.text, "another module's assessments are not shown"

    response = admin_session.get(url)
    assert "2099-01-01" in response.text, "dojo admins see upcoming deadlines"
    assert "2000-01-01" not in response.text and "2098-01-01" not in response.text, response.status_code


def test_course_dojo_is_hidden_from_public_profiles(course, example_dojo, identity_budget):
    name, session = new_user()
    assert patch_identity(session, course.dojo, course.a).json()["success"] is True
    solve_challenge_offline(course.dojo, "hello", "apple", session=session, user=name)
    solve_challenge_offline(example_dojo, "hello", "apple", session=session, user=name)
    wait_for_background_worker(timeout=15)

    course_name = db_sql(f"SELECT name FROM dojos WHERE dojo_id = {dojo_db_id(course.dojo)};").strip()
    example_name = db_sql(f"SELECT name FROM dojos WHERE dojo_id = {dojo_db_id(example_dojo)};").strip()

    # the profile lists a dojo once the stats worker has ranked the solve there
    deadline = time.time() + 20
    while example_name not in session.get(f"{DOJO_URL}/hacker/{name}").text and time.time() < deadline:
        time.sleep(1)

    for viewer in [requests.Session(), session]:
        response = viewer.get(f"{DOJO_URL}/hacker/{name}")
        assert response.status_code == 200, response.status_code
        assert example_name in response.text, "non-course dojos the user solved in are shown"
        assert course_name not in response.text, "course participation is not publicly disclosed"


def test_as_user_is_restricted_to_official_students(course, admin_session, identity_budget):
    student_name, student_session = new_user()
    student_id = get_user_id(student_name)
    assert patch_identity(student_session, course.dojo, course.a).json()["success"] is True

    ghost_name, ghost_session = new_user()
    ghost_id = get_user_id(ghost_name)
    assert patch_identity(ghost_session, course.dojo, course.ghost).json()["success"] is True

    stranger_name, stranger_session = new_user()
    stranger_id = get_user_id(stranger_name)

    admin_name, dojo_admin_session = new_user()
    join(dojo_admin_session, course.dojo)
    promote_dojo_admin(admin_session, course.dojo, get_user_id(admin_name))

    def start(as_user):
        return dojo_admin_session.post(f"{API}/docker", json=dict(
            dojo=course.dojo, module="hello", challenge="apple", as_user=as_user)).json()

    assert start(stranger_id) == {"success": False, "error": f"Not a student in this dojo ({stranger_id})"}, \
        "a dojo admin may not impersonate a non-student"
    assert start(ghost_id) == {"success": False, "error": f"Not an official student in this dojo ({ghost_id})"}, \
        "a dojo admin may not impersonate an off-roster student"

    try:
        response = start(student_id)
        assert response["success"] is True, f"a dojo admin may work as an official student: {response}"
        container = dojo_run("docker", "inspect", "-f",
                             "{{index .Config.Labels \"dojo.as_user_id\"}}", f"user_{get_user_id(admin_name)}",
                             container=get_outer_container_for(f"user_{get_user_id(admin_name)}"))
        assert container.stdout.strip() == str(student_id), \
            f"the workspace runs as the impersonated student: {container.stdout.strip()}"
        flag = workspace_run("cat /flag", user=admin_name, root=True).stdout.strip()
        assert flag == "pwn.college{support_flag}", \
            f"an as_user workspace carries a support flag, never the student's real flag: {flag}"
        assert flag != challenge_flag(course.dojo, "hello", "apple", user=student_name), \
            "impersonation must not hand out the student's flag"
    finally:
        remove_workspace_container(admin_name)


def test_discord_course_endpoints(course, random_user):
    name, session = random_user
    user_id = get_user_id(name)

    for resource in ["memes", "thanks"]:
        anonymous = requests.get(f"{API}/discord/course/{course.dojo}/{resource}", allow_redirects=False)
        assert anonymous.status_code == 302 and "/login" in anonymous.headers["Location"], \
            f"anonymous access to {resource} is rejected: {anonymous.status_code}"
        response = session.get(f"{API}/discord/course/{course.dojo}/{resource}")
        assert response.status_code == 200, response.status_code
        assert response.json() == {"success": False, "error": "Discord not linked"}, response.json()

    discord_id = random.randrange(10**17, 10**18)
    db_sql(f"INSERT INTO discord_users (user_id, discord_id) VALUES ({user_id}, {discord_id});")
    try:
        for resource in ["memes", "thanks"]:
            response = session.get(f"{API}/discord/course/{course.dojo}/{resource}")
            assert response.json() == {"success": False, "error": "No course start"}, \
                f"{resource} needs a course start date: {response.json()}"

        course.install(start_date="2020-01-01T00:00:00-07:00")
        response = session.get(f"{API}/discord/course/{course.dojo}/memes")
        assert response.status_code == 200, response.status_code
        assert response.json() == {"success": True, "memes": 0}, response.json()
    finally:
        db_sql(f"DELETE FROM discord_users WHERE user_id = {user_id};")


def test_identity_endpoint_is_rate_limited(course, identity_budget):
    """Runs last: it deliberately exhausts the per-IP identity budget for up to 60 seconds."""
    name, session = new_user()
    user_id = get_user_id(name)

    for attempt in range(10):
        response = patch_identity(session, course.dojo, course.a)
        assert response.status_code == 200, f"PATCH {attempt} should be within the limit: {response.status_code}"

    response = patch_identity(session, course.dojo, course.b)
    assert response.status_code == 429, f"the 11th PATCH in a minute is rejected: {response.status_code}"
    assert dojo_user_rows(course.dojo, user_id) == f"student|{course.a}", \
        f"a rate-limited PATCH does not change the token: {dojo_user_rows(course.dojo, user_id)!r}"
    clear_identity_ratelimit()
