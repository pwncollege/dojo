import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


spec = importlib.util.spec_from_file_location(
    "workspace_tui", Path(__file__).resolve().parents[1] / "workspace/core/tui.py"
)
tui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tui)


@pytest.fixture
def catalog_client():
    client = Mock()
    client.load_dojos.return_value = [{"id": "course", "name": "Course", "type": "course"}]
    client.load_dojo_modules.return_value = [{
        "id": "intro",
        "name": "Introduction",
        "challenges": [
            {"id": "apple", "name": "Apple"},
            {"id": "banana", "name": "Banana"},
        ],
    }]
    return client


async def press_and_settle(pilot, *keys):
    await pilot.pause()
    for key in keys:
        await pilot.press(key)
        await pilot.pause()


async def choose_challenge(pilot):
    await press_and_settle(pilot, "l", "j", "l", "j")


@pytest.mark.parametrize("mode,practice", [("s", False), ("p", True)])
@pytest.mark.parametrize("open_picker", [False, True])
def test_browser_selects_the_highlighted_challenge_and_start_mode(catalog_client, mode, practice, open_picker):
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await choose_challenge(pilot)
            await press_and_settle(pilot, "j")
            if open_picker:
                await press_and_settle(pilot, "enter")
            await press_and_settle(pilot, mode)

    asyncio.run(browse())
    assert app.return_value == {
        "dojo": "course", "module": "intro", "challenge": "banana", "practice": practice,
    }


@pytest.mark.parametrize(("api_override", "api_base"), [
    (None, "http://pwn.college:80/pwncollege_api/v1"),
    ("http://site:8000/pwncollege_api/v1", "http://site:8000/pwncollege_api/v1"),
])
def test_challenge_client_routes_requests_to_configured_api(monkeypatch, api_override, api_base):
    monkeypatch.setenv("DOJO_AUTH_TOKEN", "token")
    monkeypatch.delenv("DOJO_SSH_SERVICE_KEY", raising=False)
    monkeypatch.delenv("DOJO_USER_ID", raising=False)
    if api_override is None:
        monkeypatch.delenv("DOJO_API", raising=False)
    else:
        monkeypatch.setenv("DOJO_API", api_override)
    monkeypatch.setenv("DOJO_HOST", "dojo.example")
    get_response = Mock()
    get_response.json.return_value = {
        "success": True,
        "dojos": [{"id": "course", "name": "Course", "type": "course"}],
    }
    post_response = Mock()
    post_response.json.return_value = {"success": True}
    get = Mock(return_value=get_response)
    post = Mock(return_value=post_response)
    monkeypatch.setattr(tui.requests, "get", get)
    monkeypatch.setattr(tui.requests, "post", post)

    client = tui.ChallengeClient()
    assert client.load_dojos() == [{"id": "course", "name": "Course", "type": "course"}]
    client.start_challenge("course", "intro", "apple", True)

    headers = {
        "Authorization": "Bearer token",
        "Content-Type": "application/json",
        "Host": "dojo.example",
    }
    get.assert_called_once_with(f"{api_base}/dojos", headers=headers, timeout=20)
    post.assert_called_once_with(
        f"{api_base}/docker",
        headers=headers,
        json={
            "dojo": "course",
            "module": "intro",
            "challenge": "apple",
            "practice": True,
        },
        timeout=60,
    )
    get_response.raise_for_status.assert_called_once_with()
    post_response.raise_for_status.assert_called_once_with()


def test_challenge_client_authorizes_get_and_post_with_ssh_service_credentials(monkeypatch):
    monkeypatch.delenv("DOJO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("DOJO_SSH_SERVICE_KEY", "ssh-service-secret")
    monkeypatch.setenv("DOJO_USER_ID", "42")
    monkeypatch.setenv("DOJO_API", "http://site:8000/pwncollege_api/v1")
    monkeypatch.setenv("DOJO_HOST", "dojo.example")
    get_response = Mock()
    get_response.json.return_value = {"success": True, "modules": []}
    post_response = Mock()
    post_response.json.return_value = {"success": True}
    get = Mock(return_value=get_response)
    post = Mock(return_value=post_response)
    monkeypatch.setattr(tui.requests, "get", get)
    monkeypatch.setattr(tui.requests, "post", post)

    client = tui.ChallengeClient()
    assert client.load_dojo_modules("course") == []
    client.start_challenge("course", "intro", "apple", False)

    get.assert_called_once()
    post.assert_called_once()
    for request in (get.call_args, post.call_args):
        authorization = request.kwargs["headers"]["Authorization"]
        assert authorization.startswith("Bearer sk-ssh-service-")
        token = authorization.removeprefix("Bearer sk-ssh-service-")
        assert tui.URLSafeTimedSerializer("ssh-service-secret").loads(token) == [42, "ssh-tui"]
        assert request.kwargs["headers"]["Host"] == "dojo.example"
        assert request.kwargs["headers"]["Content-Type"] == "application/json"
    assert get.call_args.args == ("http://site:8000/pwncollege_api/v1/dojos/course/modules",)
    assert post.call_args.args == ("http://site:8000/pwncollege_api/v1/docker",)


def test_browser_cancel_returns_to_challenges_and_quit_does_not_start(catalog_client):
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await choose_challenge(pilot)
            await press_and_settle(pilot, "enter", "escape", "j")
            assert app.selection["challenge"]["id"] == "banana"
            await press_and_settle(pilot, "q")

    asyncio.run(browse())
    assert app.return_value is None
    catalog_client.start_challenge.assert_not_called()


def test_browser_cannot_start_a_dojo_or_module(catalog_client):
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await press_and_settle(pilot, "s", "p", "l", "j", "s", "p", "q")

    asyncio.run(browse())
    assert app.return_value is None
    catalog_client.start_challenge.assert_not_called()


def test_browser_can_reload_after_the_catalog_was_unavailable(catalog_client):
    catalog = catalog_client.load_dojos.return_value
    catalog_client.load_dojos.side_effect = [RuntimeError("Catalog unavailable"), catalog]
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await press_and_settle(pilot, "r")
            await choose_challenge(pilot)
            await press_and_settle(pilot, "s")

    asyncio.run(browse())
    assert app.return_value == {
        "dojo": "course", "module": "intro", "challenge": "apple", "practice": False,
    }


def test_browser_can_retry_loading_a_dojo_without_restarting(catalog_client):
    modules = catalog_client.load_dojo_modules.return_value
    catalog_client.load_dojo_modules.side_effect = [RuntimeError("Modules unavailable"), modules]
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await press_and_settle(pilot, "l", "h")
            await choose_challenge(pilot)
            await press_and_settle(pilot, "p")

    asyncio.run(browse())
    assert app.return_value == {
        "dojo": "course", "module": "intro", "challenge": "apple", "practice": True,
    }


def test_browser_empty_catalog_can_be_refreshed(catalog_client):
    catalog = catalog_client.load_dojos.return_value
    catalog_client.load_dojos.side_effect = [[], catalog]
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await press_and_settle(pilot, "s", "p", "r")
            await choose_challenge(pilot)
            await press_and_settle(pilot, "s")

    asyncio.run(browse())
    assert app.return_value["challenge"] == "apple"


def test_failed_start_returns_to_the_browser_and_can_be_retried(catalog_client, monkeypatch):
    catalog_client.start_challenge.side_effect = [RuntimeError("Please retry"), None]
    browser_type = tui.ChallengeBrowserApp
    errors = []

    def run_browser(client, start_error=None):
        app = browser_type(client, start_error=start_error)
        errors.append(start_error)

        async def browse():
            async with app.run_test() as pilot:
                await choose_challenge(pilot)
                await press_and_settle(pilot, "p" if start_error else "s")
            return app.return_value

        return Mock(run=lambda: asyncio.run(browse()))

    monkeypatch.setattr(tui, "ChallengeClient", lambda: catalog_client)
    monkeypatch.setattr(tui, "ChallengeBrowserApp", run_browser)

    assert tui.run_challenge_tui() is True
    assert errors == [None, "Please retry"]
    assert [call.args for call in catalog_client.start_challenge.call_args_list] == [
        ("course", "intro", "apple", False),
        ("course", "intro", "apple", True),
    ]
