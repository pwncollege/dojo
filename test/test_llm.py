import textwrap
import uuid

import pytest

from utils import (
    create_dojo_yml,
    db_sql,
    dojo_db_id,
    flask_exec,
    get_user_id,
    login,
    remove_workspace_container,
    remove_workspace_home,
    start_challenge,
    workspace_run,
)


LLM_SERVICE = r'''
import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from flask import current_app
from dojo_plugin.api.v1 import llm

app = current_app._get_current_object()
state = {"keys": {}, "usage": {}, "now": 0, "failure": None}

class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def dispatch(self):
        if state["failure"]:
            return self.respond(state["failure"], {"error": "provider unavailable"})
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if url.path == "/v1/models":
            record = state["keys"].get(bearer)
            if not record or record["expires"] <= state["now"]:
                return self.respond(401, {"error": "key unavailable"})
            return self.respond(200, {"data": [{"id": "dojo-tutor"}, {"id": "dojo-coder"}]})
        if bearer != "test-master-key":
            return self.respond(401, {"error": "provider authentication required"})
        if url.path == "/key/info":
            record = state["keys"].get(query["key"][0])
            return self.respond(200 if record else 404, record or {})
        if url.path in ("/key/generate", "/key/update"):
            key = body["key"]
            if url.path == "/key/generate":
                if key in state["keys"]:
                    return self.respond(409, {"error": "key already exists"})
                state["keys"][key] = dict(body, spend=0)
            elif key not in state["keys"]:
                return self.respond(404, {"error": "key missing"})
            state["keys"][key].update(body)
            state["keys"][key]["expires"] = state["now"] + int(body["duration"].removesuffix("h")) * 3600
            return self.respond(200, {"key": key})
        if url.path == "/user/daily/activity/aggregated":
            return self.respond(200, state["usage"].get(query["user_id"][0], {}))
        return self.respond(404, {"error": "unknown provider endpoint"})

def user_client(cookie, nonce):
    client = app.test_client()
    client.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie)
    client.environ_base["HTTP_CSRF_TOKEN"] = nonce
    return client

@contextlib.contextmanager
def managed_llm():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with patch.multiple(
            llm,
            LITELLM_URL=f"http://127.0.0.1:{server.server_port}",
            LITELLM_MASTER_KEY="test-master-key",
            LITELLM_USER_KEY_SECRET="test-user-key-secret",
            LITELLM_USER_BUDGET_LIMITS=[{"max_budget": 2.5, "budget_duration": "1d"}],
        ):
            yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
'''


def run_llm_case(user, code, *, other=None, cli_token=None):
    name, session = user
    setup = (
        f"user_id = {get_user_id(name)}\n"
        f"client = user_client({session.cookies.get('session')!r}, {session.headers['CSRF-Token']!r})\n"
    )
    if other:
        other_name, other_session = other
        setup += (
            f"other_id = {get_user_id(other_name)}\n"
            f"other_client = user_client({other_session.cookies.get('session')!r}, "
            f"{other_session.headers['CSRF-Token']!r})\n"
        )
    if cli_token:
        setup += f"cli_headers = {{'Authorization': 'Bearer ' + {cli_token!r}}}\n"
    script = LLM_SERVICE + setup + "with managed_llm():\n" + textwrap.indent(textwrap.dedent(code), "    ")
    output = flask_exec(script + "\nprint('LLM-CASE-PASSED')\n")
    assert "LLM-CASE-PASSED" in output.splitlines(), output


@pytest.fixture(scope="module")
def llm_dojo(admin_session, example_dojo):
    dojo = create_dojo_yml(
        f"""
id: llm-{uuid.uuid4().hex[:12]}
name: Managed LLM lessons
type: public
modules:
  - id: lessons
    challenges:
      - id: first
        import:
          dojo: {example_dojo}
          module: hello
          challenge: apple
""",
        session=admin_session,
    )
    db_sql(
        "UPDATE dojos SET data = jsonb_set(data, '{permissions}', '[\"llm\"]') "
        f"WHERE dojo_id = {dojo_db_id(dojo)}"
    )
    return dojo


@pytest.fixture
def llm_other_user():
    name = f"llm{uuid.uuid4().hex[:16]}"
    yield name, login(name, name, register=True)
    remove_workspace_container(name)
    remove_workspace_home(get_user_id(name))


def test_managed_llm_requires_login_and_enabled_configuration(random_user):
    run_llm_case(random_user, """
        anonymous = app.test_client()
        for method, path in [("post", "credentials"), ("get", "usage")]:
            response = getattr(anonymous, method)(
                f"/pwncollege_api/v1/llm/{path}", headers={"Content-Type": "application/json"}
            )
            assert response.status_code == 403, response.get_data(as_text=True)
            with patch.object(llm, "LITELLM_MASTER_KEY", ""):
                response = getattr(client, method)(f"/pwncollege_api/v1/llm/{path}", json={})
            assert response.status_code == 503, response.get_data(as_text=True)
            assert response.get_json()["success"] is False
        assert state["keys"] == {}
    """)


def test_managed_llm_credentials_require_an_active_permitted_dojo(random_user, example_dojo):
    run_llm_case(random_user, """
        response = client.post("/pwncollege_api/v1/llm/credentials", json={})
        assert response.status_code == 403, response.get_data(as_text=True)
        assert response.get_json()["success"] is False
        assert state["keys"] == {}
    """)
    start_challenge(example_dojo, "hello", "apple", session=random_user[1], home=False)
    run_llm_case(random_user, """
        response = client.post("/pwncollege_api/v1/llm/credentials", json={})
        assert response.status_code == 403, response.get_data(as_text=True)
        assert response.get_json()["success"] is False
        assert state["keys"] == {}
    """)


def test_managed_llm_credentials_renew_without_resetting_usage(random_user, llm_other_user, llm_dojo):
    start_challenge(llm_dojo, "lessons", "first", session=random_user[1], home=False)
    start_challenge(llm_dojo, "lessons", "first", session=llm_other_user[1], home=False)
    cli_token = workspace_run("cat /run/dojo/var/auth_token", user=random_user[0], root=True).stdout.strip()
    run_llm_case(random_user, """
        response = client.post("/pwncollege_api/v1/llm/credentials", json={})
        assert response.status_code == 200, response.get_data(as_text=True)
        issued = response.get_json()
        assert issued["success"] is True
        assert issued["models"] == ["dojo-tutor", "dojo-coder"]
        gateway = urlsplit(issued["base_url"])
        assert gateway.scheme == "http"
        assert gateway.netloc == llm.DOJO_HOST
        assert gateway.path == "/llm"
        record = state["keys"][issued["key"]]
        assert record["user_id"] == f"user_{user_id}"
        assert record["budget_limits"] == [{"max_budget": 2.5, "budget_duration": "1d"}]
        other_response = other_client.post("/pwncollege_api/v1/llm/credentials", json={})
        assert other_response.status_code == 200, other_response.get_data(as_text=True)
        other_key = other_response.get_json()["key"]
        assert other_key != issued["key"]
        assert state["keys"][other_key]["user_id"] == f"user_{other_id}"
        original_expiry = record["expires"]
        record["spend"] = 1.25
        state["now"] = original_expiry + 1

        response = client.post("/pwncollege_api/v1/llm/credentials", json={})
        assert response.status_code == 200, response.get_data(as_text=True)
        renewed = response.get_json()
        assert renewed["key"] == issued["key"]
        assert renewed["models"] == issued["models"]
        assert len(state["keys"]) == 2
        assert record["expires"] > state["now"]
        assert record["spend"] == 1.25
        assert record["budget_limits"] == [{"max_budget": 2.5, "budget_duration": "1d"}]

        workspace_client = app.test_client()
        workspace_credentials = workspace_client.post(
            "/pwncollege_api/v1/llm/credentials", headers=cli_headers, json={}
        )
        assert workspace_credentials.status_code == 200, workspace_credentials.get_data(as_text=True)
        assert workspace_credentials.get_json()["key"] == issued["key"]
        usage = workspace_client.get("/pwncollege_api/v1/llm/usage", headers=cli_headers)
        assert usage.status_code == 200, usage.get_data(as_text=True)
        assert usage.get_json()["spend"] == 0
        unauthenticated = workspace_client.get(
            "/pwncollege_api/v1/llm/usage", headers={"Content-Type": "application/json"}
        )
        assert unauthenticated.status_code == 403
    """, other=llm_other_user, cli_token=cli_token)


def test_managed_llm_usage_is_per_user_and_aggregates_models(random_user, llm_other_user):
    run_llm_case(random_user, """
        state["usage"][f"user_{user_id}"] = {
            "metadata": {
                "total_spend": 0.75, "total_prompt_tokens": 12,
                "total_completion_tokens": 8, "total_tokens": 20,
                "total_cache_read_input_tokens": 7, "total_cache_creation_input_tokens": 3,
                "total_api_requests": 3, "total_successful_requests": 2,
                "total_failed_requests": 1,
            },
            "results": [
                {"breakdown": {"models": {
                    "dojo-coder": {"metrics": {"spend": 0.2, "prompt_tokens": 2, "total_tokens": 5, "api_requests": 1, "cache_read_input_tokens": 3, "cache_creation_input_tokens": 1}},
                    "dojo-tutor": {"metrics": {"spend": 0.25, "prompt_tokens": 6, "total_tokens": 10, "api_requests": 1}},
                }}},
                {"breakdown": {"models": {
                    "dojo-coder": {"metrics": {"spend": 0.3, "prompt_tokens": 4, "total_tokens": 5, "api_requests": 1, "cache_read_input_tokens": 4, "cache_creation_input_tokens": 2}},
                }}},
                {"breakdown": None},
            ],
        }
        response = client.get("/pwncollege_api/v1/llm/usage")
        assert response.status_code == 200, response.get_data(as_text=True)
        usage = response.get_json()
        assert usage["success"] is True
        assert usage["spend"] == 0.75
        assert usage["prompt_tokens"] == 12
        assert usage["completion_tokens"] == 8
        assert usage["total_tokens"] == 20
        assert usage["cache_read_input_tokens"] == 7
        assert usage["cache_creation_input_tokens"] == 3
        assert usage["api_requests"] == 3
        assert usage["successful_requests"] == 2
        assert usage["failed_requests"] == 1
        assert [model["model"] for model in usage["models"]] == ["dojo-coder", "dojo-tutor"]
        coder = usage["models"][0]
        assert coder["spend"] == 0.5
        assert coder["prompt_tokens"] == 6
        assert coder["total_tokens"] == 10
        assert coder["api_requests"] == 2
        assert coder["cache_read_input_tokens"] == 7
        assert coder["cache_creation_input_tokens"] == 3

        other_usage = other_client.get("/pwncollege_api/v1/llm/usage")
        assert other_usage.status_code == 200, other_usage.get_data(as_text=True)
        assert other_usage.get_json()["models"] == []
        assert other_usage.get_json()["spend"] == 0
        assert other_usage.get_json()["api_requests"] == 0
        assert state["keys"] == {}
    """, other=llm_other_user)


def test_managed_llm_recovers_after_provider_failure(random_user, llm_dojo):
    start_challenge(llm_dojo, "lessons", "first", session=random_user[1], home=False)
    run_llm_case(random_user, """
        state["failure"] = 503
        for method, path in [("post", "credentials"), ("get", "usage")]:
            response = getattr(client, method)(f"/pwncollege_api/v1/llm/{path}", json={})
            assert response.status_code == 503, response.get_data(as_text=True)
            assert response.get_json()["success"] is False
        assert state["keys"] == {}

        state["failure"] = None
        credentials = client.post("/pwncollege_api/v1/llm/credentials", json={})
        assert credentials.status_code == 200, credentials.get_data(as_text=True)
        assert credentials.get_json()["models"]
        usage = client.get("/pwncollege_api/v1/llm/usage")
        assert usage.status_code == 200, usage.get_data(as_text=True)
        assert usage.get_json()["spend"] == 0
    """)
