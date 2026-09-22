import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import docker.errors
import pytest
from requests.exceptions import ConnectionError


@pytest.fixture
def image_distribution(monkeypatch):
    image = "registry.example/course:latest"
    nodes = []
    for index in range(3):
        node = SimpleNamespace(
            api=SimpleNamespace(base_url=f"tcp://worker-{index}:2375"),
            available=set(), reachable=True, login_available=True, authenticated=False,
        )

        def pull(reference, node=node):
            if not node.reachable:
                raise ConnectionError("Workspace node unavailable")
            if reference != image:
                raise docker.errors.ImageNotFound("No such image")
            node.available.add(reference)

        def login(username, password, node=node):
            if not node.login_available:
                raise ConnectionError("Registry login unavailable")
            node.authenticated = username == "test-registry-user" and password == "test-registry-token"

        node.images = SimpleNamespace(pull=pull)
        node.login = login
        nodes.append(node)

    package = "test_image_distribution_plugin"
    for suffix in ("", ".worker", ".worker.handlers", ".config", ".utils"):
        module = ModuleType(f"{package}{suffix}")
        module.__path__ = []
        monkeypatch.setitem(sys.modules, module.__name__, module)
    config = sys.modules[f"{package}.config"]
    config.DOCKER_USERNAME = None
    config.DOCKER_TOKEN = None
    sys.modules[f"{package}.utils"].all_docker_clients = lambda: nodes
    spec = importlib.util.spec_from_file_location(
        f"{package}.worker.handlers.image_pulls",
        Path(__file__).resolve().parents[1] / "dojo_plugin/worker/handlers/image_pulls.py",
    )
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    return SimpleNamespace(handler=handler, nodes=nodes, image=image)


def test_image_pull_makes_the_challenge_available_on_every_workspace_node(image_distribution):
    state = image_distribution

    assert state.handler.handle_image_pull_event({"image": state.image}) == (True, False)

    assert all(state.image in node.available for node in state.nodes)


def test_image_distribution_can_retry_after_a_workspace_node_recovers(image_distribution):
    state = image_distribution
    state.nodes[1].reachable = False

    assert state.handler.handle_image_pull_event({"image": state.image}) == (False, True)
    assert not all(state.image in node.available for node in state.nodes)

    state.nodes[1].reachable = True
    assert state.handler.handle_image_pull_event({"image": state.image}) == (True, False)
    assert all(state.image in node.available for node in state.nodes)


def test_missing_images_are_not_reported_as_ready_or_retried(image_distribution):
    state = image_distribution

    assert state.handler.handle_image_pull_event({"image": "registry.example/missing:latest"}) == (False, False)

    assert all(not node.available for node in state.nodes)


def test_registry_login_failure_can_recover_before_distributing_images(image_distribution):
    state = image_distribution
    state.handler.DOCKER_USERNAME = "test-registry-user"
    state.handler.DOCKER_TOKEN = "test-registry-token"
    state.nodes[0].login_available = False

    assert state.handler.handle_image_pull_event({"image": state.image}) == (False, True)
    assert all(not node.available for node in state.nodes)

    state.nodes[0].login_available = True
    assert state.handler.handle_image_pull_event({"image": state.image}) == (True, False)
    assert all(node.authenticated and state.image in node.available for node in state.nodes)


@pytest.mark.parametrize("image", [None, "mac:ventura", "pwncollege-local-image"])
def test_external_and_local_images_do_not_require_registry_distribution(image_distribution, image):
    state = image_distribution

    assert state.handler.handle_image_pull_event({"image": image}) == (True, False)

    assert all(not node.available for node in state.nodes)
