import pytest

from utils import DOJO_HOST


def get_challenge_survey(dojo, module, challenge, session):
    response = session.get(f"http://{DOJO_HOST}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/surveys")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to recieve valid survey"
    return response.json()


def post_survey_response(dojo, module, challenge, survey_response, session):
    response = session.post(
        f"http://{DOJO_HOST}/pwncollege_api/v1/dojos/{dojo}/{module}/{challenge}/surveys",
        json={"response": survey_response}
    )
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json()["success"], "Expected to successfully submit survey"


def test_surveys(surveys_dojo, random_user_session):
    assert random_user_session.get(f"http://{DOJO_HOST}/dojo/{surveys_dojo}/join/").status_code == 200

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