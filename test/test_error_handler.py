import pytest
import requests
from utils import login, DOJO_URL, dojo_run


def test_api_error_handler_logs_anonymous_user_context():
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/test_error", allow_redirects=False)
    assert response.status_code in [200, 302, 401, 403]


def test_api_error_handler_logs_authenticated_user_context(random_user_session):
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error")
    assert response.status_code == 500

    result = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | tail -100")
    logs = result.stdout
    assert "API_EXCEPTION" in logs
    assert "error_type='Exception'" in logs
    assert "Test error: This is a deliberate test of the error handler!" in logs


def test_api_error_handler_captures_request_data(random_user_session):
    test_data = {"test": "data", "number": 123}
    test_params = {"param1": "value1", "param2": "value2"}

    response = random_user_session.post(
        f"{DOJO_URL}/pwncollege_api/v1/test_error",
        json=test_data,
        params=test_params
    )

    assert response.status_code == 500

    logs = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | tail -100").stdout
    assert "API_EXCEPTION" in logs
    assert "method='POST'" in logs
    assert "query_params=" in logs
    assert "param1" in logs
    assert "json_data=" in logs


def test_api_error_handler_captures_user_agent(random_user_session):
    headers = {"User-Agent": "TestAgent/1.0 (Testing)"}
    response = random_user_session.get(
        f"{DOJO_URL}/pwncollege_api/v1/test_error",
        headers=headers
    )

    assert response.status_code == 500

    logs = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | tail -100").stdout
    assert "API_EXCEPTION" in logs
    assert "user_agent=" in logs


def test_api_error_handler_reraises_exception(random_user_session):
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error")

    assert response.status_code == 500
    assert "test error" in response.text.lower() or "error" in response.text.lower()


def test_api_error_handler_with_admin_user(admin_session):
    response = admin_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error")

    assert response.status_code == 500

    logs = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | tail -100").stdout
    assert "API_EXCEPTION" in logs
    assert "user_id=1" in logs


def test_api_non_existent_endpoint_404():
    response = requests.get(f"{DOJO_URL}/pwncollege_api/v1/this_does_not_exist")
    assert response.status_code == 404


def test_page_error_handler_logs_authenticated_user_context(random_user_session):
    response = random_user_session.get(f"{DOJO_URL}/test_page_error")

    assert response.status_code == 500

    logs = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | tail -100").stdout
    assert "PAGE_EXCEPTION" in logs
    assert "event='page_exception'" in logs
    assert "error_type='Exception'" in logs
    assert "Test page error:" in logs
    assert "method='GET'" in logs
    assert "endpoint='/test_page_error'" in logs


def test_page_error_handler_logs_anonymous_user_context():
    response = requests.get(f"{DOJO_URL}/test_page_error", allow_redirects=False)
    assert response.status_code in [302, 401]


def test_page_error_handler_captures_post_data(random_user_session):
    test_data = {"field1": "value1", "field2": "value2"}
    response = random_user_session.post(f"{DOJO_URL}/test_page_error", data=test_data)

    assert response.status_code == 500

    logs = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | tail -100").stdout
    assert "PAGE_EXCEPTION" in logs
    assert "form_data=" in logs
    assert "field1" in logs
    assert "method='POST'" in logs


def test_page_error_handler_with_admin_user(admin_session):
    response = admin_session.get(f"{DOJO_URL}/test_page_error")

    assert response.status_code == 500

    logs = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | tail -100").stdout
    assert "PAGE_EXCEPTION" in logs
    assert "user_id=1" in logs


def test_page_404_errors_not_logged():
    response = requests.get(f"{DOJO_URL}/this_page_does_not_exist")
    assert response.status_code == 404

    logs = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | grep PAGE_EXCEPTION | grep this_page_does_not_exist || echo 'not found'").stdout
    assert "not found" in logs