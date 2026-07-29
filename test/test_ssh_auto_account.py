import os
import tempfile
import subprocess
import json
import time
from types import SimpleNamespace

import requests

from utils import DOJO_URL, dojo_run, get_outer_container_for


def generate_public_key(key_type="ed25519"):
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = os.path.join(tmpdir, "test_key")
        cmd = ["ssh-keygen", "-t", key_type, "-f", key_path, "-N", ""]
        if key_type == "rsa":
            cmd = ["ssh-keygen", "-t", "rsa", "-b", "2048", "-f", key_path, "-N", ""]
        subprocess.run(cmd, check=True, capture_output=True)
        with open(f"{key_path}.pub", "r") as handle:
            return handle.read().strip()


def get_internal_token():
    config_env = dojo_run("cat", "/data/config.env").stdout
    for line in config_env.splitlines():
        if line.startswith("SSH_PIPER_API_TOKEN="):
            token = line.split("=", 1)[1].strip()
            if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
                token = token[1:-1]
            return token
    return "ssh-piper-development-token"


def provision(public_key, token, **kwargs):
    payload = {"public_key": public_key}
    payload.update(kwargs)
    response = requests.post(
        f"{DOJO_URL}/pwncollege_api/v1/ssh_auto_account",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    return response


def inspect_container(container_name):
    outer_container = get_outer_container_for(container_name)
    result = dojo_run("docker", "inspect", container_name, container=outer_container).stdout
    return json.loads(result)[0]


def wait_for_container(user_id, *, dojo, module, challenge, mode=None, attempts=30):
    container_name = f"user_{user_id}"
    for _ in range(attempts):
        try:
            container = inspect_container(container_name)
            labels = container["Config"]["Labels"]
            assert labels["dojo.dojo_id"] == dojo
            assert labels["dojo.module_id"] == module
            assert labels["dojo.challenge_id"] == challenge
            if mode is not None:
                assert labels["dojo.mode"] == mode
            return container
        except Exception:
            time.sleep(1)
    raise AssertionError(f"Timed out waiting for {container_name} to start {dojo}/{module}/{challenge}")


def test_generate_public_key_returns_valid_ed25519_public_key():
    public_key = generate_public_key("ed25519")
    parts = public_key.split()
    assert len(parts) >= 2
    assert parts[0] == "ssh-ed25519"


def test_generate_public_key_returns_valid_rsa_public_key():
    public_key = generate_public_key("rsa")
    parts = public_key.split()
    assert len(parts) >= 2
    assert parts[0] == "ssh-rsa"


def test_get_internal_token_reads_config_env_value(monkeypatch):
    monkeypatch.setattr(__import__(__name__), "dojo_run", lambda *args, **kwargs: SimpleNamespace(stdout="A=1\nSSH_PIPER_API_TOKEN=real-token\nB=2\n"))

    assert get_internal_token() == "real-token"


def test_get_internal_token_falls_back_when_missing(monkeypatch):
    monkeypatch.setattr(__import__(__name__), "dojo_run", lambda *args, **kwargs: SimpleNamespace(stdout="A=1\nB=2\n"))

    assert get_internal_token() == "ssh-piper-development-token"


def test_provision_posts_expected_payload_and_bearer_token(monkeypatch):
    captured = {}

    def fake_post(url, json, headers):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return SimpleNamespace(status_code=200, json=lambda: {"success": True})

    monkeypatch.setattr(requests, "post", fake_post)

    response = provision(
        "ssh-ed25519 AAAATESTKEY",
        "internal-token",
        bootstrap_dojo="example",
        bootstrap_module="hello",
        bootstrap_challenge="apple",
    )

    assert response.status_code == 200
    assert captured["url"] == f"{DOJO_URL}/pwncollege_api/v1/ssh_auto_account"
    assert captured["json"] == {
        "public_key": "ssh-ed25519 AAAATESTKEY",
        "bootstrap_dojo": "example",
        "bootstrap_module": "hello",
        "bootstrap_challenge": "apple",
    }
    assert captured["headers"] == {"Authorization": "Bearer internal-token"}


def test_ssh_auto_account_new_user_bootstraps_to_welcome_privileged(admin_session, welcome_dojo):
    token = get_internal_token()
    public_key = generate_public_key("ed25519")

    response = provision(public_key, token)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"]
    assert data["created_user"] is True
    assert data["workspace"]["started"] is True
    assert data["challenge"]["dojo"] == "welcome"
    assert data["challenge"]["module"] == "welcome"
    assert data["challenge"]["challenge"] == "practice"

    wait_for_container(data["user_id"], dojo="welcome", module="welcome", challenge="practice", mode="privileged")


def test_ssh_auto_account_existing_user_without_workspace_starts_welcome_privileged(admin_session, welcome_dojo):
    token = get_internal_token()
    public_key = generate_public_key("ed25519")

    first = provision(public_key, token).json()
    assert first["success"]
    user_id = first["user_id"]
    container_name = f"user_{user_id}"
    container = wait_for_container(user_id, dojo="welcome", module="welcome", challenge="practice", mode="privileged")
    created = container["Created"]

    outer_container = get_outer_container_for(container_name)
    dojo_run("docker", "rm", "-f", container_name, check=False, container=outer_container)

    second_resp = provision(public_key, token)
    assert second_resp.status_code == 200, second_resp.text
    second = second_resp.json()
    assert second["success"]
    assert second["created_user"] is False
    assert second["workspace"]["started"] is True

    restarted = wait_for_container(user_id, dojo="welcome", module="welcome", challenge="practice", mode="privileged")
    assert restarted["Created"] != created


def test_ssh_auto_account_existing_user_with_workspace_does_not_restart(admin_session, welcome_dojo):
    token = get_internal_token()
    public_key = generate_public_key("ed25519")

    first = provision(public_key, token).json()
    assert first["success"]
    user_id = first["user_id"]
    container = wait_for_container(user_id, dojo="welcome", module="welcome", challenge="practice", mode="privileged")
    created = container["Created"]

    second_resp = provision(public_key, token)
    assert second_resp.status_code == 200, second_resp.text
    second = second_resp.json()
    assert second["success"]
    assert second["created_user"] is False
    assert second["workspace"]["started"] is False

    same = wait_for_container(user_id, dojo="welcome", module="welcome", challenge="practice", mode="privileged")
    assert same["Created"] == created
