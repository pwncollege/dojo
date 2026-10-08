import collections
import json
import pathlib
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@pytest.fixture(scope="module")
def workspace_jquery():
    return (pathlib.Path(__file__).parent / "vendor/jquery-3.5.1.min.js").read_bytes()


@pytest.fixture
def workspace_site(workspace_jquery):
    theme = pathlib.Path(__file__).resolve().parents[1] / "site/theme"
    state = types.SimpleNamespace(generation=1, requests=collections.Counter(), failures={}, pending={})
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": """
            <html><head>{% block stylesheets %}{% endblock %}
            <script src="/jquery.js"></script>
            <script>window.Dojo = {fetch: window.fetch.bind(window)};</script>
            </head><body><nav class="navbar"></nav><main>
            {% block content %}{% endblock %}</main>
            {% block scripts %}{% endblock %}</body></html>
        """}),
        FileSystemLoader(theme / "templates"),
    ]))
    env.filters["markdown"] = lambda text: text
    env.globals["url_for"] = lambda endpoint, path: "/assets/" + path

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body, content_type="text/html"):
            if isinstance(body, dict):
                body, content_type = json.dumps(body), "application/json"
            if isinstance(body, str):
                body = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/jquery.js":
                return self.send(workspace_jquery, "text/javascript")
            if url.path.startswith("/assets/"):
                return self.send((theme / "static" / url.path.removeprefix("/assets/")).read_bytes(), "text/javascript")
            if url.path == "/pwncollege_api/v1/workspace":
                query = parse_qs(url.query)
                service = (query.get("service") or query["port"])[0]
                state.requests[service] += 1
                generation = state.generation
                if gate := state.pending.pop(service, None):
                    gate.wait(timeout=10)
                if failure := state.failures.pop(service, None):
                    return self.send(failure)
                return self.send({
                    "success": True,
                    "iframe_src": f"http://localhost:{self.server.server_port}/session/{service}?generation={generation}",
                })
            if url.path == "/pwncollege_api/v1/docker":
                return self.send({"success": True, "dojo": "test", "module": "test", "challenge": "test", "home": True})
            if url.path.startswith("/session/"):
                return self.send("""
                    <input id="session-state"><button id="interact">Interact</button>
                    <script>
                        window.sessionId = crypto.randomUUID();
                        if (location.pathname.endsWith('/desktop')) {
                            window.addEventListener('beforeunload', event => {
                                event.preventDefault();
                                event.returnValue = 'Disconnect the desktop?';
                            });
                        }
                    </script>
                """)
            if url.path == "/broadcast":
                return self.send("<button>Challenge broadcast</button>")
            interfaces = [
                {"name": "Terminal", "port": 7681},
                {"name": "Desktop", "port": 6080},
                {"name": "Code", "port": 8080},
                {"name": "Custom", "port": 9000},
                {"name": "SSH", "port": ""},
            ]
            challenge = types.SimpleNamespace(
                interfaces=interfaces, description="Challenge description", allow_privileged=True,
                challenge_id=state.generation, name="Test challenge", id="test",
                dojo=types.SimpleNamespace(reference_id="test"), module=types.SimpleNamespace(id="test"),
            )
            initial = next((item for item in interfaces if item["name"].lower() == url.path.split("/")[-1]), interfaces[1])
            return self.send(env.get_template("workspace.html").render(
                challenge=challenge, initial_service=f"{initial['name'].lower()}: {initial['port']}",
                popout="popout" in parse_qs(url.query), practice=False,
            ))

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state.generation += 1
            self.send({"success": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    yield state
    for gate in state.pending.values():
        gate.set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def workspace_button(browser, service):
    return browser.find_element(By.CSS_SELECTOR, f'.workspace-service[data-service^="{service}: "]')


def workspace_frame(browser):
    return WebDriverWait(browser, 10, ignored_exceptions=(StaleElementReferenceException,)).until(lambda driver: next((
        frame for frame in driver.find_elements(By.ID, "workspace-iframe")
        if frame.is_displayed() and "/session/" in frame.get_attribute("src")
    ), False))


def session_state(browser, text=None):
    frame = workspace_frame(browser)
    browser.switch_to.frame(frame)
    field = WebDriverWait(browser, 10).until(EC.presence_of_element_located((By.ID, "session-state")))
    if text is not None:
        field.send_keys(text)
    result = (browser.execute_script("return window.sessionId"), field.get_attribute("value"))
    browser.switch_to.default_content()
    return result


def test_workspace_tabs_preserve_sessions(browser_fixture, workspace_site):
    browser = browser_fixture
    browser.get(workspace_site.url + "/workspace/desktop")
    sessions = {"desktop": session_state(browser, "desktop state")}
    assert workspace_site.requests == {"desktop": 1}
    for service in ("code", "terminal", "custom"):
        workspace_button(browser, service).click()
        sessions[service] = session_state(browser, service + " state")
    for service in ("desktop", "code", "terminal", "custom", "desktop"):
        workspace_button(browser, service).click()
        assert session_state(browser) == sessions[service]
        assert sum(frame.is_displayed() for frame in browser.find_elements(By.CSS_SELECTOR, ".workspace-iframe")) == 1
        assert len(browser.find_elements(By.ID, "workspace-iframe")) == 1
        assert len(browser.find_elements(By.NAME, "workspace")) == 1
    for selector in (".workspace-description-control", '.workspace-service[data-service="ssh: "]'):
        browser.find_element(By.CSS_SELECTOR, selector).click()
        assert not any(frame.is_displayed() for frame in browser.find_elements(By.CSS_SELECTOR, ".workspace-iframe"))
        workspace_button(browser, "desktop").click()
        assert session_state(browser) == sessions["desktop"]
    assert workspace_site.requests == {"desktop": 1, "code": 1, "terminal": 1, "9000": 1}
    assert workspace_frame(browser).get_attribute("allow") == "clipboard-read *; clipboard-write *"


def test_workspace_tabs_restart_discards_sessions(browser_fixture, workspace_site):
    browser = browser_fixture
    browser.get(workspace_site.url + "/workspace/desktop")
    desktop = session_state(browser, "old desktop")
    workspace_button(browser, "terminal").click()
    terminal = session_state(browser, "old terminal")
    old_frames = browser.find_elements(By.CSS_SELECTOR, ".workspace-iframe")
    browser.find_element(By.ID, "challenge-restart").click()
    for frame in old_frames:
        WebDriverWait(browser, 10).until(EC.staleness_of(frame))
    assert session_state(browser) != terminal
    assert "generation=2" in workspace_frame(browser).get_attribute("src")
    assert len(browser.find_elements(By.CSS_SELECTOR, ".workspace-iframe")) == 1
    workspace_button(browser, "desktop").click()
    assert session_state(browser) != desktop
    assert "generation=2" in workspace_frame(browser).get_attribute("src")
    assert workspace_site.requests == {"desktop": 2, "terminal": 2}


def test_workspace_tabs_broadcast_discards_sessions(browser_fixture, workspace_site):
    browser = browser_fixture
    browser.get(workspace_site.url + "/workspace/desktop")
    desktop = session_state(browser, "old desktop")
    workspace_button(browser, "code").click()
    session_state(browser, "old editor")
    old_page = browser.find_element(By.TAG_NAME, "body")
    workspace_window = browser.current_window_handle
    browser.switch_to.new_window("tab")
    browser.get(workspace_site.url + "/broadcast")
    workspace_site.generation = 2
    browser.execute_script("new BroadcastChannel('Challenge-Sync-Channel').postMessage({'challenge-id': 2});")
    browser.switch_to.window(workspace_window)
    WebDriverWait(browser, 10).until(EC.staleness_of(old_page))
    assert session_state(browser)[1] == ""
    assert len(browser.find_elements(By.CSS_SELECTOR, ".workspace-iframe")) == 1
    workspace_button(browser, "desktop").click()
    assert session_state(browser) != desktop
    assert "generation=2" in workspace_frame(browser).get_attribute("src")


@pytest.mark.parametrize("failure", [{"success": False, "error": "Service unavailable"}, "invalid JSON"])
def test_workspace_tabs_failed_load_retries(browser_fixture, workspace_site, failure):
    browser = browser_fixture
    browser.get(workspace_site.url + "/workspace/desktop")
    desktop = session_state(browser, "desktop state")
    workspace_site.failures["code"] = failure
    workspace_button(browser, "code").click()
    WebDriverWait(browser, 10).until(lambda driver: driver.find_element(By.ID, "workspace-notification-banner").text)
    workspace_button(browser, "code").click()
    assert session_state(browser)[1] == ""
    assert workspace_site.requests["code"] == 2
    workspace_button(browser, "desktop").click()
    assert session_state(browser) == desktop


def test_workspace_tabs_pending_loads_survive_switches_and_restart(browser_fixture, workspace_site):
    browser = browser_fixture
    browser.get(workspace_site.url + "/workspace/desktop")
    desktop = session_state(browser, "desktop state")
    gate = threading.Event()
    workspace_site.pending["code"] = gate
    try:
        workspace_button(browser, "code").click()
        WebDriverWait(browser, 10).until(lambda driver: workspace_site.requests["code"] == 1)
        workspace_button(browser, "desktop").click()
        assert session_state(browser) == desktop
        workspace_button(browser, "code").click()
        assert workspace_site.requests["code"] == 1
        browser.find_element(By.ID, "challenge-restart").click()
        assert session_state(browser)[1] == ""
        assert "generation=2" in workspace_frame(browser).get_attribute("src")
        assert workspace_site.requests["code"] == 2
        gate.set()
        browser.switch_to.frame(workspace_frame(browser))
        browser.execute_async_script("setTimeout(arguments[arguments.length - 1], 200)")
        browser.switch_to.default_content()
        assert "generation=2" in workspace_frame(browser).get_attribute("src")
        assert len(browser.find_elements(By.CSS_SELECTOR, ".workspace-iframe")) == 1
    finally:
        gate.set()


def test_workspace_module_service_buttons_still_pop_out(browser_fixture, workspace_site):
    browser = browser_fixture
    browser.get(workspace_site.url + "/workspace/terminal?popout=true")
    terminal = session_state(browser, "inline terminal")
    inline_window = browser.current_window_handle
    for _ in range(2):
        workspace_button(browser, "desktop").click()
        WebDriverWait(browser, 10).until(lambda driver: len(driver.window_handles) == 2)
        popout = next(handle for handle in browser.window_handles if handle != inline_window)
        browser.switch_to.window(popout)
        assert "/workspace/desktop" in browser.current_url
        session_state(browser)
        browser.switch_to.window(inline_window)
    workspace_button(browser, "ssh").click()
    assert browser.find_element(By.CSS_SELECTOR, ".workspace-ssh").is_displayed()
    workspace_button(browser, "ssh").click()
    assert session_state(browser) == terminal
    assert workspace_site.requests == {"terminal": 1, "desktop": 1}
