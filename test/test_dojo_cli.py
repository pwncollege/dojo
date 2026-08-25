import json
import os
import random
import re
import string
import subprocess
import time

import pytest
import requests

from utils import (
    DOJO_CONTAINER,
    DOJO_URL,
    config_env,
    create_dojo_yml,
    db_sql,
    dojo_run,
    get_outer_container_for,
    get_user_id,
    journalctl,
    login,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
    systemctl,
    unit_is_active,
    workspace_run,
)


PULL_IMAGES_SCRIPT = "/opt/pwn.college/dojo_plugin/scripts/pull_images.py"

SPEC_TEMPLATE = """
id: {dojo_id}
name: CLI Load {dojo_id}
modules:
  - id: hello
    name: Hello
    challenges:
      - id: apple
        name: Apple
        image: pwncollege/challenge-simple
"""


def _rand(k=8):
    return "".join(random.choices(string.ascii_lowercase, k=k))


def _read_workspace_nodes():
    result = dojo_run("cat", "/data/workspace_nodes.json", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


WORKSPACE_NODES = _read_workspace_nodes()
MULTINODE = bool(WORKSPACE_NODES)
WORKER_CONTAINER = f"{DOJO_CONTAINER}-node{sorted(WORKSPACE_NODES)[0]}" if MULTINODE else None
WORKSPACE_CONTAINER = WORKER_CONTAINER if MULTINODE else DOJO_CONTAINER


def _curl(url, *args, container=None):
    result = dojo_run(
        "curl", "-s", "-o", "/dev/stdout", "-w", "\n%{http_code}", *args, url,
        container=container or DOJO_CONTAINER,
    )
    body, _, status = result.stdout.rpartition("\n")
    return int(status), body


def _curl_status(url, *args, container=None):
    result = dojo_run(
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", *args, url,
        container=container or DOJO_CONTAINER,
    )
    return int(result.stdout.strip())


def _service_invocation_ids(*services):
    return {
        service: systemctl(
            "show", "--property=InvocationID", "--value", service
        ).stdout.strip()
        for service in services
    }


def _ctfd_workspace_nodes():
    result = dojo_run(
        "dojo", "flask",
        input=(
            "import json; from CTFd.plugins.dojo_plugin.config import WORKSPACE_NODES; "
            "print('TOPOLOGY:' + json.dumps(WORKSPACE_NODES, sort_keys=True))\n"
        ),
    )
    match = re.search(r"TOPOLOGY:(\{[^\n]*\})", result.stdout)
    assert match, result.stdout
    return json.loads(match.group(1))


def test_dojo_command_surface():
    help_output = dojo_run("dojo", "help").stdout
    for command in (
        "up", "update", "sync", "enter", "node", "flask", "db", "backup",
        "restore", "cloud-backup", "vscode", "logs", "load-dojo", "wait", "help",
    ):
        assert f"    {command}" in help_output, f"dojo help omits {command}"
    assert "    compose" not in help_output, "dojo still exposes the removed Compose control plane"


def _homefs_driver(endpoint, payload):
    return _curl(
        f"http://localhost/VolumeDriver.{endpoint}",
        "--unix-socket", "/run/docker/plugins/homefs.sock", "-XPOST", "-d", json.dumps(payload),
    )


def _destroy_probe_volume(name):
    _homefs_driver("Remove", {"Name": name})
    dojo_run(
        "sh", "-c",
        f"for subvolume in /data/homes/{name}/snapshots/* /data/homes/{name}/overlays/* "
        f"/data/homes/{name}/snapshots /data/homes/{name}/overlays /data/homes/{name}/active "
        f"/data/homes/{name}; do btrfs subvolume delete \"$subvolume\" 2>/dev/null; done; true",
        check=False,
    )


def _delete_homefs_active_record(name):
    dojo_run(
        "python3", "-c",
        "import sqlite3, sys; connection = sqlite3.connect('/run/homefs/homefs.db'); "
        "connection.execute('DELETE FROM active_volumes WHERE name=?', (sys.argv[1],)); "
        "connection.commit()", name, check=False,
    )


def _write_spec_in_ctfd(spec):
    path = f"/tmp/cli-load-{_rand()}.yml"
    dojo_run("sh", "-c", f"cat > {path}", input=spec)
    return path


def _dojo_rows(dojo_id):
    output = db_sql(f"SELECT dojo_id FROM dojos WHERE id = '{dojo_id}';").split()
    return [int(dojo_id_value) for dojo_id_value in output]


def _reference_ids(dojo_id):
    return [f"{dojo_id}~{row & 0xFFFFFFFF:08x}" for row in _dojo_rows(dojo_id)]


def _delete_dojos(dojo_id, admin_session):
    for reference_id in _reference_ids(dojo_id):
        admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={"dojo": reference_id})


def _deploy_docker_run(tmp_path, *args, environment=None):
    executable_dir = tmp_path / f"bin-{len(list(tmp_path.iterdir()))}"
    executable_dir.mkdir()
    docker_log = executable_dir / "docker.log"
    fake_workdir = executable_dir / "workdir"
    fake_workdir.mkdir()
    executables = {
        "docker": """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case "$*" in
    "image inspect "*) exit 0 ;;
    "ps -a"*) exit 0 ;;
    "inspect -f "*) printf '172.17.0.2\\n' ;;
    *"cat /etc/resolv.conf"*) printf 'nameserver 1.1.1.1\\n' ;;
    "run "*) printf 'fake-container\\n' ;;
esac
""",
        "curl": "#!/bin/sh\nprintf 'pwn\\n'\n",
        "ip": "#!/bin/sh\nprintf 'default via 172.17.0.1 dev eth0\\n'\n",
        "mktemp": "#!/bin/sh\nprintf '%s\\n' \"$FAKE_WORKDIR\"\n",
        "mount": "#!/bin/sh\nprintf 'fake on /tmp/data-dojo-123456 type tmpfs (rw)\\n'\n",
        "sleep": "#!/bin/sh\nexit 0\n",
        "sudo": "#!/bin/sh\nexit 0\n",
    }
    for name, contents in executables.items():
        path = executable_dir / name
        path.write_text(contents)
        path.chmod(0o755)

    deploy_environment = os.environ.copy()
    deploy_environment.pop("DISCORD_CLIENT_SECRET", None)
    deploy_environment.update({
        "PATH": f"{executable_dir}:{deploy_environment['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "FAKE_WORKDIR": str(fake_workdir),
    })
    deploy_environment.update(environment or {})
    result = subprocess.run(
        ["/opt/pwn.college/deploy.sh", "-D", "", "-W", "", *args],
        capture_output=True,
        env=deploy_environment,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return next(
        line for line in docker_log.read_text().splitlines()
        if line.startswith("run ") and "--privileged" in line
    )


def test_deploy_discord_secret_scope(tmp_path):
    unconfigured = _deploy_docker_run(tmp_path)
    configured = _deploy_docker_run(
        tmp_path,
        environment={"DISCORD_CLIENT_SECRET": "operator-discord-secret"},
    )
    overridden = _deploy_docker_run(
        tmp_path,
        "-e",
        "DISCORD_CLIENT_SECRET=argument-discord-secret",
        environment={"DISCORD_CLIENT_SECRET": "operator-discord-secret"},
    )
    testing = _deploy_docker_run(tmp_path, "-t")

    assert "DISCORD_CLIENT_SECRET" not in unconfigured
    assert "DISCORD_CLIENT_SECRET=operator-discord-secret" in configured
    assert overridden.rfind("DISCORD_CLIENT_SECRET=argument-discord-secret") > overridden.rfind(
        "DISCORD_CLIENT_SECRET=operator-discord-secret"
    )
    assert "DISCORD_CLIENT_SECRET=test-discord-client-secret" in testing


@pytest.fixture(scope="module")
def cli_user(example_dojo):
    name = "clistd" + _rand(10)
    session = login(name, name, register=True)
    start_challenge(example_dojo, "hello", "apple", session=session)
    yield name, session
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def practice_cli_user(example_dojo):
    name = "clipra" + _rand(10)
    session = login(name, name, register=True)
    start_challenge(example_dojo, "hello", "apple", practice=True, session=session)
    yield name, session
    remove_workspace_container(name)


@pytest.fixture(scope="module")
def privileged_cli_user(privileged_dojo):
    name = "clipri" + _rand(10)
    session = login(name, name, register=True)
    session.get(f"{DOJO_URL}/dojo/{privileged_dojo}/join/")
    start_challenge(privileged_dojo, "test", "test", session=session)
    yield name, session
    remove_workspace_container(name)


def test_db_propagates_psql_exit_status():
    plain = dojo_run("dojo", "db", "-qAt", input="SELECT 1/0;", check=False)
    assert plain.returncode == 0, "psql without ON_ERROR_STOP is expected to swallow errors"
    assert "division by zero" in plain.stderr, plain.stderr

    stopped = dojo_run("dojo", "db", "-v", "ON_ERROR_STOP=1", "-qAt", input="SELECT 1/0;", check=False)
    assert stopped.returncode == 3, f"expected psql error exit status 3, got {stopped.returncode}"
    assert "division by zero" in stopped.stderr, stopped.stderr

    healthy = dojo_run("dojo", "db", "-v", "ON_ERROR_STOP=1", "-qAt", input="SELECT 1+1;", check=False)
    assert healthy.returncode == 0, healthy.stderr
    assert healthy.stdout.strip() == "2", healthy.stdout


def test_flask_exit_code_semantics():
    interactive = dojo_run("dojo", "flask", input='raise RuntimeError("cli-probe-boom")\n', check=False)
    assert interactive.returncode == 0, "interactive `dojo flask` is expected to always exit 0"
    assert "RuntimeError" in interactive.stdout, interactive.stdout

    failing_script = "/tmp/cli-flask-fail.py"
    dojo_run("sh", "-c", f"cat > {failing_script}", input='raise RuntimeError("cli-probe-boom")\n')
    failing = dojo_run("dojo", "flask", "--", failing_script, check=False)
    assert failing.returncode != 0, "script-mode `dojo flask` must propagate a failing script"

    marker = _rand()
    working_script = "/tmp/cli-flask-ok.py"
    dojo_run("sh", "-c", f"cat > {working_script}", input=f'print("{marker}")\n')
    working = dojo_run("dojo", "flask", "--", working_script, check=False)
    assert working.returncode == 0, working.stdout + working.stderr
    assert marker in working.stdout, working.stdout


def test_enter_enters_user_container_as_hacker_and_root(cli_user):
    name, _ = cli_user
    user_id = get_user_id(name)

    hacker = dojo_run("dojo", "enter", str(user_id), input="id -u; whoami\n")
    assert hacker.stdout.split() == ["1000", "hacker"], hacker.stdout

    marker = _rand()
    workspace_run(f"echo {marker} > /tmp/cli-enter-marker", user=name)
    by_name = dojo_run("dojo", "enter", name, input="cat /tmp/cli-enter-marker; id -u\n")
    assert by_name.stdout.split() == [marker, "1000"], \
        f"`dojo enter {name}` did not resolve the username to user_{user_id}: {by_name.stdout}"

    root = dojo_run("dojo", "enter", "-s", str(user_id), input="id -u\n")
    assert root.stdout.strip() == "0", root.stdout

    root_flag = dojo_run("dojo", "enter", "-s", str(user_id), input="cat /flag\n")
    assert "pwn.college{" in root_flag.stdout, root_flag.stdout

    hacker_flag = dojo_run("dojo", "enter", str(user_id), input="cat /flag\n", check=False)
    assert "pwn.college{" not in hacker_flag.stdout, "the hacker user must not be able to read /flag"
    assert "Permission denied" in hacker_flag.stdout + hacker_flag.stderr, hacker_flag.stdout

    status = dojo_run("dojo", "enter", str(user_id), input="exit 7\n", check=False)
    assert status.returncode == 7, f"`dojo enter` did not forward the exit status: {status.returncode}"


def test_enter_missing_container_reports_failure(random_user):
    name, _ = random_user
    missing_container = dojo_run("dojo", "enter", name, input="id -u\n", check=False)
    assert missing_container.stdout.strip() == "", missing_container.stdout
    assert missing_container.returncode != 0, \
        "`dojo enter` for a user without a running container must not report success"

    unknown_user = dojo_run("dojo", "enter", "definitely-not-a-user-xyz", input="id -u\n", check=False)
    assert unknown_user.stdout.strip() == "", unknown_user.stdout
    assert unknown_user.returncode != 0, "`dojo enter` for an unknown username must not report success"


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_enter_finds_container_on_worker_node(cli_user):
    name, _ = cli_user
    user_id = get_user_id(name)
    outer_container = get_outer_container_for(f"user_{user_id}")
    assert outer_container != DOJO_CONTAINER, "learner container is not on a worker node"
    entered = dojo_run("dojo", "enter", str(user_id), input="id -u\n")
    assert entered.stdout.strip() == "1000", \
        f"`dojo enter` from the main node did not reach the container on {outer_container}"


@pytest.mark.skipif(MULTINODE, reason="single-node unit selection")
def test_native_units_select_singlenode_role():
    expected = {
        "cadvisor", "dojo-ctfd", "dojo-stats-worker", "dojo-image-pull-worker",
        "dojo-nginx", "dojo-frontend", "dojo-homefs", "dojo-dojofs",
        "dojo-workspace-authorizer", "dojo-workspace-builder", "grafana", "pgbouncer",
        "postgresql", "postgresql-setup", "prometheus", "prometheus-node-exporter",
        "redis-dojo", "sshd",
    }
    inactive = {unit for unit in expected if not unit_is_active(unit)}
    assert not inactive, f"inactive single-node units: {inactive}"
    assert not unit_is_active("dojo-docker-api"), \
        "a single-node dojo unexpectedly exposes the worker Docker API"

    environment = config_env()
    assert environment["DOJO_CONFIG_VERSION"] == "1"
    rendered_config = dojo_run("grep", "-R", "-h", "server_name", "/run/dojo/nginx/conf.d").stdout
    assert environment["DOJO_HOST"] in rendered_config
    assert environment["WORKSPACE_HOST"] in rendered_config
    nginx_config = dojo_run("cat", "/run/dojo/nginx/nginx.conf").stdout
    assert "server 127.0.0.1:8000;" in nginx_config
    assert "server 127.0.0.1:3001;" in nginx_config
    assert "server ctfd:8000;" not in nginx_config
    assert "server frontend:3000;" not in nginx_config
    assert "access_log syslog:server=unix:/dev/log,nohostname,tag=dojo_nginx main;" in nginx_config


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_native_units_select_multinode_roles():
    workspace_units = {
        "cadvisor", "dojo-nginx", "dojo-homefs", "dojo-dojofs", "dojo-docker-api",
        "dojo-workspace-authorizer", "dojo-workspace-builder", "prometheus-node-exporter",
    }
    main_units = {
        "cadvisor", "dojo-ctfd", "dojo-stats-worker", "dojo-image-pull-worker",
        "dojo-nginx", "dojo-frontend", "dojo-homefs", "dojo-workspace-authorizer",
        "dojo-workspace-builder", "grafana", "pgbouncer", "postgresql",
        "postgresql-setup", "prometheus", "prometheus-node-exporter", "redis-dojo", "sshd",
    }

    inactive_worker_units = {
        unit for unit in workspace_units if not unit_is_active(unit, container=WORKER_CONTAINER)
    }
    assert not inactive_worker_units, f"inactive workspace-node units: {inactive_worker_units}"
    for unit in {
        "dojo-ctfd", "dojo-stats-worker", "dojo-image-pull-worker", "dojo-frontend",
        "grafana", "pgbouncer", "postgresql", "postgresql-setup", "prometheus",
        "redis-dojo", "sshd",
    }:
        assert not unit_is_active(unit, container=WORKER_CONTAINER), \
            f"workspace node unexpectedly runs {unit}"

    inactive_main_units = {unit for unit in main_units if not unit_is_active(unit)}
    assert not inactive_main_units, f"inactive main-node units: {inactive_main_units}"
    assert not unit_is_active("dojo-dojofs"), "the main node of a multinode dojo must not host workspaces"
    assert not unit_is_active("dojo-docker-api"), "the main node unexpectedly exposes the worker Docker API"


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_workspace_nodes_have_no_published_web_or_storage_ports():
    main_workspace_host = config_env()["WORKSPACE_HOST"]
    for node_id in WORKSPACE_NODES:
        worker_container = f"{DOJO_CONTAINER}-node{node_id}"
        worker_environment = config_env(container=worker_container)
        assert worker_environment["WORKSPACE_HOST"] == main_workspace_host
        assert worker_environment["STORAGE_HOST"] == "192.168.42.1"

        inspected = subprocess.run(
            ["docker", "inspect", worker_container],
            check=True,
            capture_output=True,
            text=True,
        )
        port_bindings = json.loads(inspected.stdout)[0]["HostConfig"]["PortBindings"]
        assert not port_bindings, f"workspace node {node_id} publishes host ports: {port_bindings}"

        route_config = dojo_run(
            "cat", "/run/dojo/nginx/conf.d/route-redirecter.conf", container=worker_container
        ).stdout
        assert "listen 8888;" in route_config, route_config
        assert "auth_request /_dojo_workspace_authorize;" in route_config, route_config
        assert "proxy_pass http://$container_ip:$port/" in route_config, route_config
        assert "return 307" not in route_config, route_config


def test_native_service_boundaries():
    daemon_config = json.loads(dojo_run("cat", "/run/dojo/docker-daemon.json").stdout)
    assert daemon_config["runtimes"]["io.containerd.run.kata.v2"] == {
        "runtimeType": "/opt/kata/bin/containerd-shim-kata-v2",
        "options": {
            "ConfigPath": "/opt/kata/share/defaults/kata-containers/configuration.toml",
        },
    }
    docker_start_post = systemctl(
        "show", "--property=ExecStartPost", "--value", "docker.service"
    ).stdout
    assert "dojo-docker-migrate" in docker_start_post, docker_start_post
    for service in ("dojo-ctfd", "dojo-stats-worker", "dojo-image-pull-worker"):
        part_of = systemctl("show", "--property=PartOf", "--value", service).stdout.split()
        assert "dojo-ctfd-source.service" in part_of, f"{service} is not restarted with its source view"

    effective_sshd_config = dojo_run(
        "sshd", "-T", "-C", "user=hacker,host=localhost,addr=127.0.0.1"
    ).stdout.splitlines()
    sshd_settings = {
        key.lower(): value
        for key, value in (line.split(maxsplit=1) for line in effective_sshd_config)
    }
    assert sshd_settings["authorizedkeyscommand"] == "/run/wrappers/bin/dojo-ssh-auth"
    assert sshd_settings["authorizedkeyscommanduser"] == "root"
    resolved_command = dojo_run(
        "readlink", "-f", sshd_settings["authorizedkeyscommand"]
    ).stdout.strip()
    command_parts = resolved_command.strip("/").split("/")
    command_paths = ["/"] + [
        "/" + "/".join(command_parts[:index])
        for index in range(1, len(command_parts) + 1)
    ]
    for path in command_paths:
        owner, mode = dojo_run("stat", "-Lc", "%u:%a", path).stdout.strip().split(":")
        assert owner == "0", f"unsafe AuthorizedKeysCommand owner on {path}: {owner}"
        assert int(mode, 8) & 0o22 == 0, f"unsafe AuthorizedKeysCommand mode on {path}: {mode}"

    listeners = dojo_run("ss", "-Hlnpt").stdout
    assert "127.0.0.1:8000" in listeners, listeners
    assert "0.0.0.0:8000" not in listeners, listeners
    assert "[::]:8000" not in listeners, listeners
    assert "127.0.0.1:4201" in listeners, listeners
    assert "192.168.42.1:4201" in listeners, listeners
    assert "0.0.0.0:4201" not in listeners, listeners
    assert "[::]:4201" not in listeners, listeners

    expected_permissions = {
        "/data/config.env": "600:root:root",
        "/run/dojo/config.env": "600:root:root",
        "/run/dojo/ctfd.env": "640:root:ctfd",
        "/run/dojo/pgbouncer.ini": "640:root:pgbouncer",
        "/run/dojo/ssh-auth.env": "600:root:root",
        "/run/dojo/ssh.env": "640:root:hacker",
    }
    for path, permissions in expected_permissions.items():
        actual = dojo_run("stat", "-c", "%a:%U:%G", path).stdout.strip()
        assert actual == permissions, f"{path}: {actual} != {permissions}"

    for username in ("ctfd", "hacker"):
        for path in ("/data/config.env", "/run/dojo/config.env", "/run/dojo/ssh-auth.env"):
            unreadable = dojo_run(
                "runuser", "-u", username, "--", "test", "!", "-r", path, check=False
            )
            assert unreadable.returncode == 0, f"{username} can read full configuration from {path}"
    assert dojo_run(
        "runuser", "-u", "ctfd", "--", "test", "-r", "/run/dojo/ctfd.env", check=False
    ).returncode == 0, "ctfd cannot read its scoped configuration"

    forbidden_ctfd_names = {
        "AWS_ACCESS_KEY_ID", "AWS_DEFAULT_REGION", "AWS_SECRET_ACCESS_KEY",
        "BACKUP_AES_KEY_FILE", "S3_BACKUP_BUCKET",
    }
    ctfd_configuration = dojo_run("cat", "/run/dojo/ctfd.env").stdout
    assert not forbidden_ctfd_names & {line.partition("=")[0] for line in ctfd_configuration.splitlines()}
    ssh_configuration = dojo_run("cat", "/run/dojo/ssh.env").stdout
    assert not {"DB_NAME", "DB_PASS", "DB_USER"} & {
        line.partition("=")[0] for line in ssh_configuration.splitlines()
    }

    pooled_query = dojo_run(
        "bash", "-c",
        '. /data/config.env; PGPASSWORD="$DB_PASS" psql -h 127.0.0.1 -p 6432 '
        '-U "$DB_USER" -d "$DB_NAME" -qAtc "SELECT 1"',
    )
    assert pooled_query.stdout.strip() == "1", pooled_query.stdout + pooled_query.stderr
    assert dojo_run(
        "stat", "-c", "%a:%U:%G", "/run/dojo/pgbouncer-users.txt"
    ).stdout.strip() == "640:root:pgbouncer"
    database_host = config_env()["DB_HOST"]
    database_port = "5432"
    bracketed_host = re.fullmatch(r"\[([^]]+)]:(\d+)", database_host)
    host_with_port = re.fullmatch(r"([^:/]+):(\d+)", database_host)
    if bracketed_host or host_with_port:
        database_host, database_port = (bracketed_host or host_with_port).groups()
    pgbouncer_config = dojo_run("cat", "/run/dojo/pgbouncer.ini").stdout
    assert f"*=host={database_host} port={database_port}" in pgbouncer_config
    assert "/run/dojo/pgbouncer.ini" in systemctl(
        "show", "--property=ExecStart", "--value", "pgbouncer.service"
    ).stdout
    outer_containers = [DOJO_CONTAINER]
    if MULTINODE:
        outer_containers.extend(f"{DOJO_CONTAINER}-node{node_id}" for node_id in WORKSPACE_NODES)
    for outer_container in outer_containers:
        assert not unit_is_active("dhcpcd.service", container=outer_container), \
            f"dhcpcd is managing interfaces in {outer_container}"
        assert systemctl(
            "is-enabled", "dhcpcd.service", container=outer_container, check=False
        ).returncode != 0, f"dhcpcd is enabled in {outer_container}"
        assert not unit_is_active("resolvconf.service", container=outer_container), \
            f"resolvconf is overwriting host DNS in {outer_container}"
        assert systemctl(
            "is-enabled", "resolvconf.service", container=outer_container, check=False
        ).returncode != 0, f"resolvconf is enabled in {outer_container}"
        if config_env(container=outer_container)["DOJO_OFFLINE"] != "true":
            resolved = dojo_run(
                "getent", "ahostsv4", "registry-1.docker.io",
                container=outer_container, check=False,
            )
            assert resolved.returncode == 0, \
                f"host DNS resolution failed in {outer_container}: {resolved.stderr}"

    dojo_propagation = dojo_run(
        "findmnt", "-nro", "PROPAGATION", "--target", "/run/dojo"
    ).stdout.strip()
    homefs_propagation = dojo_run(
        "findmnt", "-nro", "PROPAGATION", "--target", "/run/homefs"
    ).stdout.strip()
    assert dojo_propagation == "shared", dojo_propagation
    assert homefs_propagation == "shared", homefs_propagation


def test_retired_infrastructure_migration_is_scoped():
    suffix = _rand()
    retired = f"retired-ctfd-{suffix}"
    foreign = f"foreign-ctfd-{suffix}"
    extended = f"extended-service-{suffix}"
    nearby = f"nearby-config-{suffix}"
    permission_probe = f"/data/CTFd/.migration-permission-{suffix}"
    common = (
        "--label", "com.docker.compose.project.working_dir=/opt/pwn.college",
        "--label", "com.docker.compose.project.config_files=/opt/pwn.college/docker-compose.yml",
    )
    try:
        dojo_run("install", "-m", "600", "-o", "root", "-g", "root", "/dev/null", permission_probe)
        dojo_run(
            "docker", "create", "--name", retired, *common,
            "--label", "com.docker.compose.service=ctfd",
            "busybox:uclibc", "true",
        )
        dojo_run(
            "docker", "create", "--name", foreign,
            "--label", "com.docker.compose.project.working_dir=/srv/another-project",
            "--label", "com.docker.compose.project.config_files=/srv/another-project/docker-compose.yml",
            "--label", "com.docker.compose.service=ctfd",
            "busybox:uclibc", "true",
        )
        dojo_run(
            "docker", "create", "--name", extended, *common,
            "--label", "com.docker.compose.service=custom-service",
            "busybox:uclibc", "true",
        )
        dojo_run(
            "docker", "create", "--name", nearby,
            "--label", "com.docker.compose.project.working_dir=/opt/pwn.college",
            "--label", "com.docker.compose.project.config_files=/opt/pwn.college/docker-compose.yml.backup",
            "--label", "com.docker.compose.service=ctfd",
            "busybox:uclibc", "true",
        )

        migration = dojo_run("dojo-docker-migrate", check=False)
        assert migration.returncode == 0, migration.stdout + migration.stderr
        assert dojo_run("stat", "-c", "%U:%G", permission_probe).stdout.strip() == "ctfd:ctfd"
        assert dojo_run("docker", "inspect", retired, check=False).returncode != 0, \
            "the retired Dojo infrastructure container survived migration"
        for preserved in (foreign, extended, nearby):
            assert dojo_run("docker", "inspect", preserved, check=False).returncode == 0, \
                f"migration removed out-of-scope container {preserved}"
    finally:
        dojo_run("rm", "-f", permission_probe, check=False)
        for container in (retired, foreign, extended, nearby):
            dojo_run("docker", "rm", "--force", container, check=False)


def test_startup_gates_are_satisfied():
    assert unit_is_active("dojo-workspace-builder"), "the workspace builder did not complete"
    active_profile = "/data/workspace/nix/var/nix/profiles/dojo-workspace"
    assert dojo_run("test", "-L", active_profile, check=False).returncode == 0, \
        "the workspace profile was not built"
    logical_generation = dojo_run("readlink", active_profile).stdout.strip()
    logical_profile = dojo_run("readlink", f"/data/workspace{logical_generation}").stdout.strip()
    logical_suid_file = dojo_run("readlink", f"/data/workspace{logical_profile}/suid").stdout.strip()
    assert logical_suid_file.startswith("/nix/store/"), logical_suid_file
    suid_paths = dojo_run("cat", f"/data/workspace{logical_suid_file}").stdout.split()
    assert suid_paths, "the workspace profile has no SUID manifest entries"
    for logical_path in suid_paths:
        owner, mode = dojo_run("stat", "-c", "%u:%a", f"/data/workspace{logical_path}").stdout.strip().split(":")
        assert owner == "0", f"workspace SUID path is not root-owned: {logical_path}"
        assert int(mode, 8) & 0o4000, f"workspace SUID bit is missing: {logical_path} ({mode})"
    assert unit_is_active("dojo-stats-worker"), "the stats worker is not active"
    deadline = time.time() + 40
    while True:
        logs = journalctl("dojo-stats-worker", "--boot", check=False).stdout
        if "Cold start complete" in logs:
            return
        assert time.time() < deadline, "stats-worker never finished its cold start"
        time.sleep(2)


def test_wait_succeeds_on_healthy_dojo():
    result = dojo_run("dojo", "wait", check=False, timeout=45)
    assert result.returncode == 0, result.stdout[-2000:]


def test_wait_times_out_when_systemd_never_becomes_available(tmp_path):
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    for name, contents in {
        "dojo": "#!/bin/sh\nexit 0\n",
        "journalctl": "#!/bin/sh\nexit 0\n",
        "sleep": "#!/bin/sh\nexit 0\n",
        "systemctl": "#!/bin/sh\nexit 1\n",
    }.items():
        path = executable_dir / name
        path.write_text(contents)
        path.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{executable_dir}:{environment['PATH']}"
    environment["DOJO_WAIT_TIMEOUT"] = "2"
    result = subprocess.run(
        ["/opt/pwn.college/dojo/dojo", "wait"],
        capture_output=True,
        env=environment,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0, "dojo wait reported success without a usable systemd bus"
    assert "dojo readiness check failed" in result.stderr, result.stderr


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_wait_succeeds_without_stats_worker_on_worker():
    result = dojo_run("dojo", "wait", container=WORKER_CONTAINER, check=False, timeout=45)
    assert result.returncode == 0, result.stdout[-2000:]
    assert not unit_is_active("dojo-stats-worker", container=WORKER_CONTAINER)


def test_backup_creates_restorable_dump():
    result = dojo_run("dojo", "backup")
    match = re.search(r"Created backup at (\S+)", result.stdout)
    assert match, result.stdout
    path = match.group(1)
    try:
        assert path.startswith("/data/backups/db-"), path
        assert int(dojo_run("stat", "-c", "%s", path).stdout) > 1000, "backup is suspiciously small"
        toc = dojo_run("pg_restore", "-l", path).stdout
        assert "Format: CUSTOM" in toc, toc[:400]
        assert "TABLE DATA public users" in toc, "backup does not contain the users table"
        assert "TABLE DATA public dojos" in toc, "backup does not contain the dojos table"
    finally:
        dojo_run("rm", "-f", path, check=False)


def test_restore_missing_file_signals_failure():
    result = dojo_run("dojo", "restore", "definitely-missing.dump", check=False)
    assert "missing file to restore from" in result.stderr, result.stderr
    assert result.returncode != 0, "`dojo restore` of a missing backup must not report success"


@pytest.mark.order(-1)
def test_restore_applies_dump():
    table = f"cli_restore_probe_{_rand()}"
    dump = f"cli-restore-{_rand()}.dump"
    db_sql(f"CREATE TABLE {table} (v text); INSERT INTO {table} VALUES ('sentinel');")
    try:
        dojo_run(
            "sh", "-c",
            f'. /data/config.env; PGPASSWORD="$DB_PASS" pg_dump -h 127.0.0.1 '
            f'-U "$DB_USER" -d "$DB_NAME" -Fc -t {table} > /data/backups/{dump}',
        )
        db_sql(f"DROP TABLE {table};")
        assert db_sql(f"SELECT to_regclass('{table}') IS NULL;").strip() == "t"

        result = dojo_run("dojo", "restore", dump, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        assert db_sql(f"SELECT v FROM {table};").strip() == "sentinel", \
            "`dojo restore` did not restore the dumped rows"
    finally:
        db_sql(f"DROP TABLE IF EXISTS {table};")
        dojo_run("rm", "-f", f"/data/backups/{dump}", check=False)
    assert requests.get(DOJO_URL).status_code == 200, "the dojo did not survive a restore"


def test_cloud_backup_unconfigured_fails_loudly():
    environment = config_env()
    if environment.get("BACKUP_AES_KEY_FILE") or environment.get("S3_BACKUP_BUCKET"):
        pytest.skip("cloud backup is configured on this dojo")
    result = dojo_run("dojo", "cloud-backup", check=False)
    output = result.stdout + result.stderr
    assert result.returncode != 0, "unconfigured `dojo cloud-backup` must not report success"
    assert "BACKUP_AES_KEY_FILE must be set" in output or "S3_BACKUP_BUCKET must be set" in output, output


def test_node_show_reports_identity():
    output = dojo_run("dojo", "node", "show").stdout
    environment = config_env()
    workspace_node = int(environment["WORKSPACE_NODE"])
    assert f"DOJO_HOST: {environment['DOJO_HOST']}" in output, output
    assert f"WORKSPACE_NODE: {workspace_node}" in output, output
    assert f"WORKSPACE_HOST: {environment['WORKSPACE_HOST']}" in output, output
    assert f"WORKSPACE_SECRET: {environment['WORKSPACE_SECRET']}" in output, output

    public_key = environment["WORKSPACE_KEY"] or dojo_run("cat", "/data/wireguard/publickey").stdout.strip()
    assert f"WORKSPACE_KEY: {public_key}" in output, output
    assert "interface: wg0" in output, output
    if workspace_node == 0:
        assert f"public key: {public_key}" in output, output
        assert "listening port: 51820" in output, output


@pytest.mark.skipif(MULTINODE, reason="bouncing wireguard would disrupt registered worker nodes")
def test_node_refresh_is_stable_and_configures_main_interface():
    public_key = dojo_run("cat", "/data/wireguard/publickey").stdout
    private_key = dojo_run("cat", "/data/wireguard/privatekey").stdout
    nodes = dojo_run("cat", "/data/workspace_nodes.json").stdout

    dojo_run("rm", "-f", "/data/workspace_nodes.json")
    try:
        dojo_run("dojo", "node", "refresh")
        assert dojo_run("cat", "/data/workspace_nodes.json").stdout.strip() == "{}", \
            "`dojo node refresh` did not create an empty workspace_nodes.json"
    finally:
        dojo_run("sh", "-c", "cat > /data/workspace_nodes.json", input=nodes)

    assert dojo_run("cat", "/data/wireguard/publickey").stdout == public_key, \
        "`dojo node refresh` rotated the wireguard public key"
    assert dojo_run("cat", "/data/wireguard/privatekey").stdout == private_key, \
        "`dojo node refresh` rotated the wireguard private key"
    assert dojo_run("stat", "-c", "%a", "/data/wireguard/wg0.conf").stdout.strip() == "600", \
        "wg0.conf must not be world readable"

    config = dojo_run("cat", "/data/wireguard/wg0.conf").stdout
    assert "Address = 192.168.42.1/24" in config, config
    assert "ListenPort = 51820" in config, config
    assert "[Peer]" not in config, "a single-node dojo must not have wireguard peers"
    assert dojo_run("wg", "show", "wg0", "public-key").stdout.strip() == public_key.strip(), \
        "wg0 came back up with a different identity"
    assert "192.168.42.1/24" in dojo_run("ip", "-4", "addr", "show", "wg0").stdout


@pytest.mark.skipif(not MULTINODE, reason="requires a reachable workspace node")
def test_node_add_and_del_manage_wireguard_peers():
    node_id = max(WORKSPACE_NODES, key=int)
    node_key = WORKSPACE_NODES[node_id]
    nodes = dojo_run("cat", "/data/workspace_nodes.json").stdout
    topology_services = (
        "dojo-ctfd.service",
        "dojo-stats-worker.service",
        "dojo-image-pull-worker.service",
    )

    usage = dojo_run("dojo", "node", "add", check=False)
    usage_output = usage.stdout + usage.stderr
    assert "Usage:" in usage_output, usage_output
    assert dojo_run("cat", "/data/workspace_nodes.json").stdout == nodes, \
        "`dojo node add` without arguments modified workspace_nodes.json"

    before_delete = _service_invocation_ids(*topology_services)
    restored = None
    try:
        dojo_run("dojo", "node", "del", str(node_id))
        after_delete = _service_invocation_ids(*topology_services)
        assert all(after_delete[service] != before_delete[service] for service in topology_services), \
            f"topology consumers did not restart after node deletion: {before_delete} -> {after_delete}"

        registered = json.loads(dojo_run("cat", "/data/workspace_nodes.json").stdout)
        assert str(node_id) not in registered, registered
        assert str(node_id) not in _ctfd_workspace_nodes(), \
            "CTFd retained a deleted workspace node"
        config = dojo_run("cat", "/data/wireguard/wg0.conf").stdout
        assert f"PublicKey = {node_key}" not in config, config
        assert node_key not in dojo_run("wg", "show", "wg0").stdout, \
            "deleted peer survived on the live interface"

        if len(WORKSPACE_NODES) == 1:
            assert unit_is_active("dojo-dojofs"), "deleting the last worker did not restore single-node workspaces"

        before_add = after_delete
    finally:
        restored = dojo_run("dojo", "node", "add", str(node_id), node_key, check=False)

    assert restored.returncode == 0, restored.stdout + restored.stderr
    restored_nodes = json.loads(dojo_run("cat", "/data/workspace_nodes.json").stdout)
    assert restored_nodes == WORKSPACE_NODES, restored_nodes
    assert _ctfd_workspace_nodes() == WORKSPACE_NODES, \
        "CTFd did not load the restored workspace-node topology"
    after_add = _service_invocation_ids(*topology_services)
    assert all(after_add[service] != before_add[service] for service in topology_services), \
        f"topology consumers did not restart after node addition: {before_add} -> {after_add}"
    config = dojo_run("cat", "/data/wireguard/wg0.conf").stdout
    assert f"PublicKey = {node_key}" in config, config
    node_ip = int(node_id) + 1
    node_subnet = int(node_id) * 16
    assert f"AllowedIPs = 192.168.42.{node_ip}/32, 10.{node_subnet}.0.0/12" in config, config
    assert node_key in dojo_run("wg", "show", "wg0").stdout, "peer was not restored to the live interface"
    assert not unit_is_active("dojo-dojofs"), "adding a worker left single-node workspace hosting active"


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_node_mutation_denied_on_worker():
    nodes = dojo_run("cat", "/data/workspace_nodes.json", container=WORKER_CONTAINER, check=False).stdout

    added = dojo_run("dojo", "node", "add", "9", "key", container=WORKER_CONTAINER, check=False)
    added_output = added.stdout + added.stderr
    assert added.returncode == 1, added_output
    assert "only the main dojo node can add nodes" in added_output, added_output

    deleted = dojo_run("dojo", "node", "del", "9", container=WORKER_CONTAINER, check=False)
    deleted_output = deleted.stdout + deleted.stderr
    assert deleted.returncode == 1, deleted_output
    assert "only the main dojo node can delete nodes" in deleted_output, deleted_output

    assert dojo_run("cat", "/data/workspace_nodes.json", container=WORKER_CONTAINER, check=False).stdout == nodes


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_node_refresh_preserves_private_worker_docker_api():
    node_id = sorted(WORKSPACE_NODES)[0]
    docker_api = f"192.168.42.{int(node_id) + 1}:2375"
    hosts = json.loads(dojo_run("cat", "/run/dojo/docker-daemon.json", container=WORKER_CONTAINER).stdout)["hosts"]
    assert hosts == ["fd://"], hosts
    assert unit_is_active("dojo-docker-api", container=WORKER_CONTAINER), \
        "the worker Docker API proxy is not active"
    listeners = dojo_run(
        "ss", "-H", "-ltn", "sport = :2375", container=WORKER_CONTAINER
    ).stdout
    assert docker_api in listeners, listeners

    dojo_run("dojo", "node", "refresh", container=WORKER_CONTAINER)

    hosts = json.loads(dojo_run("cat", "/run/dojo/docker-daemon.json", container=WORKER_CONTAINER).stdout)["hosts"]
    assert hosts == ["fd://"], hosts
    assert unit_is_active("dojo-docker-api", container=WORKER_CONTAINER), \
        "the worker Docker API proxy stopped during `dojo node refresh`"
    listeners = dojo_run(
        "ss", "-H", "-ltn", "sport = :2375", container=WORKER_CONTAINER
    ).stdout
    assert docker_api in listeners, listeners


def test_load_dojo_spec_creates_usable_dojo(admin_session):
    dojo_id = f"cli-load-{_rand()}"
    path = _write_spec_in_ctfd(SPEC_TEMPLATE.format(dojo_id=dojo_id))
    try:
        result = dojo_run("dojo", "load-dojo", path, check=False)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]

        row = db_sql(
            "SELECT official, repository IS NULL, public_key IS NULL, private_key IS NULL "
            f"FROM dojos WHERE id = '{dojo_id}';"
        ).strip()
        assert row == "f|t|t|t", f"expected an unofficial, keyless, repository-less dojo, got {row}"

        owner = db_sql(
            "SELECT du.user_id, du.type FROM dojos d JOIN dojo_users du ON du.dojo_id = d.dojo_id "
            f"WHERE d.id = '{dojo_id}';"
        ).strip()
        assert owner == "1|admin", f"expected UID 1 to own the dojo as admin, got {owner}"

        reference_id, = _reference_ids(dojo_id)
        assert admin_session.get(f"{DOJO_URL}/dojo/{reference_id}/join/").status_code == 200
        assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200
        module_page = admin_session.get(f"{DOJO_URL}/{reference_id}/hello/")
        assert module_page.status_code == 200, module_page.status_code
        assert "Apple" in module_page.text, "the loaded challenge is not listed in the module"
    finally:
        _delete_dojos(dojo_id, admin_session)


def test_load_dojo_official_flag(admin_session):
    dojo_id = f"cli-load-{_rand()}"
    path = _write_spec_in_ctfd(SPEC_TEMPLATE.format(dojo_id=dojo_id))
    try:
        result = dojo_run("dojo", "load-dojo", "--official", path, check=False)
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
        assert db_sql(f"SELECT official FROM dojos WHERE id = '{dojo_id}';").strip() == "t"

        listing = requests.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
        assert listing.status_code == 200, listing.status_code
        listed = {dojo["id"]: dojo for dojo in listing.json()["dojos"]}
        assert dojo_id in listed, "an official dojo must show up in the public dojo listing"
        assert listed[dojo_id]["official"] is True, listed[dojo_id]

        assert admin_session.get(f"{DOJO_URL}/dojo/{dojo_id}/join/").status_code == 200
        solve_challenge_offline(dojo_id, "hello", "apple", session=admin_session, user="admin")
        solves = db_sql(
            "SELECT count(*) FROM submissions s JOIN dojo_challenges dc ON dc.challenge_id = s.challenge_id "
            f"JOIN dojos d ON d.dojo_id = dc.dojo_id WHERE d.id = '{dojo_id}' AND s.type = 'correct';"
        ).strip()
        assert int(solves) == 1, f"expected the CLI-loaded challenge to be solvable, got {solves} solves"
    finally:
        _delete_dojos(dojo_id, admin_session)


def test_load_dojo_user_resolution(admin_session, random_user):
    name, _ = random_user
    user_id = get_user_id(name)
    by_name = f"cli-load-{_rand()}"
    by_id = f"cli-load-{_rand()}"
    missing = f"cli-load-{_rand()}"
    try:
        for dojo_id, user_argument in ((by_name, name), (by_id, str(user_id))):
            path = _write_spec_in_ctfd(SPEC_TEMPLATE.format(dojo_id=dojo_id))
            result = dojo_run("dojo", "load-dojo", "--user", user_argument, path, check=False)
            assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
            owner = db_sql(
                "SELECT du.user_id, du.type FROM dojos d JOIN dojo_users du ON du.dojo_id = d.dojo_id "
                f"WHERE d.id = '{dojo_id}';"
            ).strip()
            assert owner == f"{user_id}|admin", f"--user {user_argument} resolved to {owner}"

        path = _write_spec_in_ctfd(SPEC_TEMPLATE.format(dojo_id=missing))
        result = dojo_run("dojo", "load-dojo", "--user", "no-such-user-xyz", path, check=False)
        assert result.returncode != 0, "an unresolvable --user must abort"
        assert int(db_sql(f"SELECT count(*) FROM dojos WHERE id = '{missing}';")) == 0, \
            "a dojo was created despite an unresolvable --user"
    finally:
        for dojo_id in (by_name, by_id, missing):
            _delete_dojos(dojo_id, admin_session)


def test_load_dojo_invalid_args():
    dojo_id = f"cli-load-{_rand()}"
    path = _write_spec_in_ctfd(SPEC_TEMPLATE.format(dojo_id=dojo_id))

    one_key = dojo_run("dojo", "load-dojo", "--public-key", "ssh-ed25519 AAAA", path, check=False)
    assert one_key.returncode == 1, one_key.stdout[-2000:]
    assert "Both the private and public key" in one_key.stdout + one_key.stderr, one_key.stdout[-2000:]

    no_location = dojo_run("dojo", "load-dojo", check=False)
    assert no_location.returncode == 2, no_location.stdout[-2000:]
    assert "usage:" in (no_location.stdout + no_location.stderr).lower(), no_location.stdout[-2000:]

    assert int(db_sql(f"SELECT count(*) FROM dojos WHERE id = '{dojo_id}';")) == 0, \
        "an invalid load-dojo invocation created a dojo"


def test_load_dojo_path_resolved_on_native_host(admin_session):
    dojo_id = f"cli-load-{_rand()}"
    spec = SPEC_TEMPLATE.format(dojo_id=dojo_id)
    outer_path = f"/tmp/{dojo_id}.yml"
    dojo_run("sh", "-c", f"cat > {outer_path}", input=spec)
    try:
        loaded = dojo_run("dojo", "load-dojo", outer_path, check=False)
        assert loaded.returncode == 0, loaded.stdout[-2000:] + loaded.stderr[-2000:]
        assert int(db_sql(f"SELECT count(*) FROM dojos WHERE id = '{dojo_id}';")) == 1
    finally:
        dojo_run("rm", "-f", outer_path, check=False)
        _delete_dojos(dojo_id, admin_session)


def test_load_dojo_duplicate_repository_rejected(example_dojo):
    repository = "pwncollege/example-dojo"
    before = int(db_sql(f"SELECT count(*) FROM dojos WHERE repository = '{repository}';"))
    assert before >= 1, "the example dojo is expected to be registered by its repository"
    result = dojo_run("dojo", "load-dojo", repository, check=False)
    assert result.returncode != 0, "loading an already registered repository must fail"
    assert "already exists as a dojo" in result.stdout + result.stderr, result.stdout[-2000:]
    assert int(db_sql(f"SELECT count(*) FROM dojos WHERE repository = '{repository}';")) == before


def test_load_dojo_duplicate_spec_id_creates_second_row(admin_session):
    dojo_id = f"cli-load-{_rand()}"
    spec = SPEC_TEMPLATE.format(dojo_id=dojo_id)
    try:
        for _ in range(2):
            path = _write_spec_in_ctfd(spec)
            result = dojo_run("dojo", "load-dojo", path, check=False)
            assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]

        rows = _dojo_rows(dojo_id)
        assert len(rows) == 2, f"expected loading the same spec twice to fork the dojo, got {rows}"
        assert len(set(rows)) == 2, "the two dojo rows share a dojo_id"
        for reference_id in _reference_ids(dojo_id):
            assert admin_session.get(f"{DOJO_URL}/{reference_id}/").status_code == 200, \
                f"{reference_id} is not reachable"
    finally:
        _delete_dojos(dojo_id, admin_session)


@pytest.mark.skipif(MULTINODE, reason="challenge images are pulled onto the workspace nodes")
def test_pull_images_pulls_challenge_images(admin_session):
    dojo_id = f"cli-pull-{_rand()}"
    unpullable = f"pwncollege/definitely-not-real-{_rand()}"
    spec = f"""
id: {dojo_id}
name: CLI Pull {dojo_id}
modules:
  - id: images
    name: Images
    challenges:
      - id: real
        name: Real
        image: pwncollege/challenge-simple
      - id: broken
        name: Broken
        image: {unpullable}
      - id: mac
        name: Mac
        image: mac:cli-probe-{_rand()}
"""
    create_dojo_yml(spec, session=admin_session)
    try:
        result = dojo_run("dojo", "flask", "--", PULL_IMAGES_SCRIPT, check=False, timeout=180)
        output = result.stdout + result.stderr
        assert result.returncode == 0, "pull_images must tolerate unpullable images"
        assert "Pulling image pwncollege/challenge-simple" in output, output[-2000:]
        assert f"Pulling image {unpullable}" in output, output[-2000:]
        assert re.search(rf"(image not found|error): {re.escape(unpullable)}", output), \
            f"the unpullable image was not reported: {output[-2000:]}"
        assert "Pulling image mac:" not in output, "mac images must not be pulled on docker daemons"
        assert "Pulling image pwncollege-" not in output, "prebuilt workspace images must not be pulled"
        assert dojo_run("docker", "image", "inspect", "pwncollege/challenge-simple", check=False).returncode == 0
    finally:
        _delete_dojos(dojo_id, admin_session)


@pytest.mark.skipif(MULTINODE, reason="home subvolumes are activated on the node that mounts them")
def test_homefs_provisions_subvolume_layout(cli_user, random_user):
    fresh_name, _ = random_user
    fresh_user_id = get_user_id(fresh_name)
    subvolumes = dojo_run("btrfs", "subvolume", "list", "/data/homes").stdout
    assert not re.search(rf"path {fresh_user_id}$", subvolumes, re.M), \
        "a home was provisioned for a user who never started a challenge"

    name, _ = cli_user
    user_id = get_user_id(name)
    for path in (f"{user_id}", f"{user_id}/snapshots", f"{user_id}/overlays", f"{user_id}/active"):
        assert re.search(rf"path {re.escape(path)}$", subvolumes, re.M), f"missing btrfs subvolume {path}"

    assert dojo_run("ls", f"/data/homes/{user_id}/snapshots").stdout.split(), "no snapshot was taken"

    mountinfo = workspace_run("cat /proc/self/mountinfo", user=name).stdout
    home_mounts = [line for line in mountinfo.splitlines() if " /home/hacker " in line]
    assert home_mounts, mountinfo
    assert f"/{user_id}/active" in home_mounts[0], home_mounts[0]
    assert workspace_run("stat -c %i /home/hacker", user=name).stdout.strip() == "256", \
        "/home/hacker is not the root of a btrfs subvolume"


@pytest.mark.skipif(MULTINODE, reason="home subvolumes are activated on the node that mounts them")
def test_homefs_enforces_1g_quota(cli_user):
    name, _ = cli_user
    user_id = get_user_id(name)
    try:
        overflow = workspace_run("dd if=/dev/zero of=/home/hacker/cli-big bs=1M count=1200 2>&1; true", user=name)
        assert "Disk quota exceeded" in overflow.stdout, overflow.stdout[-500:]
        size = int(workspace_run("stat -c %s /home/hacker/cli-big", user=name).stdout)
        assert size <= 1024 ** 3 + 8 * 1024 ** 2, f"quota let {size} bytes through"
    finally:
        workspace_run("rm -f /home/hacker/cli-big", user=name)

    assert workspace_run("echo ok", user=name).stdout.strip() == "ok", "the container did not survive the quota"
    assert workspace_run("echo ok > /tmp/cli-quota-probe && cat /tmp/cli-quota-probe", user=name).stdout.strip() == "ok", \
        "writes outside the home must be unaffected"

    qgroups = dojo_run("btrfs", "qgroup", "show", "-re", "/data/homes").stdout
    assert re.search(rf"^\S+\s+\S+\s+\S+\s+1\.00GiB\s+\S+\s+{user_id}/active$", qgroups, re.M), \
        f"no 1GiB qgroup limit registered for {user_id}/active"


@pytest.mark.skipif(MULTINODE, reason="home subvolumes are activated on the node that mounts them")
def test_homefs_home_survives_volume_recreation(cli_user, example_dojo):
    name, session = cli_user
    user_id = get_user_id(name)
    outer_container = get_outer_container_for(f"user_{user_id}")
    marker = _rand()
    workspace_run(f"echo {marker} > /home/hacker/cli-marker", user=name)
    assert dojo_run("docker", "volume", "inspect", str(user_id), check=False,
                    container=outer_container).returncode == 0, "the user's home volume does not exist"

    start_challenge(example_dojo, "hello", "apple", session=session)

    assert workspace_run("cat /home/hacker/cli-marker", user=name).stdout.strip() == marker, \
        "the home directory did not survive the volume being destroyed and recreated"
    assert dojo_run("cat", f"/data/homes/{user_id}/active/cli-marker").stdout.strip() == marker
    workspace_run("rm -f /home/hacker/cli-marker", user=name)


def test_homefs_driver_unknown_volume_404():
    for endpoint, payload in [
        ("Get", {"Name": "no-such-vol"}),
        ("Path", {"Name": "no-such-vol"}),
        ("Mount", {"Name": "no-such-vol", "ID": "x"}),
        ("Unmount", {"Name": "no-such-vol", "ID": "x"}),
        ("Remove", {"Name": "no-such-vol"}),
    ]:
        status, body = _homefs_driver(endpoint, payload)
        assert status == 404, f"{endpoint} returned {status}: {body}"
        assert json.loads(body)["Err"] == "Volume no-such-vol not found", body
    assert dojo_run("test", "-e", "/data/homes/no-such-vol", check=False).returncode != 0, \
        "a failed lookup provisioned storage"


def test_homefs_driver_duplicate_create_409():
    volume = f"cli-probe-{_rand()}"
    try:
        status, body = _homefs_driver("Create", {"Name": volume})
        assert status == 200, body
        assert json.loads(body)["Err"] == "", body

        status, body = _homefs_driver("Create", {"Name": volume})
        assert status == 409, f"duplicate create returned {status}: {body}"
        assert "already exists" in json.loads(body)["Err"], body

        _, listing = _homefs_driver("List", {})
        names = [entry["Name"] for entry in json.loads(listing)["Volumes"]]
        assert names.count(volume) == 1, names
    finally:
        _destroy_probe_volume(volume)
    _, listing = _homefs_driver("List", {})
    assert volume not in [entry["Name"] for entry in json.loads(listing)["Volumes"]]


def test_homefs_driver_remove_keeps_storage():
    volume = f"cli-probe-{_rand()}"
    try:
        status, _ = _homefs_driver("Create", {"Name": volume})
        assert status == 200
        assert _curl_status(f"http://localhost:4201/volume/{volume}") == 200
        assert dojo_run("test", "-d", f"/data/homes/{volume}", check=False).returncode == 0

        status, body = _homefs_driver("Remove", {"Name": volume})
        assert status == 200, body
        assert json.loads(body)["Err"] == "", body
        assert dojo_run("test", "-d", f"/data/homes/{volume}", check=False).returncode == 0, \
            "VolumeDriver.Remove destroyed the underlying btrfs storage"
    finally:
        _destroy_probe_volume(volume)


@pytest.mark.skipif(MULTINODE, reason="home subvolumes are activated on the node that mounts them")
def test_homefs_driver_list_mountpoints(cli_user):
    name, _ = cli_user
    user_id = get_user_id(name)
    _, listing = _homefs_driver("List", {})
    volumes = {entry["Name"]: entry["Mountpoint"] for entry in json.loads(listing)["Volumes"]}
    assert volumes.get(str(user_id)) == f"/run/homefs/{user_id}/active", volumes.get(str(user_id))

    _, body = _homefs_driver("Path", {"Name": str(user_id)})
    assert json.loads(body)["Mountpoint"] == f"/run/homefs/{user_id}/active", body

    _, body = _homefs_driver("Get", {"Name": str(user_id)})
    assert json.loads(body)["Volume"]["Mountpoint"] == f"/run/homefs/{user_id}/active", body


def test_homefs_activate_records_owning_host():
    volume = f"cli-probe-{_rand()}"
    try:
        status, body = _curl(f"http://localhost:4201/volume/{volume}/activate", "-XPOST")
        assert status == 201, f"{status}: {body}"
        status, body = _curl(f"http://localhost:4201/volume/{volume}/activate", "-XPOST")
        assert status == 201, f"re-activation from the same host must succeed: {status} {body}"

        dojo_run(
            "python3", "-c",
            "import sqlite3, sys; connection = sqlite3.connect('/run/homefs/homefs.db'); "
            "connection.execute(\"UPDATE active_volumes SET host='10.255.255.1' WHERE name=?\", "
            "(sys.argv[1],)); connection.commit()", volume,
        )

        status, body = _curl(f"http://localhost:4201/volume/{volume}/activate", "-XPOST")
        assert status == 409, f"a volume active on another host must be refused: {status} {body}"
        assert "Volume already active" in body, body
    finally:
        _delete_homefs_active_record(volume)
        _destroy_probe_volume(volume)


def test_homefs_stale_local_active_record_recovers():
    volume = f"cli-probe-{_rand()}"
    try:
        status, body = _homefs_driver("Create", {"Name": volume})
        assert status == 200, body
        status, body = _homefs_driver("Mount", {"Name": volume, "ID": "initial"})
        assert status == 200, body

        dojo_run("btrfs", "subvolume", "delete", f"/data/homes/{volume}/active")

        status, body = _curl(
            "http://localhost/VolumeDriver.Mount",
            "--unix-socket", "/run/docker/plugins/homefs.sock",
            "--max-time", "10", "-XPOST",
            "-d", json.dumps({"Name": volume, "ID": "recovery"}),
        )
        assert status == 200, body
        assert dojo_run(
            "test", "-e", f"/data/homes/{volume}/active", check=False,
        ).returncode == 0
    finally:
        _delete_homefs_active_record(volume)
        _destroy_probe_volume(volume)


def test_homefs_snapshot_etag_304(cli_user):
    name, _ = cli_user
    user_id = get_user_id(name)
    headers = dojo_run("curl", "-s", "-D-", "-o", "/dev/null", f"http://localhost:4201/volume/{user_id}").stdout
    match = re.search(r"(?i)^ETag: (\S+)", headers, re.M)
    assert match, headers
    etag = match.group(1)
    snapshots = sorted(dojo_run("ls", f"/data/homes/{user_id}/snapshots").stdout.split())
    assert etag == snapshots[-1], f"ETag {etag} is not the latest snapshot {snapshots[-1]}"

    cached = dojo_run("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                      "-H", f"If-None-Match: {etag}", f"http://localhost:4201/volume/{user_id}").stdout
    assert cached.strip() == "304", f"expected a 304 for an unchanged snapshot, got {cached}"

    stream = dojo_run("sh", "-c", f"curl -s http://localhost:4201/volume/{user_id} | head -c 12").stdout
    assert stream.startswith("btrfs-stream"), repr(stream)


def test_homefs_put_invalid_stream_400():
    volume = f"cli-probe-{_rand()}"
    try:
        status, _ = _homefs_driver("Create", {"Name": volume})
        assert status == 200
        assert _curl_status(f"http://localhost:4201/volume/{volume}") == 200
        before = dojo_run("ls", f"/data/homes/{volume}/snapshots").stdout.split()

        status, body = _curl(f"http://localhost:4201/volume/{volume}", "-XPUT",
                             "--data-binary", "not-a-btrfs-stream")
        assert status == 400, f"expected a 400 for an invalid send stream, got {status}: {body}"
        assert "ERROR" in body, body
        assert dojo_run("ls", f"/data/homes/{volume}/snapshots").stdout.split() == before, \
            "an invalid send stream created a snapshot"
    finally:
        _destroy_probe_volume(volume)


@pytest.mark.skipif(MULTINODE, reason="home subvolumes are activated on the node that mounts them")
def test_homefs_overlay_isolation(cli_user, admin_user, example_dojo):
    name, _ = cli_user
    user_id = get_user_id(name)
    admin_name, admin_session = admin_user
    admin_id = get_user_id(admin_name)
    overlay_volume = f"{admin_id}-overlay"
    overlay_path = f"/data/homes/{user_id}/overlays/{overlay_volume}"

    workspace_run("echo base > /home/hacker/cli-base.txt", user=name)
    start_challenge(example_dojo, "hello", "apple", session=admin_session, as_user=user_id)
    outer_container = get_outer_container_for(f"user_{admin_id}")
    try:
        assert workspace_run("cat /home/hacker/cli-base.txt", user=admin_name).stdout.strip() == "base", \
            "the overlay does not expose the target user's existing files"

        workspace_run("echo overlay > /home/hacker/cli-overlay.txt", user=admin_name)
        assert dojo_run("cat", f"{overlay_path}/cli-overlay.txt").stdout.strip() == "overlay"
        assert dojo_run("test", "-e", f"/data/homes/{user_id}/active/cli-overlay.txt", check=False).returncode != 0, \
            "an overlay write leaked into the target user's home"

        mountinfo = workspace_run("cat /proc/self/mountinfo", user=admin_name).stdout.splitlines()
        home_mounts = [line for line in mountinfo if " /home/hacker " in line]
        own_mounts = [line for line in mountinfo if " /home/me " in line]
        assert home_mounts and f"/{user_id}/overlays/{overlay_volume}" in home_mounts[0], home_mounts
        assert own_mounts and f"/{admin_id}/active" in own_mounts[0], \
            f"the admin's own home is not mounted at /home/me: {own_mounts}"
    finally:
        remove_workspace_container(admin_name)

    dojo_run("docker", "volume", "rm", overlay_volume, check=False, container=outer_container)
    assert dojo_run("test", "-e", overlay_path, check=False).returncode != 0, \
        "removing the overlay volume did not delete the overlay subvolume"
    assert dojo_run("cat", f"/data/homes/{user_id}/active/cli-base.txt").stdout.strip() == "base", \
        "removing the overlay volume damaged the target user's home"
    workspace_run("rm -f /home/hacker/cli-base.txt", user=name)


def test_dojofs_privileged_flag(cli_user, practice_cli_user, privileged_cli_user):
    standard_name, _ = cli_user
    practice_name, _ = practice_cli_user
    privileged_name, _ = privileged_cli_user

    assert workspace_run("cat /run/dojo/sys/workspace/privileged", user=practice_name).stdout == "1\n", \
        "a practice-mode container must report itself as privileged"
    assert workspace_run("cat /run/dojo/sys/workspace/privileged", user=standard_name).stdout == "0\n", \
        "a standard container must not report itself as privileged"
    assert workspace_run("cat /run/dojo/sys/workspace/privileged", user=privileged_name).stdout == "0\n", \
        "a non-practice container of a privileged dojo must not report itself as privileged"

    for name, expected_mode in ((practice_name, "privileged"), (standard_name, "standard"),
                                (privileged_name, "standard")):
        container = f"user_{get_user_id(name)}"
        outer_container = get_outer_container_for(container)
        mode = dojo_run("docker", "inspect", "-f", '{{index .Config.Labels "dojo.mode"}}', container,
                        container=outer_container).stdout.strip()
        assert mode == expected_mode, f"{container} has dojo.mode={mode}, expected {expected_mode}"
        runtime = dojo_run(
            "docker", "inspect", "-f", "{{.HostConfig.Runtime}}", container,
            container=outer_container,
        ).stdout.strip()
        expected_runtime = "io.containerd.run.kata.v2" if name == privileged_name else "runc"
        assert runtime == expected_runtime, \
            f"{container} uses runtime={runtime}, expected {expected_runtime}"


def test_dojofs_readonly_and_path_errors(cli_user):
    name, _ = cli_user
    write = workspace_run("echo x > /run/dojo/sys/workspace/privileged; true", user=name, root=True)
    write_error = write.stdout + write.stderr
    assert "Read-only file system" in write_error or "Permission denied" in write_error, write_error

    missing = workspace_run("cat /run/dojo/sys/workspace/nope 2>&1; true", user=name)
    assert "No such file or directory" in missing.stdout, missing.stdout

    directory = workspace_run("cat /run/dojo/sys/workspace 2>&1; true", user=name)
    assert "Is a directory" in directory.stdout, directory.stdout

    assert workspace_run("ls /run/dojo/sys/workspace", user=name).stdout.split() == ["privileged"]


def test_dojofs_outside_container_eio():
    result = dojo_run(
        "sh", "-c", "cat /run/dojo/dojofs/workspace/privileged 2>&1; echo rc=$?",
        container=WORKSPACE_CONTAINER,
    )
    assert "Input/output error" in result.stdout, result.stdout
    assert "rc=1" in result.stdout, result.stdout
    assert dojo_run(
        "stat", "-c", "%s", "/run/dojo/dojofs/workspace/privileged", container=WORKSPACE_CONTAINER
    ).stdout.strip() == "0", \
        "the privileged file has a size outside of a container"


@pytest.mark.skipif(MULTINODE, reason="a shifted-clock reaper run would evict live worker containers")
def test_watchdog_reaps_old_user_containers(cli_user, example_dojo):
    name, session = cli_user
    container = f"user_{get_user_id(name)}"
    script = (
        "import datetime\n"
        "real = datetime.datetime\n"
        "class Fake(real):\n"
        "    @classmethod\n"
        "    def now(cls, tz=None): return real.now(tz) + datetime.timedelta(hours=7)\n"
        "datetime.datetime = Fake\n"
        "source = '/opt/pwn.college/watchdog/docker_remove_containers.py'\n"
        "globals_ = {'__file__': source, '__name__': '__main__'}\n"
        "exec(open(source).read(), globals_)\n"
    )
    result = dojo_run("python3", "-c", script, check=False)
    output = result.stdout + result.stderr
    assert "Removing old docker container" in output, output[-2000:]
    running = dojo_run("docker", "ps", "--format", "{{.Names}}").stdout.split()
    assert container not in running, "the reaper left a 7-hour-old user container running"

    # The shifted clock makes every running workspace look old, so put this
    # module's shared container back for the tests that come after.
    start_challenge(example_dojo, "hello", "apple", session=session)


def test_watchdog_spares_fresh_user_and_native_services(cli_user):
    name, _ = cli_user
    container = f"user_{get_user_id(name)}"
    outer_container = get_outer_container_for(container)
    infrastructure = {
        "dojo-ctfd", "dojo-stats-worker", "dojo-image-pull-worker", "dojo-nginx",
        "dojo-frontend", "dojo-homefs",
    }

    result = dojo_run("docker_remove_containers", check=False)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-2000:]
    assert "Removing old docker container" not in output, output[-2000:]
    assert "Removing large docker container" not in output, output[-2000:]

    assert container in dojo_run("docker", "ps", "--format", "{{.Names}}",
                                 container=outer_container).stdout.split(), \
        "the reaper removed a freshly started user container"
    inactive = {unit for unit in infrastructure if not unit_is_active(unit)}
    assert not inactive, f"the reaper disrupted native services: {inactive}"


def test_watchdog_sweeps_every_daemon_hosting_user_containers(cli_user):
    name, _ = cli_user
    container = f"user_{get_user_id(name)}"
    host = get_outer_container_for(container)

    result = dojo_run("docker_remove_containers")
    output = result.stdout + result.stderr
    swept = re.findall(r"Removing docker containers on (\S+)", output)
    assert swept, "no docker daemon was swept, so no user container can ever be reaped"

    if host == DOJO_CONTAINER:
        assert any("localhost" in daemon or "unix" in daemon for daemon in swept), \
            f"the daemon hosting {container} was not swept: {swept}"
    else:
        # The docker client reports the url it dialed, whose scheme it rewrites.
        node_id = int(host.rsplit("node", 1)[1])
        expected = f"192.168.42.{node_id + 1}:2375"
        assert any(expected in daemon for daemon in swept), \
            f"the daemon hosting {container} ({expected}) was not swept: {swept}"


def test_watchdog_timers_are_active():
    timers = {"dojo-watchdog-cleanup.timer", "dojo-watchdog-prune.timer"}
    for timer in timers:
        assert unit_is_active(timer), f"{timer} is not active"
        enabled = systemctl("is-enabled", timer, check=False)
        assert enabled.returncode == 0, f"{timer} is not enabled: {enabled.stdout}{enabled.stderr}"

    listing = systemctl("list-timers", "--all", "--no-pager", "--no-legend").stdout
    for timer in timers:
        assert timer in listing, f"{timer} has no scheduled trigger: {listing}"

    started = time.time()
    cleanup = systemctl("start", "dojo-watchdog-cleanup.service", check=False)
    assert cleanup.returncode == 0, cleanup.stdout + cleanup.stderr
    logs = journalctl("dojo-watchdog-cleanup", "--since", f"@{started}", check=False).stdout
    assert "[docker_remove_containers.py] [INFO] Starting" in logs, logs
    assert "[docker_remove_containers.py] [INFO] Finished" in logs, logs


@pytest.mark.skipif(MULTINODE, reason="the pruner targets the workspace nodes, not the main daemon")
def test_watchdog_prunes_dangling_images():
    target = WORKER_CONTAINER if MULTINODE else DOJO_CONTAINER
    tag = f"cli-prune-{_rand()}"
    existing = set(dojo_run("docker", "images", "-qf", "dangling=true", container=target).stdout.split())
    created = set()
    try:
        dojo_run(
            "sh", "-c",
            f'tar -C /tmp --files-from /dev/null -cf - | '
            f'docker import --change "LABEL probe=one" - {tag} >/dev/null && '
            f'tar -C /tmp --files-from /dev/null -cf - | '
            f'docker import --change "LABEL probe=two" - {tag} >/dev/null',
            container=target,
        )
        created = set(dojo_run("docker", "images", "-qf", "dangling=true",
                               container=target).stdout.split()) - existing
        assert created, "failed to create a dangling image"

        result = dojo_run("docker_prune_images", check=False)
        output = result.stdout + result.stderr
        assert result.returncode == 0, output[-2000:]
        assert "Prune docker images complete" in output, output[-2000:]

        remaining = set(dojo_run("docker", "images", "-qf", "dangling=true", container=target).stdout.split())
        assert not created & remaining, f"dangling images survived the prune: {created & remaining}"
        assert dojo_run("docker", "image", "inspect", "pwncollege/challenge-simple", check=False,
                        container=target).returncode == 0, "the pruner removed a tagged image"
    finally:
        dojo_run("docker", "rmi", "-f", tag, check=False, container=target)
        for image in created:
            dojo_run("docker", "rmi", "-f", image, check=False, container=target)


def test_storage_homes_quota_enabled():
    assert dojo_run("findmnt", "-nro", "FSTYPE", "--", "/data/homes").stdout.strip() == "btrfs"
    quota = dojo_run("btrfs", "qgroup", "show", "-re", "/data/homes", check=False)
    output = quota.stdout + quota.stderr
    assert quota.returncode == 0, output
    assert "quotas not enabled" not in output, output
    assert "Qgroupid" in quota.stdout, quota.stdout

    homes_source = dojo_run("findmnt", "-nro", "SOURCE", "--", "/data/homes").stdout.strip()
    storage_source = dojo_run("findmnt", "-nro", "SOURCE", "--", "/run/homefs").stdout.strip()
    assert homes_source == storage_source, f"{homes_source} != {storage_source}"

    if homes_source.startswith("/dev/loop"):
        autoclear = dojo_run(
            "losetup", "--noheadings", "--output", "AUTOCLEAR", homes_source,
        ).stdout.split()
        assert autoclear and set(autoclear) == {"1"}, autoclear


def test_storage_ssh_host_keys_persist():
    stored = dojo_run("ls", "/data/ssh_host_keys").stdout.split()
    assert any(name.startswith("ssh_host_ed25519_key") for name in stored), stored

    fingerprint = dojo_run("ssh-keygen", "-lf", "/data/ssh_host_keys/ssh_host_ed25519_key.pub").stdout.split()[1]
    live = dojo_run("sh", "-c", "ssh-keyscan -t ed25519 -p 22 localhost 2>/dev/null | ssh-keygen -lf -").stdout
    assert fingerprint in live, f"the live sshd is not serving the persisted host key: {live}"


def test_workspace_egress_policy(cli_user):
    name, _ = cli_user
    status = workspace_run("curl -s -o /dev/null -w %{http_code} --max-time 10 http://pwn.college/", user=name)
    assert status.stdout.strip() == "200", f"a workspace must reach the dojo web service: {status.stdout}"

    blocked = workspace_run("curl -s -o /dev/null --max-time 5 http://1.1.1.1/; echo rc=$?", user=name)
    assert "rc=0" not in blocked.stdout, "arbitrary outbound traffic was not dropped"

    rules = dojo_run("iptables", "-S", "WORKSPACE-NET").stdout.strip().splitlines()
    assert rules[-1] == "-A WORKSPACE-NET -j DROP", f"WORKSPACE-NET does not end in DROP: {rules[-1]}"
    docker_user = dojo_run("iptables", "-S", "DOCKER-USER").stdout
    assert "-A DOCKER-USER -i workspace_net -j WORKSPACE-NET" in docker_user, docker_user
    assert "-A DOCKER-USER -o workspace_net -j WORKSPACE-NET" in docker_user, docker_user


@pytest.mark.order(-1)
@pytest.mark.skipif(MULTINODE, reason="re-running native network initialization would bounce the cluster's wireguard tunnels")
def test_config_and_storage_rerun_preserve_secrets_and_host_keys(admin_session):
    before = dojo_run("cat", "/data/config.env").stdout
    fingerprint = dojo_run("ssh-keygen", "-lf", "/data/ssh_host_keys/ssh_host_ed25519_key.pub").stdout.split()[1]

    for command in ("dojo-config", "dojo-storage"):
        result = dojo_run(command, check=False, timeout=120)
        assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]

    after = dojo_run("cat", "/data/config.env").stdout
    assert after == before, "native initialization rewrote config.env, rotating generated secrets"
    assert dojo_run("ssh-keygen", "-lf", "/data/ssh_host_keys/ssh_host_ed25519_key.pub").stdout.split()[1] == \
        fingerprint, "native initialization regenerated the ssh host keys"
    assert admin_session.get(f"{DOJO_URL}/dojos").status_code == 200, \
        "an existing session broke across native initialization"


@pytest.mark.order(-1)
@pytest.mark.skipif(MULTINODE, reason="re-running native network initialization would bounce the cluster's wireguard tunnels")
def test_network_docker_user_rules_idempotent(cli_user):
    name, _ = cli_user
    inbound = "-A DOCKER-USER -i workspace_net -j WORKSPACE-NET"
    outbound = "-A DOCKER-USER -o workspace_net -j WORKSPACE-NET"
    default_bridge_input = "-A INPUT -i docker0 -j WORKSPACE-NET"

    result = dojo_run("dojo-network", check=False, timeout=120)
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]

    rules = dojo_run("iptables", "-S", "DOCKER-USER").stdout
    input_rules = dojo_run("iptables", "-S", "INPUT").stdout
    workspace_rules = dojo_run("iptables", "-S", "WORKSPACE-NET").stdout.strip().splitlines()
    assert workspace_rules[-1] == "-A WORKSPACE-NET -j DROP", workspace_rules[-1]
    status = workspace_run("curl -s -o /dev/null -w %{http_code} --max-time 10 http://pwn.college/", user=name)
    assert status.stdout.strip() == "200", "workspaces lost access to the dojo after network initialization"

    assert rules.count(inbound) == 1, f"DOCKER-USER accumulated inbound jumps:\n{rules}"
    assert rules.count(outbound) == 1, f"DOCKER-USER accumulated outbound jumps:\n{rules}"
    default_bridge_rules = [
        rule for rule in rules.splitlines()
        if "-i docker0" in rule
        and "-d 192.168.42.0/24" in rule
        and rule.endswith("-j WORKSPACE-NET")
    ]
    assert len(default_bridge_rules) == 1, f"DOCKER-USER accumulated default-bridge jumps:\n{rules}"
    assert input_rules.count(default_bridge_input) == 1, f"INPUT accumulated default-bridge jumps:\n{input_rules}"
