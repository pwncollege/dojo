import uuid

import pytest
import yaml
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from utils import DOJO_URL, challenge_flag, create_dojo_yml, db_sql, flask_exec, get_user_id, start_challenge


@pytest.fixture(scope="module")
def progression_dojo(admin_session, example_dojo):
    return create_dojo_yml(yaml.safe_dump({
        "id": f"browser-progression-{uuid.uuid4().hex[:10]}",
        "name": "Browser Progression",
        "type": "public",
        "modules": [{
            "id": "sequence",
            "challenges": [{
                "id": challenge,
                "name": challenge.title(),
                "description": f"Instructions for {challenge}",
                "progression_locked": True,
                "import": {"dojo": example_dojo, "module": "hello", "challenge": source},
            } for challenge, source in [("first", "apple"), ("second", "banana")]],
        }],
    }), session=admin_session)


def challenge_item(browser, challenge):
    return browser.find_element(By.CSS_SELECTOR, f'input#challenge[value="{challenge}"]').find_element(
        By.XPATH, './ancestor::div[contains(concat(" ", normalize-space(@class), " "), " accordion-item ")][1]'
    )


def submit_flag(browser, challenge, flag):
    field = challenge_item(browser, challenge).find_element(By.ID, "challenge-input")
    WebDriverWait(browser, 20).until(lambda _: field.is_displayed() and field.is_enabled())
    field.clear()
    field.send_keys(flag)


def wait_for_solve(browser, challenge):
    WebDriverWait(browser, 20).until(
        lambda driver: challenge_item(driver, challenge).find_elements(By.CSS_SELECTOR, ".challenge-solved")
    )


def assert_next_challenge_locked(browser):
    button = browser.find_element(By.ID, "challenges-header-button-2")
    assert "disabled" in button.get_attribute("class").split()
    browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    ActionChains(browser).move_to_element(button).click().perform()
    field = challenge_item(browser, "second").find_element(By.ID, "challenge-input")
    with pytest.raises(TimeoutException):
        WebDriverWait(browser, 1).until(lambda _: field.is_displayed())


def test_solving_unlocks_the_next_challenge_without_reloading(
    random_user_browser, random_user_name, progression_dojo,
):
    browser = random_user_browser
    browser.get(f"{DOJO_URL}/{progression_dojo}/sequence")
    initial_solves = int(challenge_item(browser, "first").find_element(By.CLASS_NAME, "total-solves").text.split()[0])
    next_button = browser.find_element(By.ID, "challenges-header-button-2")
    assert_next_challenge_locked(browser)
    browser.find_element(By.ID, "challenges-header-button-1").click()

    submit_flag(browser, "first", challenge_flag(progression_dojo, "sequence", "first", user=random_user_name))
    wait_for_solve(browser, "first")
    WebDriverWait(browser, 20).until(lambda _: "disabled" not in next_button.get_attribute("class").split())
    next_button.click()
    WebDriverWait(browser, 20).until(
        lambda driver: "Instructions for second" in challenge_item(driver, "second").text
    )
    submit_flag(browser, "second", challenge_flag(progression_dojo, "sequence", "second", user=random_user_name))
    wait_for_solve(browser, "second")
    assert int(challenge_item(browser, "first").find_element(By.CLASS_NAME, "total-solves").text.split()[0]) == initial_solves + 1

    browser.refresh()
    wait_for_solve(browser, "first")
    wait_for_solve(browser, "second")


@pytest.mark.parametrize("submission", ["pwn.college{incorrect}", "pwn.college{practice}"])
def test_a_rejected_flag_can_be_corrected_in_the_same_form(
    random_user_browser, random_user_name, progression_dojo, submission,
):
    browser = random_user_browser
    browser.get(f"{DOJO_URL}/{progression_dojo}/sequence")
    browser.find_element(By.ID, "challenges-header-button-1").click()
    submit_flag(browser, "first", submission)
    WebDriverWait(browser, 20).until(EC.visibility_of_element_located((By.ID, "result-notification")))
    assert not challenge_item(browser, "first").find_elements(By.CSS_SELECTOR, ".challenge-solved")
    assert_next_challenge_locked(browser)

    submit_flag(browser, "first", challenge_flag(progression_dojo, "sequence", "first", user=random_user_name))
    wait_for_solve(browser, "first")


@pytest.mark.parametrize("submission_page", ["module", "workspace", "inline"])
def test_a_solve_in_another_tab_updates_progress_and_unlocks_the_next_challenge(
    random_user_browser, random_user_name, random_user_session, progression_dojo, submission_page,
):
    browser = random_user_browser
    module_url = f"{DOJO_URL}/{progression_dojo}/sequence"
    browser.get(module_url)
    initial_solves = int(challenge_item(browser, "first").find_element(By.CLASS_NAME, "total-solves").text.split()[0])
    original_tab = browser.current_window_handle
    browser.switch_to.new_window("tab")
    flag = challenge_flag(progression_dojo, "sequence", "first", user=random_user_name)
    if submission_page == "module":
        browser.get(module_url)
        browser.find_element(By.ID, "challenges-header-button-1").click()
        submit_flag(browser, "first", flag)
        wait_for_solve(browser, "first")
    else:
        start_challenge(progression_dojo, "sequence", "first", session=random_user_session, home=False)
        browser.get(f"{DOJO_URL}/workspace" if submission_page == "workspace" else module_url)
        if submission_page == "inline":
            browser.find_element(By.ID, "challenges-header-button-1").click()
        field = WebDriverWait(browser, 20).until(EC.element_to_be_clickable((By.ID, "flag-input")))
        field.send_keys(flag)
        WebDriverWait(browser, 20).until(EC.text_to_be_present_in_element(
            (By.ID, "workspace-notification-banner"), "Successfully completed",
        ))
        if submission_page == "inline":
            wait_for_solve(browser, "first")
            button = browser.find_element(By.ID, "challenges-header-button-2")
            WebDriverWait(browser, 20).until(lambda _: "disabled" not in button.get_attribute("class").split())
            button.click()
            WebDriverWait(browser, 20).until(
                lambda driver: "Instructions for second" in challenge_item(driver, "second").text
            )
            assert int(challenge_item(browser, "first").find_element(By.CLASS_NAME, "total-solves").text.split()[0]) == initial_solves + 1

    browser.switch_to.window(original_tab)
    wait_for_solve(browser, "first")
    assert int(challenge_item(browser, "first").find_element(By.CLASS_NAME, "total-solves").text.split()[0]) == initial_solves + 1
    next_button = browser.find_element(By.ID, "challenges-header-button-2")
    WebDriverWait(browser, 20).until(lambda _: "disabled" not in next_button.get_attribute("class").split())
    next_button.click()
    WebDriverWait(browser, 20).until(
        lambda driver: "Instructions for second" in challenge_item(driver, "second").text
    )


def test_authorized_dojo_javascript_adds_a_working_lesson_action(
    admin_session, random_user_browser, random_user_session, example_dojo,
):
    spec = {
        "id": f"browser-custom-{uuid.uuid4().hex[:10]}",
        "type": "public",
        "modules": [{"id": "lesson", "challenges": [{
            "id": "exercise", "import": {"dojo": example_dojo, "module": "hello", "challenge": "apple"},
        }]}],
        "files": [{"type": "text", "path": "custom.js", "content": """
const lessonAction = document.createElement('button');
lessonAction.id = 'lesson-action';
lessonAction.textContent = 'Try the lesson action';
lessonAction.addEventListener('click', () => { lessonAction.textContent = 'Lesson action completed'; });
document.querySelector('main').appendChild(lessonAction);
"""}],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    output = flask_exec(
        "from CTFd.models import db\n"
        "from CTFd.plugins.dojo_plugin.models import Dojos\n"
        "from CTFd.plugins.dojo_plugin.utils.dojo import dojo_from_dir\n"
        f"dojo = Dojos.from_id({dojo!r}).one()\n"
        "dojo.permissions = ['custom_js']\n"
        "dojo_from_dir(dojo.path, dojo=dojo, platform_admin=True)\n"
        "db.session.commit()\n"
        "print('lesson script loaded')\n"
    )
    assert "lesson script loaded" in output, output
    start_challenge(dojo, "lesson", "exercise", session=random_user_session, home=False)

    browser = random_user_browser
    browser.get(f"{DOJO_URL}/{dojo}/lesson")
    button = WebDriverWait(browser, 20).until(EC.element_to_be_clickable((By.ID, "lesson-action")))
    button.click()
    assert button.text == "Lesson action completed"
    response = random_user_session.delete(f"{DOJO_URL}/pwncollege_api/v1/docker", json={})
    assert response.status_code == 200 and response.json()["success"], response.text
    browser.get(DOJO_URL)
    assert not browser.find_elements(By.ID, "lesson-action")


def test_javascript_survey_form_saves_the_answer_entered_after_page_load(
    admin_session, random_user_browser, random_user_name, example_dojo,
):
    dojo = create_dojo_yml(yaml.safe_dump({
        "id": f"browser-survey-{uuid.uuid4().hex[:10]}",
        "type": "public",
        "survey": {
            "prompt": "What did you learn?",
            "data": '<label>Feedback <input name="response"></label><button type="submit">Send feedback</button>',
        },
        "modules": [{"id": "lesson", "challenges": [{
            "id": "exercise", "import": {"dojo": example_dojo, "module": "hello", "challenge": "apple"},
        }]}],
    }), session=admin_session)
    browser = random_user_browser
    browser.get(f"{DOJO_URL}/{dojo}/lesson")
    browser.find_element(By.ID, "challenges-header-button-1").click()
    submit_flag(browser, "exercise", challenge_flag(dojo, "lesson", "exercise", user=random_user_name))
    wait_for_solve(browser, "exercise")
    form = WebDriverWait(browser, 20).until(EC.visibility_of_element_located((By.ID, "survey-notification")))
    answer = f"I learned something new {uuid.uuid4().hex}"
    form.find_element(By.NAME, "response").send_keys(answer)
    form.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    user_id = get_user_id(random_user_name)
    WebDriverWait(browser, 15).until(lambda _: db_sql(
        f"SELECT count(*) FROM survey_responses WHERE user_id = {user_id}"
    ).strip() == "1")
    assert db_sql(f"SELECT response FROM survey_responses WHERE user_id = {user_id}").strip() == answer
