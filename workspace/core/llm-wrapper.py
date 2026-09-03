#!/usr/bin/env python3

import json
import os
import pathlib
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def is_management_command(client, args):
    if any(arg in ("-h", "--help", "-V", "--version") for arg in args):
        return True
    command = next((arg for arg in args if not arg.startswith("-")), None)
    if client == "codex":
        return command in ("completion", "login", "logout", "update")
    if client == "claude":
        return command in ("auth", "doctor", "install", "update")
    return command in ("auth", "completion", "providers", "uninstall", "upgrade")


def has_saved_opencode_credentials():
    data_home = pathlib.Path(os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local/share"))
    auth_path = data_home / "opencode/auth.json"
    try:
        return bool(json.loads(auth_path.read_text()))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False


def is_authenticated(client, executable):
    if client == "codex":
        if os.environ.get("OPENAI_API_KEY"):
            return True
        command = [executable, "login", "status"]
    elif client == "claude":
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return True
        command = [executable, "auth", "status", "--json"]
    else:
        return has_saved_opencode_credentials()

    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def managed_credentials():
    token = os.environ.get("DOJO_AUTH_TOKEN")
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    if dojo_host := os.environ.get("DOJO_HOST"):
        headers["Host"] = dojo_host
    request = Request(
        "http://pwn.college:80/pwncollege_api/v1/llm/credentials",
        data=b"",
        method="POST",
        headers=headers,
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as error:
        if error.code not in (401, 403):
            print("Managed dojo LLM access is unavailable; using the client's normal login.", file=sys.stderr)
        return None
    except (URLError, TimeoutError, json.JSONDecodeError):
        print("Managed dojo LLM access is unavailable; using the client's normal login.", file=sys.stderr)
        return None

    required = ("base_url", "key", "default_model", "models")
    if not result.get("success") or not all(result.get(name) for name in required[:3]):
        return None
    if not isinstance(result.get("models"), list):
        return None
    return result


def codex_args(credentials, args):
    base_url = f"{credentials['base_url'].rstrip('/')}/v1"
    settings = {
        "model": credentials["default_model"],
        "model_provider": "dojo",
        "model_providers.dojo.name": "Dojo",
        "model_providers.dojo.base_url": base_url,
        "model_providers.dojo.env_key": "DOJO_LLM_API_KEY",
        "model_providers.dojo.wire_api": "responses",
    }
    overrides = [
        argument
        for name, value in settings.items()
        for argument in ("--config", f"{name}={json.dumps(value)}")
    ]
    return [*overrides, *args]


def configure_opencode(credentials):
    config_dir = pathlib.Path.home() / ".config/dojo"
    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path = config_dir / "opencode.json"
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"dojo/{credentials['default_model']}",
        "provider": {
            "dojo": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Dojo",
                "options": {
                    "apiKey": "{env:DOJO_LLM_API_KEY}",
                    "baseURL": f"{credentials['base_url'].rstrip('/')}/v1",
                },
                "models": {
                    model: {"name": model}
                    for model in credentials["models"]
                    if isinstance(model, str)
                },
            }
        },
    }
    temporary_path = config_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(config, indent=2) + "\n")
    temporary_path.chmod(0o600)
    temporary_path.replace(config_path)
    return str(config_path)


def main():
    client, executable, *args = sys.argv[1:]
    env = os.environ.copy()
    if (
        not os.environ.get("DOJO_LLM_DISABLE")
        and not is_management_command(client, args)
        and not is_authenticated(client, executable)
    ):
        credentials = managed_credentials()
        if credentials is not None:
            env["DOJO_LLM_API_KEY"] = credentials["key"]
            if client == "codex":
                args = codex_args(credentials, args)
            elif client == "claude":
                model = credentials["default_model"]
                env.update({
                    "ANTHROPIC_AUTH_TOKEN": credentials["key"],
                    "ANTHROPIC_BASE_URL": credentials["base_url"],
                    "ANTHROPIC_MODEL": model,
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
                    "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
                    "CLAUDE_CODE_SUBAGENT_MODEL": model,
                })
            else:
                env["OPENCODE_CONFIG"] = configure_opencode(credentials)

    os.execve(executable, [executable, *args], env)


if __name__ == "__main__":
    main()
