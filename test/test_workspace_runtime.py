import hashlib
import hmac
import json
import random
import socket
import string
import subprocess
import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests

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


def forwarded_port(iframe_src):
    return int([part for part in urlparse(iframe_src).path.split("/") if part][3])


def forwarded_signature(iframe_src):
    return [part for part in urlparse(iframe_src).path.split("/") if part][2]


def replace_forwarded_signature(iframe_src, signature):
    parsed = urlparse(iframe_src)
    parts = parsed.path.split("/")
    parts[3] = signature
    return parsed._replace(path="/".join(parts)).geturl()


def private_worker_proxy_status(iframe_src):
    parsed = urlparse(iframe_src)
    forward_target = [part for part in parsed.path.split("/") if part][1]
    target_host = forward_target.rsplit(":", 1)[1]
    result = dojo_run(
        "curl", "--silent", "--show-error", "--noproxy", "*", "--output", "/dev/null",
        "--write-out", "%{http_code}",
        "--header", f"Host: {parsed.netloc}",
        "--header", f"X-Forwarded-Proto: {parsed.scheme}",
        f"http://{target_host}:8888{parsed.path}",
        timeout=30,
    )
    return int(result.stdout)


def dojo_host():
    return dojo_run(
        "sh", "-c", ". /data/config.env; printf '%s' \"$DOJO_HOST\""
    ).stdout.strip()


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
                   "ssh-entrypoint", "scp", "dojo-terminal", "dojo-code", "dojo-desktop"]:
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


def test_desktop_service_contract(runtime_workspace):
    name, session = runtime_workspace

    response = session.get(f"{WORKSPACE_API}?service=desktop")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
    result = response.json()
    assert result["success"] and result["active"], f"Expected an active desktop workspace, but got {result}"
    assert forwarded_port(result["iframe_src"]) == 6080, f"Expected noVNC on port 6080: {result['iframe_src']}"

    token = workspace_output(name, "cat /run/dojo/var/auth_token")
    expected = hmac.HMAC(token.encode(), b"desktop-interact", hashlib.sha256).hexdigest()[:8]
    password = parse_qs(urlparse(result["iframe_src"]).query)["password"][0]
    assert password == expected, (
        f"Expected the vnc password to be HMAC-SHA256(auth token, 'desktop-interact')[:8] = {expected}, got {password}"
    )

    for service in ["Xvnc", "novnc", "xfce4-session"]:
        pid = service_pid(name, f"desktop-service/{service}")
        assert workspace_exec(name, f"kill -0 {pid}").returncode == 0, (
            f"Expected the desktop's {service} (pid {pid}) to be running"
        )
    assert workspace_exec(name, "test -s /run/dojo/var/desktop-service/Xvnc.passwd").returncode == 0, (
        "Expected the desktop service to write a vnc password file"
    )

    xvnc_cmdline = process_cmdline(name, service_pid(name, "desktop-service/Xvnc"))
    for argument in ["-nolisten tcp", "-geometry 1024x768", "-depth 24",
                     "-rfbunixpath /run/dojo/var/desktop-service/Xvnc.sock"]:
        assert argument in xvnc_cmdline, f"Expected Xvnc to be started with {argument}, but got {xvnc_cmdline!r}"

    listening = workspace_output(name, "ss -ltn", root=True)
    assert ":6080" in listening, f"Expected noVNC to be listening on 6080, but saw {listening!r}"


def test_desktop_vnc_server_is_not_reachable_over_tcp(runtime_workspace):
    name, session = runtime_workspace
    session.get(f"{WORKSPACE_API}?service=desktop")

    listening = workspace_output(name, "ss -ltn", root=True)
    assert ":5900" not in listening, (
        f"Expected the desktop's vnc server to be reachable only over its unix socket, but it listens: {listening!r}"
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


def test_workspace_proxy_signature_covers_the_container_and_port(runtime_workspace, random_user_session):
    name, session = runtime_workspace
    code_response = session.get(f"{WORKSPACE_API}?service=code")
    assert code_response.status_code == 200, f"Expected the code service to start, got {code_response.status_code}"
    code_iframe_src = code_response.json()["iframe_src"]
    assert forwarded_port(code_iframe_src) == 8080, f"Expected code on port 8080, got {code_iframe_src}"

    code_proxy = requests.get(code_iframe_src, timeout=30, allow_redirects=False)
    assert code_proxy.status_code == 200, f"Expected the signed code url to work, got {code_proxy.status_code}"
    assert "Location" not in code_proxy.headers, (
        f"Expected the main proxy to keep the learner URL stable, got {code_proxy.headers['Location']}"
    )
    if MULTINODE:
        assert private_worker_proxy_status(code_iframe_src) == 200, \
            "Expected the worker's private proxy to accept the signed code URL"

    token = workspace_output(name, "cat /run/dojo/var/auth_token")
    view_password = hmac.HMAC(token.encode(), b"desktop-view", hashlib.sha256).hexdigest()
    shared = random_user_session.get(
        f"{WORKSPACE_API}?user={get_user_id(name)}&password={view_password}&service=desktop"
    )
    assert shared.status_code == 200, f"Expected the view-only desktop share to be granted, got {shared.status_code}"
    desktop_iframe_src = shared.json()["iframe_src"]
    assert forwarded_port(desktop_iframe_src) == 6080, (
        f"Expected the shared desktop on port 6080, but got {desktop_iframe_src}"
    )
    desktop_proxy = requests.get(desktop_iframe_src, timeout=30)
    assert desktop_proxy.status_code == 200, (
        f"Expected the signed desktop url to work, got {desktop_proxy.status_code}"
    )

    desktop_signature = forwarded_signature(desktop_iframe_src)
    assert desktop_signature != forwarded_signature(code_iframe_src), (
        "Expected the same container to use different signatures for ports 6080 and 8080"
    )

    tampered_code_iframe_src = replace_forwarded_signature(code_iframe_src, desktop_signature)
    tampered_code_proxy = requests.get(tampered_code_iframe_src, timeout=30, allow_redirects=False)
    assert tampered_code_proxy.status_code == 404, (
        f"Expected the desktop signature to reject port 8080, got {tampered_code_proxy.status_code}"
    )
    assert tampered_code_proxy.text.strip() == "Workspace not found", tampered_code_proxy.text
    if MULTINODE:
        assert private_worker_proxy_status(tampered_code_iframe_src) == 404, \
            "Expected the worker's private proxy to reject a signature for a different port"


def test_nginx_routes_by_host_header(workspace_runtime_dojo):
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
    assert workspace_runtime_dojo in frontend.text, (
        "Expected the server-rendered frontend to load dojos from the native CTFd origin"
    )

    for api_path in ("/api/v1/challenges", "/pwncollege_api/v1/dojos"):
        api_response = requests.get(f"{base}{api_path}", headers={"Host": f"future.{host}"}, timeout=30)
        assert api_response.headers.get("Content-Type", "").startswith("application/json"), (
            f"Expected {api_path} on the future host to be served by CTFd, but got {api_response.headers}"
        )

    unknown = requests.get(base, headers={"Host": "bogus.example"}, timeout=30)
    assert unknown.status_code == 200, f"Expected status code 200 for an unknown host, but got {unknown.status_code}"
    assert "session" in unknown.cookies, "Expected an unknown host to fall through to CTFd's default server"

    workspace = requests.get(
        f"{base}/workspace/deadbeefdead@10.0.1.1/badsig/8080/",
        headers={"Host": f"workspace.{host}"},
        timeout=30,
    )
    assert workspace.status_code == 404, (
        f"Expected an unsigned workspace url to be rejected, but got {workspace.status_code}"
    )
    assert workspace.headers["Content-Type"].startswith("text/plain"), (
        f"Expected a plain text rejection, but got {workspace.headers.get('Content-Type')}"
    )
    assert workspace.text.strip() == "Workspace not found", f"Unexpected rejection body: {workspace.text!r}"


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
