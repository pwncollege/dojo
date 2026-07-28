import datetime
import json
import random
import re
import string
import time

import pytest
import requests

from utils import (
    DOJO_CONTAINER,
    DOJO_URL,
    create_dojo_yml,
    db_sql,
    dojo_run,
    get_outer_container_for,
    get_user_id,
    login,
    remove_workspace_container,
    solve_challenge_offline,
    start_challenge,
    workspace_run,
)


CLI_SUBCOMMANDS = [
    "up", "update", "sync", "enter", "compose", "node", "flask", "db", "backup",
    "restore", "cloud-backup", "vscode", "logs", "load-dojo", "wait", "init", "help",
]

PULL_IMAGES_SCRIPT = "/opt/CTFd/CTFd/plugins/dojo_plugin/scripts/pull_images.py"

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


def _config_env(container=None):
    return dict(
        line.split("=", 1)
        for line in dojo_run("cat", "/data/config.env", container=container or DOJO_CONTAINER).stdout.splitlines()
        if "=" in line
    )


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


def _homefs_driver(endpoint, payload):
    return _curl(f"http://localhost:4201/VolumeDriver.{endpoint}", "-XPOST", "-d", json.dumps(payload))


def _destroy_probe_volume(name):
    _homefs_driver("Remove", {"Name": name})
    dojo_run(
        "sh", "-c",
        f"for subvolume in /data/homes/{name}/snapshots/* /data/homes/{name}/overlays/* "
        f"/data/homes/{name}/snapshots /data/homes/{name}/overlays /data/homes/{name}/active "
        f"/data/homes/{name}; do btrfs subvolume delete \"$subvolume\" 2>/dev/null; done; true",
        check=False,
    )


def _rerun_dojo_init():
    # dojo-init truncates ssh_known_hosts before re-scanning github, so a flaky lookup here would
    # break every later dojo clone in the suite.
    known_hosts = dojo_run("cat", "/data/ssh_host_keys/ssh_known_hosts", check=False).stdout
    try:
        return dojo_run("dojo-init", check=False, timeout=120)
    finally:
        if known_hosts.strip() and not dojo_run(
            "cat", "/data/ssh_host_keys/ssh_known_hosts", check=False
        ).stdout.strip():
            dojo_run("sh", "-c", "cat > /data/ssh_host_keys/ssh_known_hosts", input=known_hosts)


def _write_spec_in_ctfd(spec):
    path = f"/tmp/cli-load-{_rand()}.yml"
    dojo_run("docker", "exec", "-i", "ctfd", "sh", "-c", f"cat > {path}", input=spec)
    return path


def _dojo_rows(dojo_id):
    output = db_sql(f"SELECT dojo_id FROM dojos WHERE id = '{dojo_id}';").split()
    return [int(dojo_id_value) for dojo_id_value in output]


def _reference_ids(dojo_id):
    return [f"{dojo_id}~{row & 0xFFFFFFFF:08x}" for row in _dojo_rows(dojo_id)]


def _delete_dojos(dojo_id, admin_session):
    for reference_id in _reference_ids(dojo_id):
        admin_session.post(f"{DOJO_URL}/dojo/{reference_id}/delete/", json={"dojo": reference_id})


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


def test_help_lists_every_annotated_subcommand():
    for args in (["help"], []):
        invocation = f"dojo {' '.join(args)}".strip()
        result = dojo_run("dojo", *args, check=False)
        assert result.returncode == 0, f"`{invocation}` exited {result.returncode}"
        assert "COMMANDS:" in result.stdout, f"`{invocation}` printed no command list"
        for command in CLI_SUBCOMMANDS:
            assert re.search(rf"^\t{re.escape(command)}[: ]", result.stdout, re.M), \
                f"`{invocation}` does not document the `{command}` subcommand"


def test_unknown_subcommand_exits_nonzero():
    result = dojo_run("dojo", "not-a-real-command", check=False)
    assert result.returncode == 1, f"`dojo not-a-real-command` exited {result.returncode}"
    assert "Unknown command" in result.stdout, result.stdout
    assert "COMMANDS:" in result.stdout, "unknown command did not print the help text"

    node_result = dojo_run("dojo", "node", "not-a-real-command", check=False)
    assert node_result.returncode == 1, f"`dojo node not-a-real-command` exited {node_result.returncode}"
    assert "Unknown command" in node_result.stdout, node_result.stdout
    assert "COMMANDS:" in node_result.stdout, "unknown node command did not print the help text"


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
    dojo_run("docker", "exec", "-i", "ctfd", "sh", "-c", f"cat > {failing_script}",
             input='raise RuntimeError("cli-probe-boom")\n')
    failing = dojo_run("dojo", "flask", "--", failing_script, check=False)
    assert failing.returncode != 0, "script-mode `dojo flask` must propagate a failing script"

    marker = _rand()
    working_script = "/tmp/cli-flask-ok.py"
    dojo_run("docker", "exec", "-i", "ctfd", "sh", "-c", f"cat > {working_script}",
             input=f'print("{marker}")\n')
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


@pytest.mark.skipif(MULTINODE, reason="single-node profile selection")
def test_compose_selects_singlenode_profiles():
    services = set(dojo_run("dojo", "compose", "config", "--services").stdout.split())
    expected = {
        "ctfd", "db", "cache", "nginx", "sshd", "stats-worker", "image-pull-worker",
        "homefs", "dojofs", "watchdog", "workspace-builder",
    }
    assert expected <= services, f"missing services: {expected - services}"
    assert "nginx-workspace" not in services, "worker-only service selected on a single-node dojo"
    assert "splunk" not in services, "splunk profile selected without ENABLE_SPLUNK"

    config = dojo_run("dojo", "compose", "config").stdout
    environment = _config_env()
    assert f"DOJO_HOST: {environment['DOJO_HOST']}" in config, "config.env was not interpolated into the compose config"
    assert f"WORKSPACE_HOST: {environment['WORKSPACE_HOST']}" in config, config[:200]


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_compose_selects_profiles_by_node_role():
    worker_services = set(dojo_run("dojo", "compose", "config", "--services", container=WORKER_CONTAINER).stdout.split())
    assert "nginx-workspace" in worker_services, worker_services
    assert "dojofs" in worker_services, worker_services
    assert "ctfd" not in worker_services, "a workspace node must not run ctfd"
    assert "db" not in worker_services, "a workspace node must not run the database"
    assert "sshd" not in worker_services, "a workspace node must not run sshd"

    main_services = set(dojo_run("dojo", "compose", "config", "--services").stdout.split())
    assert "ctfd" in main_services, main_services
    assert "dojofs" not in main_services, "the main node of a multinode dojo must not host workspaces"
    assert "workspace-builder" not in main_services, main_services


def test_startup_gates_are_satisfied():
    builder = dojo_run("docker", "inspect", "-f", "{{.State.ExitCode}}", "workspace-builder", check=False)
    if builder.returncode == 0:
        assert builder.stdout.strip() == "0", "workspace-builder did not exit successfully"

    if "stats-worker" not in dojo_run("docker", "ps", "--format", "{{.Names}}").stdout.split():
        return
    deadline = time.time() + 40
    while True:
        logs = dojo_run("docker", "logs", "stats-worker", check=False)
        if "Cold start complete" in logs.stdout + logs.stderr:
            return
        assert time.time() < deadline, "stats-worker never finished its cold start"
        time.sleep(2)


def test_wait_succeeds_on_healthy_dojo():
    result = dojo_run("dojo", "wait", check=False, timeout=45)
    assert result.returncode == 0, result.stdout[-2000:]


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_wait_skips_stats_gate_on_worker():
    result = dojo_run("dojo", "wait", container=WORKER_CONTAINER, check=False, timeout=45)
    assert result.returncode == 0, result.stdout[-2000:]
    assert "No stats-worker container found" in result.stdout, result.stdout[-2000:]
    running = dojo_run("docker", "ps", "--format", "{{.Names}}", container=WORKER_CONTAINER).stdout.split()
    assert "stats-worker" not in running, running


def test_backup_creates_restorable_dump():
    result = dojo_run("dojo", "backup")
    match = re.search(r"Created backup at (\S+)", result.stdout)
    assert match, result.stdout
    path = match.group(1)
    try:
        assert path.startswith("/data/backups/db-"), path
        assert int(dojo_run("stat", "-c", "%s", path).stdout) > 1000, "backup is suspiciously small"
        toc = dojo_run("sh", "-c", f"docker exec -i db pg_restore -l < '{path}'").stdout
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
        dojo_run("sh", "-c", f"docker exec -i db pg_dump -Fc -t {table} > /data/backups/{dump}")
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
    environment = _config_env()
    if environment.get("BACKUP_AES_KEY_FILE") or environment.get("S3_BACKUP_BUCKET"):
        pytest.skip("cloud backup is configured on this dojo")
    result = dojo_run("dojo", "cloud-backup", check=False)
    output = result.stdout + result.stderr
    assert result.returncode != 0, "unconfigured `dojo cloud-backup` must not report success"
    assert "BACKUP_AES_KEY_FILE must be set" in output or "S3_BACKUP_BUCKET must be set" in output, output


def test_sync_copies_plugin_and_theme():
    marker = f"cli-sync-{_rand()}"
    source = f"/opt/pwn.college/dojo_theme/{marker}.txt"
    destination = f"/opt/CTFd/CTFd/themes/dojo_theme/{marker}.txt"
    dojo_run("sh", "-c", f"echo {marker} > {source}")
    try:
        result = dojo_run("dojo", "sync", check=False)
        assert result.returncode == 0, result.stderr[-2000:]
        assert dojo_run("cat", destination).stdout.strip() == marker, "dojo sync did not copy the theme"
        assert dojo_run("test", "-f", "/opt/CTFd/CTFd/plugins/dojo_plugin/__init__.py", check=False).returncode == 0, \
            "dojo sync did not copy the plugin"
    finally:
        dojo_run("rm", "-f", source, check=False)
        dojo_run("rm", "-f", destination, check=False)


def test_node_show_reports_identity():
    output = dojo_run("dojo", "node", "show").stdout
    environment = _config_env()
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


@pytest.mark.skipif(MULTINODE, reason="registering a fake peer would disrupt real worker nodes")
def test_node_add_and_del_manage_wireguard_peers():
    node_key = dojo_run("sh", "-c", "wg genkey | wg pubkey").stdout.strip()
    nodes = dojo_run("cat", "/data/workspace_nodes.json").stdout

    usage = dojo_run("dojo", "node", "add", check=False)
    assert "Usage:" in usage.stdout, usage.stdout
    assert dojo_run("cat", "/data/workspace_nodes.json").stdout == nodes, \
        "`dojo node add` without arguments modified workspace_nodes.json"

    try:
        dojo_run("dojo", "node", "add", "5", node_key)
        registered = json.loads(dojo_run("cat", "/data/workspace_nodes.json").stdout)
        assert registered.get("5") == node_key, registered
        config = dojo_run("cat", "/data/wireguard/wg0.conf").stdout
        assert f"PublicKey = {node_key}" in config, config
        assert "AllowedIPs = 192.168.42.6/32, 10.80.0.0/12" in config, config
        assert node_key in dojo_run("wg", "show", "wg0").stdout, "peer was not applied to the live interface"
    finally:
        dojo_run("dojo", "node", "del", "5", check=False)
        dojo_run("sh", "-c", "cat > /data/workspace_nodes.json", input=nodes)

    assert "5" not in json.loads(dojo_run("cat", "/data/workspace_nodes.json").stdout)
    assert node_key not in dojo_run("cat", "/data/wireguard/wg0.conf").stdout, "peer survived `dojo node del`"
    assert node_key not in dojo_run("wg", "show", "wg0").stdout, "peer survived on the live interface"


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_node_mutation_denied_on_worker():
    nodes = dojo_run("cat", "/data/workspace_nodes.json", container=WORKER_CONTAINER, check=False).stdout

    added = dojo_run("dojo", "node", "add", "9", "key", container=WORKER_CONTAINER, check=False)
    assert added.returncode == 1, added.stdout
    assert "only the main dojo node can add nodes" in added.stdout, added.stdout

    deleted = dojo_run("dojo", "node", "del", "9", container=WORKER_CONTAINER, check=False)
    assert deleted.returncode == 1, deleted.stdout
    assert "only the main dojo node can delete nodes" in deleted.stdout, deleted.stdout

    assert dojo_run("cat", "/data/workspace_nodes.json", container=WORKER_CONTAINER, check=False).stdout == nodes


@pytest.mark.skipif(not MULTINODE, reason="requires a multinode deployment")
def test_node_refresh_worker_daemon_json_idempotent():
    node_id = sorted(WORKSPACE_NODES)[0]
    host = f"tcp://192.168.42.{int(node_id) + 1}:2375"
    hosts = json.loads(dojo_run("cat", "/etc/docker/daemon.json", container=WORKER_CONTAINER).stdout)["hosts"]
    assert hosts.count(host) == 1, hosts
    dojo_run("dojo", "node", "refresh", container=WORKER_CONTAINER)
    hosts = json.loads(dojo_run("cat", "/etc/docker/daemon.json", container=WORKER_CONTAINER).stdout)["hosts"]
    assert hosts.count(host) == 1, hosts


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


def test_load_dojo_path_resolved_inside_ctfd(admin_session):
    dojo_id = f"cli-load-{_rand()}"
    spec = SPEC_TEMPLATE.format(dojo_id=dojo_id)
    outer_path = f"/tmp/{dojo_id}.yml"
    dojo_run("sh", "-c", f"cat > {outer_path}", input=spec)
    try:
        outer_only = dojo_run("dojo", "load-dojo", outer_path, check=False)
        assert outer_only.returncode == 1, outer_only.stdout[-2000:]
        assert "Invalid repository" in outer_only.stdout + outer_only.stderr, outer_only.stdout[-2000:]
        assert int(db_sql(f"SELECT count(*) FROM dojos WHERE id = '{dojo_id}';")) == 0

        inner_path = _write_spec_in_ctfd(spec)
        loaded = dojo_run("dojo", "load-dojo", inner_path, check=False)
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

        dojo_run("docker", "exec", "homefs", "python", "-c",
                 "import sqlite3; connection = sqlite3.connect('/run/homefs/homefs.db'); "
                 f"connection.execute(\"update active_volumes set host='10.255.255.1' where name='{volume}'\"); "
                 "connection.commit()")

        status, body = _curl(f"http://localhost:4201/volume/{volume}/activate", "-XPOST")
        assert status == 409, f"a volume active on another host must be refused: {status} {body}"
        assert "Volume already active" in body, body
    finally:
        dojo_run("docker", "exec", "homefs", "python", "-c",
                 "import sqlite3; connection = sqlite3.connect('/run/homefs/homefs.db'); "
                 f"connection.execute(\"delete from active_volumes where name='{volume}'\"); "
                 "connection.commit()", check=False)
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
        mode = dojo_run("docker", "inspect", "-f", '{{index .Config.Labels "dojo.mode"}}', container,
                        container=get_outer_container_for(container)).stdout.strip()
        assert mode == expected_mode, f"{container} has dojo.mode={mode}, expected {expected_mode}"


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
    result = dojo_run("sh", "-c", "cat /run/dojo/dojofs/workspace/privileged 2>&1; echo rc=$?")
    assert "Input/output error" in result.stdout, result.stdout
    assert "rc=1" in result.stdout, result.stdout
    assert dojo_run("stat", "-c", "%s", "/run/dojo/dojofs/workspace/privileged").stdout.strip() == "0", \
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
        "globals_ = {'__file__': '/usr/local/bin/docker_remove_containers', '__name__': '__main__'}\n"
        "exec(open('/usr/local/bin/docker_remove_containers').read(), globals_)\n"
    )
    result = dojo_run("docker", "exec", "-i", "watchdog", "python3", "-c", script, check=False)
    output = result.stdout + result.stderr
    assert "Removing old docker container" in output, output[-2000:]
    running = dojo_run("docker", "ps", "--format", "{{.Names}}").stdout.split()
    assert container not in running, "the reaper left a 7-hour-old user container running"

    # The shifted clock makes every running workspace look old, so put this
    # module's shared container back for the tests that come after.
    start_challenge(example_dojo, "hello", "apple", session=session)


def test_watchdog_spares_fresh_and_infrastructure_containers(cli_user):
    name, _ = cli_user
    container = f"user_{get_user_id(name)}"
    outer_container = get_outer_container_for(container)
    infrastructure = {"ctfd", "db", "cache", "nginx", "homefs", "watchdog"}

    result = dojo_run("docker", "exec", "watchdog", "/usr/local/bin/docker_remove_containers", check=False)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-2000:]
    assert "Removing old docker container" not in output, output[-2000:]
    assert "Removing large docker container" not in output, output[-2000:]

    assert container in dojo_run("docker", "ps", "--format", "{{.Names}}",
                                 container=outer_container).stdout.split(), \
        "the reaper removed a freshly started user container"
    running = set(dojo_run("docker", "ps", "--format", "{{.Names}}").stdout.split())
    assert infrastructure <= running, f"the reaper removed infrastructure containers: {infrastructure - running}"


def test_watchdog_sweeps_every_daemon_hosting_user_containers(cli_user):
    name, _ = cli_user
    container = f"user_{get_user_id(name)}"
    host = get_outer_container_for(container)

    result = dojo_run("docker", "exec", "watchdog", "/usr/local/bin/docker_remove_containers")
    output = result.stdout + result.stderr
    swept = re.findall(r"Removing docker containers on (\S+)", output)
    assert swept, "no docker daemon was swept, so no user container can ever be reaped"

    if host == DOJO_CONTAINER:
        assert any("localhost" in daemon or "unix" in daemon for daemon in swept), \
            f"the daemon hosting {container} was not swept: {swept}"
    else:
        node_id = int(host.rsplit("node", 1)[1])
        expected = f"tcp://192.168.42.{node_id + 1}:2375"
        assert any(expected in daemon for daemon in swept), \
            f"the daemon hosting {container} ({expected}) was not swept: {swept}"


def test_watchdog_cron_runs():
    started_at = dojo_run("docker", "inspect", "-f", "{{.State.StartedAt}}", "watchdog").stdout.strip()
    started = datetime.datetime.fromisoformat(re.sub(r"(\.\d{0,6})\d*Z$", r"\1+00:00", started_at))
    uptime = (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds()

    crontab = dojo_run("docker", "exec", "watchdog", "crontab", "-l").stdout
    assert re.search(r"^\*/5 \* \* \* \* /usr/local/bin/docker_remove_containers", crontab, re.M), crontab
    assert re.search(r"^0 9 \* \* \* /usr/local/bin/docker_prune_images", crontab, re.M), crontab

    if uptime < 400:
        pytest.skip("watchdog has not been up for a full cron interval")

    logs = dojo_run("docker", "logs", "--since", "7m", "watchdog")
    recent = logs.stdout + logs.stderr
    assert "[docker_remove_containers] [INFO] Starting" in recent, "the reaper cron job did not run"
    assert "[docker_remove_containers] [INFO] Finished" in recent, "the reaper cron job did not complete"

    logs = dojo_run("docker", "logs", "--since", "20m", "-t", "watchdog")
    timestamps = re.findall(r"^(\S+) .*\[docker_remove_containers\] \[INFO\] Starting",
                            logs.stdout + logs.stderr, re.M)
    if len(timestamps) >= 2:
        parsed = [datetime.datetime.fromisoformat(re.sub(r"(\.\d{0,6})\d*Z$", r"\1+00:00", stamp))
                  for stamp in timestamps[-2:]]
        interval = (parsed[1] - parsed[0]).total_seconds()
        assert 240 <= interval <= 360, f"consecutive reaper runs were {interval}s apart"


@pytest.mark.skipif(MULTINODE, reason="the pruner targets the workspace nodes, not the main daemon")
def test_watchdog_prunes_dangling_images():
    target = WORKER_CONTAINER if MULTINODE else DOJO_CONTAINER
    tag = f"cli-prune-{_rand()}"
    existing = set(dojo_run("docker", "images", "-qf", "dangling=true", container=target).stdout.split())
    created = set()
    try:
        dojo_run("sh", "-c",
                 f'printf "FROM hello-world\\nLABEL probe=one\\n" | docker build -q -t {tag} - && '
                 f'printf "FROM hello-world\\nLABEL probe=two\\n" | docker build -q -t {tag} -',
                 container=target)
        created = set(dojo_run("docker", "images", "-qf", "dangling=true",
                               container=target).stdout.split()) - existing
        assert created, "failed to create a dangling image"

        result = dojo_run("docker", "exec", "watchdog", "/usr/local/bin/docker_prune_images", check=False)
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


def test_init_config_env_shape():
    lines = [line for line in dojo_run("cat", "/data/config.env").stdout.splitlines() if "=" in line]
    keys = [line.split("=", 1)[0] for line in lines]
    assert len(keys) == len(set(keys)), f"duplicate keys in config.env: {keys}"
    required = {"DOJO_HOST", "WORKSPACE_HOST", "DOJO_ENV", "WORKSPACE_NODE", "SECRET_KEY",
                "WORKSPACE_SECRET", "DOJO_SSH_SERVICE_KEY", "DB_NAME", "DB_USER"}
    assert required <= set(keys), f"missing config keys: {required - set(keys)}"

    environment = _config_env()
    assert environment["DOJO_ENV"] in ("development", "coverage", "production"), environment["DOJO_ENV"]
    assert environment["SECRET_KEY"], "SECRET_KEY was never generated"
    assert environment["WORKSPACE_SECRET"], "WORKSPACE_SECRET was never generated"
    assert environment["DOJO_SSH_SERVICE_KEY"], "DOJO_SSH_SERVICE_KEY was never generated"


def test_init_homes_quota_enabled():
    assert dojo_run("findmnt", "-nro", "FSTYPE", "--", "/data/homes").stdout.strip() == "btrfs"
    quota = dojo_run("btrfs", "qgroup", "show", "-re", "/data/homes", check=False)
    output = quota.stdout + quota.stderr
    assert quota.returncode == 0, output
    assert "quotas not enabled" not in output, output
    assert "Qgroupid" in quota.stdout, quota.stdout

    homes_source = dojo_run("findmnt", "-nro", "SOURCE", "--", "/data/homes").stdout.strip()
    storage_source = dojo_run("findmnt", "-nro", "SOURCE", "--", "/run/homefs").stdout.strip()
    assert homes_source == storage_source, f"{homes_source} != {storage_source}"


def test_init_ssh_host_keys_persist():
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


def test_splunk_forwarder_disabled_noop():
    environment = _config_env()
    if environment.get("ENABLE_SPLUNK") == "true":
        pytest.skip("splunk is enabled on this dojo")
    result = dojo_run("env", "ENABLE_SPLUNK=false", "/opt/pwn.college/dojo/journal-to-splunk",
                      check=False, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Splunk is not enabled, exiting" in result.stdout, result.stdout
    active = dojo_run("systemctl", "is-active", "journal-to-splunk", check=False)
    assert active.stdout.strip() != "active", "journal-to-splunk is running without ENABLE_SPLUNK"


@pytest.mark.order(-1)
@pytest.mark.skipif(MULTINODE, reason="re-running dojo-init would bounce the cluster's wireguard tunnels")
def test_init_rerun_preserves_secrets_and_host_keys(admin_session):
    before = dojo_run("cat", "/data/config.env").stdout
    fingerprint = dojo_run("ssh-keygen", "-lf", "/data/ssh_host_keys/ssh_host_ed25519_key.pub").stdout.split()[1]

    result = _rerun_dojo_init()
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]

    after = dojo_run("cat", "/data/config.env").stdout
    assert after == before, "dojo-init rewrote config.env, rotating generated secrets"
    assert dojo_run("ssh-keygen", "-lf", "/data/ssh_host_keys/ssh_host_ed25519_key.pub").stdout.split()[1] == \
        fingerprint, "dojo-init regenerated the ssh host keys"
    assert admin_session.get(f"{DOJO_URL}/dojos").status_code == 200, "an existing session broke across dojo-init"


@pytest.mark.order(-1)
@pytest.mark.skipif(MULTINODE, reason="re-running dojo-init would bounce the cluster's wireguard tunnels")
def test_init_docker_user_rules_idempotent(cli_user):
    name, _ = cli_user
    inbound = "-A DOCKER-USER -i workspace_net -j WORKSPACE-NET"
    outbound = "-A DOCKER-USER -o workspace_net -j WORKSPACE-NET"

    result = _rerun_dojo_init()
    assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]

    rules = dojo_run("iptables", "-S", "DOCKER-USER").stdout
    workspace_rules = dojo_run("iptables", "-S", "WORKSPACE-NET").stdout.strip().splitlines()
    assert workspace_rules[-1] == "-A WORKSPACE-NET -j DROP", workspace_rules[-1]
    status = workspace_run("curl -s -o /dev/null -w %{http_code} --max-time 10 http://pwn.college/", user=name)
    assert status.stdout.strip() == "200", "workspaces lost access to the dojo after dojo-init"

    assert rules.count(inbound) == 1, f"DOCKER-USER accumulated inbound jumps:\n{rules}"
    assert rules.count(outbound) == 1, f"DOCKER-USER accumulated outbound jumps:\n{rules}"
