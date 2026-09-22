import datetime
import json
import uuid

import pytest
import yaml

from utils import (
    DOJO_URL,
    challenge_db_id,
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    dojo_run,
    get_user_id,
    login,
)


@pytest.fixture(autouse=True)
def survey_budget():
    keys = dojo_run("docker", "exec", "cache", "redis-cli", "--scan", "--pattern",
                    "flask_cache_rl:*:pwncollege_api.dojos_dojo_survey").stdout.split()
    if keys:
        dojo_run("docker", "exec", "cache", "redis-cli", "DEL", *keys)


def survey_responses(user_id):
    return json.loads(db_sql(
        "SELECT coalesce(json_agg(row_to_json(responses)), '[]'::json) FROM "
        "(SELECT dojo_id, challenge_id, user_id, prompt, response, timestamp "
        f"FROM survey_responses WHERE user_id = {user_id} ORDER BY id) responses"))


def create_survey_dojo(admin_session, *, imported=None):
    challenge = {"id": "feedback"}
    if imported:
        challenge["import"] = imported
    spec = {
        "id": f"survey-{uuid.uuid4().hex[:12]}",
        "type": "public",
        "image": "pwncollege/challenge-simple",
        "survey": {"prompt": "How was this lesson?", "data": "Feedback"},
        "modules": [{"id": "lesson", "challenges": [challenge]}],
    }
    return create_dojo_yml(yaml.safe_dump(spec), session=admin_session), spec


def get_challenge_survey(dojo, module, challenge, session):
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/surveys")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to recieve valid survey"
    return response.json()


def post_survey_response(dojo, module, challenge, survey_response, session):
    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/surveys",
        json={"response": survey_response}
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit survey"


def test_surveys(surveys_dojo, random_user, random_user_session):
    name, _ = random_user
    user_id = get_user_id(name)
    started = datetime.datetime.now(datetime.timezone.utc)
    assert random_user_session.get(f"{DOJO_URL}/dojo/{surveys_dojo}/join/").status_code == 200

    challenge_level_survey = get_challenge_survey(surveys_dojo, "surveys-module-1", "challenge-level", session=random_user_session)
    module_level_survey = get_challenge_survey(surveys_dojo, "surveys-module-1", "module-level", session=random_user_session)
    dojo_level_survey = get_challenge_survey(surveys_dojo, "surveys-module-2", "dojo-level", session=random_user_session)

    assert challenge_level_survey["prompt"] == "Challenge-level prompt", "Challenge-level survey prompt is wrong/missing"
    assert module_level_survey["prompt"] == "Module-level prompt", "Module-level survey prompt is wrong/missing"
    assert dojo_level_survey["prompt"] == "Dojo-level prompt", "Dojo-level survey prompt is wrong/missing"

    assert challenge_level_survey["data"] == "<div>challenge</div>", "Challenge-level survey data is wrong/missing"
    assert module_level_survey["data"] == "<div>module</div>", "Module-level survey data is wrong/missing"
    assert dojo_level_survey["data"] == "<div>dojo</div>", "Dojo-level survey data is wrong/missing"

    post_survey_response(surveys_dojo, "surveys-module-1", "challenge-level", "Test response", session=random_user_session)
    post_survey_response(surveys_dojo, "surveys-module-1", "module-level", "up", session=random_user_session)
    post_survey_response(surveys_dojo, "surveys-module-2", "dojo-level", 1, session=random_user_session)

    rows = survey_responses(user_id)
    assert [(row["challenge_id"], row["prompt"], row["response"]) for row in rows] == [
        (challenge_db_id(surveys_dojo, "surveys-module-1", "challenge-level"), "Challenge-level prompt", "Test response"),
        (challenge_db_id(surveys_dojo, "surveys-module-1", "module-level"), "Module-level prompt", "up"),
        (challenge_db_id(surveys_dojo, "surveys-module-2", "dojo-level"), "Dojo-level prompt", "1"),
    ]
    for row in rows:
        assert row["dojo_id"] == dojo_db_id(surveys_dojo)
        assert row["user_id"] == user_id
        timestamp = datetime.datetime.fromisoformat(row["timestamp"]).replace(tzinfo=datetime.timezone.utc)
        assert started - datetime.timedelta(seconds=10) <= timestamp <= datetime.datetime.now(datetime.timezone.utc)

    solves = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{surveys_dojo}/solves")
    assert solves.status_code == 200
    assert solves.json()["solves"] == [], "answering a survey must not solve its challenge"


@pytest.mark.parametrize("answer,stored", [
    ("A learner's feedback\nVery useful — спасибо!", "A learner's feedback\nVery useful — спасибо!"),
    ("", ""),
    (0, "0"),
    (2.5, "2.5"),
    (True, "true"),
    (False, "false"),
])
def test_survey_answers_preserve_supported_values(surveys_dojo, random_user, answer, stored):
    name, session = random_user
    post_survey_response(surveys_dojo, "surveys-module-1", "challenge-level", answer, session=session)
    rows = survey_responses(get_user_id(name))
    assert len(rows) == 1
    assert rows[0]["response"] == stored


def test_survey_responses_preserve_history_when_the_prompt_changes(admin_session, random_user):
    name, session = random_user
    dojo, spec = create_survey_dojo(admin_session)
    post_survey_response(dojo, "lesson", "feedback", "Before revision", session=session)
    post_survey_response(dojo, "lesson", "feedback", "A second answer", session=session)

    spec["survey"]["prompt"] = "Did the revised lesson help?"
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/update", json=spec)
    assert response.status_code == 200 and response.json()["success"], response.text
    assert get_challenge_survey(dojo, "lesson", "feedback", session)["prompt"] == spec["survey"]["prompt"]
    post_survey_response(dojo, "lesson", "feedback", "After revision", session=session)

    rows = survey_responses(get_user_id(name))
    assert [(row["prompt"], row["response"]) for row in rows] == [
        ("How was this lesson?", "Before revision"),
        ("How was this lesson?", "A second answer"),
        ("Did the revised lesson help?", "After revision"),
    ]
    assert {row["challenge_id"] for row in rows} == {challenge_db_id(dojo, "lesson", "feedback")}
    assert {row["dojo_id"] for row in rows} == {dojo_db_id(dojo)}


def test_imported_challenges_keep_feedback_associated_with_its_dojo_and_user(admin_session, random_user):
    name, session = random_user
    source, _ = create_survey_dojo(admin_session)
    imported, _ = create_survey_dojo(admin_session, imported={
        "dojo": source, "module": "lesson", "challenge": "feedback",
    })
    other_name = f"survey-{uuid.uuid4().hex[:12]}"
    other_session = login(other_name, other_name, register=True)

    post_survey_response(source, "lesson", "feedback", "Original lesson", session=session)
    post_survey_response(imported, "lesson", "feedback", "Imported lesson", session=session)
    post_survey_response(imported, "lesson", "feedback", "Another learner", session=other_session)

    source_challenge = challenge_db_id(source, "lesson", "feedback")
    assert source_challenge == challenge_db_id(imported, "lesson", "feedback")
    rows = survey_responses(get_user_id(name))
    assert [(row["dojo_id"], row["response"]) for row in rows] == [
        (dojo_db_id(source), "Original lesson"),
        (dojo_db_id(imported), "Imported lesson"),
    ]
    assert {row["challenge_id"] for row in rows} == {source_challenge}
    other_rows = survey_responses(get_user_id(other_name))
    assert len(other_rows) == 1
    assert (other_rows[0]["dojo_id"], other_rows[0]["challenge_id"], other_rows[0]["response"]) == (
        dojo_db_id(imported), source_challenge, "Another learner")
