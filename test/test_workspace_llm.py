import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
WRAPPER = REPOSITORY / "workspace/additional/llm-wrapper.py"
DOJO_CLI = REPOSITORY / "workspace/core/dojo-cli.py"


@pytest.fixture
def llm_gateway():
    state = {
        "status": 200,
        "body": {
            "success": True,
            "base_url": "https://dojo.example.test/llm",
            "key": "test-managed-key",
            "models": ["custom/general", "openai/teaching", "anthropic/teaching"],
        },
        "credentials_issued": 0,
        "usage_reads": 0,
    }

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def dispatch(self):
            path = urlsplit(self.path).path
            if self.headers.get("Authorization") != "Bearer test-workspace-token":
                status, body = 401, {"success": False, "error": "Workspace login required"}
            elif path == "/pwncollege_api/v1/llm/credentials" and self.command == "POST":
                status, body = state["status"], state["body"]
                if status == 200 and isinstance(body, dict) and body.get("key"):
                    state["credentials_issued"] += 1
            elif path == "/pwncollege_api/v1/llm/usage" and self.command == "GET":
                state["usage_reads"] += 1
                status, body = state["status"], state["body"]
            else:
                status, body = 404, {"success": False, "error": "Unknown API endpoint"}
            payload = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["proxy"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def llm_client(tmp_path, llm_gateway):
    client = tmp_path / "client"
    client.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if sys.argv[1:] in (['login', 'status'], ['auth', 'status', '--json']):\n"
        "    sys.exit(0 if os.environ.get('TEST_CLIENT_AUTHENTICATED') else 1)\n"
        "print(json.dumps({'args': sys.argv[1:], 'env': {key: value for key, value in os.environ.items() "
        "if key.startswith(('DOJO_LLM_', 'ANTHROPIC_', 'CLAUDE_CODE_', 'OPENCODE_', 'OPENAI_'))}}))\n"
        "sys.exit(int(os.environ.get('TEST_CLIENT_EXIT', '0')))\n"
    )
    client.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    saved_configs = {
        home / ".codex/config.toml": 'model = "personal-model"\n',
        home / ".claude/settings.json": '{"theme": "dark"}\n',
        home / ".config/opencode/opencode.json": '{"theme": "system"}\n',
    }
    for path, content in saved_configs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    env = {
        "PATH": os.defpath,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "DOJO_AUTH_TOKEN": "test-workspace-token",
        "DOJO_HOST": "dojo.example.test",
        "http_proxy": llm_gateway["proxy"],
        "https_proxy": llm_gateway["proxy"],
        "no_proxy": "",
    }

    def run(client_name, args, **overrides):
        child_env = dict(env, **overrides)
        child_env = {key: value for key, value in child_env.items() if value is not None}
        result = subprocess.run(
            [sys.executable, str(WRAPPER), client_name, str(client), *args],
            env=child_env, cwd=tmp_path, text=True, capture_output=True, timeout=15,
        )
        for path, content in saved_configs.items():
            assert path.read_text() == content
        return result

    return run, env


@pytest.mark.parametrize("client_name", ["codex", "claude", "opencode"])
def test_workspace_llm_configures_clients_without_changing_saved_settings(llm_client, llm_gateway, client_name):
    run, _ = llm_client
    arguments = ["ask", "explain this exercise", "--verbose"]
    result = run(client_name, arguments)
    assert result.returncode == 0, result.stderr
    child = json.loads(result.stdout)
    assert child["args"][-len(arguments):] == arguments
    assert child["env"]["DOJO_LLM_API_KEY"] == "test-managed-key"
    assert llm_gateway["credentials_issued"] == 1

    if client_name == "codex":
        options = child["args"][:-len(arguments)]
        assert len(options) % 2 == 0
        assert options[::2] == ["--config"] * (len(options) // 2)
        settings = dict(option.split("=", 1) for option in options[1::2])
        settings = {key: json.loads(value) for key, value in settings.items()}
        assert settings["model"] == "openai/teaching"
        assert settings["model_provider"] == "dojo"
        assert settings["model_providers.dojo.base_url"] == "https://dojo.example.test/llm/v1"
        assert child["env"][settings["model_providers.dojo.env_key"]] == "test-managed-key"
        assert settings["model_providers.dojo.wire_api"] == "responses"
    elif client_name == "claude":
        assert child["env"]["ANTHROPIC_AUTH_TOKEN"] == "test-managed-key"
        assert child["env"]["ANTHROPIC_BASE_URL"] == "https://dojo.example.test/llm"
        for key in [
            "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL",
        ]:
            assert child["env"][key] == "anthropic/teaching"
    else:
        configuration = json.loads(child["env"]["OPENCODE_CONFIG_CONTENT"])
        assert configuration["model"] == "dojo/custom/general"
        provider = configuration["provider"]["dojo"]
        assert provider["options"]["baseURL"] == "https://dojo.example.test/llm/v1"
        assert provider["options"]["apiKey"] == "{env:DOJO_LLM_API_KEY}"
        assert set(provider["models"]) == set(llm_gateway["body"]["models"])


@pytest.mark.parametrize("client_name,credentials", [
    ("codex", {"OPENAI_API_KEY": "personal-openai-key"}),
    ("codex", {"TEST_CLIENT_AUTHENTICATED": "1"}),
    ("claude", {"ANTHROPIC_API_KEY": "personal-anthropic-key"}),
    ("claude", {"ANTHROPIC_AUTH_TOKEN": "personal-anthropic-token"}),
    ("claude", {"TEST_CLIENT_AUTHENTICATED": "1"}),
    ("opencode", {}),
])
def test_workspace_llm_preserves_personal_authentication(llm_client, llm_gateway, client_name, credentials):
    run, env = llm_client
    if client_name == "opencode":
        auth_path = Path(env["XDG_DATA_HOME"]) / "opencode/auth.json"
        auth_path.parent.mkdir(parents=True)
        auth_path.write_text(json.dumps({"openai": {"type": "api", "key": "personal-openai-key"}}))
    result = run(client_name, ["ask", "question"], **credentials)
    assert result.returncode == 0, result.stderr
    child = json.loads(result.stdout)
    assert child["args"] == ["ask", "question"]
    assert "DOJO_LLM_API_KEY" not in child["env"]
    for key, value in credentials.items():
        if key != "TEST_CLIENT_AUTHENTICATED":
            assert child["env"][key] == value
    assert llm_gateway["credentials_issued"] == 0


@pytest.mark.parametrize("client_name,arguments,overrides", [
    ("codex", ["ask", "question"], {"DOJO_LLM_DISABLE": "1"}),
    ("codex", ["ask", "question"], {"DOJO_AUTH_TOKEN": None}),
    ("codex", ["login"], {}),
    ("claude", ["auth", "login"], {}),
    ("opencode", ["providers"], {}),
])
def test_workspace_llm_passes_through_management_and_opt_out(llm_client, llm_gateway, client_name, arguments, overrides):
    run, _ = llm_client
    result = run(client_name, arguments, TEST_CLIENT_EXIT="7", **overrides)
    assert result.returncode == 7, result.stderr
    child = json.loads(result.stdout)
    assert child["args"] == arguments
    assert "DOJO_LLM_API_KEY" not in child["env"]
    assert llm_gateway["credentials_issued"] == 0


@pytest.mark.parametrize("status,body", [
    (403, {"success": False, "error": "Dojo does not permit managed access"}),
    (503, {"success": False, "error": "Provider temporarily unavailable"}),
    (200, "invalid JSON"),
    (200, {"success": True, "base_url": "https://dojo.example.test/llm", "key": "test-managed-key", "models": []}),
])
def test_workspace_llm_unavailable_credentials_preserve_normal_client_login(llm_client, llm_gateway, status, body):
    llm_gateway.update(status=status, body=body)
    run, _ = llm_client
    result = run("codex", ["ask", "question"])
    assert result.returncode == 0, result.stderr
    child = json.loads(result.stdout)
    assert child["args"] == ["ask", "question"]
    assert "DOJO_LLM_API_KEY" not in child["env"]


def usage_payload(*, empty=False):
    return {
        "success": True,
        "spend": 0 if empty else 1.25,
        "prompt_tokens": 0 if empty else 1200,
        "cache_read_input_tokens": 0 if empty else 100,
        "cache_creation_input_tokens": 0 if empty else 50,
        "completion_tokens": 0 if empty else 300,
        "total_tokens": 0 if empty else 1500,
        "api_requests": 0 if empty else 4,
        "successful_requests": 0 if empty else 3,
        "failed_requests": 0 if empty else 1,
        "models": [] if empty else [{"model": "openai/teaching", "spend": 1.25, "total_tokens": 1500}],
    }


@pytest.mark.parametrize("empty", [False, True])
def test_dojo_llm_usage_reports_spend_tokens_requests_and_models(llm_client, llm_gateway, tmp_path, empty):
    _, env = llm_client
    payload = usage_payload(empty=empty)
    llm_gateway["body"] = payload
    result = subprocess.run(
        [sys.executable, str(DOJO_CLI), "llm-usage"],
        env=env, cwd=tmp_path, text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    lines = {label.strip(): value.strip() for line in result.stdout.splitlines() if ":" in line for label, value in [line.split(":", 1)]}
    assert Decimal(lines["Spend"].removeprefix("$")) == Decimal(str(payload["spend"]))
    for label, metric in {
        "Input tokens": "prompt_tokens", "Cache reads": "cache_read_input_tokens",
        "Cache writes": "cache_creation_input_tokens", "Output tokens": "completion_tokens",
        "Total tokens": "total_tokens", "Requests": "api_requests",
        "Successful": "successful_requests", "Failed": "failed_requests",
    }.items():
        assert int(lines[label].replace(",", "")) == payload[metric]
    for model in payload["models"]:
        row = next(line.split() for line in result.stdout.splitlines() if line.startswith(model["model"]))
        assert Decimal("".join(row[1:-2]).removeprefix("$")) == Decimal(str(model["spend"]))
        assert int(row[-2].replace(",", "")) == model["total_tokens"]


def test_dojo_llm_usage_reports_unavailability_and_requires_workspace_login(llm_client, llm_gateway, tmp_path):
    _, env = llm_client
    llm_gateway.update(status=503, body={"success": False, "error": "Managed LLM access is disabled."})
    result = subprocess.run(
        [sys.executable, str(DOJO_CLI), "llm-usage"],
        env=env, cwd=tmp_path, text=True, capture_output=True, timeout=15,
    )
    assert result.returncode != 0
    assert llm_gateway["body"]["error"] in result.stderr
    assert not result.stdout

    without_login = {key: value for key, value in env.items() if key != "DOJO_AUTH_TOKEN"}
    llm_gateway["usage_reads"] = 0
    result = subprocess.run(
        [sys.executable, str(DOJO_CLI), "llm-usage"],
        env=without_login, cwd=tmp_path, text=True, capture_output=True, timeout=15,
    )
    assert result.returncode != 0
    assert "DOJO_AUTH_TOKEN" in result.stderr
    assert llm_gateway["usage_reads"] == 0
