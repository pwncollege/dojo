import hashlib
import hmac
import json
import random
import shlex
import socket
import string
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
import requests
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from utils import (
    DOJO_CONTAINER,
    DOJO_URL,
    TEST_DOJOS_LOCATION,
    challenge_flag,
    create_dojo_yml,
    dojo_run,
    get_outer_container_for,
    get_user_id,
    login,
    remove_workspace_container,
    start_challenge,
)

def _workspace_nodes():
    nodes = dojo_run("cat", "/data/workspace_nodes.json", check=False).stdout.strip()
    try:
        return json.loads(nodes) if nodes else {}
    except json.JSONDecodeError:
        return {}


MULTINODE = bool(_workspace_nodes())

DOCKER_API = f"{DOJO_URL}/pwncollege_api/v1/docker"
WORKSPACE_API = f"{DOJO_URL}/pwncollege_api/v1/workspace"

CHALLENGE_IMAGE = "pwncollege/challenge-simple"
NIX_PROFILE = "/nix/var/nix/profiles/dojo-workspace"
INIT_LOG_MARKER = "DOJO_INIT_LOG_MARKER_9F3A"
CHALLENGE_SHADOW_MARKER = "DOJO_CHALLENGE_SHADOW_4B2C"
XPRA_CLIENT_PARAMS = {
    "reconnect": ["1"],
    "clipboard": ["1"],
    "sharing": ["1"],
    "steal": ["1"],
    "toolbar_position": ["novnc"],
    "autohide": ["1"],
    "sound": ["0"],
    "printing": ["0"],
    "file_transfer": ["0"],
    "remote_logging": ["0"],
}
XPRA_HARDENING_ARGUMENTS = [
    "--commands=no",
    "--shell=no",
    "--control=no",
    "--dbus=no",
    "--pulseaudio=no",
    "--audio=no",
    "--webcam=no",
    "--printing=no",
    "--file-transfer=no",
    "--open-files=no",
    "--open-url=no",
    "--start-new-commands=no",
    "--notifications=no",
    "--tray=no",
    "--system-tray=no",
    "--bell=no",
    "--mdns=no",
    "--mmap=no",
    "--rfb-upgrade=no",
    "--sharing=yes",
    "--lock=no",
    "--remote-logging=no",
    "--opengl=no",
]


def random_name(prefix):
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def workspace_exec(user, command, *, root=False):
    container = f"user_{get_user_id(user)}"
    outer = get_outer_container_for(container)
    return dojo_run(
        "docker", "exec", f"--user={0 if root else 1000}", container, "bash", "-c", command,
        container=outer, check=False, stdin=subprocess.DEVNULL,
    )


def workspace_output(user, command, *, root=False):
    result = workspace_exec(user, command, root=root)
    assert result.returncode == 0, (
        f"Expected `{command}` to succeed in the workspace, but it exited {result.returncode}: {result.stderr}"
    )
    return result.stdout.strip()


def container_logs(user):
    container = f"user_{get_user_id(user)}"
    outer = get_outer_container_for(container)
    result = dojo_run("docker", "logs", container, container=outer, check=False)
    return result.stdout + result.stderr


def service_pid(user, service_name, timeout=15):
    deadline = time.time() + timeout
    while True:
        result = workspace_exec(user, f"cat /run/dojo/var/{service_name}.pid")
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        assert time.time() < deadline, f"Service {service_name} never recorded a pid file"
        time.sleep(0.2)


def cleanup_service(user, service_name, pid=None):
    if pid:
        workspace_exec(user, f"kill -9 {pid}", root=True)
    workspace_exec(user, f"rm -rf /run/dojo/var/{service_name.split('/')[0]}", root=True)


def process_cmdline(user, pid):
    return workspace_output(user, f"tr '\\0' ' ' < /proc/{pid}/cmdline")


def workspace_xpra_keyboard_state(user, shift_pressed=None):
    operation = ""
    if shift_pressed is not None:
        operation = (
            f"xtest.xtest_fake_key(shift_keycode, {shift_pressed!r}); "
            "xtest.XFlush(); "
        )
    python_code = (
        "import json; "
        "from xpra.x11.bindings.display_source import init_display_source; "
        "init_display_source(); "
        "from xpra.x11.bindings.keyboard import X11KeyboardBindings; "
        "from xpra.x11.bindings.test import XTestBindings; "
        "keyboard=X11KeyboardBindings(); "
        "xtest=XTestBindings(); "
        "shift_keycode=keyboard.get_keycodes('Shift_L')[0]; "
        f"{operation}"
        "keys_down=keyboard.get_keycodes_down(); "
        "print(json.dumps({'mask': keyboard.query_mask(), "
        "'shift_keycode': shift_keycode, 'shift_down': shift_keycode in keys_down}))"
    )
    command = (
        "xpra_pid=$(cat /run/dojo/var/desktop-service/xpra.pid); "
        "xpra_python=$(readlink -f /proc/$xpra_pid/exe); "
        "xpra_entry=$(tr '\\0' '\\n' < /proc/$xpra_pid/cmdline | sed -n '2p'); "
        "xpra_root=$(dirname \"$(dirname \"$xpra_entry\")\"); "
        "xpra_site=$(find \"$xpra_root/lib\" -path '*/site-packages' -type d | head -1); "
        f"DISPLAY=:0 PYTHONPATH=\"$xpra_site\" \"$xpra_python\" -c {shlex.quote(python_code)}"
    )
    return json.loads(workspace_output(user, command))


def assert_xpra_service_alive(user, service_name, port, expected_pid):
    assert service_pid(user, service_name) == expected_pid, (
        f"Expected {service_name} to retain pid {expected_pid}"
    )
    assert workspace_exec(user, f"kill -0 {expected_pid}").returncode == 0, (
        f"Expected {service_name} pid {expected_pid} to remain alive"
    )
    assert workspace_exec(
        user, f"ss -ltnH 'sport = :{port}' | grep -q ."
    ).returncode == 0, f"Expected {service_name} to remain listening on port {port}"


def assert_xpra_process_arguments(cmdline, expected_arguments):
    for argument in [*XPRA_HARDENING_ARGUMENTS, *expected_arguments]:
        assert argument in cmdline, f"Expected Xpra to be started with {argument}, but got {cmdline!r}"


def assert_xpra_route(iframe_src, port):
    parsed = urlparse(iframe_src)
    assert forwarded_port(iframe_src) == port, f"Expected Xpra on port {port}, but got {iframe_src}"
    assert parsed.path.endswith(f"/xpra/{port}/"), (
        f"Expected Xpra to use the signed transport route root, but got {iframe_src}"
    )
    params = parse_qs(parsed.query)
    assert params == XPRA_CLIENT_PARAMS, f"Expected only the Xpra client settings in the URL, but got {params}"
    assert not {"password", "path", "view_only"} & params.keys(), (
        f"Expected workspace routing to keep desktop credentials out of the client URL, but got {params}"
    )

    requests_to_check = [
        (requests.head, parsed._replace(query="").geturl()),
        (requests.get, iframe_src),
    ]
    for method, url in requests_to_check:
        response = method(url, timeout=30, allow_redirects=True)
        assert response.status_code == 200, (
            f"Expected {method.__name__.upper()} on the signed Xpra route to succeed, got {response.status_code}"
        )


def visible_desktop_canvas(driver):
    canvases = [
        canvas
        for canvas in driver.find_elements(By.CSS_SELECTOR, "canvas")
        if canvas.is_displayed() and canvas.size["width"] >= 320 and canvas.size["height"] >= 200
    ]
    return max(canvases, key=lambda canvas: canvas.size["width"] * canvas.size["height"], default=False)


def connect_xpra_browser(browser, iframe_src):
    browser.get(iframe_src)
    wait = WebDriverWait(browser, 30)
    wait.until(
        lambda driver: driver.execute_script(
            "return typeof client !== 'undefined' && client.connected;"
        )
    )
    canvas = wait.until(visible_desktop_canvas)
    assert browser.execute_script(
        "return Object.values(client.id_to_window).length > 0 && "
        "Object.values(client.id_to_window).every(window => !window.decorated);"
    ), "Expected the remote desktop to fill the workspace without an Xpra window frame"
    return canvas


def assert_xpra_browser_ping(browser, timeout=10):
    ping_token = random.randint(1_500_000_000, 2_000_000_000)
    browser.execute_script("client.send(['ping', arguments[0]]);", ping_token)
    WebDriverWait(browser, timeout).until(
        lambda driver: driver.execute_script(
            "return typeof client !== 'undefined' && client.connected && "
            "client.last_ping_echoed_time === arguments[0];",
            ping_token,
        )
    )


def assert_xpra_info_denied(browser, sensitive_value=None, timeout=10):
    browser.execute_script(
        "client.server_last_info = null;"
        "client.send(['info-request', [], [], []]);"
    )
    WebDriverWait(browser, timeout).until(
        lambda driver: driver.execute_script(
            "return client.server_last_info && client.server_last_info.error;"
        )
    )
    info_response = browser.execute_script(
        "return JSON.stringify(client.server_last_info);"
    )
    if sensitive_value is not None:
        assert sensitive_value not in info_response, (
            "Expected Xpra info denial not to expose the sensitive value"
        )
    assert "not enabled" in info_response, (
        f"Expected Xpra info requests to be denied, got {info_response}"
    )
    return info_response


def wait_for_workspace_path(user, path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if workspace_exec(user, f"test -e {shlex.quote(path)}").returncode == 0:
            return True
        time.sleep(0.25)
    return False


def wait_for_workspace_clipboard(user, expected, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = workspace_exec(
            user,
            "DISPLAY=:0 timeout 2 xclip -selection clipboard -out 2>/dev/null",
        )
        if result.returncode == 0 and result.stdout == expected:
            return True
        time.sleep(0.25)
    return False


def forwarded_container(iframe_src):
    return [part for part in urlparse(iframe_src).path.split("/") if part][1]


def forwarded_port(iframe_src):
    parts = [part for part in urlparse(iframe_src).path.split("/") if part]
    return int(parts[4] if parts[3] == "xpra" else parts[3])


def forwarded_signature(iframe_src):
    return [part for part in urlparse(iframe_src).path.split("/") if part][2]


def replace_forwarded_signature(iframe_src, signature):
    parsed = urlparse(iframe_src)
    parts = parsed.path.split("/")
    parts[3] = signature
    return parsed._replace(path="/".join(parts)).geturl()


def replace_forwarded_port(iframe_src, port):
    parsed = urlparse(iframe_src)
    parts = parsed.path.split("/")
    port_index = 5 if parts[4] == "xpra" else 4
    parts[port_index] = str(port)
    return parsed._replace(path="/".join(parts)).geturl()


def remove_forwarded_transport(iframe_src):
    parsed = urlparse(iframe_src)
    parts = parsed.path.split("/")
    assert parts[4] == "xpra"
    del parts[4]
    return parsed._replace(path="/".join(parts)).geturl()


def replace_forwarded_container(iframe_src, container):
    parsed = urlparse(iframe_src)
    parts = parsed.path.split("/")
    parts[2] = container
    return parsed._replace(path="/".join(parts)).geturl()


def dojo_host():
    return dojo_run("docker", "exec", "nginx", "printenv", "DOJO_HOST").stdout.strip()


@pytest.fixture(scope="module")
def workspace_runtime_dojo(admin_session):
    suffix = "".join(random.choices(string.ascii_lowercase, k=8))
    spec = open(TEST_DOJOS_LOCATION / "workspace_runtime.yml").read().replace(
        "id: workspace-runtime", f"id: workspace-runtime-{suffix}"
    )
    return create_dojo_yml(spec, session=admin_session)


@pytest.fixture(scope="module")
def runtime_workspace(workspace_runtime_dojo):
    name = random_name("wsruntime")
    session = login(name, name, register=True)
    session.get(f"{DOJO_URL}/dojo/{workspace_runtime_dojo}/join/")
    start_challenge(workspace_runtime_dojo, "runtime", "hooked", session=session)
    yield name, session
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def privileged_workspace(privileged_dojo):
    name = random_name("wsrpriv")
    session = login(name, name, register=True)
    session.get(f"{DOJO_URL}/dojo/{privileged_dojo}/join/")
    start_challenge(privileged_dojo, "test", "test", practice=True, session=session)
    yield name, session
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def init_proof(runtime_workspace):
    name, _ = runtime_workspace
    proof = {}
    for line in workspace_output(name, "cat /tmp/init-proof").splitlines():
        key, _, value = line.partition("=")
        proof[key] = value
    return proof


@pytest.fixture(scope="module")
def failed_init_start(workspace_runtime_dojo):
    name = random_name("wsrinitfail")
    session = login(name, name, register=True)
    session.get(f"{DOJO_URL}/dojo/{workspace_runtime_dojo}/join/")
    response = session.post(DOCKER_API, json=dict(
        dojo=workspace_runtime_dojo, module="runtime", challenge="init-failure", practice=False
    ))
    container = f"user_{get_user_id(name)}"
    try:
        outer = get_outer_container_for(container)
    except RuntimeError:
        leftover = None
    else:
        leftover = dojo_run(
            "docker", "inspect", "--format", "{{.State.Status}}", container,
            container=outer, check=False,
        ).stdout.strip()
    yield response, leftover
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def init_test_node():
    candidates = [DOJO_CONTAINER]
    nodes = dojo_run("cat", "/data/workspace_nodes.json", check=False).stdout.strip()
    if nodes:
        try:
            candidates += [f"{DOJO_CONTAINER}-node{node}" for node in json.loads(nodes)]
        except json.JSONDecodeError:
            pass
    for candidate in candidates:
        has_nix = dojo_run("test", "-d", "/data/workspace/nix", container=candidate, check=False).returncode == 0
        has_image = dojo_run("docker", "images", "-q", CHALLENGE_IMAGE, container=candidate, check=False).stdout.strip()
        if has_nix and has_image:
            return candidate
    pytest.skip(f"no node with both /data/workspace/nix and {CHALLENGE_IMAGE} available")


def raw_init_run(node, *, stdin, command, extra_args=""):
    script = (
        f"{stdin} docker run --rm -i -v /data/workspace/nix:/nix:ro {extra_args} "
        f"--entrypoint {NIX_PROFILE}/bin/dojo-init {CHALLENGE_IMAGE} {NIX_PROFILE}/bin/bash -c '{command}'"
    )
    start = time.time()
    result = dojo_run("sh", "-c", script, container=node, check=False, stdin=subprocess.DEVNULL)
    return result, time.time() - start


def test_challenge_init_hook_runs_as_root_after_the_flag_is_installed(
    init_proof, runtime_workspace, workspace_runtime_dojo
):
    name, _ = runtime_workspace
    expected_flag = challenge_flag(workspace_runtime_dojo, "runtime", "hooked", user=name)

    assert init_proof["uid"] == "0", f"Expected /challenge/.init to run as root, but it saw uid {init_proof['uid']}"
    assert init_proof["flag"] == expected_flag, (
        f"Expected /challenge/.init to see the installed flag {expected_flag}, but it saw {init_proof['flag']}"
    )
    assert init_proof["flagmode"] == "400:root", (
        f"Expected /flag to be mode 400 owned by root by the time .init runs, but it was {init_proof['flagmode']}"
    )


def test_challenge_init_hook_resolves_tools_from_the_challenge_image_path(init_proof):
    path = init_proof["path"].split(":")
    assert path[0] == "/run/challenge/bin", f"Expected /run/challenge/bin to lead .init's PATH, but got {path}"
    assert "/usr/bin" in path, f"Expected the challenge image's own PATH entries in .init's PATH, but got {path}"
    assert not any(entry.startswith(("/run/dojo", "/nix")) for entry in path), (
        f"Expected the nix workspace bin dir to be excluded from .init's PATH, but got {path}"
    )
    assert not init_proof["python3"].startswith(("/run/dojo", "/nix")), (
        f"Expected .init to resolve the image's python3, but it resolved {init_proof['python3']}"
    )


def test_challenge_init_log_is_root_only_and_mirrored_to_the_container_log(runtime_workspace):
    name, _ = runtime_workspace

    assert workspace_output(name, "stat -c '%a %U' /run/dojo/var/root/init.log", root=True) == "600 root", (
        "Expected the challenge init log to be mode 600 owned by root"
    )

    denied = workspace_exec(name, "cat /run/dojo/var/root/init.log")
    assert denied.returncode != 0, "Expected the hacker user to be unable to read the challenge init log"
    assert "Permission denied" in denied.stderr, f"Expected a permission error, but got {denied.stderr!r}"

    assert INIT_LOG_MARKER in container_logs(name), (
        "Expected the challenge init output to be echoed to the container log for operators"
    )


def test_challenge_init_failure_fails_the_container_start(failed_init_start):
    response, leftover = failed_init_start
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    assert response.json() == {"success": False, "error": "Docker failed"}, (
        f"Expected a failing /challenge/.init to fail the start, but got {response.json()}"
    )
    assert leftover is None, (
        f"Expected no workspace container after a failed start, but one was left in state {leftover!r}"
    )


def test_challenge_init_hook_is_capped_at_thirty_seconds(init_test_node):
    dojo_run(
        "sh", "-c",
        "rm -rf /tmp/wsr-slow-init && mkdir -p /tmp/wsr-slow-init && "
        "printf '#!/bin/sh\\nsleep 300\\n' > /tmp/wsr-slow-init/.init && chmod 755 /tmp/wsr-slow-init/.init",
        container=init_test_node,
    )
    result, elapsed = raw_init_run(
        init_test_node,
        stdin="echo 'pwn.college{slow}' |",
        command="true",
        extra_args="-v /tmp/wsr-slow-init:/challenge:ro",
    )
    assert "DOJO_INIT_FAILED:Challenge initialization error." in result.stdout, (
        f"Expected a hanging /challenge/.init to be reported as an initialization error, but got {result.stdout!r}"
    )
    assert 20 < elapsed < 50, (
        f"Expected the .init hook to be killed by its 30s cap, but the run took {elapsed:.1f}s"
    )
    dojo_run("rm", "-rf", "/tmp/wsr-slow-init", container=init_test_node, check=False)


def test_dojo_init_requires_a_flag_on_stdin_within_five_seconds(init_test_node):
    result, elapsed = raw_init_run(
        init_test_node,
        stdin="F=/tmp/wsr-fifo.$$; mkfifo -m 600 $F; exec 3<>$F; rm -f $F;",
        command="true",
    )
    lines = [line for line in result.stdout.splitlines() if line.startswith("DOJO_INIT_")]
    assert lines == ["DOJO_INIT_INITIALIZED", "DOJO_INIT_FAILED:Flag initialization error."], (
        f"Expected dojo-init to announce initialization and then time out waiting for the flag, but got {lines}"
    )
    assert result.returncode != 0, "Expected dojo-init to exit nonzero when no flag arrives"
    assert elapsed < 20, f"Expected the flag handshake to time out in about 5 seconds, but it took {elapsed:.1f}s"


def test_dojo_init_installs_the_flag_read_only_to_root(init_test_node):
    result, _ = raw_init_run(
        init_test_node,
        stdin="echo 'pwn.college{handshake}' |",
        command="stat -c %a:%U /flag; cat /flag",
    )
    assert "DOJO_INIT_READY" in result.stdout, f"Expected the workspace to become ready, but got {result.stdout!r}"
    assert "400:root" in result.stdout, f"Expected /flag to be installed mode 400 root, but got {result.stdout!r}"
    assert "pwn.college{handshake}" in result.stdout, (
        f"Expected the flag fed on stdin to land in /flag, but got {result.stdout!r}"
    )


def test_workspace_profile_symlink_farm_exposes_the_toolchain(runtime_workspace):
    name, _ = runtime_workspace

    assert workspace_output(name, "readlink /run/current-system/sw") == NIX_PROFILE, (
        f"Expected /run/current-system/sw to point at {NIX_PROFILE}"
    )

    for entry in ["bin", "etc", "share", "lib", "suid"]:
        target = workspace_output(name, f"readlink /run/dojo/{entry}")
        assert target == f"/run/current-system/sw/{entry}", (
            f"Expected /run/dojo/{entry} to be a symlink into the active profile, but it pointed at {target}"
        )
        resolved = workspace_output(name, f"readlink -f /run/dojo/{entry}")
        assert resolved.startswith("/nix/store/"), (
            f"Expected /run/dojo/{entry} to resolve into the nix store, but it resolved to {resolved}"
        )

    for binary in ["bash", "sh", "sudo", "exec-suid", "dojo", "dojo-service", "dojo-init",
                   "ssh-entrypoint", "scp", "dojo-terminal", "dojo-code", "dojo-desktop",
                   "dojo-desktop-view", "xpra"]:
        assert workspace_exec(name, f"test -x /run/dojo/bin/{binary}").returncode == 0, (
            f"Expected /run/dojo/bin/{binary} to exist and be executable in the workspace"
        )

    assert workspace_exec(name, "test -x /run/dojo/libexec/sftp-server").returncode == 0, (
        "Expected the workspace SSH file-transfer server to exist and be executable"
    )


def test_workspace_synthesizes_passwd_and_group_entries(runtime_workspace):
    name, _ = runtime_workspace

    assert workspace_output(name, "bash -lc 'getent passwd hacker'") == \
        "hacker:x:1000:1000:hacker:/home/hacker:/run/dojo/bin/bash", "Unexpected synthesized hacker passwd entry"
    assert workspace_output(name, "bash -lc 'getent group hacker'") == "hacker:x:1000:", (
        "Expected the hacker group to be gid 1000"
    )
    assert workspace_output(name, "grep -c '^root:' /etc/passwd") == "2", (
        "Expected dojo-init to append its own root entry after the image's"
    )
    assert workspace_output(name, "bash -lc 'getent passwd root'").endswith("/bin/bash"), (
        "Expected the challenge image's root entry to win name resolution over the appended dojo entry"
    )


def test_image_bin_sh_survives_and_challenge_bin_shadows_the_workspace(runtime_workspace):
    name, _ = runtime_workspace

    resolved_sh = workspace_output(name, "readlink -f /bin/sh")
    assert not resolved_sh.startswith(("/run/dojo", "/nix")), (
        f"Expected the image's own /bin/sh to be left alone, but it resolved to {resolved_sh}"
    )

    assert workspace_output(name, "readlink /run/challenge/bin") == "/challenge/bin", (
        "Expected /run/challenge/bin to be symlinked to the challenge's bin directory"
    )

    assert workspace_output(name, "bash -lc 'command -v hostname'") == "/run/challenge/bin/hostname", (
        "Expected /run/challenge/bin to precede /run/dojo/bin on the login PATH"
    )
    assert workspace_output(name, "bash -lc hostname") == CHALLENGE_SHADOW_MARKER, (
        "Expected the challenge's own hostname to shadow the workspace tool"
    )


def test_login_shell_gets_the_dojo_workspace_profile_environment(runtime_workspace):
    name, _ = runtime_workspace

    values = workspace_output(
        name,
        "bash -lc 'printf \"%s\\n\" \"$PATH\" \"$LANG\" \"$MANPATH\" \"$SSL_CERT_FILE\" \"$TERMINFO\" \"$PROMPT_COMMAND\"'"
    ).splitlines()
    path, lang, manpath, ssl_cert_file, terminfo, prompt_command = values

    assert path.startswith("/run/challenge/bin:/run/dojo/bin:"), f"Unexpected login PATH: {path}"
    assert lang == "C.UTF-8", f"Expected LANG=C.UTF-8, but got {lang}"
    assert manpath == "/run/dojo/share/man:", f"Expected the workspace manpath with a trailing colon, but got {manpath}"
    assert ssl_cert_file == "/run/dojo/etc/ssl/certs/ca-bundle.crt", f"Unexpected SSL_CERT_FILE: {ssl_cert_file}"
    assert terminfo == "/run/dojo/share/terminfo", f"Unexpected TERMINFO: {terminfo}"
    assert prompt_command.startswith("history -a;"), (
        f"Expected the login shell to append history on every prompt, but PROMPT_COMMAND was {prompt_command!r}"
    )

    assert workspace_output(name, "readlink /etc/profile.d/99-dojo-workspace.sh") == \
        "/run/dojo/etc/profile.d/99-dojo-workspace.sh", "Expected the profile snippet to be linked out of /run/dojo"

    assert workspace_exec(name, f"test -d {terminfo}").returncode == 0, f"Expected {terminfo} to exist"
    subject = workspace_exec(name, f"openssl x509 -in {ssl_cert_file} -noout -subject")
    assert subject.returncode == 0 and subject.stdout.strip(), (
        f"Expected SSL_CERT_FILE to be a usable CA bundle, but openssl failed: {subject.stderr!r}"
    )


def test_workspace_auth_token_is_a_container_credential(privileged_workspace):
    name, _ = privileged_workspace

    assert workspace_output(name, "stat -c %a /run/dojo/var") == "1777", (
        "Expected /run/dojo/var to be world writable so any workspace uid can use it"
    )
    assert workspace_output(name, "stat -c '%a %U' /run/dojo/var/auth_token") == "644 root", (
        "Expected the container auth token to be world readable and root owned"
    )

    borrowed = workspace_exec(
        name, "sudo -u nobody sh -c 'DOJO_AUTH_TOKEN=$(cat /run/dojo/var/auth_token) dojo whoami'"
    )
    assert borrowed.returncode == 0, f"Expected an unprivileged uid to be able to use the token: {borrowed.stderr}"
    assert name in borrowed.stdout, (
        f"Expected the token to identify the owning user {name}, but got {borrowed.stdout!r}"
    )


def test_suid_bit_is_set_only_on_the_manifest_paths(runtime_workspace):
    name, _ = runtime_workspace

    manifest = workspace_output(name, "cat /run/dojo/suid").split()
    assert manifest, "Expected the workspace profile to ship a suid manifest"
    for path in manifest:
        mode_owner = workspace_output(name, f"stat -c '%a %U' {path}")
        mode, owner = mode_owner.split()
        assert int(mode, 8) & 0o4000, f"Expected {path} to carry the setuid bit, but its mode was {mode}"
        assert owner == "root", f"Expected {path} to be owned by root, but it was owned by {owner}"

    setuid_binaries = set(workspace_output(
        name, r"find -L /run/dojo/bin -maxdepth 1 -perm -4000 -printf '%f\n'"
    ).split())
    assert setuid_binaries == {"sudo", "exec-suid"}, (
        f"Expected only sudo and exec-suid to be setuid in the workspace, but found {setuid_binaries}"
    )


def test_sudo_shim_resolves_users_and_rewrites_the_environment(privileged_workspace):
    name, _ = privileged_workspace

    assert workspace_output(name, "cat /run/dojo/sys/workspace/privileged") == "1", (
        "Expected a practice-mode workspace to be flagged privileged"
    )
    assert workspace_output(name, "sudo whoami") == "root", "Expected sudo with no user to switch to root"
    assert workspace_output(name, "sudo -u hacker id -u") == "1000", "Expected sudo to resolve a user by name"
    assert workspace_output(name, "sudo -u 1000 sh -c 'echo $HOME $USER $SHELL'") == \
        "/home/hacker hacker /run/dojo/bin/bash", "Expected sudo to rewrite HOME/USER/SHELL from the passwd entry"


def test_sudo_shim_rejects_unknown_users_and_commands(privileged_workspace):
    name, _ = privileged_workspace

    unknown_user = workspace_exec(name, "sudo -u nosuchuser id")
    assert unknown_user.returncode == 1, f"Expected exit code 1, but got {unknown_user.returncode}"
    assert "sudo: unknown user: nosuchuser" in unknown_user.stderr, (
        f"Expected an unknown user error, but got {unknown_user.stderr!r}"
    )

    unknown_command = workspace_exec(name, "sudo definitelynotacommand")
    assert unknown_command.returncode == 1, f"Expected exit code 1, but got {unknown_command.returncode}"
    assert "sudo: definitelynotacommand: command not found" in unknown_command.stderr, (
        f"Expected a command-not-found error, but got {unknown_command.stderr!r}"
    )


def test_dojo_service_start_is_idempotent(runtime_workspace):
    name, _ = runtime_workspace
    service = "wsr-idempotent/sleeper"
    command = "/run/dojo/bin/sleep 3117"
    pid = None
    try:
        assert workspace_exec(name, f"dojo-service start {service} {command}").returncode == 0, (
            "Expected dojo-service start to succeed"
        )
        pid = service_pid(name, service)
        assert workspace_exec(name, f"test -f /run/dojo/var/{service}.log").returncode == 0, (
            "Expected the nested service name to create its log file"
        )
        assert workspace_exec(name, f"kill -0 {pid}").returncode == 0, (
            f"Expected the recorded pid {pid} to be a live process"
        )

        again = workspace_exec(name, f"dojo-service start {service} {command}")
        assert f"Service {service} is already running." in again.stdout, (
            f"Expected a second start to be refused, but got {again.stdout!r}"
        )
        assert workspace_output(name, f"pgrep -c -f '^{command}$'") == "1", (
            "Expected the second start to spawn no additional process"
        )

        assert workspace_output(name, f"dojo-service status {service}") == \
            f"Service {service} is running with PID {pid}.", "Unexpected dojo-service status output"
        assert f"is running with PID {pid}" in workspace_output(name, "dojo-service status wsr-idempotent"), (
            "Expected the directory form of dojo-service status to recurse into nested services"
        )
    finally:
        cleanup_service(name, service, pid)


def test_dojo_service_kill_terminates_a_service_that_ignores_sigterm(runtime_workspace):
    name, _ = runtime_workspace
    service = "wsr-kill/stubborn"
    pid = None
    try:
        workspace_exec(
            name, f"dojo-service start {service} /run/dojo/bin/bash -c 'trap \"\" TERM; sleep 3119'"
        )
        pid = service_pid(name, service)
        workspace_exec(name, f"dojo-service kill {service}")
        time.sleep(1)
        assert workspace_exec(name, f"kill -0 {pid}").returncode != 0, (
            f"Expected `dojo-service kill` to force-kill pid {pid}, but it survived SIGTERM and is unmanaged now"
        )
    finally:
        cleanup_service(name, service, pid)


def test_terminal_service_contract(runtime_workspace):
    name, session = runtime_workspace

    response = session.get(f"{WORKSPACE_API}?service=terminal")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    result = response.json()
    assert result["success"] and result["active"], f"Expected an active terminal workspace, but got {result}"
    assert forwarded_port(result["iframe_src"]) == 7681, f"Expected the terminal on port 7681: {result['iframe_src']}"

    pid = service_pid(name, "terminal-service/ttyd")
    cmdline = process_cmdline(name, pid)
    assert "ttyd" in cmdline, f"Expected the recorded pid to be ttyd, but its cmdline was {cmdline!r}"
    for argument in ["--port 7681", "--interface 0.0.0.0", "--writable", "--login"]:
        assert argument in cmdline, f"Expected ttyd to be started with {argument}, but its cmdline was {cmdline!r}"
    assert workspace_output(name, f"awk '/^Uid:/ {{print $2}}' /proc/{pid}/status") == "1000", (
        "Expected on-demand services to run as the hacker user"
    )

    assert workspace_output(name, "curl -fs -o /dev/null -w '%{http_code}' localhost:7681") == "200", (
        "Expected ttyd to be answering on port 7681 once the workspace API returned"
    )


def test_code_service_contract(runtime_workspace):
    name, session = runtime_workspace

    response = session.get(f"{WORKSPACE_API}?service=code")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    result = response.json()
    assert result["success"] and result["active"], f"Expected an active code workspace, but got {result}"
    assert forwarded_port(result["iframe_src"]) == 8080, f"Expected code-server on port 8080: {result['iframe_src']}"

    pid = service_pid(name, "code-service/code-server")
    cmdline = process_cmdline(name, pid)
    for argument in ["--auth=none", "--bind-addr=0.0.0.0:8080", "--disable-telemetry", "--config=/dev/null"]:
        assert argument in cmdline, f"Expected code-server to be started with {argument}, but got {cmdline!r}"
    cmdline_parts = cmdline.split()
    extensions_dir = next(
        (part.split("=", 1)[1] for part in cmdline_parts if part.startswith("--extensions-dir=")), None
    )
    if extensions_dir is None and "--extensions-dir" in cmdline_parts:
        extensions_dir = cmdline_parts[cmdline_parts.index("--extensions-dir") + 1]
    assert extensions_dir and extensions_dir.startswith("/nix/store/"), (
        f"Expected the packaged extension directory to be used, but got {extensions_dir}"
    )

    assert workspace_output(name, "curl -fs -o /dev/null -w '%{http_code}' localhost:8080") == "200", (
        "Expected code-server to be answering on port 8080 once the workspace API returned"
    )


def test_desktop_service_serializes_startup_and_migrates_a_live_novnc_runtime(
    runtime_workspace, random_user_session
):
    name, session = runtime_workspace
    marker = random_name("legacy-novnc-")
    workspace_output(
        name,
        "mkdir -p /tmp/legacy-novnc && "
        f"printf %s {shlex.quote(marker)} > /tmp/legacy-novnc/index.html && "
        "dojo-service start desktop-service/Xvnc /run/dojo/bin/sleep 3119 && "
        "dojo-service start desktop-service/xfce4-session /run/dojo/bin/sleep 3121 && "
        "dojo-service start desktop-service/novnc python3 -m http.server 6080 "
        "--bind 0.0.0.0 --directory /tmp/legacy-novnc",
    )
    legacy_pids = [
        service_pid(name, service)
        for service in (
            "desktop-service/Xvnc",
            "desktop-service/xfce4-session",
            "desktop-service/novnc",
        )
    ]
    workspace_output(
        name,
        "touch /run/dojo/var/desktop-service/Xvnc.sock "
        "/run/dojo/var/desktop-service/Xvnc.passwd",
    )
    deadline = time.time() + 15
    while workspace_exec(name, "curl -fs http://localhost:6080/").returncode != 0:
        assert time.time() < deadline, "Expected the simulated noVNC service to become ready"
        time.sleep(0.2)

    generic_response = session.get(f"{WORKSPACE_API}?port=6080")
    assert generic_response.status_code == 200 and generic_response.json()["success"]
    generic_src = generic_response.json()["iframe_src"]
    assert forwarded_port(generic_src) == 6080 and "/xpra/" not in urlparse(generic_src).path
    proxied_generic = requests.get(generic_src, timeout=30, allow_redirects=True)
    assert proxied_generic.status_code == 200 and marker in proxied_generic.text, (
        "Expected a generic port-6080 route to retain plaintext HTTP forwarding"
    )

    token = workspace_output(name, "cat /run/dojo/var/auth_token")
    view_password = hmac.HMAC(token.encode(), b"desktop-view", hashlib.sha256).hexdigest()
    with ThreadPoolExecutor(max_workers=2) as executor:
        desktop_future = executor.submit(
            session.get, f"{WORKSPACE_API}?service=desktop", timeout=260
        )
        view_future = executor.submit(
            random_user_session.get,
            WORKSPACE_API,
            params={"user": get_user_id(name), "service": "desktop"},
            headers={"X-Workspace-Password": view_password},
            timeout=260,
        )
        desktop_response = desktop_future.result()
        view_response = view_future.result()
    assert desktop_response.status_code == 200 and desktop_response.json()["success"], (
        f"Expected the desktop request to migrate the legacy runtime: {desktop_response.text}"
    )
    assert view_response.status_code == 200 and view_response.json()["success"], (
        f"Expected the concurrent view request to succeed: {view_response.text}"
    )
    assert_xpra_route(desktop_response.json()["iframe_src"], 6080)
    assert_xpra_route(view_response.json()["iframe_src"], 6081)
    assert workspace_output(
        name, "pgrep -fc '[x]pra monitor :0'"
    ) == "1", "Expected concurrent startup to leave exactly one tracked monitor server"
    for legacy_pid in legacy_pids:
        assert workspace_exec(name, f"kill -0 {legacy_pid}").returncode != 0, (
            f"Expected migrated legacy pid {legacy_pid} to be terminated"
        )
    assert workspace_exec(
        name,
        "test ! -e /run/dojo/var/desktop-service/Xvnc.pid && "
        "test ! -e /run/dojo/var/desktop-service/novnc.pid && "
        "test ! -e /run/dojo/var/desktop-service/Xvnc.sock && "
        "test ! -e /run/dojo/var/desktop-service/Xvnc.passwd",
    ).returncode == 0, "Expected the lazy migration to remove legacy noVNC runtime state"


def test_desktop_service_contract(runtime_workspace, random_user_session):
    name, session = runtime_workspace

    response = session.get(f"{WORKSPACE_API}?service=desktop")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    result = response.json()
    assert result["success"] and result["active"], f"Expected an active desktop workspace, but got {result}"
    assert_xpra_route(result["iframe_src"], 6080)

    token = workspace_output(name, "cat /run/dojo/var/auth_token")
    assert token not in result["iframe_src"], (
        f"Expected the signed workspace route to keep the container token out of the URL, got {result['iframe_src']}"
    )

    for service in ["xpra", "xfce4-session"]:
        pid = service_pid(name, f"desktop-service/{service}")
        assert workspace_exec(name, f"kill -0 {pid}").returncode == 0, (
            f"Expected the desktop's {service} (pid {pid}) to be running"
        )

    xpra_cmdline = process_cmdline(name, service_pid(name, "desktop-service/xpra"))
    assert " monitor :0 " in f" {xpra_cmdline}", f"Expected an Xpra monitor server, but got {xpra_cmdline!r}"
    assert workspace_exec(
        name,
        "! tr '\\0' '\\n' < /proc/$(cat /run/dojo/var/desktop-service/xpra.pid)/environ "
        "| grep -Eq '^(DOJO_AUTH_TOKEN|DOJO_XPRA_[^=]+)='",
    ).returncode == 0, "Expected the Xpra server not to inherit workspace credentials"
    assert workspace_exec(
        name,
        "tr '\\0' '\\n' < /proc/$(cat /run/dojo/var/desktop-service/xpra.pid)/environ "
        "| grep -qx 'XPRA_UNAUTHENTICATED_HELLO_REQUESTS='",
    ).returncode == 0, "Expected every Xpra protocol request to require route authentication"
    desktop_route_password = "/run/dojo/var/desktop-service/xpra-route-password"
    desktop_signature = forwarded_signature(result["iframe_src"])
    assert workspace_exec(
        name,
        f"test \"$(cat {desktop_route_password})\" = {shlex.quote(desktop_signature)} && "
        f"test \"$(stat -c %a {desktop_route_password})\" = 600 && "
        f"test \"$(wc -c < {desktop_route_password})\" = 44",
    ).returncode == 0, "Expected Xpra's 0600 password file to contain only the signed route credential"
    tls_certificate = "/run/dojo/var/desktop-tls/certificate.pem"
    tls_private_key = "/run/dojo/var/desktop-tls/private-key.pem"
    container_id = forwarded_container(result["iframe_src"]).split(":", 1)[0]
    assert workspace_exec(
        name,
        f"test \"$(stat -c %a {tls_certificate})\" = 600 && "
        f"test \"$(stat -c %a {tls_private_key})\" = 600 && "
        f"openssl x509 -in {tls_certificate} -noout -checkhost {shlex.quote(container_id)} && "
        f"test \"$(openssl x509 -in {tls_certificate} -pubkey -noout | sha256sum)\" = "
        f"\"$(openssl pkey -in {tls_private_key} -pubout | sha256sum)\"",
    ).returncode == 0, "Expected a matching 0600 Xpra certificate and container-specific private key"
    assert_xpra_process_arguments(xpra_cmdline, [
        "--daemon=no",
        "--attach=no",
        "--use-display=no",
        "--bind=none",
        "--bind-wss=0.0.0.0:6080,auth=file,filename=/run/dojo/var/desktop-service/"
        "xpra-route-password,verify-username=no,info=no,exit=no,stop=no,detach=no",
        f"--ssl-cert={tls_certificate}",
        f"--ssl-key={tls_private_key}",
        "--html=/nix/store/",
        "xpra-html5-20/share/xpra/www",
        "--http-scripts=off",
        "--ssl-upgrade=no",
        "--source=no",
        "--resize-display=yes:1024x768",
        "--pixel-depth=24",
        "--input-devices=xtest",
        "/bin/Xorg -novtswitch",
        "xpra-xorg.conf",
        "-extension GLX",
        "--clipboard-direction=both",
    ])
    xpra_arguments = shlex.split(xpra_cmdline)
    xorg_config = xpra_arguments[xpra_arguments.index("-config") + 1]
    assert workspace_exec(
        name,
        f"grep -q '^  VideoRam 65536$' {shlex.quote(xorg_config)} && "
        f"test \"$(grep -c '^    Virtual 4096 2160$' {shlex.quote(xorg_config)})\" -eq 4",
    ).returncode == 0, f"Expected a 4096x2160 Xpra framebuffer cap in {xorg_config}"

    view_password = hmac.HMAC(token.encode(), b"desktop-view", hashlib.sha256).hexdigest()
    clipboard_sentinel = f"xpra-pre-view-clipboard-{random_name('')}"
    clipboard_pid = f"/tmp/xpra-pre-view-clipboard-{random_name('')}.pid"
    workspace_exec(
        name,
        f"printf %s {shlex.quote(clipboard_sentinel)} | "
        "DISPLAY=:0 timeout 60 xclip -selection clipboard -in >/dev/null 2>&1 & "
        f"echo $! > {shlex.quote(clipboard_pid)}",
    )
    assert wait_for_workspace_clipboard(name, clipboard_sentinel), (
        "Expected the owner clipboard sentinel to be established before view-only Xpra starts"
    )
    view_response = random_user_session.get(
        WORKSPACE_API,
        params={"user": get_user_id(name), "service": "desktop"},
        headers={"X-Workspace-Password": view_password},
    )
    assert view_response.status_code == 200, (
        f"Expected the view-only desktop share to start, got {view_response.status_code}"
    )
    view_result = view_response.json()
    assert view_result["success"] and view_result["active"], (
        f"Expected an active view-only desktop workspace, but got {view_result}"
    )
    assert view_password not in view_result["iframe_src"], (
        f"Expected the desktop share password to be exchanged only through the API, got {view_result['iframe_src']}"
    )
    assert_xpra_route(view_result["iframe_src"], 6081)
    assert wait_for_workspace_clipboard(name, clipboard_sentinel, timeout=3), (
        "Expected starting the to-client view service not to steal the owner's clipboard selection"
    )
    workspace_exec(
        name,
        f"kill \"$(cat {shlex.quote(clipboard_pid)})\" 2>/dev/null || true; "
        f"rm -f {shlex.quote(clipboard_pid)}",
    )

    view_pid = service_pid(name, "desktop-view-service/xpra")
    assert workspace_exec(name, f"kill -0 {view_pid}").returncode == 0, (
        f"Expected the view-only Xpra server (pid {view_pid}) to be running"
    )
    view_cmdline = process_cmdline(name, view_pid)
    assert " shadow :0 " in f" {view_cmdline}", f"Expected an Xpra shadow server, but got {view_cmdline!r}"
    assert workspace_exec(
        name,
        f"tr '\\0' '\\n' < /proc/{view_pid}/environ | grep -qx 'XPRA_SYNC_ICC=0'",
    ).returncode == 0, "Expected view-only Xpra clients to be unable to mutate the shared display ICC profile"
    assert workspace_exec(
        name,
        f"! tr '\\0' '\\n' < /proc/{view_pid}/environ "
        "| grep -Eq '^(DOJO_AUTH_TOKEN|DOJO_XPRA_[^=]+)='",
    ).returncode == 0, "Expected the view-only Xpra server not to inherit workspace credentials"
    assert workspace_exec(
        name,
        f"tr '\\0' '\\n' < /proc/{view_pid}/environ | grep -qx 'XPRA_UNAUTHENTICATED_HELLO_REQUESTS='",
    ).returncode == 0, "Expected every view-only Xpra request to require route authentication"
    view_route_password = "/run/dojo/var/desktop-view-service/xpra-route-password"
    view_signature = forwarded_signature(view_result["iframe_src"])
    assert workspace_exec(
        name,
        f"test \"$(cat {view_route_password})\" = {shlex.quote(view_signature)} && "
        f"test \"$(stat -c %a {view_route_password})\" = 600 && "
        f"test \"$(wc -c < {view_route_password})\" = 44",
    ).returncode == 0, "Expected view-only Xpra to use only its signed 6081 route credential"
    view_xpra_entry = shlex.split(view_cmdline)[1]
    view_xpra_root = view_xpra_entry.rsplit("/bin/", 1)[0]
    assert workspace_exec(
        name,
        f"icc_module=$(find {shlex.quote(view_xpra_root)}/lib -path "
        "'*/xpra/x11/subsystem/icc.py' -type f -print -quit); "
        "grep -A3 '^    def reset_icc_profile' \"$icc_module\" | grep -q 'if not SYNC_ICC:'",
    ).returncode == 0, "Expected disabled ICC sync to preserve the owner's root profile on viewer disconnect"
    assert workspace_exec(
        name,
        f"proxy_module=$(find {shlex.quote(view_xpra_root)}/lib -path "
        "'*/xpra/x11/selection/proxy.py' -type f -print -quit); "
        "grep -A3 '^    def claim(self)' \"$proxy_module\" | grep -q 'if not self._can_receive:'",
    ).returncode == 0, "Expected to-client clipboard proxies not to steal the owner's X11 selections"
    assert_xpra_process_arguments(view_cmdline, [
        "--daemon=no",
        "--attach=no",
        "--use-display=yes",
        "--bind=none",
        "--bind-wss=0.0.0.0:6081,auth=file,filename=/run/dojo/var/desktop-view-service/"
        "xpra-route-password,verify-username=no,info=no,exit=no,stop=no,detach=no",
        f"--ssl-cert={tls_certificate}",
        f"--ssl-key={tls_private_key}",
        "--html=/nix/store/",
        "xpra-html5-20/share/xpra/www",
        "--http-scripts=off",
        "--ssl-upgrade=no",
        "--source=no",
        "--readonly=yes",
        "--resize-display=no",
        "--clipboard-direction=to-client",
    ])

    listening = workspace_output(name, "ss -ltn", root=True)
    assert ":6080" in listening, f"Expected Xpra to be listening on port 6080, but saw {listening!r}"
    assert ":6081" in listening, f"Expected read-only Xpra to be listening on port 6081, but saw {listening!r}"
    for port in (6080, 6081):
        assert workspace_exec(
            name, f"curl -fs --max-time 3 http://localhost:{port}/"
        ).returncode != 0, f"Expected port {port} to reject plaintext upstream traffic"
        assert workspace_exec(
            name, f"curl -kfs --max-time 3 https://localhost:{port}/ -o /dev/null"
        ).returncode == 0, f"Expected port {port} to serve only HTTPS upstream traffic"
    assert workspace_exec(
        name,
        "! pgrep -x Xvnc && ! pgrep -f '[n]ovnc'",
    ).returncode == 0, "Expected the Linux desktop runtime to contain no legacy VNC process"
    assert workspace_exec(
        name,
        "test ! -e /run/dojo/var/desktop-service/Xvnc.passwd && "
        "! command -v Xvnc && ! command -v novnc",
    ).returncode == 0, "Expected the Linux desktop profile to contain no legacy VNC artifacts"


def test_desktop_service_restarts_for_rotated_route_credentials(runtime_workspace):
    name, session = runtime_workspace
    desktop_pid = service_pid(name, "desktop-service/xpra")
    view_pid = service_pid(name, "desktop-view-service/xpra")
    rotated_password = "r" * 44
    rotated = workspace_exec(
        name,
        f"DOJO_XPRA_DESKTOP_ROUTE_PASSWORD={rotated_password} "
        'DOJO_XPRA_TLS_CERTIFICATE="$(cat /run/dojo/var/desktop-tls/certificate.pem)" '
        'DOJO_XPRA_TLS_PRIVATE_KEY="$(cat /run/dojo/var/desktop-tls/private-key.pem)" '
        "timeout 180 dojo-desktop",
    )
    assert rotated.returncode == 0, f"Expected credential rotation to restart Xpra: {rotated.stderr}"
    rotated_pid = service_pid(name, "desktop-service/xpra")
    assert rotated_pid != desktop_pid
    for old_pid in (desktop_pid, view_pid):
        assert workspace_exec(name, f"kill -0 {old_pid}").returncode != 0, (
            f"Expected credential rotation to terminate old Xpra pid {old_pid}"
        )
    assert workspace_output(
        name, "cat /run/dojo/var/desktop-service/xpra-route-password"
    ) == rotated_password
    assert workspace_exec(
        name, "test ! -e /run/dojo/var/desktop-view-service/xpra.pid"
    ).returncode == 0, "Expected TLS credential rotation to stop the view-only server too"

    restored = session.get(f"{WORKSPACE_API}?service=desktop", timeout=210)
    assert restored.status_code == 200 and restored.json()["success"], restored.text
    restored_src = restored.json()["iframe_src"]
    assert_xpra_route(restored_src, 6080)
    restored_pid = service_pid(name, "desktop-service/xpra")
    assert restored_pid != rotated_pid
    assert workspace_output(
        name, "cat /run/dojo/var/desktop-service/xpra-route-password"
    ) == forwarded_signature(restored_src)


def test_desktop_service_recovers_from_an_orphaned_xorg(runtime_workspace):
    name, session = runtime_workspace
    desktop_pid = service_pid(name, "desktop-service/xpra")
    xorg_pid = workspace_output(
        name, "cat /run/dojo/var/desktop-service/sessions/*/xvfb.pid"
    )
    assert workspace_exec(name, f"kill -KILL {desktop_pid}").returncode == 0
    deadline = time.time() + 15
    while workspace_exec(name, f"kill -0 {desktop_pid}").returncode == 0:
        assert time.time() < deadline, "Expected the killed Xpra server to exit"
        time.sleep(0.2)
    assert workspace_exec(name, f"kill -0 {xorg_pid}").returncode == 0, (
        "Expected the detached Xorg to survive an abrupt Xpra exit"
    )

    recovered = session.get(f"{WORKSPACE_API}?service=desktop", timeout=210)
    assert recovered.status_code == 200 and recovered.json()["success"], recovered.text
    assert_xpra_route(recovered.json()["iframe_src"], 6080)
    assert service_pid(name, "desktop-service/xpra") != desktop_pid
    assert workspace_exec(name, f"kill -0 {xorg_pid}").returncode != 0, (
        f"Expected recovery to terminate orphaned Xorg pid {xorg_pid}"
    )
    assert workspace_output(
        name, "cat /run/dojo/var/desktop-service/sessions/*/xvfb.pid"
    ) != xorg_pid


def test_xpra_allows_shared_clients_and_reconnects_without_stealing(
    runtime_workspace, browser_fixture
):
    _, session = runtime_workspace
    response = session.get(f"{WORKSPACE_API}?service=desktop")
    assert response.status_code == 200, (
        f"Expected the interactive desktop to start, got {response.status_code}"
    )
    result = response.json()
    assert result["success"] and result["active"], (
        f"Expected an active interactive desktop, but got {result}"
    )
    iframe_src = result["iframe_src"]
    assert_xpra_route(iframe_src, 6080)

    connect_xpra_browser(browser_fixture, iframe_src)
    first_handle = browser_fixture.current_window_handle
    browser_fixture.switch_to.new_window("tab")
    second_handle = browser_fixture.current_window_handle
    connect_xpra_browser(browser_fixture, iframe_src)

    browser_fixture.switch_to.window(first_handle)
    assert_xpra_browser_ping(browser_fixture)
    browser_fixture.execute_script(
        "window.__xpraReconnectConnections = 0;"
        "const originalOnConnect = client.on_connect;"
        "client.on_connect = (...args) => {"
        "window.__xpraReconnectConnections += 1;"
        "return originalOnConnect.apply(client, args);"
        "};"
        "client.do_reconnect();"
    )
    WebDriverWait(browser_fixture, 30).until(
        lambda driver: driver.execute_script(
            "return client.connected && window.__xpraReconnectConnections >= 1;"
        )
    )
    assert_xpra_browser_ping(browser_fixture)

    browser_fixture.switch_to.window(second_handle)
    assert_xpra_browser_ping(browser_fixture)

    name = runtime_workspace[0]
    desktop_pid = service_pid(name, "desktop-service/xpra")
    browser_fixture.execute_script(
        "window.__xpraAuthRejected = '';"
        "client.callback_close = reason => { window.__xpraAuthRejected = String(reason || 'closed'); };"
        "client.reconnect = false;"
        "client.reconnect_count = 0;"
        "client.workspace_route_password = 'wrong';"
        "client.passwords = ['wrong'];"
        "client.do_reconnect();"
    )
    WebDriverWait(browser_fixture, 30).until(
        lambda driver: driver.execute_script(
            "return window.__xpraAuthRejected && !client.connected;"
        )
    )
    assert_xpra_service_alive(name, "desktop-service/xpra", 6080, desktop_pid)
    connect_xpra_browser(browser_fixture, iframe_src)
    assert_xpra_browser_ping(browser_fixture)


def test_xpra_file_auth_rejects_weak_digests(runtime_workspace):
    name, session = runtime_workspace
    response = session.get(f"{WORKSPACE_API}?service=desktop")
    assert response.status_code == 200 and response.json()["success"], (
        f"Expected the interactive desktop to start, got {response.text}"
    )
    xpra_cmdline = process_cmdline(name, service_pid(name, "desktop-service/xpra"))
    xpra_entry = shlex.split(xpra_cmdline)[1]
    xpra_root = xpra_entry.rsplit("/bin/", 1)[0]
    auth_check = """
from xpra.auth.file import Authenticator

def authenticator():
    return Authenticator(
        username="hacker",
        filename="/run/dojo/var/desktop-service/xpra-route-password",
        **{"verify-username": "no"},
    )

for weak_digest in ("xor", "des"):
    try:
        authenticator().get_challenge((weak_digest,))
    except ValueError:
        pass
    else:
        raise AssertionError(f"accepted weak challenge digest {weak_digest}")

selected = authenticator()
_, digest = selected.get_challenge(("xor", "des", "hmac+sha256"))
assert digest == "hmac+sha256"
assert selected.choose_salt_digest(("xor", "hmac+sha512")) == "hmac+sha256"
assert selected.choose_salt_digest(("bogus",)) == "hmac+sha256"
"""
    assert workspace_exec(
        name,
        "xpra_pid=$(cat /run/dojo/var/desktop-service/xpra.pid); "
        "xpra_python=$(readlink -f /proc/$xpra_pid/exe); "
        f"xpra_site=$(find {shlex.quote(xpra_root)}/lib -path '*/site-packages' -type d | head -1); "
        f"PYTHONPATH=\"$xpra_site\" \"$xpra_python\" -c {shlex.quote(auth_check)}",
    ).returncode == 0, "Expected Xpra file authentication to enforce HMAC-SHA256 on the server"


def test_xpra_readonly_protocol_ignores_input_side_effects(runtime_workspace):
    name, session = runtime_workspace
    response = session.get(f"{WORKSPACE_API}?service=desktop-view")
    assert response.status_code == 200 and response.json()["success"], (
        f"Expected the desktop services to start, got {response.text}"
    )
    xpra_cmdline = process_cmdline(name, service_pid(name, "desktop-view-service/xpra"))
    xpra_entry = shlex.split(xpra_cmdline)[1]
    xpra_root = xpra_entry.rsplit("/bin/", 1)[0]
    readonly_hello_check = """
from types import SimpleNamespace

from xpra.server.subsystem.keyboard import KeyboardServer
from xpra.util.objects import typedict
import xpra.x11.subsystem.display as display_module
from xpra.x11.subsystem.display import X11DisplayManager

effects = []
server = KeyboardServer()
server.readonly = True
server._server_sources = {}
server.get_keyboard_config = lambda caps: effects.append(("keyboard-config", caps))
server.set_keyboard_repeat = lambda delay, interval: effects.append(("repeat", delay, interval))
server.set_keymap = lambda source: effects.append(("keymap", source))
source = SimpleNamespace(
    uuid="hostile-viewer",
    ui_client=True,
    keyboard_config=object(),
    make_keymask_match=lambda modifiers: effects.append(("modifiers", modifiers)),
)
caps = typedict({"modifiers": ("shift", "lock"), "key_repeat": (1, 1)})
server.parse_hello_ui_keyboard(source, caps)
assert effects == [], effects

display = object.__new__(X11DisplayManager)
display.readonly = True
display_module.x11_ungrab = lambda: effects.append(("force-ungrab",))
display._process_force_ungrab(object(), ("force-ungrab", 0))
assert effects == [], effects
"""
    assert workspace_exec(
        name,
        f"xpra_wrapper={shlex.quote(xpra_root)}/bin/.xpra-wrapped; "
        "xpra_python=$(head -1 \"$xpra_wrapper\" | cut -c3-); "
        "xpra_bootstrap=$(sed -n '3p' \"$xpra_wrapper\"); "
        f"\"$xpra_python\" -c \"$xpra_bootstrap\"$'\\n'{shlex.quote(readonly_hello_check)}",
    ).returncode == 0, "Expected read-only Xpra to ignore input-state side effects"


def test_xpra_owner_clipboard_round_trip(runtime_workspace, browser_fixture):
    name, session = runtime_workspace
    response = session.get(f"{WORKSPACE_API}?service=desktop")
    assert response.status_code == 200, (
        f"Expected the interactive desktop to start, got {response.status_code}"
    )
    result = response.json()
    assert result["success"] and result["active"], (
        f"Expected an active interactive desktop, but got {result}"
    )
    iframe_src = result["iframe_src"]
    assert_xpra_route(iframe_src, 6080)
    connect_xpra_browser(browser_fixture, iframe_src)

    suffix = random_name("")
    clipboard_from_workspace = f"pwn.college ✓ λ {suffix}"
    clipboard_from_browser = f"browser ⇄ workspace ✓ {suffix}"
    clipboard_pid = f"/tmp/xpra-owner-clipboard-{suffix}.pid"
    clipboard_log = f"/tmp/xpra-owner-clipboard-{suffix}.log"
    try:
        workspace_exec(
            name,
            f"printf %s {shlex.quote(clipboard_from_workspace)} | "
            f"DISPLAY=:0 timeout 60 xclip -selection clipboard -in "
            f">{shlex.quote(clipboard_log)} 2>&1 & "
            f"echo $! > {shlex.quote(clipboard_pid)}",
        )
        assert wait_for_workspace_clipboard(name, clipboard_from_workspace), (
            "Expected the Unicode workspace clipboard value to be established"
        )
        assert WebDriverWait(browser_fixture, 10).until(
            lambda driver: driver.execute_script("return client.get_clipboard_buffer();")
            == clipboard_from_workspace
        ), "Expected the browser client to receive the Unicode workspace clipboard value"
        browser_fixture.execute_script(
            "Object.defineProperty(navigator, 'clipboard', {"
            "configurable: true, value: {readText: () => Promise.resolve(arguments[0])}"
            "});"
            "client.clipboard_buffer = '';"
            "client.read_clipboard_text();",
            clipboard_from_browser,
        )
        assert wait_for_workspace_clipboard(name, clipboard_from_browser), (
            "Expected the workspace to receive the Unicode browser clipboard value"
        )
    finally:
        workspace_exec(
            name,
            f"if test -s {shlex.quote(clipboard_pid)}; then "
            f"kill \"$(cat {shlex.quote(clipboard_pid)})\" 2>/dev/null || true; fi; "
            f"rm -f {shlex.quote(clipboard_pid)} {shlex.quote(clipboard_log)}",
        )


def test_authenticated_xpra_clients_cannot_stop_desktop_services(
    runtime_workspace, random_user_session, browser_fixture
):
    name, session = runtime_workspace
    interactive_response = session.get(f"{WORKSPACE_API}?service=desktop")
    assert interactive_response.status_code == 200, (
        f"Expected the interactive desktop to start, got {interactive_response.status_code}"
    )
    interactive_result = interactive_response.json()
    assert interactive_result["success"] and interactive_result["active"], (
        f"Expected an active interactive desktop, but got {interactive_result}"
    )
    assert_xpra_route(interactive_result["iframe_src"], 6080)

    token = workspace_output(name, "cat /run/dojo/var/auth_token")
    view_password = hmac.HMAC(token.encode(), b"desktop-view", hashlib.sha256).hexdigest()
    view_response = random_user_session.get(
        WORKSPACE_API,
        params={"user": get_user_id(name), "service": "desktop"},
        headers={"X-Workspace-Password": view_password},
    )
    assert view_response.status_code == 200, (
        f"Expected the view-only desktop share to start, got {view_response.status_code}"
    )
    view_result = view_response.json()
    assert view_result["success"] and view_result["active"], (
        f"Expected an active view-only desktop workspace, but got {view_result}"
    )
    assert_xpra_route(view_result["iframe_src"], 6081)

    services = [
        (
            "desktop-service/xpra",
            6080,
            interactive_result["iframe_src"],
            service_pid(name, "desktop-service/xpra"),
        ),
        (
            "desktop-view-service/xpra",
            6081,
            view_result["iframe_src"],
            service_pid(name, "desktop-view-service/xpra"),
        ),
    ]
    for service_name, port, iframe_src, expected_pid in services:
        assert_xpra_service_alive(name, service_name, port, expected_pid)
        connect_xpra_browser(browser_fixture, iframe_src)
        assert_xpra_info_denied(browser_fixture, sensitive_value=token)
        for packet_type in ["exit-server", "shutdown-server"]:
            browser_fixture.execute_script(
                "client.send([arguments[0]]);", packet_type
            )
            assert_xpra_info_denied(browser_fixture, sensitive_value=token)
            for checked_service, checked_port, _, checked_pid in services:
                assert_xpra_service_alive(
                    name, checked_service, checked_port, checked_pid
                )


def test_desktop_view_route_enforces_read_only(
    runtime_workspace, random_user_session, browser_fixture
):
    name, session = runtime_workspace
    interactive_response = session.get(f"{WORKSPACE_API}?service=desktop")
    assert interactive_response.status_code == 200, (
        f"Expected the interactive desktop to start, got {interactive_response.status_code}"
    )
    interactive_result = interactive_response.json()
    assert interactive_result["success"] and interactive_result["active"], (
        f"Expected an active interactive desktop, but got {interactive_result}"
    )
    interactive_src = interactive_result["iframe_src"]
    assert_xpra_route(interactive_src, 6080)

    token = workspace_output(name, "cat /run/dojo/var/auth_token")
    view_password = hmac.HMAC(token.encode(), b"desktop-view", hashlib.sha256).hexdigest()
    view_response = random_user_session.get(
        WORKSPACE_API,
        params={"user": get_user_id(name), "service": "desktop"},
        headers={"X-Workspace-Password": view_password},
    )
    assert view_response.status_code == 200, (
        f"Expected the signed desktop view route to succeed, got {view_response.status_code}"
    )
    view_result = view_response.json()
    assert view_result["success"] and view_result["active"], (
        f"Expected an active signed desktop view route, but got {view_result}"
    )
    view_src = view_result["iframe_src"]
    assert_xpra_route(view_src, 6081)

    parsed_view_src = urlparse(view_src)
    hostile_params = parse_qs(parsed_view_src.query)
    hostile_params.update({
        "readonly": ["0"],
        "view_only": ["0"],
        "sharing": ["0"],
        "steal": ["1"],
        "password": ["wrong"],
        "token": ["wrong"],
        "path": ["/"],
        "server": ["attacker.invalid"],
        "port": ["9"],
        "ssl": ["0" if parsed_view_src.scheme == "https" else "1"],
        "webtransport": ["1"],
        "insecure": ["1"],
        "encryption": ["AES-CBC"],
        "key": ["route-secret-exfiltration"],
    })
    hostile_view_src = parsed_view_src._replace(query=urlencode(hostile_params, doseq=True)).geturl()
    assert forwarded_port(hostile_view_src) == 6081
    assert forwarded_signature(hostile_view_src) == forwarded_signature(view_src)
    hostile_response = requests.get(hostile_view_src, timeout=30, allow_redirects=True)
    assert hostile_response.status_code == 200, (
        f"Expected query manipulation to leave the valid signed 6081 route reachable, got "
        f"{hostile_response.status_code}"
    )

    suffix = random_name("")
    interactive_marker = f"/tmp/xpra-interactive-{suffix}"
    view_marker = f"/tmp/xpra-view-{suffix}"
    clipboard_sentinel = f"xpra-view-clipboard-sentinel-{suffix}"
    clipboard_from_workspace = f"xpra-view-workspace-clipboard-{suffix}"
    clipboard_attack = f"xpra-view-clipboard-attack-{suffix}"
    clipboard_pid = f"/tmp/xpra-view-clipboard-{suffix}.pid"
    clipboard_log = f"/tmp/xpra-view-clipboard-{suffix}.log"
    workspace_exec(
        name,
        f"rm -f {shlex.quote(interactive_marker)} {shlex.quote(view_marker)} && "
        "DISPLAY=:0 xfce4-terminal --disable-server >/tmp/xpra-readonly-test-terminal.log 2>&1 &",
    )
    try:
        interactive_canvas = connect_xpra_browser(browser_fixture, interactive_src)
        assert browser_fixture.execute_script("return client.server_readonly;") is False
        time.sleep(2)
        ActionChains(browser_fixture).move_to_element(interactive_canvas).click().send_keys(
            f"touch {interactive_marker}"
        ).send_keys(Keys.ENTER).perform()
        assert wait_for_workspace_path(name, interactive_marker), (
            "Expected the interactive 6080 connection to accept the test keyboard input"
        )
        ActionChains(browser_fixture).move_to_element(interactive_canvas).click().send_keys(
            f"touch {view_marker}"
        ).perform()
        modifier_state_before_view = workspace_xpra_keyboard_state(name, True)
        assert modifier_state_before_view["shift_down"] and modifier_state_before_view["mask"], (
            f"Expected the test fixture to hold Shift before the viewer hello, got {modifier_state_before_view}"
        )

        workspace_exec(
            name,
            f"printf %s {shlex.quote(clipboard_sentinel)} | "
            f"DISPLAY=:0 timeout 60 xclip -selection clipboard -in "
            f">{shlex.quote(clipboard_log)} 2>&1 & "
            f"echo $! > {shlex.quote(clipboard_pid)}",
        )
        assert wait_for_workspace_clipboard(name, clipboard_sentinel), (
            "Expected the stable clipboard sentinel to be owned by the workspace"
        )

        browser_fixture.switch_to.new_window("tab")
        view_canvas = connect_xpra_browser(browser_fixture, hostile_view_src)
        modifier_state_after_view = workspace_xpra_keyboard_state(name)
        assert modifier_state_after_view == modifier_state_before_view, (
            "Expected the read-only viewer hello not to mutate the owner's live modifier state, got "
            f"{modifier_state_before_view} before and {modifier_state_after_view} after"
        )
        workspace_xpra_keyboard_state(name, False)
        pinned_transport = browser_fixture.execute_script(
            "return {"
            "host: client.host,"
            "expectedHost: window.location.hostname,"
            "port: String(client.port),"
            "expectedPort: window.location.port,"
            "ssl: client.ssl,"
            "expectedSsl: window.location.protocol === 'https:',"
            "webtransport: client.webtransport,"
            "path: client.path,"
            "expectedPath: window.location.pathname,"
            "insecure: client.insecure,"
            "encryption: client.encryption,"
            "encryptionKey: client.encryption_key,"
            "digests: client._get_digests(),"
            "title: document.title,"
            "storageKeys: Object.keys(sessionStorage)"
            "};"
        )
        assert pinned_transport == {
            "host": pinned_transport["expectedHost"],
            "expectedHost": pinned_transport["expectedHost"],
            "port": pinned_transport["expectedPort"],
            "expectedPort": pinned_transport["expectedPort"],
            "ssl": pinned_transport["expectedSsl"],
            "expectedSsl": pinned_transport["expectedSsl"],
            "webtransport": False,
            "path": pinned_transport["expectedPath"],
            "expectedPath": pinned_transport["expectedPath"],
            "insecure": False,
            "encryption": False,
            "encryptionKey": None,
            "digests": ["hmac+sha256"],
            "title": "Desktop",
            "storageKeys": pinned_transport["storageKeys"],
        }, f"Expected signed routes to pin every transport and authentication setting, got {pinned_transport}"
        assert all(forwarded_signature(view_src) not in key for key in pinned_transport["storageKeys"]), (
            f"Expected the signed route not to appear in sessionStorage keys, got {pinned_transport['storageKeys']}"
        )
        assert browser_fixture.execute_script("return client.server_readonly;") is True, (
            "Expected the 6081 server hello to remain read-only despite hostile query parameters"
        )
        workspace_exec(
            name,
            f"kill \"$(cat {shlex.quote(clipboard_pid)})\" 2>/dev/null || true; "
            f"printf %s {shlex.quote(clipboard_from_workspace)} | "
            f"DISPLAY=:0 timeout 60 xclip -selection clipboard -in "
            f">{shlex.quote(clipboard_log)} 2>&1 & "
            f"echo $! > {shlex.quote(clipboard_pid)}",
        )
        assert wait_for_workspace_clipboard(name, clipboard_from_workspace), (
            "Expected the workspace clipboard update to be established after the viewer connected"
        )
        assert WebDriverWait(browser_fixture, 10).until(
            lambda driver: driver.execute_script("return client.get_clipboard_buffer();")
            == clipboard_from_workspace
        ), "Expected the read-only 6081 viewer to receive the workspace clipboard"
        browser_fixture.execute_script(
            "window.__xpraTestClipboardTokens = 0;"
            "const originalSend = client.send.bind(client);"
            "client.send = (...args) => {"
            "const packet = args[0];"
            "if (packet && packet[0] === 'clipboard-token') window.__xpraTestClipboardTokens += 1;"
            "return originalSend(...args);"
            "};"
            "client.server_readonly = false;"
            "client.clipboard_enabled = true;"
            "window.__xpraTestKeyWindowId = Number(Object.keys(client.id_to_window)[0]);"
            "client.send(['key-action', window.__xpraTestKeyWindowId, 'Return', true, [], 13, 'Enter', 13, 0]);"
            "client.send(['key-action', window.__xpraTestKeyWindowId, 'Return', false, [], 13, 'Enter', 13, 0]);"
        )
        assert browser_fixture.execute_script(
            "return Boolean(window.__xpraTestKeyWindowId > 0 && "
            "client.id_to_window[window.__xpraTestKeyWindowId]);"
        ), "Expected the hostile keyboard packets to target the real desktop window"
        browser_fixture.execute_script(
            "client.send_clipboard_token(Utilities.StringToUint8(arguments[0]), "
            "['text/plain', 'UTF8_STRING']);",
            clipboard_attack,
        )
        assert browser_fixture.execute_script("return window.__xpraTestClipboardTokens;") > 0, (
            "Expected the test to bypass the HTML client's clipboard guard and transmit a clipboard token"
        )
        assert_xpra_info_denied(browser_fixture)
        assert_xpra_info_denied(browser_fixture)
        assert workspace_exec(name, f"test ! -e {shlex.quote(view_marker)}").returncode == 0, (
            "Expected the server-side read-only 6081 service to reject the transmitted keyboard input"
        )
        assert wait_for_workspace_clipboard(name, clipboard_from_workspace, timeout=3), (
            "Expected the 6081 to-client clipboard policy to reject the transmitted clipboard token"
        )
    finally:
        workspace_xpra_keyboard_state(name, False)
        workspace_exec(
            name,
            f"if test -s {shlex.quote(clipboard_pid)}; then "
            f"kill \"$(cat {shlex.quote(clipboard_pid)})\" 2>/dev/null || true; fi; "
            "pkill -f '[x]fce4-terminal' 2>/dev/null || true; "
            f"rm -f {shlex.quote(interactive_marker)} {shlex.quote(view_marker)} "
            f"{shlex.quote(clipboard_pid)} {shlex.quote(clipboard_log)}",
        )


def test_desktop_does_not_expose_a_legacy_vnc_port(runtime_workspace):
    name, session = runtime_workspace
    session.get(f"{WORKSPACE_API}?service=desktop")

    listening = workspace_output(name, "ss -ltn", root=True)
    assert ":5900" not in listening, (
        f"Expected the desktop to expose only Xpra's HTML5 service rather than VNC, but it listens: {listening!r}"
    )


def test_only_whitelisted_services_are_executed_in_the_workspace(runtime_workspace):
    name, session = runtime_workspace

    before = workspace_output(name, "ls /run/dojo/var", root=True)
    response = session.get(f"{WORKSPACE_API}?service=desktop-windows")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    result = response.json()
    assert result["success"] and result["iframe_src"], (
        f"Expected a signed url even for a service that is never executed, but got {result}"
    )
    assert forwarded_port(result["iframe_src"]) == 6082, (
        f"Expected desktop-windows to forward to port 6082, but got {result['iframe_src']}"
    )

    after = workspace_output(name, "ls /run/dojo/var", root=True)
    assert after == before, (
        f"Expected a non-whitelisted service to start nothing, but /run/dojo/var changed from {before!r} to {after!r}"
    )
    assert workspace_output(name, "find /run/dojo/var -name '*desktop-windows*' | wc -l", root=True) == "0", (
        "Expected no desktop-windows service state to be created"
    )


@pytest.mark.skipif(MULTINODE, reason="the workspace proxy redirects to the per-node vhost in multinode")
def test_workspace_proxy_passes_websocket_upgrades_through(runtime_workspace):
    _, session = runtime_workspace

    iframe_src = session.get(f"{WORKSPACE_API}?service=terminal").json()["iframe_src"]
    parsed = urlparse(iframe_src)
    target = urlparse(DOJO_URL)
    request = (
        f"GET {parsed.path}ws HTTP/1.1\r\n"
        f"Host: {parsed.netloc}\r\n"
        "Connection: Upgrade\r\n"
        "Upgrade: websocket\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        "Sec-WebSocket-Protocol: tty\r\n"
        "\r\n"
    )
    with socket.create_connection((target.hostname, target.port or 80), timeout=30) as connection:
        connection.sendall(request.encode())
        response = connection.recv(4096).decode(errors="replace")

    assert response.startswith("HTTP/1.1 101"), (
        f"Expected the workspace proxy to complete the websocket handshake, but got {response.splitlines()[:1]}"
    )
    assert "upgrade" in response.lower(), f"Expected an Upgrade response from the proxy, but got {response!r}"


def test_workspace_proxy_signature_covers_the_container_and_port(
    runtime_workspace, privileged_workspace, random_user_session
):
    name, session = runtime_workspace
    code_response = session.get(f"{WORKSPACE_API}?service=code")
    assert code_response.status_code == 200, f"Expected the code service to start, got {code_response.status_code}"
    code_iframe_src = code_response.json()["iframe_src"]
    assert forwarded_port(code_iframe_src) == 8080, f"Expected code on port 8080, got {code_iframe_src}"

    code_proxy = requests.get(code_iframe_src, timeout=30, allow_redirects=False)
    node_code_iframe_src = None
    if MULTINODE:
        assert code_proxy.status_code == 307, (
            f"Expected the main proxy to redirect to the workspace node, got {code_proxy.status_code}"
        )
        node_code_iframe_src = code_proxy.headers["Location"]
        code_proxy = requests.get(node_code_iframe_src, timeout=30, allow_redirects=False)
        workspace_outer = get_outer_container_for(f"user_{get_user_id(name)}")
        workspace_proxy_log = dojo_run(
            "docker", "exec", "nginx-workspace", "cat", "/var/log/nginx/access.log",
            container=workspace_outer,
        ).stdout
        assert forwarded_signature(code_iframe_src) not in workspace_proxy_log, (
            "Expected the node redirecter to redact signed workspace routes from its access log"
        )
    assert code_proxy.status_code == 200, f"Expected the signed code url to work, got {code_proxy.status_code}"

    token = workspace_output(name, "cat /run/dojo/var/auth_token")
    view_password = hmac.HMAC(token.encode(), b"desktop-view", hashlib.sha256).hexdigest()
    shared = random_user_session.get(
        WORKSPACE_API,
        params={"user": get_user_id(name), "service": "desktop"},
        headers={"X-Workspace-Password": view_password},
    )
    assert shared.status_code == 200, f"Expected the view-only desktop share to be granted, got {shared.status_code}"
    desktop_iframe_src = shared.json()["iframe_src"]
    assert forwarded_port(desktop_iframe_src) == 6081, (
        f"Expected the shared desktop on the read-only port 6081, but got {desktop_iframe_src}"
    )
    desktop_proxy = requests.get(desktop_iframe_src, timeout=30, allow_redirects=True)
    assert desktop_proxy.status_code == 200, (
        f"Expected the signed read-only desktop url to work, got {desktop_proxy.status_code}"
    )

    desktop_signature = forwarded_signature(desktop_iframe_src)
    assert desktop_signature != forwarded_signature(code_iframe_src), (
        "Expected the same container to use different signatures for ports 6081 and 8080"
    )

    peer_name, _ = privileged_workspace
    peer_token = workspace_output(peer_name, "cat /run/dojo/var/auth_token")
    peer_view_password = hmac.HMAC(peer_token.encode(), b"desktop-view", hashlib.sha256).hexdigest()
    peer_shared = random_user_session.get(
        WORKSPACE_API,
        params={"user": get_user_id(peer_name), "service": "desktop"},
        headers={"X-Workspace-Password": peer_view_password},
    )
    assert peer_shared.status_code == 200, (
        f"Expected the peer read-only desktop share to be granted, got {peer_shared.status_code}"
    )
    peer_iframe_src = peer_shared.json()["iframe_src"]
    assert_xpra_route(peer_iframe_src, 6081)
    assert forwarded_container(peer_iframe_src) != forwarded_container(desktop_iframe_src), (
        "Expected the signature transplant fixture to use a distinct active workspace container"
    )

    desktop_container = forwarded_container(desktop_iframe_src).split(":", 1)[0]
    peer_container = forwarded_container(peer_iframe_src).split(":", 1)[0]
    desktop_outer = get_outer_container_for(f"user_{get_user_id(name)}")
    peer_outer = get_outer_container_for(f"user_{get_user_id(peer_name)}")
    tls_proxy = "nginx-workspace" if MULTINODE else "nginx"
    verified_leaf = dojo_run(
        "docker", "exec", tls_proxy, "sh", "-c",
        f"openssl s_client -connect {desktop_container}:6081 -servername {desktop_container} "
        f"-verify_hostname {desktop_container} -CAfile /run/dojo-xpra-ca.crt "
        "-verify_return_error </dev/null >/dev/null",
        container=desktop_outer,
        check=False,
    )
    assert verified_leaf.returncode == 0, (
        f"Expected Nginx's CA and container hostname to verify the Xpra leaf: {verified_leaf.stderr}"
    )
    wrong_hostname = dojo_run(
        "docker", "exec", tls_proxy, "sh", "-c",
        f"openssl s_client -connect {desktop_container}:6081 -servername {peer_container} "
        f"-verify_hostname {peer_container} -CAfile /run/dojo-xpra-ca.crt "
        "-verify_return_error </dev/null >/dev/null",
        container=desktop_outer,
        check=False,
    )
    assert wrong_hostname.returncode != 0, (
        "Expected a different workspace's hostname to fail verification against the desktop leaf"
    )

    def xpra_leaf_fingerprint(container, outer):
        return dojo_run(
            "docker", "exec", tls_proxy, "sh", "-c",
            f"openssl s_client -connect {container}:6081 -servername {container} "
            "</dev/null 2>/dev/null | openssl x509 -noout -sha256 -fingerprint",
            container=outer,
        ).stdout.strip()

    desktop_fingerprint = xpra_leaf_fingerprint(desktop_container, desktop_outer)
    peer_fingerprint = xpra_leaf_fingerprint(peer_container, peer_outer)
    assert desktop_fingerprint and peer_fingerprint and desktop_fingerprint != peer_fingerprint, (
        f"Expected unique Xpra leaves per workspace, got {desktop_fingerprint!r} and {peer_fingerprint!r}"
    )
    nginx_config = dojo_run(
        "docker", "exec", tls_proxy, "nginx", "-T", container=desktop_outer
    ).stdout
    assert "proxy_ssl_verify on;" in nginx_config
    assert "proxy_ssl_name $container_id;" in nginx_config
    assert "secure_link_hmac_message \"$container_id:xpra:$port\";" in nginx_config
    assert "proxy_pass https://$container_id:$port/" in nginx_config
    assert "proxy_pass http://$container_id:$port/" in nginx_config
    assert "$workspace_upstream_scheme" not in nginx_config
    assert "log_format workspace" in nginx_config
    assert "access_log /var/log/nginx/access.log workspace;" in nginx_config
    if MULTINODE:
        redirecter_config = nginx_config.split("listen 8888;", 1)[1].split("server {", 1)[0]
        assert "access_log /var/log/nginx/access.log workspace;" in redirecter_config

    transplanted_container_iframe_src = replace_forwarded_container(
        desktop_iframe_src, forwarded_container(peer_iframe_src)
    )
    transplanted_container_proxy = requests.get(
        transplanted_container_iframe_src, timeout=30, allow_redirects=False
    )
    assert transplanted_container_proxy.status_code == 404, (
        "Expected the source container's port-6081 signature to reject the peer container, got "
        f"{transplanted_container_proxy.status_code}"
    )
    assert transplanted_container_proxy.text.strip() == "Workspace not found", (
        transplanted_container_proxy.text
    )

    tampered_interactive_iframe_src = replace_forwarded_port(desktop_iframe_src, 6080)
    tampered_interactive_proxy = requests.get(
        tampered_interactive_iframe_src, timeout=30, allow_redirects=False
    )
    assert tampered_interactive_proxy.status_code == 404, (
        f"Expected the port-6081 signature to reject port 6080, got {tampered_interactive_proxy.status_code}"
    )
    assert tampered_interactive_proxy.text.strip() == "Workspace not found", tampered_interactive_proxy.text

    unmarked_desktop_iframe_src = remove_forwarded_transport(desktop_iframe_src)
    unmarked_desktop_proxy = requests.get(
        unmarked_desktop_iframe_src, timeout=30, allow_redirects=False
    )
    assert unmarked_desktop_proxy.status_code == 404, (
        "Expected the Xpra signature to reject a route without its transport marker"
    )
    assert unmarked_desktop_proxy.text.strip() == "Workspace not found", unmarked_desktop_proxy.text

    tampered_code_iframe_src = replace_forwarded_signature(code_iframe_src, desktop_signature)
    tampered_code_proxy = requests.get(tampered_code_iframe_src, timeout=30, allow_redirects=False)
    assert tampered_code_proxy.status_code == 404, (
        f"Expected the desktop signature to reject port 8080, got {tampered_code_proxy.status_code}"
    )
    assert tampered_code_proxy.text.strip() == "Workspace not found", tampered_code_proxy.text

    if node_code_iframe_src:
        tampered_node_iframe_src = replace_forwarded_signature(node_code_iframe_src, desktop_signature)
        tampered_node_proxy = requests.get(tampered_node_iframe_src, timeout=30, allow_redirects=False)
        assert tampered_node_proxy.status_code == 404, (
            f"Expected the workspace node to reject the desktop signature on port 8080, "
            f"got {tampered_node_proxy.status_code}"
        )
        assert tampered_node_proxy.text.strip() == "Workspace not found", tampered_node_proxy.text

    log_since = str(int(time.time()) - 1)
    desktop_view_pid = service_pid(name, "desktop-view-service/xpra")
    assert workspace_exec(name, f"kill {desktop_view_pid}", root=True).returncode == 0
    deadline = time.time() + 10
    while workspace_exec(name, f"kill -0 {desktop_view_pid}", root=True).returncode == 0:
        assert time.time() < deadline, "Expected the read-only Xpra service to stop for the proxy failure test"
        time.sleep(0.1)
    failed_desktop_proxy = requests.get(desktop_iframe_src, timeout=30, allow_redirects=True)
    assert failed_desktop_proxy.status_code == 404, (
        f"Expected the stopped Xpra upstream to produce a redacted 404, got {failed_desktop_proxy.status_code}"
    )
    time.sleep(0.2)
    proxy_targets = [(desktop_outer, tls_proxy)]
    if MULTINODE:
        proxy_targets.append((DOJO_CONTAINER, "nginx"))
    for outer, proxy in proxy_targets:
        proxy_logs = dojo_run(
            "docker", "logs", "--since", log_since, proxy,
            container=outer,
            check=False,
        )
        combined_proxy_logs = proxy_logs.stdout + proxy_logs.stderr
        assert desktop_signature not in combined_proxy_logs, (
            f"Expected {proxy} access and error logs to redact the Xpra route credential"
        )
        assert view_password not in combined_proxy_logs, (
            f"Expected {proxy} access and error logs not to contain the desktop share password"
        )
        assert '"status":"404"' in combined_proxy_logs, (
            f"Expected {proxy} to record the redacted upstream failure, got {combined_proxy_logs!r}"
        )


@pytest.mark.parametrize("image", ["pwncollege-nginx", "pwncollege-nginx-workspace"])
@pytest.mark.parametrize("route_tail", ["6080/", "xpra/6080/"])
def test_production_workspace_http_redirects_before_route_proxying(image, route_tail):
    proxy_name = random_name("workspace_redirect_")
    workspace_host = "workspace.example.test"
    route = "/workspace/aaaaaaaaaaaa/" + "b" * 64 + f"/{route_tail}?reconnect=1"
    try:
        started = dojo_run(
            "docker", "run", "--detach", "--name", proxy_name,
            "--env", "DOJO_ENV=production",
            "--env", "DOJO_HOST=dojo.example.test",
            "--env", f"WORKSPACE_HOST={workspace_host}",
            "--env", "WORKSPACE_SECRET=production-redirect-test",
            image,
            check=False,
        )
        assert started.returncode == 0, f"Expected {image} to start: {started.stderr}"
        proxy_ip = dojo_run(
            "docker", "inspect", "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", proxy_name,
        ).stdout.strip()
        response = None
        deadline = time.time() + 15
        while time.time() < deadline:
            response = dojo_run(
                "curl", "--silent", "--show-error", "--output", "/dev/null",
                "--write-out", "%{http_code}\n%{redirect_url}",
                "--header", f"Host: {workspace_host}", f"http://{proxy_ip}{route}",
                check=False,
            )
            if response.returncode == 0:
                break
            time.sleep(0.2)
        assert response and response.returncode == 0, (
            f"Expected the production HTTP proxy to answer: {response.stderr if response else ''}"
        )
        status, location = response.stdout.splitlines()
        assert status == "307", f"Expected HTTP to redirect before route handling, got {response.stdout!r}"
        assert location == f"https://{workspace_host}{route}", (
            f"Expected the signed route to be preserved only in the HTTPS redirect, got {location!r}"
        )
    finally:
        dojo_run("docker", "rm", "--force", proxy_name, check=False)


def test_nginx_routes_by_host_header():
    host = dojo_host()
    base = DOJO_URL.rstrip("/")

    ctfd = requests.get(base, headers={"Host": host}, timeout=30)
    assert ctfd.status_code == 200, f"Expected status code 200 for the dojo host, but got {ctfd.status_code}"
    assert "session" in ctfd.cookies, "Expected the dojo host to be served by CTFd"

    frontend = requests.get(base, headers={"Host": f"future.{host}"}, timeout=30)
    assert frontend.status_code == 200, f"Expected status code 200 for the future host, but got {frontend.status_code}"
    assert frontend.headers.get("X-Powered-By") == "Next.js", (
        f"Expected the future host to be served by the frontend, but got {frontend.headers}"
    )

    unknown = requests.get(base, headers={"Host": "bogus.example"}, timeout=30)
    assert unknown.status_code == 200, f"Expected status code 200 for an unknown host, but got {unknown.status_code}"
    assert "session" in unknown.cookies, "Expected an unknown host to fall through to CTFd's default server"

    workspace = requests.get(
        f"{base}/workspace/deadbeef/badsig/8080/", headers={"Host": f"workspace.{host}"}, timeout=30
    )
    assert workspace.status_code == 404, (
        f"Expected an unsigned workspace url to be rejected, but got {workspace.status_code}"
    )
    assert workspace.headers["Content-Type"].startswith("text/plain"), (
        f"Expected a plain text rejection, but got {workspace.headers.get('Content-Type')}"
    )
    assert workspace.text.strip() == "Workspace not found", f"Unexpected rejection body: {workspace.text!r}"

    nginx_config = dojo_run("docker", "exec", "nginx", "nginx", "-T").stdout
    workspace_api_location = nginx_config.split(
        "location = /pwncollege_api/v1/workspace {", 1
    )[1].split("}", 1)[0]
    assert "proxy_read_timeout 300s;" in workspace_api_location, (
        "Expected the public proxy timeout to cover serialized desktop startup"
    )
    assert "proxy_pass http://ctfd_upstream;" in workspace_api_location

    gunicorn_config = dojo_run(
        "docker", "exec", "ctfd", "gunicorn", "--print-config", "CTFd:create_app()"
    ).stdout
    effective_timeout = next(
        line for line in gunicorn_config.splitlines() if line.startswith("timeout ")
    )
    assert effective_timeout.split("=", 1)[1].strip() == "300", (
        f"Expected Gunicorn to outlive serialized desktop startup, got {effective_timeout!r}"
    )


def test_nginx_streams_server_sent_events_without_buffering():
    with requests.get(f"{DOJO_URL}/pwncollege_api/v1/feed/stream", stream=True, timeout=30) as response:
        assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
        assert response.headers["Content-Type"].startswith("text/event-stream"), (
            f"Expected an event stream, but got {response.headers.get('Content-Type')}"
        )
        start = time.time()
        first_frame = next(line for line in response.iter_lines(decode_unicode=True) if line)
        elapsed = time.time() - start

    assert json.loads(first_frame.removeprefix("data: "))["type"] == "connected", (
        f"Expected the stream to open with a connected frame, but got {first_frame!r}"
    )
    assert elapsed < 10, (
        f"Expected the first frame to arrive immediately rather than being buffered, but it took {elapsed:.1f}s"
    )


def test_cli_error_paths_all_exit_one(runtime_workspace):
    name, _ = runtime_workspace

    missing_token = workspace_exec(name, "env -u DOJO_AUTH_TOKEN dojo whoami")
    assert missing_token.returncode == 1, f"Expected exit code 1, but got {missing_token.returncode}"
    assert "Missing DOJO_AUTH_TOKEN." in missing_token.stderr, f"Unexpected error: {missing_token.stderr!r}"

    no_subcommand = workspace_exec(name, "dojo")
    assert no_subcommand.returncode == 1, f"Expected exit code 1, but got {no_subcommand.returncode}"
    assert "usage: dojo" in no_subcommand.stdout, f"Expected usage output, but got {no_subcommand.stdout!r}"

    bad_token = workspace_exec(name, "DOJO_AUTH_TOKEN=sk-workspace-local-garbage dojo whoami")
    assert bad_token.returncode == 1, f"Expected exit code 1, but got {bad_token.returncode}"
    assert "Failed to authenticate container token." in bad_token.stderr, (
        f"Expected the server's error to be surfaced rather than a traceback, but got {bad_token.stderr!r}"
    )
    assert "Traceback" not in bad_token.stderr, f"Expected no traceback, but got {bad_token.stderr!r}"

    wrong_flag = workspace_exec(name, "dojo submit pwn.college{wrong}")
    assert wrong_flag.returncode == 1, f"Expected exit code 1, but got {wrong_flag.returncode}"
    assert "Incorrect flag." in wrong_flag.stderr, f"Unexpected error: {wrong_flag.stderr!r}"


def test_cli_list_filters_by_dojo_type(runtime_workspace, workspace_runtime_dojo):
    name, _ = runtime_workspace

    default_listing = workspace_output(name, "dojo list /").split()
    assert workspace_runtime_dojo not in default_listing, (
        "Expected a community dojo to be hidden from the default dojo listing"
    )

    community_listing = workspace_output(name, "dojo list -C /").split()
    assert workspace_runtime_dojo in community_listing, (
        "Expected -C to include community dojos in the listing"
    )

    all_listing = workspace_output(name, "dojo list -a /").split()
    assert workspace_runtime_dojo in all_listing, "Expected -a to include community dojos in the listing"

    expanded = workspace_output(name, "dojo list -l -C /")
    assert expanded.startswith("Community: "), f"Expected a community header row, but got {expanded[:80]!r}"

    bad_path = workspace_exec(name, "dojo list /a/b/c")
    assert bad_path.returncode == 1, f"Expected exit code 1, but got {bad_path.returncode}"
    assert 'Dojo path must match one of "/", "/<dojo>", or "/<dojo>/<module>".' in bad_path.stderr, (
        f"Unexpected error: {bad_path.stderr!r}"
    )


def test_cli_rejects_incomplete_absolute_paths(runtime_workspace, workspace_runtime_dojo):
    name, _ = runtime_workspace

    dojo_only = workspace_exec(name, f"dojo start /{workspace_runtime_dojo}")
    assert dojo_only.returncode == 1, f"Expected exit code 1, but got {dojo_only.returncode}"
    assert "Absolute paths must be complete for starting challenges." in dojo_only.stderr, (
        f"Unexpected error: {dojo_only.stderr!r}"
    )

    module_only = workspace_exec(name, f"dojo start /{workspace_runtime_dojo}/runtime")
    assert module_only.returncode == 1, f"Expected exit code 1, but got {module_only.returncode}"
    assert "Absolute paths must be complete for starting challenges." in module_only.stderr, (
        f"Unexpected error: {module_only.stderr!r}"
    )

    too_deep = workspace_exec(name, "dojo start a/b/c/d")
    assert too_deep.returncode == 1, f"Expected exit code 1, but got {too_deep.returncode}"
    assert "Incorrect path format" in too_deep.stderr, f"Unexpected error: {too_deep.stderr!r}"
