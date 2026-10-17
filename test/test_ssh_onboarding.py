import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock, call

import pytest


spec = importlib.util.spec_from_file_location(
    "ssh_onboarding", Path(__file__).resolve().parents[1] / "sshd/onboard.py"
)
onboarding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(onboarding)


def status_text(app):
    return str(app.query_one("#status", onboarding.Static).content)


async def submit(app, pilot, value):
    app.input().value = value
    await pilot.press("enter")


def configure_main(monkeypatch, result):
    monkeypatch.setattr(
        onboarding.sys,
        "argv",
        ["onboard.py", "--key-type", "ssh-ed25519", "--key-base64", "AAAAkey"],
    )
    monkeypatch.delenv("SSH_ORIGINAL_COMMAND", raising=False)
    client = Mock(ssh_key_settings_url="https://dojo.example/settings#ssh-key")
    client_type = Mock(return_value=client)
    app = Mock()
    app.run.return_value = result
    app_type = Mock(return_value=app)
    monkeypatch.setattr(onboarding, "OnboardingClient", client_type)
    monkeypatch.setattr(onboarding, "OnboardingApp", app_type)
    return client, client_type, app, app_type


def test_client_uses_internal_site_and_custom_host(monkeypatch):
    monkeypatch.setenv("DOJO_SSH_SERVICE_KEY", "test-secret")
    monkeypatch.setenv("DOJO_HOST", "dojo.example")
    monkeypatch.setenv("DOJO_ENV", "production")
    monkeypatch.setenv("DOJO_API", "http://site.internal/pwncollege_api/v1")
    monkeypatch.setenv("SSH_CONNECTION", "203.0.113.7 12345 192.0.2.10 22")
    response = Mock()
    response.json.return_value = {"success": True, "data": {"user_id": 123}}
    post = Mock(return_value=response)
    monkeypatch.setattr(onboarding.requests, "post", post)

    client = onboarding.OnboardingClient("ssh-ed25519", "AAAAkey")
    assert client.ssh_key_settings_url == "https://dojo.example/settings#ssh-key"
    assert client.register("hacker", "hacker@example.com", "password", "code") == {
        "success": True,
        "data": {"user_id": 123},
    }

    request = post.call_args
    assert request.args == ("http://site.internal/pwncollege_api/v1/auth/register",)
    assert request.kwargs["headers"]["Host"] == "dojo.example"
    assert request.kwargs["headers"]["X-Forwarded-Proto"] == "https"
    assert request.kwargs["headers"]["X-Forwarded-For"] == "203.0.113.7"
    authorization = request.kwargs["headers"]["Authorization"]
    assert authorization.startswith("Bearer sk-ssh-service-")
    token = authorization.removeprefix("Bearer sk-ssh-service-")
    assert onboarding.URLSafeTimedSerializer("test-secret").loads(token) == "ssh-onboarding"
    assert request.kwargs["json"] == {
        "key_type": "ssh-ed25519",
        "key_base64": "AAAAkey",
        "name": "hacker",
        "email": "hacker@example.com",
        "password": "password",
        "registration_code": "code",
    }
    assert request.kwargs["timeout"] == 20


def test_client_uses_development_defaults_without_forwarded_client(monkeypatch):
    monkeypatch.setenv("DOJO_SSH_SERVICE_KEY", "test-secret")
    for name in ("DOJO_HOST", "DOJO_ENV", "DOJO_API", "SSH_CONNECTION"):
        monkeypatch.delenv(name, raising=False)
    response = Mock()
    response.json.return_value = {"success": True, "data": {"user_id": 123}}
    post = Mock(return_value=response)
    monkeypatch.setattr(onboarding.requests, "post", post)

    client = onboarding.OnboardingClient("ssh-rsa", "AAAAdefault")

    assert client.dojo_host == "pwn.college"
    assert client.api_base == "http://site:8000/pwncollege_api/v1"
    assert client.client_ip == ""
    assert client.ssh_key_settings_url == "http://pwn.college/settings#ssh-key"
    client.register("hacker", "hacker@example.com", "password")
    request = post.call_args
    assert request.args == ("http://site:8000/pwncollege_api/v1/auth/register",)
    assert request.kwargs["headers"]["Host"] == "pwn.college"
    assert request.kwargs["headers"]["X-Forwarded-Proto"] == "http"
    assert "X-Forwarded-For" not in request.kwargs["headers"]
    assert request.kwargs["json"]["registration_code"] == ""


def test_client_requires_service_secret(monkeypatch):
    monkeypatch.delenv("DOJO_SSH_SERVICE_KEY", raising=False)

    with pytest.raises(RuntimeError, match="^Missing DOJO_SSH_SERVICE_KEY$"):
        onboarding.OnboardingClient("ssh-ed25519", "AAAAkey")


@pytest.mark.parametrize(
    "response_data, expected_errors",
    [
        (
            {"success": False, "errors": ["Username is unavailable", "Email is invalid"]},
            ["Username is unavailable", "Email is invalid"],
        ),
        ({"success": False, "error": "Registration is disabled"}, ["Registration is disabled"]),
        ({"success": False, "message": "Try again later"}, ["Try again later"]),
        ({"success": False}, ["Request failed"]),
    ],
)
def test_client_maps_api_failures_to_registration_errors(monkeypatch, response_data, expected_errors):
    monkeypatch.setenv("DOJO_SSH_SERVICE_KEY", "test-secret")
    response = Mock()
    response.json.return_value = response_data
    monkeypatch.setattr(onboarding.requests, "post", Mock(return_value=response))
    client = onboarding.OnboardingClient("ssh-ed25519", "AAAAkey")

    with pytest.raises(onboarding.RegistrationError) as raised:
        client.register("hacker", "hacker@example.com", "password")

    assert raised.value.errors == expected_errors
    assert str(raised.value) == "\n".join(expected_errors)


@pytest.mark.parametrize("returncode, expected", [(0, True), (1, False)])
def test_challenge_tui_receives_the_created_user(monkeypatch, returncode, expected):
    monkeypatch.setenv("PRESERVED", "value")
    run = Mock(return_value=Mock(returncode=returncode))
    monkeypatch.setattr(onboarding.subprocess, "run", run)

    assert onboarding.run_challenge_tui(42) is expected
    assert run.call_args.args == ([onboarding.DOJO_CLI, "tui"],)
    assert run.call_args.kwargs["env"]["DOJO_USER_ID"] == "42"
    assert run.call_args.kwargs["env"]["PRESERVED"] == "value"


def test_create_account_flow_submits_trimmed_fields_and_returns_user():
    client = Mock()
    client.register.return_value = {
        "success": True,
        "data": {"username": "alice", "user_id": 42},
    }
    app = onboarding.OnboardingApp(client, timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            scheduled = []
            app.set_timer = lambda delay, callback: scheduled.append((delay, callback))
            await pilot.press("c")
            assert app.state == "create-name"
            assert app.input().placeholder == "username"
            await submit(app, pilot, "  alice  ")
            assert app.state == "create-email"
            assert app.input().placeholder == "email"
            await submit(app, pilot, "  alice@example.com  ")
            assert app.state == "create-password"
            assert app.input().password is True
            await submit(app, pilot, "  swordfish  ")
            assert app.state == "create-submitting"
            assert app.input().display is False
            scheduled.pop(0)[1]()
            await pilot.pause()
            assert status_text(app) == "Account created"
            assert "Created `alice` and linked this SSH key." in app.query_one(
                "#content", onboarding.Markdown
            ).source
            assert app.account_password == ""
            scheduled.pop(0)[1]()

    asyncio.run(run())
    assert client.register.call_args == call("alice", "alice@example.com", "swordfish", "")
    assert app.return_value == {"action": "create", "user_id": 42}


def test_create_account_rejects_empty_name_email_and_password():
    client = Mock()
    app = onboarding.OnboardingApp(client, timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            await pilot.press("c")
            await submit(app, pilot, " \t ")
            assert app.state == "create-name"
            assert status_text(app) == "Username is required"
            await submit(app, pilot, "alice")
            await submit(app, pilot, "   ")
            assert app.state == "create-email"
            assert status_text(app) == "Email is required"
            await submit(app, pilot, "alice@example.com")
            await submit(app, pilot, " ")
            assert app.state == "create-password"
            assert status_text(app) == "Password is required"
            assert app.input().display is True
            assert app.input().password is True
            await pilot.press("escape")
            assert app.state == "menu"
            assert app.input().display is False

    asyncio.run(run())
    client.register.assert_not_called()


def test_registration_code_prompt_retains_password_and_resubmits():
    client = Mock()
    client.register.side_effect = [
        onboarding.RegistrationError(["Invalid registration code"]),
        {"success": True, "data": {"username": "alice", "user_id": 42}},
    ]
    app = onboarding.OnboardingApp(client, timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            scheduled = []
            app.set_timer = lambda delay, callback: scheduled.append((delay, callback))
            await pilot.press("c")
            await submit(app, pilot, "alice")
            await submit(app, pilot, "alice@example.com")
            await submit(app, pilot, "swordfish")
            scheduled.pop(0)[1]()
            await pilot.pause()
            assert app.state == "create-registration-code"
            assert app.account_password == "swordfish"
            assert app.input().display is True
            assert app.input().password is True
            assert app.input().placeholder == "registration code"
            assert status_text(app) == "Enter registration code"
            await submit(app, pilot, "  invite-only  ")
            assert app.state == "create-submitting"
            scheduled.pop(0)[1]()
            await pilot.pause()
            assert app.account_password == ""
            assert status_text(app) == "Account created"
            scheduled.pop(0)[1]()

    asyncio.run(run())
    assert client.register.call_args_list == [
        call("alice", "alice@example.com", "swordfish", ""),
        call("alice", "alice@example.com", "swordfish", "invite-only"),
    ]
    assert app.return_value == {"action": "create", "user_id": 42}


def test_invalid_submitted_registration_code_returns_to_a_reusable_menu():
    client = Mock()
    client.register.side_effect = onboarding.RegistrationError(["Invalid registration code"])
    app = onboarding.OnboardingApp(client, timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            app.account_password = "swordfish"
            app.finish_registration(
                "alice",
                "alice@example.com",
                "swordfish",
                "wrong-code",
            )
            await pilot.pause()
            assert app.state == "menu"
            assert app.account_password == ""
            assert app.query_one("#choices", onboarding.ListView).display is True
            assert app.input().display is False
            assert status_text(app) == "Account creation failed: Invalid registration code"
            await pilot.press("c")
            assert app.state == "create-name"

    asyncio.run(run())
    client.register.assert_called_once_with(
        "alice",
        "alice@example.com",
        "swordfish",
        "wrong-code",
    )


def test_registration_code_prompt_can_be_cancelled_with_escape():
    client = Mock()
    client.register.side_effect = onboarding.RegistrationError(["Invalid registration code"])
    app = onboarding.OnboardingApp(client, timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            app.account_password = "swordfish"
            app.finish_registration("alice", "alice@example.com", "swordfish")
            await pilot.pause()
            assert app.state == "create-registration-code"
            assert app.account_password == "swordfish"
            await pilot.press("escape")
            await pilot.pause()
            assert app.state == "menu"
            assert app.account_password == ""
            assert app.query_one("#choices", onboarding.ListView).display is True
            assert app.input().display is False

    asyncio.run(run())


@pytest.mark.parametrize(
    "error, expected_status",
    [
        (
            onboarding.RegistrationError(["Username is unavailable", "Email is invalid"]),
            "Account creation failed: Username is unavailable\nEmail is invalid",
        ),
        (RuntimeError("Site is unavailable"), "Account creation failed: Site is unavailable"),
    ],
)
def test_registration_failures_return_to_a_reusable_menu(error, expected_status):
    client = Mock()
    client.register.side_effect = error
    app = onboarding.OnboardingApp(client, timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            app.account_password = "swordfish"
            app.finish_registration("alice", "alice@example.com", "swordfish")
            await pilot.pause()
            assert app.state == "menu"
            assert app.account_password == ""
            assert app.query_one("#choices", onboarding.ListView).display is True
            assert app.input().display is False
            assert status_text(app) == expected_status
            assert app.query_one("#status", onboarding.Static).size.height >= len(expected_status.splitlines())
            await pilot.press("c")
            assert app.state == "create-name"

    asyncio.run(run())


def test_link_selection_returns_link_action():
    app = onboarding.OnboardingApp(Mock(), timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            await pilot.press("down")
            await pilot.press("enter")

    asyncio.run(run())
    assert app.return_value == {"action": "link"}


def test_link_hotkey_returns_link_action():
    app = onboarding.OnboardingApp(Mock(), timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("l")

    asyncio.run(run())
    assert app.return_value == {"action": "link"}


def test_default_menu_selection_opens_create_account_flow():
    client = Mock()
    app = onboarding.OnboardingApp(client, timeout_seconds=60)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#choices", onboarding.ListView).index == 0
            await pilot.press("enter")
            await pilot.pause()
            assert app.state == "create-name"
            assert app.input().display is True
            assert app.input().placeholder == "username"
            assert status_text(app) == "Enter username"

    asyncio.run(run())
    client.register.assert_not_called()


def test_onboarding_session_has_a_bounded_lifetime():
    app = onboarding.OnboardingApp(Mock(), timeout_seconds=0.05)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)

    asyncio.run(run())
    assert app.return_value == {"action": "timeout"}


def test_main_rejects_remote_commands_before_starting_onboarding(monkeypatch, capsys):
    monkeypatch.setattr(
        onboarding.sys,
        "argv",
        ["onboard.py", "--key-type", "ssh-ed25519", "--key-base64", "AAAAkey"],
    )
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "id")
    client_type = Mock()
    app_type = Mock()
    monkeypatch.setattr(onboarding, "OnboardingClient", client_type)
    monkeypatch.setattr(onboarding, "OnboardingApp", app_type)

    assert onboarding.main() == 1
    assert "Connect without a command to set it up." in capsys.readouterr().err
    client_type.assert_not_called()
    app_type.assert_not_called()


def test_main_reports_onboarding_timeout(monkeypatch, capsys):
    configure_main(monkeypatch, {"action": "timeout"})

    assert onboarding.main() == 1
    assert capsys.readouterr().err == "SSH onboarding timed out.\n"


def test_main_prints_existing_account_link_instructions(monkeypatch, capsys):
    client, client_type, app, app_type = configure_main(monkeypatch, {"action": "link"})

    assert onboarding.main() == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert client.ssh_key_settings_url in output.out
    assert "paste your SSH public key" in output.out
    assert "reconnect over SSH" in output.out
    client_type.assert_called_once_with("ssh-ed25519", "AAAAkey")
    app_type.assert_called_once_with(client)
    app.run.assert_called_once_with()


def test_main_hands_created_user_from_challenge_browser_to_enter(monkeypatch):
    configure_main(monkeypatch, {"action": "create", "user_id": 42})
    run_challenge_tui = Mock(return_value=True)
    execv = Mock()
    monkeypatch.setattr(onboarding, "run_challenge_tui", run_challenge_tui)
    monkeypatch.setattr(onboarding.os, "execv", execv)

    assert onboarding.main() == 0
    run_challenge_tui.assert_called_once_with(42)
    enter_path = Path(onboarding.__file__).parent.resolve() / "enter.py"
    execv.assert_called_once_with(
        sys.executable,
        [sys.executable, str(enter_path), "user_42"],
    )


def test_main_does_not_enter_when_challenge_browser_is_cancelled(monkeypatch):
    configure_main(monkeypatch, {"action": "create", "user_id": 42})
    monkeypatch.setattr(onboarding, "run_challenge_tui", Mock(return_value=False))
    execv = Mock()
    monkeypatch.setattr(onboarding.os, "execv", execv)

    assert onboarding.main() == 0
    execv.assert_not_called()


def test_main_reports_startup_failure(monkeypatch, capsys):
    client, client_type, app, app_type = configure_main(monkeypatch, None)
    app.run.side_effect = RuntimeError("No terminal")

    assert onboarding.main() == 1
    assert capsys.readouterr().err == "Failed to start SSH onboarding: No terminal\n"
    client_type.assert_called_once_with("ssh-ed25519", "AAAAkey")
    app_type.assert_called_once_with(client)


@pytest.mark.parametrize("failure", [RuntimeError("No browser"), OSError("Cannot exec")])
def test_main_reports_challenge_handoff_failures(monkeypatch, capsys, failure):
    configure_main(monkeypatch, {"action": "create", "user_id": 42})
    if isinstance(failure, OSError):
        monkeypatch.setattr(onboarding, "run_challenge_tui", Mock(return_value=True))
        monkeypatch.setattr(onboarding.os, "execv", Mock(side_effect=failure))
    else:
        monkeypatch.setattr(onboarding, "run_challenge_tui", Mock(side_effect=failure))

    assert onboarding.main() == 1
    assert capsys.readouterr().err == f"Failed to launch challenge browser: {failure}\n"
