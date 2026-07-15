import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import Mock


spec = importlib.util.spec_from_file_location(
    "ssh_onboarding", Path(__file__).resolve().parents[1] / "sshd/onboard.py"
)
onboarding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(onboarding)


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
    assert request.kwargs["headers"]["Authorization"].startswith("Bearer sk-ssh-service-")
    assert request.kwargs["json"] == {
        "key_type": "ssh-ed25519",
        "key_base64": "AAAAkey",
        "name": "hacker",
        "email": "hacker@example.com",
        "password": "password",
        "registration_code": "code",
    }


def test_onboarding_session_has_a_bounded_lifetime():
    app = onboarding.OnboardingApp(Mock(), timeout_seconds=0.01)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.05)

    asyncio.run(run())
    assert app.return_value == {"action": "timeout"}
