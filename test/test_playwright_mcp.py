#!/usr/bin/env python3
"""
Test login flow using MCP server
"""
import subprocess
import pytest
import json
import time

from utils import DOJO_HOST

class MockMCPClient:
    def __init__(self, process):
        self.process = process
        self.id = 0

    def call(self, method, params=None):
        self.id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.id,
            "method": method,
            "params": params or {}
        }

        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()

        response_line = self.process.stdout.readline()
        if not response_line:
            raise RuntimeError("MCP server died")

        response = json.loads(response_line)
        if 'error' in response:
            raise RuntimeError(f"MCP error: {response['error']}")

        return response.get('result', {})

    def tool(self, name, **kwargs):
        return self.call("tools/call", {"name": name, "arguments": kwargs})


@pytest.fixture
def mcp():
    """Start MCP server"""
    process = subprocess.Popen(
        ["npx", "--yes", "@playwright/mcp@0.0.32", "--browser", "chromium", "--headless"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=0
    )

    time.sleep(3)

    client = MockMCPClient(process)
    yield client

    client.tool("browser_close")
    process.terminate()
    process.wait(timeout=5)

@pytest.mark.skip(reason="Playwright MCP environment not available")
def test_login_flow(mcp, random_user_name):
    """Test the login flow on pwn.college"""

    result = mcp.tool("browser_navigate", url=f"http://{DOJO_HOST}/login")
    assert 'content' in result
    time.sleep(2)

    snapshot = mcp.tool("browser_snapshot")
    assert 'content' in snapshot
    snapshot_text = json.dumps(snapshot)

    if 'name="name"' in snapshot_text or 'User' in snapshot_text:
        mcp.tool("browser_type",
            element="Username input field",
            ref="input[name='name']",
            text=random_user_name
        )

    if 'name="password"' in snapshot_text or 'Pass' in snapshot_text:
        mcp.tool("browser_type",
            element="Password input field",
            ref="input[name='password']",
            text=random_user_name
        )

    mcp.tool("browser_click",
        element="Login button",
        ref="button[type='submit']"
    )
    time.sleep(3)

    result = mcp.tool("browser_evaluate", function="() => window.location.pathname")
    current_path = result['content'][0]['text']
    assert current_path != "/login", "Should have navigated away from login page"
    mcp.tool("browser_take_screenshot", filename="/tmp/login_test.png")
