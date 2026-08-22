import hmac
import random
import string
import subprocess
from urllib.parse import urlparse, parse_qs

import pytest
import requests

from utils import (
    DOJO_URL,
    dojo_run,
    get_outer_container_for,
    get_user_id,
    login,
    remove_workspace_container,
    start_challenge,
    workspace_run,
)

WORKSPACE_API = f"{DOJO_URL}/pwncollege_api/v1/workspace"


def random_name(prefix):
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def container_auth_token(user_name):
    container = f"user_{get_user_id(user_name)}"
    outer_container = get_outer_container_for(container)
    result = dojo_run(
        "docker", "inspect", "--format", '{{index .Config.Labels "dojo.auth_token"}}',
        container, container=outer_container,
    )
    auth_token = result.stdout.strip()
    assert auth_token, f"container {container} has no dojo.auth_token label"
    return auth_token


def container_password(user_name, *args):
    key = container_auth_token(user_name).encode()
    return hmac.HMAC(key, "-".join(args).encode(), "sha256").hexdigest()


def forwarded_port(iframe_src):
    parts = [part for part in urlparse(iframe_src).path.split("/") if part]
    assert parts and parts[0] == "workspace", f"unexpected workspace url: {iframe_src}"
    assert len(parts) >= 4, f"workspace url is missing its port segment: {iframe_src}"
    return int(parts[3])


@pytest.fixture(scope="module")
def workspace_owner(example_dojo):
    name = random_name("wsproxy")
    session = login(name, name, register=True)
    start_challenge(example_dojo, "hello", "apple", session=session)
    yield name, session, get_user_id(name)
    remove_workspace_container(name)


def test_workspace_pages_require_authentication():
    anonymous = requests.Session()
    for path in ["/workspace", "/workspace/8080", "/workspace/terminal", "/pwncollege_api/v1/workspace"]:
        response = anonymous.get(f"{DOJO_URL}{path}", allow_redirects=False)
        assert response.status_code == 302, f"Expected {path} to redirect anonymous users, got {response.status_code}"
        assert "/login" in response.headers.get("Location", ""), (
            f"Expected {path} to redirect to login, got {response.headers.get('Location')}"
        )


def test_workspace_page_without_container_reports_no_active_challenge(random_user_session):
    response = random_user_session.get(f"{DOJO_URL}/workspace")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert "start a challenge" in response.text, "Expected the no-active-challenge message on /workspace"


def test_workspace_api_without_container_reports_inactive(random_user_session):
    response = random_user_session.get(f"{WORKSPACE_API}?service=challenge")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json() == {"success": False, "active": False}, (
        f"Expected an inactive workspace, but got {response.json()}"
    )


def test_workspace_port_and_service_pages_target_their_workspace(workspace_owner):
    _, session, _ = workspace_owner

    port_page = session.get(f"{DOJO_URL}/workspace/8080")
    assert port_page.status_code == 200, f"Expected status code 200, but got {port_page.status_code}"
    assert 'data-initial-service="code: 8080"' in port_page.text, \
        "Expected /workspace/8080 to select the code service"

    service_page = session.get(f"{DOJO_URL}/workspace/terminal")
    assert service_page.status_code == 200, f"Expected status code 200, but got {service_page.status_code}"
    assert 'data-initial-service="terminal: 7681"' in service_page.text, \
        "Expected /workspace/terminal to select the terminal service"

    unavailable_page = session.get(f"{DOJO_URL}/workspace/1234")
    assert unavailable_page.status_code == 404, \
        f"Expected an unavailable workspace port to return 404, got {unavailable_page.status_code}"


def test_workspace_api_service_names_map_to_ports(workspace_owner, example_dojo):
    _, session, _ = workspace_owner

    for service, port in [("challenge", 80), ("terminal", 7681), ("desktop-windows", 6082)]:
        response = session.get(f"{WORKSPACE_API}?service={service}")
        assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
        result = response.json()
        assert result["success"] and result["active"], f"Expected an active workspace for {service}: {result}"
        assert result["service"] == service, f"Expected service {service}, but got {result['service']}"
        assert forwarded_port(result["iframe_src"]) == port, (
            f"Expected service {service} to forward to port {port}, but got {result['iframe_src']}"
        )
        assert result["current_challenge"] == {
            "dojo_id": example_dojo, "module_id": "hello", "challenge_id": "apple"
        }, f"Expected the running challenge to be reported, but got {result['current_challenge']}"


def test_workspace_api_numeric_service_is_a_raw_port(workspace_owner):
    _, session, _ = workspace_owner

    service_response = session.get(f"{WORKSPACE_API}?service=1234")
    assert service_response.status_code == 200, f"Expected status code 200, but got {service_response.status_code}"
    assert forwarded_port(service_response.json()["iframe_src"]) == 1234, (
        f"Expected a numeric service to be a raw port, but got {service_response.json()['iframe_src']}"
    )

    port_response = session.get(f"{WORKSPACE_API}?port=1337")
    assert port_response.status_code == 200, f"Expected status code 200, but got {port_response.status_code}"
    port_result = port_response.json()
    assert port_result["service"] is None, f"Expected no service for a port request, but got {port_result['service']}"
    assert forwarded_port(port_result["iframe_src"]) == 1337, (
        f"Expected port 1337 to be forwarded, but got {port_result['iframe_src']}"
    )


def test_workspace_api_unknown_service_is_not_found(workspace_owner):
    _, session, _ = workspace_owner
    for service in ["bogusservice", "terminal~notanumber", "terminal~1~2~3"]:
        response = session.get(f"{WORKSPACE_API}?service={service}")
        assert response.status_code == 404, (
            f"Expected status code 404 for service {service}, but got {response.status_code}"
        )


def test_workspace_api_service_user_form_requires_dojo_admin(workspace_owner, admin_session):
    name, session, user_id = workspace_owner

    own_workspace = session.get(f"{WORKSPACE_API}?service=terminal~{user_id}")
    assert own_workspace.status_code == 403, (
        f"Expected the service~user form to be admin-only, but got {own_workspace.status_code}"
    )

    as_admin = admin_session.get(f"{WORKSPACE_API}?user={user_id}&service=terminal~{user_id}")
    assert as_admin.status_code == 200, f"Expected status code 200, but got {as_admin.status_code}"
    assert forwarded_port(as_admin.json()["iframe_src"]) == 7681, (
        f"Expected an admin to reach the user's terminal, but got {as_admin.json()['iframe_src']}"
    )

    missing_user = session.get(f"{WORKSPACE_API}?service=terminal~99999999")
    assert missing_user.status_code == 404, (
        f"Expected status code 404 for an unknown user, but got {missing_user.status_code}"
    )


def test_workspace_api_service_user_code_form_checks_access_code(workspace_owner):
    name, session, user_id = workspace_owner

    correct_code = container_password(name, "terminal")
    granted = session.get(f"{WORKSPACE_API}?service=terminal~{user_id}~{correct_code}")
    assert granted.status_code == 200, f"Expected status code 200, but got {granted.status_code}"
    assert forwarded_port(granted.json()["iframe_src"]) == 7681, (
        f"Expected the access code to grant the terminal, but got {granted.json()['iframe_src']}"
    )

    wrong_code = "0" * len(correct_code)
    denied = session.get(f"{WORKSPACE_API}?service=terminal~{user_id}~{wrong_code}")
    assert denied.status_code == 403, (
        f"Expected status code 403 for a wrong access code, but got {denied.status_code}"
    )

    other_service_code = session.get(f"{WORKSPACE_API}?service=code~{user_id}~{correct_code}")
    assert other_service_code.status_code == 403, (
        f"Expected a terminal access code to not grant code-server, but got {other_service_code.status_code}"
    )

    code_granted = session.get(f"{WORKSPACE_API}?service=code~{user_id}~{container_password(name, 'code')}")
    assert code_granted.status_code == 200, f"Expected status code 200, but got {code_granted.status_code}"
    assert forwarded_port(code_granted.json()["iframe_src"]) == 8080, (
        f"Expected the code access code to grant code-server, but got {code_granted.json()['iframe_src']}"
    )


def test_workspace_api_other_user_requires_admin_or_password(workspace_owner, random_user_session, admin_session):
    _, _, user_id = workspace_owner

    no_password = random_user_session.get(f"{WORKSPACE_API}?user={user_id}")
    assert no_password.status_code == 403, (
        f"Expected status code 403 without a password, but got {no_password.status_code}"
    )

    non_desktop = random_user_session.get(f"{WORKSPACE_API}?user={user_id}&password=x&service=terminal")
    assert non_desktop.status_code == 403, (
        f"Expected status code 403 for a non-desktop service, but got {non_desktop.status_code}"
    )

    as_admin = admin_session.get(f"{WORKSPACE_API}?user={user_id}&service=challenge")
    assert as_admin.status_code == 200, f"Expected status code 200, but got {as_admin.status_code}"
    assert forwarded_port(as_admin.json()["iframe_src"]) == 80, (
        f"Expected an admin to reach the user's workspace, but got {as_admin.json()['iframe_src']}"
    )


def test_workspace_api_desktop_sharing_requires_the_desktop_password(workspace_owner, random_user_session):
    name, _, user_id = workspace_owner

    wrong_password = random_user_session.get(f"{WORKSPACE_API}?user={user_id}&password=wrong&service=desktop")
    assert wrong_password.status_code == 403, (
        f"Expected status code 403 for a wrong desktop password, but got {wrong_password.status_code}"
    )

    view_password = container_password(name, "desktop", "view")
    shared = random_user_session.get(f"{WORKSPACE_API}?user={user_id}&password={view_password}&service=desktop")
    assert shared.status_code == 200, f"Expected status code 200, but got {shared.status_code}"
    result = shared.json()
    assert result["success"], f"Expected desktop sharing to succeed, but got {result}"
    assert forwarded_port(result["iframe_src"]) == 6080, (
        f"Expected the desktop to forward to port 6080, but got {result['iframe_src']}"
    )

    params = parse_qs(urlparse(result["iframe_src"]).query)
    assert params["view_only"] == ["1"], f"Expected a shared desktop to be view-only, but got {params.get('view_only')}"
    assert params["password"] == [view_password[:8]], (
        f"Expected the vnc password to be derived from the supplied password, but got {params.get('password')}"
    )
    assert params["path"][0].endswith("/6080/websockify"), (
        f"Expected the vnc websocket to be forwarded to the desktop port, but got {params.get('path')}"
    )


def test_workspace_system_mounts_are_read_only(workspace_owner):
    name, _, _ = workspace_owner

    for path in ["/nix", "/run/dojo/sys"]:
        options = workspace_run(f"findmnt -no OPTIONS {path}", user=name).stdout.strip().split(",")
        assert "ro" in options, f"Expected {path} to be mounted read-only, but got {options}"

        with pytest.raises(subprocess.CalledProcessError) as exception:
            workspace_run(f"touch {path}/evil", user=name, root=True)
        assert "Read-only file system" in exception.value.stderr, (
            f"Expected root to be unable to write to {path}, but got {exception.value.stderr}"
        )
