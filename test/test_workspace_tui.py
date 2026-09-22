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


async def choose_challenge(pilot):
    await pilot.press("l", "j", "l", "j")


@pytest.mark.parametrize("mode,practice", [("s", False), ("p", True)])
@pytest.mark.parametrize("open_picker", [False, True])
def test_browser_selects_the_highlighted_challenge_and_start_mode(catalog_client, mode, practice, open_picker):
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await choose_challenge(pilot)
            await pilot.press("j")
            if open_picker:
                await pilot.press("enter")
            await pilot.press(mode)

    asyncio.run(browse())
    assert app.return_value == {
        "dojo": "course", "module": "intro", "challenge": "banana", "practice": practice,
    }


def test_browser_cancel_returns_to_challenges_and_quit_does_not_start(catalog_client):
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await choose_challenge(pilot)
            await pilot.press("enter", "escape", "j")
            assert app.selection["challenge"]["id"] == "banana"
            await pilot.press("q")

    asyncio.run(browse())
    assert app.return_value is None
    catalog_client.start_challenge.assert_not_called()


def test_browser_cannot_start_a_dojo_or_module(catalog_client):
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await pilot.press("s", "p", "l", "j", "s", "p", "q")

    asyncio.run(browse())
    assert app.return_value is None
    catalog_client.start_challenge.assert_not_called()


def test_browser_can_reload_after_the_catalog_was_unavailable(catalog_client):
    catalog = catalog_client.load_dojos.return_value
    catalog_client.load_dojos.side_effect = [RuntimeError("Catalog unavailable"), catalog]
    app = tui.ChallengeBrowserApp(catalog_client)

    async def browse():
        async with app.run_test() as pilot:
            await pilot.press("r")
            await choose_challenge(pilot)
            await pilot.press("s")

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
            await pilot.press("l", "h")
            await choose_challenge(pilot)
            await pilot.press("p")

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
            await pilot.press("s", "p", "r")
            await choose_challenge(pilot)
            await pilot.press("s")

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
                await pilot.press("p" if start_error else "s")
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
