import json
import re
import shutil
import subprocess
import sys
import time
import uuid

import pytest
import requests

from restore_test_utils import (
    docker_network_ip_owners,
    is_transient_docker_ip_allocation_error,
)
from utils import DOJO_CONTAINER, DOJO_URL, db_sql, dojo_run, parse_csrf_token


pytestmark = pytest.mark.database_restore_integration


DATABASE_CLIENTS = (
    "ctfd",
    "stats-worker",
    "image-pull-worker",
    "sshd",
    "pgbouncer",
)
RESTORE_SERVICES = DATABASE_CLIENTS + ("cache", "nginx")
RESTORE_HELPER = "/opt/pwn.college/dojo/dojo-restore"
RESTORE_STATE = "/data/.dojo-restore"
DYNAMIC_HOLDER_LABEL = "pwn.college.dojo-restore-ip-holder"
DYNAMIC_NGINX_NETWORK_CONTAINERS = ("ctfd", "frontend", "nginx")


def container_info(service):
    result = dojo_run("docker", "inspect", "--type=container", service)
    return json.loads(result.stdout)[0]


def service_snapshot():
    result = {}
    for service in RESTORE_SERVICES:
        container = container_info(service)
        result[service] = {
            "running": container["State"]["Running"],
            "status": container["State"]["Status"],
            "restart": container["HostConfig"]["RestartPolicy"],
        }
    return result


def restore_service_snapshot(snapshot):
    for service, expected in snapshot.items():
        policy = expected["restart"]["Name"] or "no"
        retries = expected["restart"]["MaximumRetryCount"]
        if policy == "on-failure" and retries:
            policy = f"{policy}:{retries}"
        dojo_run("docker", "update", f"--restart={policy}", service, check=False)
    for service in (
        "cache",
        "pgbouncer",
        "stats-worker",
        "image-pull-worker",
        "sshd",
        "ctfd",
        "nginx",
    ):
        expected = snapshot[service]
        dojo_run(
            "docker",
            "start" if expected["running"] else "stop",
            service,
            check=False,
        )


def redis_cli(*arguments, check=True):
    return dojo_run(
        "docker",
        "exec",
        "cache",
        "redis-cli",
        *arguments,
        check=check,
    ).stdout.strip()


def wait_for_stats_cold_start(started_at):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        stats = container_info("stats-worker")
        assert stats["State"]["Running"] is True
        assert stats["State"]["StartedAt"] == started_at
        logs_result = dojo_run(
            "docker",
            "logs",
            "--since",
            started_at,
            "stats-worker",
        )
        logs = logs_result.stdout + logs_result.stderr
        assert "Error during cold start:" not in logs
        assert "SKIP_COLD_START" not in logs
        if "Cold start complete - all stats initialized" in logs:
            return logs
        time.sleep(1)
    raise AssertionError("stats-worker cold start did not complete")


def sql_literal(value):
    if value is None:
        return "NULL"
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def sql_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def installation_id():
    result = dojo_run("cat", f"{RESTORE_STATE}/installation-id")
    value = result.stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{32}", value)
    return value


def fenced_database_name():
    return f"dojo_restore_{installation_id()}"


def maintenance_database_sql(database_name, sql, check=True):
    command = r'''
. /data/config.env
DB_PORT="${DB_PORT:-5432}"
installation_id=$(cat /data/.dojo-restore/installation-id)
PGPASSWORD=$(cat /data/.dojo-restore/maintenance-secret)
PGAPPNAME="dojo-test-inspection:${installation_id}"
export PGPASSWORD PGAPPNAME
exec docker exec -e PGPASSWORD -e PGAPPNAME db psql \
    --host="$DB_HOST" --port="$DB_PORT" \
    --username="dojo_restore_${installation_id}" --dbname="$1" \
    --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command "$2"
'''
    result = dojo_run(
        "sh",
        "-c",
        command,
        "dojo-maintenance-sql",
        database_name,
        sql,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(command_diagnostics("maintenance PostgreSQL query", result))
    return result.stdout.strip() if check else result


def application_database_sql(database_name, sql, check=True):
    command = r'''
. /data/config.env
DB_PORT="${DB_PORT:-5432}"
PGPASSWORD="$DB_PASS"
PGAPPNAME="dojo-test-application"
export PGPASSWORD PGAPPNAME
exec docker exec -e PGPASSWORD -e PGAPPNAME db psql \
    --host="$DB_HOST" --port="$DB_PORT" \
    --username="$DB_USER" --dbname="$1" \
    --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command "$2"
'''
    result = dojo_run(
        "sh",
        "-c",
        command,
        "dojo-application-sql",
        database_name,
        sql,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(command_diagnostics("application PostgreSQL query", result))
    return result.stdout.strip() if check else result


def postgres_sql(sql, check=True):
    if restore_phase() is not None:
        return maintenance_database_sql("postgres", sql, check=check)
    result = dojo_run(
        "docker",
        "exec",
        "db",
        "psql",
        "--dbname=postgres",
        "--no-psqlrc",
        "--tuples-only",
        "--no-align",
        "--set=ON_ERROR_STOP=1",
        "--command",
        sql,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(command_diagnostics("PostgreSQL query", result))
    return result.stdout.strip() if check else result


def direct_database_sql(database_name, sql, check=True):
    result = dojo_run(
        "docker",
        "exec",
        "db",
        "psql",
        f"--dbname={database_name}",
        "--no-psqlrc",
        "--tuples-only",
        "--no-align",
        "--set=ON_ERROR_STOP=1",
        "--command",
        sql,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(command_diagnostics("direct PostgreSQL query", result))
    return result.stdout.strip() if check else result


def maintenance_role_state():
    role = f"dojo_restore_{installation_id()}"
    result = direct_database_sql(
        "postgres",
        "SELECT json_build_object("
        "'role', to_jsonb(role), "
        "'comment', shobj_description(role.oid, 'pg_authid'), "
        "'memberships', COALESCE((SELECT json_agg(to_jsonb(membership) "
        "ORDER BY membership.roleid, membership.member, membership.grantor) "
        "FROM pg_auth_members AS membership "
        "WHERE membership.roleid = role.oid OR membership.member = role.oid), "
        "'[]'::json)"
        ") FROM pg_roles AS role "
        f"WHERE role.rolname = {sql_literal(role)};",
    )
    return json.loads(result) if result else None


def prepare_transaction_through_pgbouncer(sql):
    program = """
import os
import sys

from sqlalchemy import create_engine

database_url = os.environ["DATABASE_URL"]
if database_url.count("@pgbouncer:5432/") != 1:
    raise RuntimeError("CTFd is not configured for the deployed PgBouncer endpoint")
engine = create_engine(database_url)
connection = engine.raw_connection()
try:
    cursor = connection.cursor()
    cursor.execute(sys.argv[1])
    cursor.close()
finally:
    connection.close()
"""
    return dojo_run(
        "docker",
        "exec",
        "ctfd",
        "python",
        "-c",
        program,
        sql,
        check=False,
    )


def wait_for_postgres():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = dojo_run("docker", "exec", "db", "pg_isready", check=False)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise AssertionError("postgres did not recover")


def database_identity():
    return json.loads(
        db_sql(
            "SELECT json_build_object("
            "'oid', database.oid::bigint, "
            "'owner', pg_get_userbyid(database.datdba), "
            "'encoding', pg_encoding_to_char(database.encoding), "
            "'locale_provider', database.datlocprovider, "
            "'collate', database.datcollate, "
            "'ctype', database.datctype, "
            "'locale', database.datlocale, "
            "'icu_rules', database.daticurules, "
            "'collation_version', database.datcollversion, "
            "'tablespace', tablespace.spcname, "
            "'allow_connections', database.datallowconn, "
            "'is_template', database.datistemplate, "
            "'connection_limit', database.datconnlimit, "
            "'acl_default', database.datacl IS NULL, "
            "'acl', COALESCE((SELECT json_agg(json_build_object("
            "'grantor', pg_get_userbyid(acl.grantor), "
            "'grantee', CASE WHEN acl.grantee = 0 THEN NULL "
            "ELSE pg_get_userbyid(acl.grantee) END, "
            "'privilege', acl.privilege_type, 'grantable', acl.is_grantable"
            ") ORDER BY acl.grantor, acl.grantee, acl.privilege_type) "
            "FROM aclexplode(database.datacl) AS acl), '[]'::json), "
            "'comment', shobj_description(database.oid, 'pg_database'), "
            "'settings', COALESCE((SELECT json_agg(json_build_object("
            "'role', CASE WHEN setting.setrole = 0 THEN NULL "
            "ELSE pg_get_userbyid(setting.setrole) END, "
            "'value', item.value) ORDER BY setting.setrole, item.value) "
            "FROM pg_db_role_setting AS setting "
            "CROSS JOIN LATERAL unnest(setting.setconfig) AS item(value) "
            "WHERE setting.setdatabase = database.oid), '[]'::json), "
            "'security_labels', COALESCE((SELECT json_agg(json_build_object("
            "'provider', label.provider, 'label', label.label"
            ") ORDER BY label.provider) FROM pg_shseclabel AS label "
            "WHERE label.classoid = 'pg_database'::regclass "
            "AND label.objoid = database.oid), '[]'::json)"
            ") FROM pg_database AS database "
            "JOIN pg_tablespace AS tablespace "
            "ON tablespace.oid = database.dattablespace "
            "WHERE database.datname = current_database();"
        )
    )


def create_backup():
    result = dojo_run("dojo", "backup", check=False)
    assert result.returncode == 0, result.stderr
    return parse_backup_filename(result)


def parse_backup_filename(result):
    match = re.search(r"Created backup at /data/backups/([^/\s]+)\s*$", result.stdout)
    assert match, result.stdout
    return match.group(1)


def write_config(config):
    program = """
import os
import sys

path = "/data/config.env"
temporary = f"{path}.{os.getpid()}.partial"
mode = os.stat(path).st_mode & 0o777
descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
try:
    payload = sys.stdin.buffer.read()
    offset = 0
    while offset < len(payload):
        offset += os.write(descriptor, payload[offset:])
    os.fsync(descriptor)
finally:
    os.close(descriptor)
os.replace(temporary, path)
directory = os.open("/data", os.O_RDONLY | os.O_DIRECTORY)
os.fsync(directory)
os.close(directory)
"""
    dojo_run("python3", "-c", program, input=config)


def configured_database_config(config, **values):
    remaining = dict(values)
    lines = []
    for line in config.splitlines():
        name = line.split("=", 1)[0]
        if name in remaining:
            lines.append(f"{name}={remaining.pop(name)}")
        else:
            lines.append(line)
    lines.extend(f"{name}={value}" for name, value in remaining.items())
    return "\n".join(lines) + "\n"


def assert_restore_timeout_wrapper_exports(suffix):
    original_config = dojo_run("cat", "/data/config.env").stdout
    cases = (
        (
            "DOJO_RESTORE_READY_TIMEOUT_SECONDS",
            {
                "DOJO_RESTORE_READY_TIMEOUT_SECONDS": "invalid",
                "DOJO_RESTORE_COLD_START_TIMEOUT_SECONDS": "1",
            },
        ),
        (
            "DOJO_RESTORE_COLD_START_TIMEOUT_SECONDS",
            {
                "DOJO_RESTORE_READY_TIMEOUT_SECONDS": "1",
                "DOJO_RESTORE_COLD_START_TIMEOUT_SECONDS": "invalid",
            },
        ),
    )
    try:
        for expected_error, values in cases:
            write_config(configured_database_config(original_config, **values))
            result = dojo_run(
                "env",
                "-u",
                "DOJO_RESTORE_READY_TIMEOUT_SECONDS",
                "-u",
                "DOJO_RESTORE_COLD_START_TIMEOUT_SECONDS",
                "dojo",
                "restore",
                f"missing-timeout-test-{suffix}.dump",
                check=False,
            )
            assert result.returncode != 0
            assert expected_error in result.stderr
    finally:
        write_config(original_config)


def outer_process(*arguments):
    return subprocess.Popen(
        [shutil.which("docker"), "exec", "-i", DOJO_CONTAINER, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def maintenance_database_process(database_name, sql, application_name):
    command = r'''
. /data/config.env
DB_PORT="${DB_PORT:-5432}"
installation_id=$(cat /data/.dojo-restore/installation-id)
PGPASSWORD=$(cat /data/.dojo-restore/maintenance-secret)
PGAPPNAME="$3"
export PGPASSWORD PGAPPNAME
exec docker exec -e PGPASSWORD -e PGAPPNAME db psql \
    --host="$DB_HOST" --port="$DB_PORT" \
    --username="dojo_restore_${installation_id}" --dbname="$1" \
    --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command "$2"
'''
    return outer_process(
        "sh",
        "-c",
        command,
        "dojo-maintenance-process",
        database_name,
        sql,
        application_name,
    )


def restore_phase():
    result = dojo_run(
        "python3",
        "-c",
        (
            "import json; "
            f"print(json.load(open('{RESTORE_STATE}/journal'))['phase'])"
        ),
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def restore_process_states(filename):
    script = f"""
import os

states = []
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        arguments = open(f"/proc/{{entry}}/cmdline", "rb").read().decode(errors="ignore").split("\\0")
        process_stat = open(f"/proc/{{entry}}/stat").read()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if {RESTORE_HELPER!r} not in arguments or {filename!r} not in arguments:
        continue
    states.append(process_stat.rsplit(")", 1)[1].strip().split()[0])
print(" ".join(states))
"""
    result = dojo_run("python3", "-c", script, check=False)
    assert result.returncode == 0
    return set(result.stdout.split())


def wait_for_paused_phase(process, filename, expected_phase):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if restore_phase() == expected_phase and restore_process_states(filename) & {
            "T",
            "t",
        }:
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"restore exited before {expected_phase} pause\n{stdout}\n{stderr}"
            )
        time.sleep(0.05)
    raise AssertionError(f"restore did not pause in {expected_phase}")


def wait_for_paused_point(process, filename):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if restore_process_states(filename) & {"T", "t"}:
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"restore exited before deterministic pause\n{stdout}\n{stderr}"
            )
        time.sleep(0.05)
    raise AssertionError("restore did not reach deterministic pause")


def wait_for_release_renamed(process, filename, database_name):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        database_names = postgres_sql(
            "SELECT string_agg(datname, ',' ORDER BY datname) FROM pg_database "
            f"WHERE datname IN ({sql_literal(database_name)}, "
            f"{sql_literal(fenced_database_name())});"
        )
        if (
            database_names == database_name
            and restore_process_states(filename) & {"T", "t"}
        ):
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"restore exited before release rename pause\n{stdout}\n{stderr}"
            )
        time.sleep(0.05)
    raise AssertionError("restore did not pause after the release rename")


def wait_for_database_application(application_name):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if postgres_sql(
            "SELECT count(*) FROM pg_stat_activity "
            f"WHERE application_name = {sql_literal(application_name)};"
        ) == "1":
            return
        time.sleep(0.05)
    raise AssertionError(f"database application did not connect: {application_name}")


def maintenance_session_count():
    identifier = installation_id()
    applications = ", ".join(
        sql_literal(application)
        for application in (
            f"dojo-restore:{identifier}",
            f"dojo-restore-snapshot:{identifier}",
            f"dojo-backup:{identifier}",
        )
    )
    return int(
        postgres_sql(
            "SELECT count(*) FROM pg_stat_activity "
            f"WHERE application_name IN ({applications});"
        )
    )


def wait_for_database_drop_sleep(process, database_name):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        sleeping = postgres_sql(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = 'postgres' "
            f"AND application_name = {sql_literal(f'dojo-restore:{installation_id()}')} "
            "AND query LIKE '%pg_sleep(300)%';"
        )
        database_present = postgres_sql(
            "SELECT count(*) FROM pg_database "
            f"WHERE datname = {sql_literal(database_name)};"
        )
        if restore_phase() == "restoring" and sleeping == "1" and database_present == "0":
            return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"restore exited before the DROP/CREATE interruption window\n"
                f"{stdout}\n{stderr}"
            )
        time.sleep(0.05)
    raise AssertionError("restore did not enter the DROP/CREATE interruption window")


def wait_for_maintenance(process):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        phase = restore_phase()
        pgbouncer = container_info("pgbouncer")["State"]["Running"]
        if phase in {
            "snapshotting",
            "fenced",
            "ready",
            "restoring",
            "restored",
            "warming",
        } and not pgbouncer:
            return phase
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"restore exited before maintenance gate\n{stdout}\n{stderr}")
        time.sleep(0.05)
    raise AssertionError("restore did not enter maintenance mode")


def signal_restore(filename, signal_name):
    script = f"""
import os
import signal

matches = []
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        arguments = open(f"/proc/{{entry}}/cmdline", "rb").read().decode(errors="ignore").split("\\0")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if {RESTORE_HELPER!r} not in arguments or {filename!r} not in arguments:
        continue
    process_id = int(entry)
    os.kill(process_id, getattr(signal, "SIG" + {signal_name!r}))
    matches.append(process_id)
assert matches
"""
    result = dojo_run(
        "python3",
        "-c",
        script,
        check=False,
    )
    assert result.returncode == 0


def backup_process_states():
    script = f"""
import os

states = []
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        arguments = open(f"/proc/{{entry}}/cmdline", "rb").read().decode(errors="ignore").split("\\0")
        process_stat = open(f"/proc/{{entry}}/stat").read()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if {RESTORE_HELPER!r} not in arguments or "--backup" not in arguments:
        continue
    states.append(process_stat.rsplit(")", 1)[1].strip().split()[0])
print(" ".join(states))
"""
    result = dojo_run("python3", "-c", script, check=False)
    assert result.returncode == 0
    return set(result.stdout.split())


def backup_partials():
    return set(
        dojo_run(
            "find",
            "/data/backups",
            "-maxdepth",
            "1",
            "-type",
            "f",
            "-name",
            ".dojo-backup.*.partial",
        ).stdout.split()
    )


def wait_for_paused_backup(process):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        partials = backup_partials()
        if partials and backup_process_states() & {"T", "t"}:
            return partials
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"backup exited before deterministic pause\n{stdout}\n{stderr}")
        time.sleep(0.05)
    raise AssertionError("backup did not reach deterministic pause")


def signal_backup(signal_name):
    script = f"""
import os
import signal

matches = []
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        arguments = open(f"/proc/{{entry}}/cmdline", "rb").read().decode(errors="ignore").split("\\0")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if {RESTORE_HELPER!r} not in arguments or "--backup" not in arguments:
        continue
    process_id = int(entry)
    os.kill(process_id, getattr(signal, "SIG" + {signal_name!r}))
    matches.append(process_id)
assert matches
"""
    result = dojo_run("python3", "-c", script, check=False)
    assert result.returncode == 0


def wait_for_http():
    deadline = time.monotonic() + 90
    last_error = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(DOJO_URL, timeout=5)
            if response.status_code == 200 and "'csrfNonce':" in response.text:
                return
            last_error = (
                f"HTTP {response.status_code} without the expected CTFd response"
            )
        except requests.RequestException as error:
            last_error = str(error)
        time.sleep(1)
    raise AssertionError(f"dojo HTTP did not recover: {last_error}")


def assert_http_unavailable():
    try:
        response = requests.get(DOJO_URL, timeout=3)
    except requests.RequestException:
        return
    raise AssertionError(f"HTTP ingress remained available with {response.status_code}")


def application_role_attributes(database_name):
    return direct_database_sql(
        database_name,
        "SELECT to_jsonb(role)::text FROM pg_roles AS role "
        "WHERE role.rolname = current_user;",
    )


def fenced_application_role_attributes(database_name):
    journal = json.loads(dojo_run("cat", f"{RESTORE_STATE}/journal").stdout)
    role = journal["application_role"]["name"]
    return maintenance_database_sql(
        database_name,
        "SELECT to_jsonb(role)::text FROM pg_roles AS role "
        f"WHERE role.rolname = {sql_literal(role)};",
    )


def assert_restore_fence(
    schema,
    row_id,
    decoy_database,
    expected_role_attributes,
    *,
    application_role_disabled=True,
):
    for service in (*DATABASE_CLIENTS, "nginx"):
        assert container_info(service)["State"]["Running"] is False
    assert_http_unavailable()
    rejected_write = dojo_run(
        "docker",
        "exec",
        "pgbouncer",
        "psql",
        "--set=ON_ERROR_STOP=1",
        "--command",
        f"INSERT INTO {schema}.parents VALUES ({row_id}, 'fence-bypass');",
        check=False,
    )
    assert rejected_write.returncode != 0
    database_name = json.loads(
        dojo_run("cat", f"{RESTORE_STATE}/journal").stdout
    )["target"]["name"]
    rejected_direct_write = direct_database_sql(
        database_name,
        f"INSERT INTO {schema}.parents VALUES ({row_id}, 'direct-fence-bypass');",
        check=False,
    )
    assert rejected_direct_write.returncode != 0
    expected_fenced_attributes = json.loads(expected_role_attributes)
    if application_role_disabled:
        expected_fenced_attributes["rolcanlogin"] = False
    assert json.loads(fenced_application_role_attributes(decoy_database)) == (
        expected_fenced_attributes
    )
    fenced_login = application_database_sql(
        fenced_database_name(),
        "SELECT 1;",
        check=False,
    )
    fenced_exists = postgres_sql(
        "SELECT count(*) FROM pg_database "
        f"WHERE datname = {sql_literal(fenced_database_name())};"
    )
    if fenced_exists == "1":
        assert fenced_login.returncode != 0
        assert "not permitted to log in" in fenced_login.stderr
    assert maintenance_database_sql(
        decoy_database,
        "SELECT set_config('session_replication_role', 'replica', false);",
    ) == "replica"
    assert maintenance_database_sql(
        decoy_database,
        "WITH activity AS ("
        "UPDATE restore_decoy SET value = value RETURNING value"
        ") SELECT value FROM activity;",
    ) == "untouched"


def assert_repeated_reconnects_rejected(database_name, schema, first_row_id):
    for row_id in range(first_row_id, first_row_id + 3):
        result = direct_database_sql(
            database_name,
            f"INSERT INTO {schema}.parents VALUES ({row_id}, 'reconnect-bypass');",
            check=False,
        )
        assert result.returncode != 0


def register_user(name):
    session = requests.Session()
    registration_page = session.get(f"{DOJO_URL}/register", timeout=5)
    registration_page.raise_for_status()
    nonce = parse_csrf_token(registration_page.text)
    while True:
        registration = session.post(
            f"{DOJO_URL}/register",
            data={
                "name": name,
                "email": f"{name}@example.com",
                "password": name,
                "nonce": nonce,
            },
            allow_redirects=False,
            timeout=5,
        )
        if registration.status_code != 429:
            break
        time.sleep(1)
    assert registration.status_code == 302, registration.text


def command_diagnostics(name, result):
    return (
        f"{name} exited {result.returncode}"
        f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def remove_optional_container(name):
    result = dojo_run("docker", "rm", "--force", name, check=False)
    output = (result.stdout + result.stderr).lower()
    if result.returncode != 0 and "no such container" not in output:
        raise AssertionError(command_diagnostics(f"{name} cleanup", result))


def inspect_network_ip(network, ip_address):
    result = dojo_run("docker", "network", "inspect", network, check=False)
    if result.returncode != 0:
        raise AssertionError(command_diagnostics("docker network inspect", result))
    try:
        network_documents = json.loads(result.stdout)
        owners = docker_network_ip_owners(network_documents, ip_address)
    except (json.JSONDecodeError, ValueError) as error:
        raise AssertionError(
            f"docker network inspect returned invalid data: {error}"
            f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        ) from error
    return owners, result


def assert_holder_network_ip(holder, network, ip_address):
    inspection = dojo_run(
        "docker", "inspect", "--type=container", holder, check=False
    )
    if inspection.returncode != 0:
        raise AssertionError(command_diagnostics("holder inspection", inspection))
    try:
        holder_documents = json.loads(inspection.stdout)
        if not isinstance(holder_documents, list) or len(holder_documents) != 1:
            raise ValueError("inspection must contain exactly one container")
        holder_info = holder_documents[0]
        running = holder_info["State"]["Running"]
        holder_networks = holder_info["NetworkSettings"]["Networks"]
        holder_endpoint = holder_networks.get(network)
        allocated_ip = None if holder_endpoint is None else holder_endpoint["IPAddress"]
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise AssertionError(
            f"holder inspection returned invalid data: {error}"
            f"\n{command_diagnostics('holder inspection', inspection)}"
        ) from error
    if running is True and allocated_ip == ip_address:
        return
    logs = dojo_run("docker", "logs", holder, check=False)
    raise AssertionError(
        f"holder did not remain running on {ip_address} in {network}; "
        f"running={running!r}, allocated_ip={allocated_ip!r}"
        f"\n{command_diagnostics('holder inspection', inspection)}"
        f"\n{command_diagnostics('holder logs', logs)}"
    )


def create_explicit_test_network(network, holder):
    failures = []
    for subnet in (
        "192.0.2.0/24",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "100.127.255.0/24",
    ):
        result = dojo_run(
            "docker",
            "network",
            "create",
            "--driver=bridge",
            f"--subnet={subnet}",
            "--label",
            f"{DYNAMIC_HOLDER_LABEL}={holder}",
            network,
            check=False,
        )
        if result.returncode == 0:
            return subnet
        failures.append(command_diagnostics(f"network creation for {subnet}", result))
        message = (result.stdout + result.stderr).lower()
        if "pool overlaps" not in message and "overlap with other one" not in message:
            break
    raise AssertionError("could not create an explicit-subnet test network\n" + "\n".join(failures))


def connect_container_network(container, network, alias):
    result = dojo_run(
        "docker",
        "network",
        "connect",
        "--alias",
        alias,
        network,
        container,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            command_diagnostics(f"connecting {container} to {network}", result)
        )


def connect_dynamic_nginx_network(network):
    for container in DYNAMIC_NGINX_NETWORK_CONTAINERS:
        connect_container_network(container, network, container)


def reload_nginx():
    result = dojo_run("docker", "exec", "nginx", "nginx", "-s", "reload", check=False)
    if result.returncode != 0:
        raise AssertionError(command_diagnostics("nginx reload", result))


def reserve_network_ip(holder, network, ip_address, image):
    deadline = time.monotonic() + 30
    remove_optional_container(holder)
    while True:
        owners, inspection = inspect_network_ip(network, ip_address)
        if owners:
            if time.monotonic() >= deadline:
                raise AssertionError(
                    f"Docker network {network} did not release {ip_address}; "
                    f"owners: {', '.join(owners)}\n"
                    f"{command_diagnostics('docker network inspect', inspection)}"
                )
            time.sleep(0.25)
            continue
        run = dojo_run(
            "docker",
            "run",
            "--detach",
            "--pull=never",
            "--name",
            holder,
            "--label",
            f"{DYNAMIC_HOLDER_LABEL}={holder}",
            "--network",
            network,
            "--ip",
            ip_address,
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            "exec sleep 300",
            check=False,
        )
        if run.returncode == 0:
            assert_holder_network_ip(holder, network, ip_address)
            return
        remove_optional_container(holder)
        try:
            owners, inspection = inspect_network_ip(network, ip_address)
            network_details = command_diagnostics(
                "docker network inspect", inspection
            )
        except AssertionError as error:
            raise AssertionError(
                f"{command_diagnostics('holder container creation', run)}"
                f"\n{error}"
            ) from error
        if not is_transient_docker_ip_allocation_error(run.stderr):
            raise AssertionError(
                f"{command_diagnostics('holder container creation', run)}"
                f"\nnetwork owners: {', '.join(owners) or 'none'}"
                f"\nnetwork inspection:\n{network_details}"
            )
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"transient Docker IP allocation did not clear for {ip_address}"
                f"\n{command_diagnostics('holder container creation', run)}"
                f"\nnetwork owners: {', '.join(owners) or 'none'}"
                f"\nnetwork inspection:\n{network_details}"
            )
        time.sleep(0.25)


def container_networks(container):
    inspection = dojo_run(
        "docker", "inspect", "--type=container", container, check=False
    )
    if inspection.returncode != 0:
        raise AssertionError(
            command_diagnostics(f"{container} network inspection", inspection)
        )
    try:
        documents = json.loads(inspection.stdout)
        if not isinstance(documents, list) or len(documents) != 1:
            raise ValueError("inspection must contain exactly one container")
        networks = documents[0]["NetworkSettings"]["Networks"]
        if not isinstance(networks, dict):
            raise ValueError("container networks must be an object")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise AssertionError(
            f"{container} network inspection returned invalid data: {error}"
            f"\n{command_diagnostics(f'{container} network inspection', inspection)}"
        ) from error
    return networks


def ignore_missing_network_result(name, result):
    if result.returncode == 0:
        return None
    message = (result.stdout + result.stderr).lower()
    if any(
        expected in message
        for expected in (
            "is not connected to network",
            "no such network",
            "network not found",
        )
    ):
        return None
    return command_diagnostics(name, result)


def restore_ctfd_after_dynamic_test(holder, test_network, default_network):
    failures = []
    try:
        remove_optional_container(holder)
    except AssertionError as error:
        failures.append(str(error))
    try:
        nginx_networks = container_networks("nginx")
        if default_network not in nginx_networks:
            connect_container_network("nginx", default_network, "nginx")
    except AssertionError as error:
        failures.append(str(error))
    for container in DYNAMIC_NGINX_NETWORK_CONTAINERS:
        disconnection = dojo_run(
            "docker",
            "network",
            "disconnect",
            "--force",
            test_network,
            container,
            check=False,
        )
        failure = ignore_missing_network_result(
            f"disconnecting {container} from {test_network}", disconnection
        )
        if failure:
            failures.append(failure)
    network_removal = dojo_run(
        "docker", "network", "rm", test_network, check=False
    )
    network_failure = ignore_missing_network_result(
        f"removing {test_network}", network_removal
    )
    if network_failure:
        failures.append(network_failure)
    ctfd_start = dojo_run(
        "dojo", "compose", "up", "--detach", "ctfd", check=False
    )
    if ctfd_start.returncode != 0:
        failures.append(command_diagnostics("CTFd cleanup startup", ctfd_start))
    if ctfd_start.returncode == 0:
        try:
            reload_nginx()
            wait_for_http()
        except AssertionError as error:
            failures.append(str(error))
    return "\n".join(failures)


def assert_dynamic_ctfd_upstream(holder):
    nginx_check = dojo_run(
        "docker", "exec", "nginx", "nginx", "-t", check=False
    )
    if nginx_check.returncode != 0:
        raise AssertionError(command_diagnostics("nginx configuration test", nginx_check))
    ctfd = container_info("ctfd")
    ctfd_networks = ctfd["NetworkSettings"]["Networks"]
    if len(ctfd_networks) != 1:
        raise AssertionError(
            f"CTFd must have exactly one Compose network: "
            f"{json.dumps(ctfd_networks, sort_keys=True)}"
        )
    default_network = next(iter(ctfd_networks))
    test_network = f"restore-nginx-{holder[-12:]}"
    image = ctfd["Image"]
    failure = None
    try:
        create_explicit_test_network(test_network, holder)
        connect_dynamic_nginx_network(test_network)
        old_ip = container_networks("ctfd")[test_network]["IPAddress"]
        nginx_disconnect = dojo_run(
            "docker",
            "network",
            "disconnect",
            default_network,
            "nginx",
            check=False,
        )
        if nginx_disconnect.returncode != 0:
            raise AssertionError(
                command_diagnostics(
                    f"disconnecting nginx from {default_network}", nginx_disconnect
                )
            )
        reload_nginx()
        wait_for_http()
        removal = dojo_run("docker", "rm", "--force", "ctfd", check=False)
        if removal.returncode != 0:
            raise AssertionError(command_diagnostics("CTFd removal", removal))
        reserve_network_ip(holder, test_network, old_ip, image)
        ctfd_start = dojo_run(
            "dojo", "compose", "up", "--detach", "ctfd", check=False
        )
        if ctfd_start.returncode != 0:
            raise AssertionError(command_diagnostics("CTFd startup", ctfd_start))
        connect_container_network("ctfd", test_network, "ctfd")
        assert_holder_network_ip(holder, test_network, old_ip)
        new_endpoint = container_networks("ctfd").get(test_network)
        if new_endpoint is None:
            raise AssertionError(f"recreated CTFd did not join {test_network}")
        new_ip = new_endpoint["IPAddress"]
        assert new_ip and new_ip != old_ip, (
            f"recreated CTFd retained {old_ip} while the holder reserved it"
        )
        wait_for_http()
    except Exception as error:
        failure = error
    cleanup_failure = restore_ctfd_after_dynamic_test(
        holder, test_network, default_network
    )
    if failure is not None:
        if cleanup_failure:
            raise AssertionError(
                f"{failure}\ndynamic CTFd cleanup also failed:\n{cleanup_failure}"
            ) from failure
        raise failure
    if cleanup_failure:
        raise AssertionError(cleanup_failure)


@pytest.mark.parametrize("disconnect_failure", [False, True])
def test_dynamic_nginx_network_fixture_cleans_every_dependency(
    monkeypatch,
    disconnect_failure,
):
    test_network = "restore-nginx-unit"
    default_network = "dojo-default"
    required_containers = ("ctfd", "frontend", "nginx")
    connected = []
    disconnected = []
    network_removals = []
    module = sys.modules[__name__]

    monkeypatch.setattr(
        module,
        "connect_container_network",
        lambda container, network, alias: connected.append(
            (container, network, alias)
        ),
    )
    connect_dynamic_nginx_network(test_network)
    assert DYNAMIC_NGINX_NETWORK_CONTAINERS == required_containers
    assert connected == [
        (container, test_network, container)
        for container in required_containers
    ]

    def fake_dojo_run(*arguments, check=True):
        assert check is False
        failure = False
        if arguments[:4] == ("docker", "network", "disconnect", "--force"):
            disconnected.append(arguments[-1])
            failure = disconnect_failure
        elif arguments[:3] == ("docker", "network", "rm"):
            network_removals.append(arguments[-1])
            failure = disconnect_failure
        elif arguments[:4] != ("dojo", "compose", "up", "--detach"):
            raise AssertionError(f"unexpected cleanup command: {arguments}")
        return subprocess.CompletedProcess(
            arguments,
            int(failure),
            "",
            "forced cleanup failure" if failure else "",
        )

    monkeypatch.setattr(module, "dojo_run", fake_dojo_run)
    monkeypatch.setattr(
        module,
        "remove_optional_container",
        lambda _holder: None,
    )
    monkeypatch.setattr(
        module,
        "container_networks",
        lambda _container: {default_network: {}},
    )
    monkeypatch.setattr(module, "reload_nginx", lambda: None)
    monkeypatch.setattr(module, "wait_for_http", lambda: None)

    cleanup_failure = restore_ctfd_after_dynamic_test(
        "holder", test_network, default_network
    )

    assert disconnected == list(required_containers)
    assert network_removals == [test_network]
    if disconnect_failure:
        for container in required_containers:
            assert f"disconnecting {container}" in cleanup_failure
        assert f"removing {test_network}" in cleanup_failure
    else:
        assert cleanup_failure == ""


@pytest.mark.timeout(2400)
def test_database_backup_restore():
    suffix = uuid.uuid4().hex
    schema = f"backup_restore_{suffix}"
    live_only_schema = f"restore_live_only_{suffix}"
    target_only_schema = f"restore_target_only_{suffix}"
    injection_schema = f"restore_i_{suffix[:12]}"
    writer_name = f"restore_writer_{suffix}"
    rollback_writer_name = f"restore_rollback_writer_{suffix}"
    holder = f"ctfd-ip-holder-{suffix}"
    metadata_role = f"restore_metadata_{suffix}"
    metadata_setting = f"dojo.restore_{suffix}"
    metadata_text = f"m\\';CREATE SCHEMA {injection_schema};--"
    subscription_name = f"restore_blocker_{suffix}"
    backup_filename = None
    backup_paths = []
    backup_directories = [
        f"/data/backups/first-{suffix}",
        f"/data/backups/second-{suffix}",
    ]
    initial_services = service_snapshot()
    initial_ctfd_network = next(
        iter(container_info("ctfd")["NetworkSettings"]["Networks"])
    )
    dynamic_test_network = f"restore-nginx-{holder[-12:]}"
    helper_link = "/usr/local/bin/dojo-restore"
    helper_target = None
    restore_process = None
    waiting_process = None
    forward_boundary_process = None
    rollback_boundary_process = None
    preflight_race_process = None
    validation_failure_process = None
    fence_substep_process = None
    fence_writer_process = None
    identity_mismatch_process = None
    boot_recovery_process = None
    legacy_recovery_process = None
    oid_recovery_process = None
    backup_race_restore_process = None
    backup_race_process = None
    interrupted_backup_process = None
    orphan_restore_process = None
    activation_crash_process = None
    activation_recovery_process = None
    deactivation_crash_process = None
    arbitrary_maintenance_process = None
    arbitrary_maintenance_application = f"dojo-test-unscoped-helper-{suffix}"
    first_filename = None
    second_filename = None
    failed_backup_filename = None
    owner_role = f"restore_owner_{suffix}"
    database_name = None
    initial_database_identity = None
    postgres_scs_setting = None
    postgres_scs_modified = False
    initial_max_prepared_transactions = None
    max_prepared_transactions_modified = False
    prepared_transaction = f"restore-race-{suffix}"
    prepared_transaction_active = False
    failed_dump_directory = f"/tmp/dojo-backup-failure-{suffix}"
    legacy_rollback_path = f"/tmp/dojo-restore-v2-rollback-{suffix}"
    wrong_database_name = f"restore_decoy_{suffix}"
    journal_writer = None
    trusted_recovery_journal = None
    trusted_recovery_requires_missing = False
    reserved_role = None
    collision_member = f"restore_collision_member_{suffix}"
    collision_role_active = False
    owned_maintenance_role = None

    try:
        dojo_run(RESTORE_HELPER, "--recover")
        assert restore_phase() is None
        postgres_scs_setting = postgres_sql(
            "SELECT COALESCE((SELECT substring(item.value FROM "
            "position('=' IN item.value) + 1) "
            "FROM pg_db_role_setting AS setting "
            "CROSS JOIN LATERAL unnest(setting.setconfig) AS item(value) "
            "WHERE setting.setdatabase = (SELECT oid FROM pg_database "
            "WHERE datname = 'postgres') AND setting.setrole = 0 "
            "AND split_part(item.value, '=', 1) = "
            "'standard_conforming_strings'), '');"
        )
        assert postgres_scs_setting in {"", "on", "off"}
        postgres_sql(
            "ALTER DATABASE postgres SET standard_conforming_strings TO off;"
        )
        postgres_scs_modified = True
        assert postgres_sql("SHOW standard_conforming_strings;") == "off"
        initial_max_prepared_transactions = int(
            postgres_sql("SHOW max_prepared_transactions;")
        )
        if initial_max_prepared_transactions == 0:
            postgres_sql("ALTER SYSTEM SET max_prepared_transactions TO 10;")
            max_prepared_transactions_modified = True
            dojo_run("docker", "restart", "db")
            wait_for_postgres()
            wait_for_http()
            assert int(postgres_sql("SHOW max_prepared_transactions;")) == 10
        database_name = db_sql("SELECT current_database();").strip()
        initial_database_identity = database_identity()
        db_sql(
            f"CREATE ROLE {metadata_role};"
            f"COMMENT ON DATABASE {sql_identifier(database_name)} "
            f"IS {sql_literal(metadata_text)};"
            f"ALTER DATABASE {sql_identifier(database_name)} CONNECTION LIMIT 777;"
            f"ALTER DATABASE {sql_identifier(database_name)} "
            f"SET {sql_identifier(metadata_setting)} TO {sql_literal(metadata_text)};"
            f"ALTER ROLE {metadata_role} IN DATABASE {sql_identifier(database_name)} "
            f"SET application_name TO {sql_literal(metadata_text)};"
        )
        dojo_script = dojo_run("cat", "/opt/pwn.college/dojo/dojo").stdout
        assert f"{RESTORE_HELPER} --prepare-recovery" in dojo_script
        assert f"{RESTORE_HELPER} --recover" in dojo_script
        assert '--no-deps --no-recreate db' in dojo_script
        assert f"exec {RESTORE_HELPER}" in dojo_script
        assert_restore_timeout_wrapper_exports(suffix)

        helper_target_result = dojo_run("readlink", helper_link, check=False)
        if helper_target_result.returncode == 0:
            helper_target = helper_target_result.stdout.strip()
            dojo_run("rm", helper_link)
            upgrade_result = dojo_run("dojo", "restore", "../config.env", check=False)
            assert upgrade_result.returncode != 127
            assert "command not found" not in upgrade_result.stderr
            dojo_run("ln", "--symbolic", helper_target, helper_link)
            helper_target = None

        db_sql(
            f"CREATE SCHEMA {schema};"
            f"CREATE TABLE {schema}.parents (id integer PRIMARY KEY, value text NOT NULL);"
            f"CREATE TABLE {schema}.children ("
            "id integer PRIMARY KEY, "
            f"parent_id integer NOT NULL REFERENCES {schema}.parents(id)"
            ");"
            f"CREATE TABLE {schema}.payload AS "
            "SELECT value, md5(random()::text || value::text) AS data "
            "FROM generate_series(1, 100000) AS values(value);"
            f"INSERT INTO {schema}.parents VALUES (1, 'from-backup');"
            f"INSERT INTO {schema}.children VALUES (1, 1);"
        )
        identity_before = database_identity()
        backup_filename = create_backup()
        backup_path = f"/data/backups/{backup_filename}"
        backup_paths.append(backup_path)
        assert dojo_run("stat", "--format=%a:%U", backup_path).stdout.strip() == (
            "600:root"
        )

        collision_services = service_snapshot()
        collision_identity = database_identity()
        collision_role_attributes = application_role_attributes(database_name)
        reserved_role = f"dojo_restore_{installation_id()}"
        postgres_sql(
            f"CREATE ROLE {sql_identifier(collision_member)};"
            f"CREATE ROLE {sql_identifier(reserved_role)} WITH NOSUPERUSER "
            "NOINHERIT CREATEDB CREATEROLE NOLOGIN NOREPLICATION NOBYPASSRLS "
            "CONNECTION LIMIT 7 VALID UNTIL '2035-01-02 03:04:05+00';"
            f"ALTER ROLE {sql_identifier(reserved_role)} "
            "SET statement_timeout TO '17s';"
            f"COMMENT ON ROLE {sql_identifier(reserved_role)} IS "
            f"{sql_literal(f'unrelated collision {suffix}')};"
            f"GRANT {sql_identifier(collision_member)} "
            f"TO {sql_identifier(reserved_role)};"
        )
        collision_role_active = True
        unrelated_role_before = maintenance_role_state()
        assert unrelated_role_before["role"]["rolsuper"] is False
        assert unrelated_role_before["role"]["rolcanlogin"] is False
        assert unrelated_role_before["memberships"]
        unrelated_collision = dojo_run(
            RESTORE_HELPER,
            backup_filename,
            check=False,
        )
        assert unrelated_collision.returncode != 0
        assert "not owned by this installation" in unrelated_collision.stderr
        assert maintenance_role_state() == unrelated_role_before
        assert service_snapshot() == collision_services
        assert database_identity() == collision_identity
        assert application_role_attributes(database_name) == collision_role_attributes
        assert restore_phase() is None
        postgres_sql(
            f"DROP ROLE {sql_identifier(reserved_role)};"
            f"DROP ROLE {sql_identifier(collision_member)};"
        )
        collision_role_active = False
        role_collision = dojo_run(
            "env",
            f"DB_USER={reserved_role}",
            RESTORE_HELPER,
            backup_filename,
            check=False,
        )
        assert role_collision.returncode != 0
        assert "maintenance role must differ" in role_collision.stderr
        assert service_snapshot() == collision_services
        assert database_identity() == collision_identity
        assert application_role_attributes(database_name) == collision_role_attributes
        assert restore_phase() is None

        reserved_database = fenced_database_name()
        postgres_sql(f"CREATE DATABASE {sql_identifier(reserved_database)};")
        try:
            database_collision = dojo_run(
                "env",
                f"DB_NAME={reserved_database}",
                RESTORE_HELPER,
                backup_filename,
                check=False,
            )
            assert database_collision.returncode != 0
            assert "maintenance name is already in use" in database_collision.stderr
            assert service_snapshot() == collision_services
            assert database_identity() == collision_identity
            assert application_role_attributes(database_name) == (
                collision_role_attributes
            )
            assert restore_phase() is None
        finally:
            postgres_sql(f"DROP DATABASE {sql_identifier(reserved_database)};")

        activation_services = service_snapshot()
        activation_identity = database_identity()
        activation_crash_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=maintenance-role-activated",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_point(activation_crash_process, backup_filename)
        activation_journal = json.loads(
            dojo_run("cat", f"{RESTORE_STATE}/journal").stdout
        )
        assert activation_journal["version"] == 5
        assert activation_journal["maintenance"] == "activating"
        active_role = maintenance_role_state()
        assert active_role["role"]["rolcanlogin"] is True
        for service in (*DATABASE_CLIENTS, "nginx"):
            assert container_info(service)["State"]["Running"] is False
        assert_http_unavailable()
        signal_restore(backup_filename, "KILL")
        activation_crash_process.communicate(timeout=15)
        assert activation_crash_process.returncode != 0
        activation_crash_process = None
        dojo_run("docker", "rm", "--force", "db")
        activation_recovery_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=journal-maintenance-role-deactivated",
            "dojo",
            "up",
        )
        wait_for_paused_point(activation_recovery_process, "--recover")
        assert container_info("db")["State"]["Running"] is True
        assert maintenance_role_state()["role"]["rolcanlogin"] is False
        for service in (*DATABASE_CLIENTS, "nginx"):
            assert container_info(service)["State"]["Running"] is False
        assert_http_unavailable()
        signal_restore("--recover", "CONT")
        recovery_stdout, recovery_stderr = activation_recovery_process.communicate(
            timeout=300
        )
        assert activation_recovery_process.returncode == 0, (
            recovery_stdout,
            recovery_stderr,
        )
        activation_recovery_process = None
        assert restore_phase() is None
        assert maintenance_role_state()["role"]["rolcanlogin"] is False
        assert service_snapshot() == activation_services
        assert database_identity() == activation_identity

        deactivation_services = service_snapshot()
        deactivation_identity = database_identity()
        deactivation_crash_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=journal-maintenance-role-deactivated",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_point(deactivation_crash_process, backup_filename)
        deactivation_journal = json.loads(
            dojo_run("cat", f"{RESTORE_STATE}/journal").stdout
        )
        assert deactivation_journal["version"] == 5
        assert deactivation_journal["phase"] == "committed"
        assert deactivation_journal["maintenance"] == "deactivating"
        assert maintenance_role_state()["role"]["rolcanlogin"] is False
        for service in (*DATABASE_CLIENTS, "nginx"):
            assert container_info(service)["State"]["Running"] is False
        assert_http_unavailable()
        signal_restore(backup_filename, "KILL")
        deactivation_crash_process.communicate(timeout=15)
        assert deactivation_crash_process.returncode != 0
        deactivation_crash_process = None
        deactivation_database_container_id = container_info("db")["Id"]
        dojo_run("docker", "stop", "db")
        dojo_run("dojo", "up")
        assert container_info("db")["State"]["Running"] is True
        assert container_info("db")["Id"] == deactivation_database_container_id
        assert restore_phase() is None
        assert maintenance_role_state()["role"]["rolcanlogin"] is False
        assert service_snapshot() == deactivation_services
        assert database_identity() == deactivation_identity

        startup_services = service_snapshot()
        startup_identity = database_identity()
        direct_database_sql(
            "postgres",
            f"ALTER ROLE {sql_identifier(reserved_role)} LOGIN;",
        )
        assert restore_phase() is None
        assert maintenance_role_state()["role"]["rolcanlogin"] is True
        arbitrary_maintenance_process = maintenance_database_process(
            "postgres",
            "SELECT pg_sleep(300);",
            arbitrary_maintenance_application,
        )
        wait_for_database_application(arbitrary_maintenance_application)
        dojo_run(RESTORE_HELPER, "--recover")
        arbitrary_stdout, arbitrary_stderr = arbitrary_maintenance_process.communicate(
            timeout=30
        )
        assert arbitrary_maintenance_process.returncode != 0, (
            arbitrary_stdout,
            arbitrary_stderr,
        )
        arbitrary_maintenance_process = None
        assert maintenance_role_state()["role"]["rolcanlogin"] is False
        assert postgres_sql(
            "SELECT count(*) FROM pg_stat_activity "
            f"WHERE application_name = {sql_literal(arbitrary_maintenance_application)};"
        ) == "0"
        assert service_snapshot() == startup_services
        assert database_identity() == startup_identity
        direct_database_sql(
            "postgres",
            f"ALTER ROLE {sql_identifier(reserved_role)} LOGIN;",
        )
        assert maintenance_role_state()["role"]["rolcanlogin"] is True
        dojo_run("docker", "rm", "--force", "db")
        activation_recovery_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=startup-maintenance-role-deactivated",
            "dojo",
            "up",
        )
        wait_for_paused_point(activation_recovery_process, "--recover")
        startup_journal = json.loads(
            dojo_run("cat", f"{RESTORE_STATE}/journal").stdout
        )
        assert startup_journal["version"] == 6
        assert startup_journal["kind"] == "startup"
        assert startup_journal["database"] == {
            "present": True,
            "running": True,
            "id": container_info("db")["Id"],
        }
        assert maintenance_role_state()["role"]["rolcanlogin"] is False
        for service in (*DATABASE_CLIENTS, "nginx"):
            assert container_info(service)["State"]["Running"] is False
        assert_http_unavailable()
        signal_restore("--recover", "CONT")
        startup_stdout, startup_stderr = activation_recovery_process.communicate(
            timeout=300
        )
        assert activation_recovery_process.returncode == 0, (
            startup_stdout,
            startup_stderr,
        )
        activation_recovery_process = None
        assert restore_phase() is None
        assert maintenance_role_state()["role"]["rolcanlogin"] is False
        assert service_snapshot() == startup_services
        assert database_identity() == startup_identity

        concurrent_backups = [
            outer_process("sh", "-c", "umask 0777; exec dojo backup")
            for _ in range(2)
        ]
        concurrent_filenames = []
        for process in concurrent_backups:
            stdout, stderr = process.communicate(timeout=180)
            result = subprocess.CompletedProcess(
                process.args,
                process.returncode,
                stdout,
                stderr,
            )
            assert result.returncode == 0, result.stderr
            filename = parse_backup_filename(result)
            concurrent_filenames.append(filename)
            path = f"/data/backups/{filename}"
            backup_paths.append(path)
            assert dojo_run("stat", "--format=%a:%U", path).stdout.strip() == (
                "600:root"
            )
        assert len(set(concurrent_filenames)) == 2

        dojo_run("mkdir", "--mode=0700", failed_dump_directory)
        failed_docker = f"{failed_dump_directory}/docker"
        dojo_run(
            "tee",
            failed_docker,
            input="#!/bin/sh\nprintf 'partial archive'\nexit 23\n",
        )
        dojo_run("chmod", "0700", failed_docker)
        backups_before_failure = set(
            dojo_run("find", "/data/backups", "-maxdepth", "1", "-type", "f").stdout.split()
        )
        failed_dump = dojo_run(
            "env",
            f"PATH={failed_dump_directory}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "dojo",
            "backup",
            check=False,
        )
        assert failed_dump.returncode != 0
        assert "Created backup" not in failed_dump.stdout
        assert set(
            dojo_run("find", "/data/backups", "-maxdepth", "1", "-type", "f").stdout.split()
        ) == backups_before_failure
        assert not dojo_run(
            "find",
            "/data/backups",
            "-maxdepth",
            "1",
            "-name",
            "*.partial",
        ).stdout.split()

        interrupted_backup_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=backup-created",
            "dojo",
            "backup",
        )
        wait_for_paused_backup(interrupted_backup_process)
        signal_backup("TERM")
        signal_backup("CONT")
        interrupted_stdout, interrupted_stderr = (
            interrupted_backup_process.communicate(timeout=15)
        )
        assert interrupted_backup_process.returncode != 0, interrupted_stdout
        assert "backup interrupted by signal" in interrupted_stderr
        interrupted_backup_process = None
        assert not backup_partials()

        interrupted_backup_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=backup-created",
            "dojo",
            "backup",
        )
        killed_partials = wait_for_paused_backup(interrupted_backup_process)
        signal_backup("KILL")
        interrupted_backup_process.communicate(timeout=15)
        assert interrupted_backup_process.returncode != 0
        interrupted_backup_process = None
        assert backup_partials() == killed_partials
        post_kill_backup = create_backup()
        post_kill_backup_path = f"/data/backups/{post_kill_backup}"
        backup_paths.append(post_kill_backup_path)
        assert not backup_partials()
        assert all(
            dojo_run("stat", partial, check=False).returncode != 0
            for partial in killed_partials
        )

        invalid_names = {
            "empty": f"empty-{suffix}.dump",
            "fifo": f"fifo-{suffix}.dump",
            "symlink": f"symlink-{suffix}.dump",
            "writable": f"writable-{suffix}.dump",
            "corrupt": f"corrupt-{suffix}.dump",
        }
        invalid_paths = {
            name: f"/data/backups/{filename}"
            for name, filename in invalid_names.items()
        }
        backup_paths.extend(invalid_paths.values())
        dojo_run("touch", invalid_paths["empty"])
        dojo_run("mkfifo", invalid_paths["fifo"])
        dojo_run("ln", "--symbolic", "/data/config.env", invalid_paths["symlink"])
        dojo_run("cp", "--reflink=auto", backup_path, invalid_paths["writable"])
        dojo_run("chmod", "0666", invalid_paths["writable"])
        dojo_run("cp", "--reflink=auto", backup_path, invalid_paths["corrupt"])
        dojo_run("truncate", "--size=-8192", invalid_paths["corrupt"])
        services_before_invalid = service_snapshot()
        for filename in invalid_names.values():
            result = dojo_run("dojo", "restore", filename, check=False)
            assert result.returncode != 0
            assert service_snapshot() == services_before_invalid
            assert database_identity() == identity_before
            assert db_sql(
                f"SELECT value FROM {schema}.parents WHERE id = 1;"
            ).strip() == "from-backup"
            assert db_sql(
                f"SELECT to_regnamespace('{injection_schema}') IS NULL;"
            ).strip() == "t"
            assert restore_phase() is None
            assert dojo_run(
                "stat", f"{RESTORE_STATE}/rollback.dump", check=False
            ).returncode != 0

        services_before_race = service_snapshot()
        preflight_race_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=after-initial-preflight",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_point(preflight_race_process, backup_filename)
        assert restore_phase() is None
        prepared_transaction_active = True
        prepared_result = prepare_transaction_through_pgbouncer(
            "BEGIN;"
            f"INSERT INTO {schema}.parents VALUES (8, 'prepared-race');"
            f"PREPARE TRANSACTION {sql_literal(prepared_transaction)};"
        )
        assert prepared_result.returncode == 0, prepared_result.stderr
        assert direct_database_sql(
            database_name,
            "SELECT count(*) FROM pg_prepared_xacts "
            f"WHERE gid = {sql_literal(prepared_transaction)};",
        ) == "1"
        signal_restore(backup_filename, "CONT")
        race_stdout, race_stderr = preflight_race_process.communicate(timeout=180)
        assert preflight_race_process.returncode != 0, race_stdout
        assert "prepared transactions" in race_stderr
        preflight_race_process = None
        assert service_snapshot() == services_before_race
        assert database_identity() == identity_before
        assert db_sql(f"SELECT count(*) FROM {schema}.parents WHERE id = 8;").strip() == "0"
        assert restore_phase() is None
        assert dojo_run(
            "stat", f"{RESTORE_STATE}/rollback.dump", check=False
        ).returncode != 0
        direct_database_sql(
            database_name,
            f"ROLLBACK PREPARED {sql_literal(prepared_transaction)};",
        )
        prepared_transaction_active = False
        owned_maintenance_role = maintenance_role_state()
        assert owned_maintenance_role["role"]["rolsuper"] is True
        assert owned_maintenance_role["role"]["rolcanlogin"] is False
        assert owned_maintenance_role["memberships"] == []
        assert owned_maintenance_role["comment"].startswith(
            "pwn.college dojo-restore maintenance role v1:"
            f"{installation_id()}:"
        )

        db_sql(
            f"CREATE SUBSCRIPTION {sql_identifier(subscription_name)} "
            "CONNECTION 'host=127.0.0.1 port=1 dbname=postgres' "
            "PUBLICATION unavailable_publication "
            "WITH (connect = false, enabled = false, create_slot = false, "
            "slot_name = NONE);"
        )
        services_before_blocker = service_snapshot()
        blocked_restore = dojo_run("dojo", "restore", backup_filename, check=False)
        assert blocked_restore.returncode != 0
        assert "subscriptions" in blocked_restore.stderr
        assert service_snapshot() == services_before_blocker
        assert database_identity() == identity_before
        assert db_sql(
            f"SELECT value FROM {schema}.parents WHERE id = 1;"
        ).strip() == "from-backup"
        assert db_sql(
            f"SELECT to_regnamespace('{injection_schema}') IS NULL;"
        ).strip() == "t"
        assert restore_phase() is None
        assert dojo_run(
            "stat", f"{RESTORE_STATE}/rollback.dump", check=False
        ).returncode != 0
        direct_database_sql(
            database_name,
            f"ALTER SUBSCRIPTION {sql_identifier(subscription_name)} DISABLE;"
            f"ALTER SUBSCRIPTION {sql_identifier(subscription_name)} "
            "SET (slot_name = NONE);"
            f"DROP SUBSCRIPTION {sql_identifier(subscription_name)};",
        )
        assert postgres_sql(
            "SELECT count(*) FROM pg_subscription AS subscription "
            "JOIN pg_database AS database ON database.oid = subscription.subdbid "
            f"WHERE subscription.subname = {sql_literal(subscription_name)} "
            f"AND database.datname = {sql_literal(database_name)};"
        ) == "0"
        assert postgres_sql(
            "SELECT count(*) FROM pg_subscription "
            f"WHERE subname = {sql_literal(subscription_name)};"
        ) == "0"

        postgres_sql(f"CREATE DATABASE {sql_identifier(wrong_database_name)};")
        direct_database_sql(
            wrong_database_name,
            "CREATE TABLE restore_decoy (value text NOT NULL);"
            "INSERT INTO restore_decoy VALUES ('untouched');",
        )
        application_role_before_restore = application_role_attributes(
            wrong_database_name
        )
        fence_writer_application = f"restore-fence-writer-{suffix}"
        fence_writer_process = outer_process(
            "docker",
            "exec",
            "--env",
            f"PGAPPNAME={fence_writer_application}",
            "db",
            "psql",
            f"--dbname={database_name}",
            "--no-psqlrc",
            "--set=ON_ERROR_STOP=1",
            "--command",
            (
                "DO $writer$ DECLARE value integer := 0; BEGIN LOOP "
                "value := value + 1; "
                f"INSERT INTO {schema}.parents VALUES "
                "(1000000 + value, 'held-fence-writer'); "
                "PERFORM pg_sleep(0.02); END LOOP; END $writer$;"
            ),
        )
        wait_for_database_application(fence_writer_application)
        for point_index, pause_point in enumerate(
            (
                "fence-drained",
                "fence-denied",
                "application-role-disabled",
                "fence-renamed",
                "fence-enabled",
            )
        ):
            fence_substep_process = outer_process(
                "env",
                f"DOJO_RESTORE_TEST_PAUSE_POINTS={pause_point}",
                RESTORE_HELPER,
                backup_filename,
            )
            wait_for_paused_point(fence_substep_process, backup_filename)
            if pause_point == "fence-drained":
                fence_writer_stdout, fence_writer_stderr = (
                    fence_writer_process.communicate(timeout=15)
                )
                assert fence_writer_process.returncode != 0, (
                    fence_writer_stdout,
                    fence_writer_stderr,
                )
                fence_writer_process = None
            first_row_id = 20 + point_index * 4
            assert_restore_fence(
                schema,
                first_row_id,
                wrong_database_name,
                application_role_before_restore,
                application_role_disabled=pause_point
                not in {"fence-denied", "fence-drained"},
            )
            assert_repeated_reconnects_rejected(
                database_name,
                schema,
                first_row_id + 1,
            )
            signal_restore(backup_filename, "KILL")
            fence_substep_process.communicate(timeout=15)
            assert fence_substep_process.returncode != 0
            fence_substep_process = None
            dojo_run(RESTORE_HELPER, "--recover")
            assert restore_phase() is None
            assert maintenance_role_state() == owned_maintenance_role
            assert database_identity() == identity_before
            assert application_role_attributes(
                wrong_database_name
            ) == application_role_before_restore
            assert db_sql(
                f"SELECT count(*) FROM {schema}.parents "
                "WHERE id >= 1000000;"
            ).strip() == "0"
        identity_mismatch_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_PHASES=fenced",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_phase(
            identity_mismatch_process,
            backup_filename,
            "fenced",
        )
        assert_restore_fence(
            schema,
            15,
            wrong_database_name,
            application_role_before_restore,
        )
        signal_restore(backup_filename, "KILL")
        identity_mismatch_process.communicate(timeout=15)
        identity_mismatch_process = None
        fenced_services = service_snapshot()
        for changed_setting in (
            f"DB_NAME={wrong_database_name}",
            "DB_HOST=127.0.0.1",
        ):
            refused_recovery = dojo_run(
                "env",
                changed_setting,
                RESTORE_HELPER,
                "--recover",
                check=False,
            )
            assert refused_recovery.returncode != 0
            assert "does not match the pending restore journal" in refused_recovery.stderr
            assert service_snapshot() == fenced_services
            assert maintenance_database_sql(
                wrong_database_name,
                "SELECT value FROM restore_decoy;",
            ) == "untouched"
            assert maintenance_database_sql(
                fenced_database_name(),
                f"SELECT value FROM {schema}.parents WHERE id = 1;"
            ) == "from-backup"
        pending_journal = json.loads(
            dojo_run("cat", f"{RESTORE_STATE}/journal").stdout
        )
        trusted_recovery_journal = json.loads(json.dumps(pending_journal))
        tampered_journal = json.loads(json.dumps(pending_journal))
        system_identifier = int(
            tampered_journal["target"]["server"]["system_identifier"]
        )
        tampered_journal["target"]["server"]["system_identifier"] = str(
            system_identifier + 1
        )
        journal_writer = f"""
import os
import stat
import sys

payload = sys.stdin.buffer.read()
directory = os.open(
    {RESTORE_STATE!r},
    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
)
try:
    try:
        descriptor = os.open(
            "journal",
            os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW,
            dir_fd=directory,
        )
    except FileNotFoundError:
        descriptor = os.open(
            "journal",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
    try:
        def verify_regular_file():
            descriptor_stat = os.fstat(descriptor)
            path_stat = os.stat(
                "journal",
                dir_fd=directory,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or descriptor_stat.st_nlink != 1
                or (descriptor_stat.st_dev, descriptor_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise RuntimeError("restore journal path is not a trusted regular file")

        verify_regular_file()
        os.ftruncate(descriptor, 0)
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        verify_regular_file()
    finally:
        os.close(descriptor)
    os.fsync(directory)
finally:
    os.close(directory)
"""
        dojo_run(
            "python3",
            "-c",
            journal_writer,
            input=json.dumps(tampered_journal, separators=(",", ":")),
        )
        refused_identity = dojo_run(
            RESTORE_HELPER,
            "--recover",
            check=False,
        )
        assert refused_identity.returncode != 0
        assert "server identity does not match" in refused_identity.stderr
        assert service_snapshot() == fenced_services
        assert maintenance_database_sql(
            wrong_database_name,
            "SELECT value FROM restore_decoy;",
        ) == "untouched"
        dojo_run(
            "python3",
            "-c",
            journal_writer,
            input=json.dumps(pending_journal, separators=(",", ":")),
        )
        dojo_run(RESTORE_HELPER, "--recover")
        trusted_recovery_journal = None
        assert restore_phase() is None
        assert direct_database_sql(
            wrong_database_name,
            "SELECT value FROM restore_decoy;",
        ) == "untouched"

        boot_recovery_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_PHASES=ready",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_phase(
            boot_recovery_process,
            backup_filename,
            "ready",
        )
        signal_restore(backup_filename, "KILL")
        boot_recovery_process.communicate(timeout=15)
        boot_recovery_process = None
        dojo_run("docker", "stop", "db")
        dojo_run(RESTORE_HELPER, "--recover")
        assert container_info("db")["State"]["Running"] is True
        assert restore_phase() is None

        oid_recovery_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_PHASES=ready",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_phase(
            oid_recovery_process,
            backup_filename,
            "ready",
        )
        signal_restore(backup_filename, "KILL")
        oid_recovery_process.communicate(timeout=15)
        oid_recovery_process = None
        oid_journal = json.loads(
            dojo_run("cat", f"{RESTORE_STATE}/journal").stdout
        )
        trusted_recovery_journal = json.loads(json.dumps(oid_journal))
        expected_oid = oid_journal["database"]["oid"]
        postgres_sql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = {sql_literal(fenced_database_name())} "
            "AND pid <> pg_backend_pid();"
        )
        trusted_recovery_requires_missing = True
        postgres_sql(f"DROP DATABASE {sql_identifier(fenced_database_name())};")
        postgres_sql(f"CREATE DATABASE {sql_identifier(database_name)};")
        replacement_oid = int(
            postgres_sql(
                "SELECT oid::bigint FROM pg_database "
                f"WHERE datname = {sql_literal(database_name)};"
            )
        )
        assert replacement_oid != expected_oid
        maintenance_database_sql(
            database_name,
            "CREATE TABLE replacement_sentinel (value text NOT NULL);"
            "INSERT INTO replacement_sentinel VALUES ('preserve-me');",
        )
        replacement_services = service_snapshot()
        refused_replacement = dojo_run(
            RESTORE_HELPER,
            "--recover",
            check=False,
        )
        assert refused_replacement.returncode != 0
        assert "database identity does not match" in refused_replacement.stderr
        assert service_snapshot() == replacement_services
        assert maintenance_database_sql(
            database_name,
            "SELECT value FROM replacement_sentinel;",
        ) == "preserve-me"
        assert int(
            postgres_sql(
                "SELECT oid::bigint FROM pg_database "
                f"WHERE datname = {sql_literal(database_name)};"
            )
        ) == replacement_oid

        postgres_sql(f"DROP DATABASE {sql_identifier(database_name)};")
        oid_journal["phase"] = "restoring"
        trusted_recovery_journal = json.loads(json.dumps(oid_journal))
        trusted_recovery_requires_missing = False
        dojo_run(
            "python3",
            "-c",
            journal_writer,
            input=json.dumps(oid_journal, separators=(",", ":")),
        )
        dojo_run(RESTORE_HELPER, "--recover")
        trusted_recovery_journal = None
        assert restore_phase() is None
        assert database_identity() == identity_before
        assert db_sql(
            f"SELECT value FROM {schema}.parents WHERE id = 1;"
        ).strip() == "from-backup"

        db_sql(
            f"INSERT INTO {schema}.parents VALUES "
            "(6, 'preserved-from-ready-phase');"
        )
        legacy_recovery_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_PHASES=ready",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_phase(
            legacy_recovery_process,
            backup_filename,
            "ready",
        )
        assert container_info("pgbouncer")["State"]["Running"] is False
        rejected_reconnect = direct_database_sql(
            database_name,
            f"INSERT INTO {schema}.parents VALUES "
            "(7, 'reconnected-after-snapshot');",
            check=False,
        )
        assert rejected_reconnect.returncode != 0
        signal_restore(backup_filename, "KILL")
        legacy_recovery_process.communicate(timeout=15)
        legacy_recovery_process = None
        version_five_journal = json.loads(
            dojo_run("cat", f"{RESTORE_STATE}/journal").stdout
        )
        version_two_journal = json.loads(json.dumps(version_five_journal))
        version_two_journal["version"] = 2
        version_two_journal.pop("installation_id")
        version_two_journal.pop("application_role")
        version_two_journal.pop("maintenance")
        version_three_journal = {
            **json.loads(json.dumps(version_two_journal)),
            "version": 3,
            "installation_id": version_five_journal["installation_id"],
        }
        version_four_journal = {
            **json.loads(json.dumps(version_three_journal)),
            "version": 4,
            "application_role": version_five_journal["application_role"],
        }
        version_one_journal = json.loads(json.dumps(version_two_journal))
        version_one_journal["version"] = 1
        version_one_journal.pop("target")
        version_one_journal["services"].pop("nginx")
        dojo_run(
            "cp",
            "--preserve=mode,ownership,timestamps",
            f"{RESTORE_STATE}/rollback.dump",
            legacy_rollback_path,
        )
        dojo_run(RESTORE_HELPER, "--recover")
        assert restore_phase() is None
        assert database_identity()["oid"] == version_two_journal["database"]["oid"]
        assert application_role_attributes(
            wrong_database_name
        ) == application_role_before_restore
        preprovenance_services = service_snapshot()
        preprovenance_role = maintenance_role_state()
        for preprovenance_journal in (
            version_three_journal,
            version_four_journal,
        ):
            dojo_run(
                "python3",
                "-c",
                journal_writer,
                input=json.dumps(preprovenance_journal, separators=(",", ":")),
            )
            refused_preprovenance = dojo_run(
                RESTORE_HELPER,
                "--recover",
                check=False,
            )
            assert refused_preprovenance.returncode != 0
            assert (
                "predates maintenance-role provenance"
                in refused_preprovenance.stderr
            )
            assert service_snapshot() == preprovenance_services
            assert maintenance_role_state() == preprovenance_role
            assert direct_database_sql(
                database_name,
                f"SELECT value FROM {schema}.parents WHERE id = 6;",
            ) == "preserved-from-ready-phase"
        dojo_run("docker", "update", "--restart=no", *RESTORE_SERVICES)
        for service in (
            "nginx",
            "sshd",
            "image-pull-worker",
            "stats-worker",
            "ctfd",
            "pgbouncer",
        ):
            dojo_run("docker", "stop", service)
        dojo_run(
            "cp",
            "--preserve=mode,ownership,timestamps",
            legacy_rollback_path,
            f"{RESTORE_STATE}/rollback.dump",
        )
        dojo_run(
            "python3",
            "-c",
            (
                "import os; "
                f"descriptor=os.open('{RESTORE_STATE}/rollback.dump', "
                "os.O_RDONLY | os.O_NOFOLLOW); "
                "os.fsync(descriptor); os.close(descriptor); "
                f"descriptor=os.open('{RESTORE_STATE}', "
                "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW); "
                "os.fsync(descriptor); os.close(descriptor)"
            ),
        )
        trusted_recovery_journal = json.loads(json.dumps(version_two_journal))
        trusted_recovery_journal["phase"] = "ready"
        stopped_legacy_services = service_snapshot()
        stopped_legacy_role = maintenance_role_state()
        legacy_version_two = json.loads(json.dumps(version_two_journal))
        legacy_version_two["services"].pop("nginx")
        legacy_version_three = json.loads(json.dumps(version_three_journal))
        legacy_version_three["services"].pop("nginx")
        for legacy_journal in (legacy_version_two, legacy_version_three):
            for legacy_phase in ("snapshotting", "rolling_back", "committed"):
                legacy_journal["phase"] = legacy_phase
                dojo_run(
                    "python3",
                    "-c",
                    journal_writer,
                    input=json.dumps(legacy_journal, separators=(",", ":")),
                )
                refused_legacy_snapshot = dojo_run(
                    RESTORE_HELPER,
                    "--recover",
                    check=False,
                )
                assert refused_legacy_snapshot.returncode != 0
                assert (
                    "unsupported legacy service snapshot"
                    in refused_legacy_snapshot.stderr
                )
                assert service_snapshot() == stopped_legacy_services
                assert maintenance_role_state() == stopped_legacy_role
                assert direct_database_sql(
                    database_name,
                    f"SELECT value FROM {schema}.parents WHERE id = 6;",
                ) == "preserved-from-ready-phase"
        for legacy_phase in (
            "restoring",
            "restored",
            "warming",
            "rolling_back",
            "rollback_warming",
            "committed",
        ):
            version_one_journal["phase"] = legacy_phase
            dojo_run(
                "python3",
                "-c",
                journal_writer,
                input=json.dumps(version_one_journal, separators=(",", ":")),
            )
            for changed_setting in (
                None,
                f"DB_NAME={wrong_database_name}",
                "DB_HOST=127.0.0.1",
            ):
                recovery_arguments = (
                    [] if changed_setting is None else ["env", changed_setting]
                )
                refused_legacy = dojo_run(
                    *recovery_arguments,
                    RESTORE_HELPER,
                    "--recover",
                    check=False,
                )
                assert refused_legacy.returncode != 0
                assert "not bound to a database target" in refused_legacy.stderr
                assert direct_database_sql(
                    database_name,
                    f"SELECT value FROM {schema}.parents WHERE id = 6;",
                ) == "preserved-from-ready-phase"
                assert direct_database_sql(
                    wrong_database_name,
                    "SELECT value FROM restore_decoy;",
                ) == "untouched"
                assert container_info("pgbouncer")["State"]["Running"] is False
        version_two_journal["phase"] = "ready"
        dojo_run(
            "python3",
            "-c",
            journal_writer,
            input=json.dumps(version_two_journal, separators=(",", ":")),
        )
        assert int(
            dojo_run(
                "stat",
                "--format=%s",
                f"{RESTORE_STATE}/rollback.dump",
            ).stdout
        ) > 0
        assert version_two_journal["target"]["name"] == database_name
        assert json.loads(
            direct_database_sql(
                "postgres",
                "SELECT json_build_object("
                "'system_identifier', control.system_identifier::text, "
                "'server_version_num', "
                "current_setting('server_version_num')::integer"
                ") FROM pg_control_system() AS control;",
            )
        ) == version_two_journal["target"]["server"]
        assert int(
            direct_database_sql(
                "postgres",
                "SELECT oid::bigint FROM pg_database "
                f"WHERE datname = {sql_literal(database_name)};",
            )
        ) == version_two_journal["database"]["oid"]
        assert direct_database_sql(
            "postgres",
            "SELECT rolcanlogin FROM pg_roles "
            f"WHERE rolname = {sql_literal(version_two_journal['target']['user'])};",
        ) == "t"
        for service in (*DATABASE_CLIENTS, "nginx"):
            assert container_info(service)["State"]["Running"] is False
        dojo_run(RESTORE_HELPER, "--recover")
        trusted_recovery_journal = None
        assert db_sql(
            f"SELECT value FROM {schema}.parents WHERE id = 6;"
        ).strip() == "preserved-from-ready-phase"
        assert db_sql(
            f"SELECT count(*) FROM {schema}.parents WHERE id = 7;"
        ).strip() == "0"
        assert maintenance_role_state() == stopped_legacy_role
        assert restore_phase() is None

        orphan_restore_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_SLEEP_AFTER_DATABASE_DROP=1",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_database_drop_sleep(orphan_restore_process, database_name)
        signal_restore(backup_filename, "KILL")
        orphan_restore_process.communicate(timeout=15)
        assert orphan_restore_process.returncode != 0
        orphan_restore_process = None
        assert maintenance_session_count() >= 1
        dojo_run(RESTORE_HELPER, "--recover")
        assert maintenance_session_count() == 0
        assert database_identity() == identity_before
        assert db_sql(
            f"SELECT value FROM {schema}.parents WHERE id = 6;"
        ).strip() == "preserved-from-ready-phase"
        assert restore_phase() is None

        orphan_restore_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=database-recreated",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_point(orphan_restore_process, backup_filename)
        assert restore_phase() == "restoring"
        assert_restore_fence(
            schema,
            8,
            wrong_database_name,
            application_role_before_restore,
        )
        assert maintenance_database_sql(
            fenced_database_name(),
            f"SELECT to_regclass('{schema}.parents') IS NULL;",
        ) == "t"
        signal_restore(backup_filename, "KILL")
        orphan_restore_process.communicate(timeout=15)
        assert orphan_restore_process.returncode != 0
        orphan_restore_process = None
        dojo_run(RESTORE_HELPER, "--recover")
        assert database_identity() == identity_before
        assert db_sql(
            f"SELECT value FROM {schema}.parents WHERE id = 6;"
        ).strip() == "preserved-from-ready-phase"
        assert restore_phase() is None

        services_before_backup_race = service_snapshot()
        backup_race_restore_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_PHASES=warming",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_phase(
            backup_race_restore_process,
            backup_filename,
            "warming",
        )
        trusted_recovery_journal = json.loads(
            dojo_run("cat", f"{RESTORE_STATE}/journal").stdout
        )
        assert maintenance_database_sql(
            fenced_database_name(),
            f"SELECT count(*) FROM {schema}.parents WHERE id = 6;",
        ) == "0"
        backups_before_race = set(
            dojo_run(
                "find",
                "/data/backups",
                "-maxdepth",
                "1",
                "-type",
                "f",
            ).stdout.split()
        )
        backup_race_process = outer_process("dojo", "backup")
        time.sleep(1)
        assert backup_race_process.poll() is None
        assert set(
            dojo_run(
                "find",
                "/data/backups",
                "-maxdepth",
                "1",
                "-type",
                "f",
            ).stdout.split()
        ) == backups_before_race
        assert not backup_partials()
        signal_restore(backup_filename, "KILL")
        backup_race_restore_process.communicate(timeout=15)
        backup_race_restore_process = None
        backup_race_stdout, backup_race_stderr = backup_race_process.communicate(
            timeout=15
        )
        assert backup_race_process.returncode != 0, backup_race_stdout
        assert "restore recovery is pending" in backup_race_stderr
        backup_race_process = None
        assert set(
            dojo_run(
                "find",
                "/data/backups",
                "-maxdepth",
                "1",
                "-type",
                "f",
            ).stdout.split()
        ) == backups_before_race
        assert not backup_partials()
        dojo_run(RESTORE_HELPER, "--recover")
        trusted_recovery_journal = None
        assert service_snapshot() == services_before_backup_race
        assert db_sql(
            f"SELECT value FROM {schema}.parents WHERE id = 6;"
        ).strip() == "preserved-from-ready-phase"
        assert restore_phase() is None

        db_sql(
            f"CREATE SCHEMA {live_only_schema};"
            f"CREATE TABLE {live_only_schema}.must_be_removed (value integer);"
            f"INSERT INTO {live_only_schema}.must_be_removed VALUES (1);"
            f"INSERT INTO {schema}.parents VALUES (2, 'acknowledged-before-maintenance');"
            f"INSERT INTO {schema}.children VALUES (2, 2);"
        )
        dojo_run("docker", "update", "--restart=unless-stopped", "ctfd")
        dojo_run("docker", "update", "--restart=on-failure:7", "stats-worker")
        dojo_run("docker", "stop", "image-pull-worker")
        expected_services = service_snapshot()
        assert expected_services["ctfd"]["restart"] == {
            "Name": "unless-stopped",
            "MaximumRetryCount": 0,
        }
        assert expected_services["stats-worker"]["restart"] == {
            "Name": "on-failure",
            "MaximumRetryCount": 7,
        }

        writer = requests.Session()
        writer_nonce = parse_csrf_token(writer.get(f"{DOJO_URL}/register").text)
        for directory in backup_directories:
            dojo_run("mkdir", "--mode=0755", directory)
            destination = f"{directory}/{backup_filename}"
            dojo_run("cp", "--reflink=auto", backup_path, destination)
            backup_paths.append(destination)

        first_filename = f"first-{suffix}/{backup_filename}"
        second_filename = f"second-{suffix}/{backup_filename}"
        restore_process = outer_process("dojo", "restore", first_filename)
        assert wait_for_maintenance(restore_process) in {"snapshotting", "fenced"}
        signal_restore(first_filename, "STOP")

        rejected_write = dojo_run(
            "docker",
            "exec",
            "pgbouncer",
            "psql",
            "--set=ON_ERROR_STOP=1",
            "--command",
            f"INSERT INTO {schema}.parents VALUES (3, 'during-maintenance');",
            check=False,
        )
        assert rejected_write.returncode != 0
        try:
            registration = writer.post(
                f"{DOJO_URL}/register",
                data={
                    "name": writer_name,
                    "email": f"{writer_name}@example.com",
                    "password": writer_name,
                    "nonce": writer_nonce,
                },
                allow_redirects=False,
                timeout=5,
            )
            assert registration.status_code != 302
        except requests.RequestException:
            pass

        waiting_process = outer_process("dojo", "restore", second_filename)
        time.sleep(1)
        assert waiting_process.poll() is None
        signal_restore(second_filename, "KILL")
        waiting_process.communicate(timeout=15)
        waiting_process = None

        signal_restore(first_filename, "KILL")
        restore_process.communicate(timeout=15)
        restore_process = None
        dojo_run("docker", "stop", "cache")
        dojo_run(RESTORE_HELPER, "--recover")

        assert service_snapshot() == expected_services
        assert db_sql(f"SELECT value FROM {schema}.parents WHERE id = 2;").strip() == (
            "acknowledged-before-maintenance"
        )
        assert db_sql(f"SELECT count(*) FROM {schema}.parents WHERE id = 3;").strip() == "0"
        assert db_sql(f"SELECT count(*) FROM users WHERE name = '{writer_name}';").strip() == "0"
        assert db_sql(f"SELECT to_regnamespace('{live_only_schema}') IS NOT NULL;").strip() == "t"
        assert restore_phase() is None

        redis_cli("SET", "stats:restore-sentinel", "stale")
        redis_cli("SET", "activity_feed:restore-sentinel", "stale")
        redis_cli("XADD", "stat:events", "*", "data", '{"stale":true}')
        stats_started_before = container_info("stats-worker")["State"]["StartedAt"]

        forward_boundary_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=release-drained,release-renamed",
            "DOJO_RESTORE_TEST_PAUSE_PHASES=validating",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_phase(
            forward_boundary_process,
            backup_filename,
            "validating",
        )
        assert_restore_fence(
            schema,
            9,
            wrong_database_name,
            application_role_before_restore,
        )
        signal_restore(backup_filename, "CONT")
        wait_for_paused_phase(
            forward_boundary_process,
            backup_filename,
            "committed",
        )
        assert_restore_fence(
            schema,
            40,
            wrong_database_name,
            application_role_before_restore,
        )
        assert_repeated_reconnects_rejected(database_name, schema, 41)
        signal_restore(backup_filename, "CONT")
        wait_for_release_renamed(
            forward_boundary_process,
            backup_filename,
            database_name,
        )
        assert_restore_fence(
            schema,
            44,
            wrong_database_name,
            application_role_before_restore,
        )
        signal_restore(backup_filename, "KILL")
        forward_boundary_process.communicate(timeout=15)
        assert forward_boundary_process.returncode != 0
        forward_boundary_process = None
        dojo_run(RESTORE_HELPER, "--recover")
        assert service_snapshot() == expected_services
        assert restore_phase() is None

        forward_boundary_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_POINTS=application-role-enabled",
            "DOJO_RESTORE_TEST_PAUSE_PHASES=committed_exposed",
            RESTORE_HELPER,
            backup_filename,
        )
        wait_for_paused_phase(
            forward_boundary_process,
            backup_filename,
            "committed",
        )
        for service in (*DATABASE_CLIENTS, "nginx"):
            assert container_info(service)["State"]["Running"] is False
        assert application_role_attributes(database_name) == (
            application_role_before_restore
        )
        assert application_database_sql(database_name, "SELECT 1;") == "1"
        signal_restore(backup_filename, "CONT")
        wait_for_paused_phase(
            forward_boundary_process,
            backup_filename,
            "committed_exposed",
        )
        register_user(writer_name)
        signal_restore(backup_filename, "KILL")
        forward_boundary_process.communicate(timeout=15)
        assert forward_boundary_process.returncode != 0
        forward_boundary_process = None
        dojo_run(RESTORE_HELPER, "--recover")

        assert service_snapshot() == expected_services
        assert database_identity() == identity_before
        assert db_sql(
            f"SELECT parents.value FROM {schema}.children "
            f"JOIN {schema}.parents ON parents.id = children.parent_id "
            "WHERE children.id = 1;"
        ).strip() == "from-backup"
        assert db_sql(f"SELECT count(*) FROM {schema}.parents WHERE id = 2;").strip() == "0"
        assert db_sql(f"SELECT count(*) FROM {schema}.payload;").strip() == "100000"
        assert db_sql(f"SELECT to_regnamespace('{live_only_schema}') IS NULL;").strip() == "t"
        assert db_sql(
            f"SELECT to_regnamespace('{injection_schema}') IS NULL;"
        ).strip() == "t"
        assert db_sql(
            f"SELECT count(*) FROM users WHERE name = {sql_literal(writer_name)};"
        ).strip() == "1"
        foreign_key = dojo_run(
            "dojo",
            "db",
            "--set=ON_ERROR_STOP=1",
            input=f"INSERT INTO {schema}.children VALUES (3, 999);",
            check=False,
        )
        assert foreign_key.returncode != 0

        assert redis_cli("EXISTS", "stats:restore-sentinel") == "0"
        assert redis_cli("EXISTS", "activity_feed:restore-sentinel") == "0"
        assert redis_cli("XLEN", "stat:events") == "0"
        assert redis_cli(
            "EXISTS", "stats:belts", "stats:emojis", "stats:containers"
        ) == "3"
        stats = container_info("stats-worker")
        assert stats["State"]["StartedAt"] != stats_started_before
        stats_logs = wait_for_stats_cold_start(stats["State"]["StartedAt"])
        assert "Cold start complete - all stats initialized" in stats_logs
        assert restore_phase() is None

        db_sql(
            f"CREATE ROLE {owner_role};"
            f"CREATE TABLE {schema}.missing_owner (value integer);"
            f"ALTER TABLE {schema}.missing_owner OWNER TO {owner_role};"
        )
        time.sleep(1.1)
        failed_backup_filename = create_backup()
        failed_backup_path = f"/data/backups/{failed_backup_filename}"
        backup_paths.append(failed_backup_path)
        db_sql(
            f"DROP TABLE {schema}.missing_owner;"
            f"DROP ROLE {owner_role};"
            f"INSERT INTO {schema}.parents VALUES (4, 'before-failed-restore');"
        )
        services_before_failure = service_snapshot()
        rollback_boundary_process = outer_process(
            "env",
            "DOJO_RESTORE_TEST_PAUSE_PHASES="
            "rolling_back,rollback_warming,rollback_validating,rolled_back_exposed",
            RESTORE_HELPER,
            failed_backup_filename,
        )
        wait_for_paused_phase(
            rollback_boundary_process,
            failed_backup_filename,
            "rolling_back",
        )
        assert_restore_fence(
            schema,
            10,
            wrong_database_name,
            application_role_before_restore,
        )
        signal_restore(failed_backup_filename, "CONT")
        wait_for_paused_phase(
            rollback_boundary_process,
            failed_backup_filename,
            "rollback_warming",
        )
        assert_restore_fence(
            schema,
            11,
            wrong_database_name,
            application_role_before_restore,
        )
        signal_restore(failed_backup_filename, "CONT")
        wait_for_paused_phase(
            rollback_boundary_process,
            failed_backup_filename,
            "rollback_validating",
        )
        assert_restore_fence(
            schema,
            12,
            wrong_database_name,
            application_role_before_restore,
        )
        signal_restore(failed_backup_filename, "CONT")
        wait_for_paused_phase(
            rollback_boundary_process,
            failed_backup_filename,
            "rolled_back_exposed",
        )
        register_user(rollback_writer_name)
        signal_restore(failed_backup_filename, "KILL")
        rollback_boundary_process.communicate(timeout=15)
        assert rollback_boundary_process.returncode != 0
        rollback_boundary_process = None
        dojo_run(RESTORE_HELPER, "--recover")
        assert service_snapshot() == services_before_failure
        assert db_sql(f"SELECT value FROM {schema}.parents WHERE id = 4;").strip() == (
            "before-failed-restore"
        )
        assert db_sql(f"SELECT to_regclass('{schema}.missing_owner') IS NULL;").strip() == "t"
        assert db_sql(
            "SELECT count(*) FROM users WHERE name IN "
            f"({sql_literal(writer_name)}, {sql_literal(rollback_writer_name)});"
        ).strip() == "2"
        assert db_sql(
            f"SELECT to_regnamespace('{injection_schema}') IS NULL;"
        ).strip() == "t"
        assert database_identity() == identity_before
        assert restore_phase() is None
        assert dojo_run(
            "stat", f"{RESTORE_STATE}/rollback.dump", check=False
        ).returncode != 0

        db_sql(
            f"CREATE SCHEMA {target_only_schema};"
            f"CREATE TABLE {target_only_schema}.must_not_survive (value integer);"
            f"INSERT INTO {target_only_schema}.must_not_survive VALUES (1);"
        )
        time.sleep(1.1)
        validation_failure_backup = create_backup()
        backup_paths.append(f"/data/backups/{validation_failure_backup}")
        db_sql(
            f"DROP SCHEMA {target_only_schema} CASCADE;"
            f"INSERT INTO {schema}.parents VALUES (5, 'before-http-validation');"
        )
        services_before_validation = service_snapshot()
        validation_failure_process = outer_process(
            "env",
            "DOJO_RESTORE_READY_TIMEOUT_SECONDS=60",
            "DOJO_RESTORE_TEST_FAIL_APPLICATION_VALIDATION=1",
            "DOJO_RESTORE_TEST_PAUSE_PHASES=warming,validating",
            RESTORE_HELPER,
            validation_failure_backup,
        )
        wait_for_paused_phase(
            validation_failure_process,
            validation_failure_backup,
            "warming",
        )
        assert_restore_fence(
            schema,
            13,
            wrong_database_name,
            application_role_before_restore,
        )
        signal_restore(validation_failure_backup, "CONT")
        wait_for_paused_phase(
            validation_failure_process,
            validation_failure_backup,
            "validating",
        )
        assert_restore_fence(
            schema,
            14,
            wrong_database_name,
            application_role_before_restore,
        )
        signal_restore(validation_failure_backup, "CONT")
        validation_stdout, validation_stderr = validation_failure_process.communicate(
            timeout=240
        )
        assert validation_failure_process.returncode != 0, validation_stdout
        assert "private application validation failed" in validation_stderr
        validation_failure_process = None
        assert service_snapshot() == services_before_validation
        assert database_identity() == identity_before
        assert db_sql(f"SELECT value FROM {schema}.parents WHERE id = 5;").strip() == (
            "before-http-validation"
        )
        assert db_sql(
            f"SELECT count(*) FROM {schema}.parents WHERE id IN (13, 14);"
        ).strip() == "0"
        assert db_sql(f"SELECT to_regnamespace('{target_only_schema}') IS NULL;").strip() == "t"
        assert restore_phase() is None
        assert dojo_run(
            "stat", f"{RESTORE_STATE}/rollback.dump", check=False
        ).returncode != 0

        assert_dynamic_ctfd_upstream(holder)
    finally:
        if (
            activation_recovery_process is not None
            and activation_recovery_process.poll() is None
        ):
            signal_restore("--recover", "KILL")
            activation_recovery_process.communicate(timeout=15)
        if (
            activation_crash_process is not None
            and activation_crash_process.poll() is None
        ):
            signal_restore(backup_filename, "KILL")
            activation_crash_process.communicate(timeout=15)
        if (
            deactivation_crash_process is not None
            and deactivation_crash_process.poll() is None
        ):
            signal_restore(backup_filename, "KILL")
            deactivation_crash_process.communicate(timeout=15)
        if (
            arbitrary_maintenance_process is not None
            and arbitrary_maintenance_process.poll() is None
        ):
            direct_database_sql(
                "postgres",
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE application_name = {sql_literal(arbitrary_maintenance_application)} "
                "AND pid <> pg_backend_pid();",
                check=False,
            )
            arbitrary_maintenance_process.communicate(timeout=15)
        if interrupted_backup_process is not None and interrupted_backup_process.poll() is None:
            signal_backup("KILL")
            interrupted_backup_process.communicate(timeout=15)
        if orphan_restore_process is not None and orphan_restore_process.poll() is None:
            signal_restore(backup_filename, "KILL")
            orphan_restore_process.communicate(timeout=15)
        if backup_race_process is not None and backup_race_process.poll() is None:
            signal_backup("KILL")
            backup_race_process.communicate(timeout=15)
        if (
            backup_race_restore_process is not None
            and backup_race_restore_process.poll() is None
        ):
            signal_restore(backup_filename, "KILL")
            backup_race_restore_process.communicate(timeout=15)
        if oid_recovery_process is not None and oid_recovery_process.poll() is None:
            signal_restore(backup_filename, "KILL")
            oid_recovery_process.communicate(timeout=15)
        if boot_recovery_process is not None and boot_recovery_process.poll() is None:
            signal_restore(backup_filename, "KILL")
            boot_recovery_process.communicate(timeout=15)
        if fence_substep_process is not None and fence_substep_process.poll() is None:
            signal_restore(backup_filename, "KILL")
            fence_substep_process.communicate(timeout=15)
        if fence_writer_process is not None and fence_writer_process.poll() is None:
            fence_writer_process.kill()
            fence_writer_process.communicate(timeout=15)
        if (
            legacy_recovery_process is not None
            and legacy_recovery_process.poll() is None
        ):
            signal_restore(backup_filename, "KILL")
            legacy_recovery_process.kill()
        if (
            identity_mismatch_process is not None
            and identity_mismatch_process.poll() is None
        ):
            signal_restore(backup_filename, "KILL")
            identity_mismatch_process.kill()
        if (
            validation_failure_process is not None
            and validation_failure_process.poll() is None
        ):
            signal_restore(validation_failure_backup, "KILL")
            validation_failure_process.kill()
        if preflight_race_process is not None and preflight_race_process.poll() is None:
            signal_restore(backup_filename, "KILL")
            preflight_race_process.kill()
        if (
            rollback_boundary_process is not None
            and rollback_boundary_process.poll() is None
        ):
            signal_restore(failed_backup_filename, "KILL")
            rollback_boundary_process.kill()
        if (
            forward_boundary_process is not None
            and forward_boundary_process.poll() is None
        ):
            signal_restore(backup_filename, "KILL")
            forward_boundary_process.kill()
        if waiting_process is not None and waiting_process.poll() is None:
            signal_restore(second_filename, "KILL")
            waiting_process.kill()
        if restore_process is not None and restore_process.poll() is None:
            signal_restore(first_filename, "KILL")
            restore_process.kill()
        dojo_run("docker", "rm", "--force", holder, check=False)
        dojo_run(
            "docker",
            "network",
            "connect",
            "--alias",
            "nginx",
            initial_ctfd_network,
            "nginx",
            check=False,
        )
        for container in DYNAMIC_NGINX_NETWORK_CONTAINERS:
            dojo_run(
                "docker",
                "network",
                "disconnect",
                "--force",
                dynamic_test_network,
                container,
                check=False,
            )
        dojo_run("docker", "network", "rm", dynamic_test_network, check=False)
        if trusted_recovery_journal is not None and journal_writer is not None:
            if trusted_recovery_requires_missing and database_name is not None:
                postgres_sql(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    f"WHERE datname = {sql_literal(database_name)} "
                    "AND pid <> pg_backend_pid();",
                    check=False,
                )
                postgres_sql(
                    f"DROP DATABASE IF EXISTS {sql_identifier(database_name)};",
                    check=False,
                )
                trusted_recovery_journal["phase"] = "restoring"
            dojo_run(
                "python3",
                "-c",
                journal_writer,
                input=json.dumps(trusted_recovery_journal, separators=(",", ":")),
                check=False,
            )
        dojo_run(RESTORE_HELPER, "--recover", check=False)
        trusted_state_cleanup = f"""
import importlib.machinery
import importlib.util

loader = importlib.machinery.SourceFileLoader("cleanup_restore", {RESTORE_HELPER!r})
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
with module.RestoreState() as state:
    state.cleanup()
    module.cleanup_backup_partials(state)
"""
        dojo_run("python3", "-c", trusted_state_cleanup, check=False)
        if collision_role_active and reserved_role is not None:
            direct_database_sql(
                "postgres",
                f"DROP ROLE IF EXISTS {sql_identifier(reserved_role)};"
                f"DROP ROLE IF EXISTS {sql_identifier(collision_member)};",
                check=False,
            )
        if prepared_transaction_active and database_name is not None:
            direct_database_sql(
                database_name,
                f"ROLLBACK PREPARED {sql_literal(prepared_transaction)};",
                check=False,
            )
        if database_name is not None:
            for subscription_cleanup in (
                f"ALTER SUBSCRIPTION {sql_identifier(subscription_name)} DISABLE;",
                f"ALTER SUBSCRIPTION {sql_identifier(subscription_name)} "
                "SET (slot_name = NONE);",
                f"DROP SUBSCRIPTION {sql_identifier(subscription_name)};",
            ):
                direct_database_sql(
                    database_name,
                    subscription_cleanup,
                    check=False,
                )
        dojo_run("dojo", "compose", "up", "--detach", "ctfd", check=False)
        dojo_run(
            "dojo",
            "db",
            "--set=ON_ERROR_STOP=1",
            input=(
                f"DROP SCHEMA IF EXISTS {schema} CASCADE;"
                f"DROP SCHEMA IF EXISTS {live_only_schema} CASCADE;"
                f"DROP SCHEMA IF EXISTS {target_only_schema} CASCADE;"
                f"DROP SCHEMA IF EXISTS {injection_schema} CASCADE;"
                "DELETE FROM users WHERE name IN "
                f"({sql_literal(writer_name)}, {sql_literal(rollback_writer_name)});"
                f"DROP ROLE IF EXISTS {owner_role};"
            ),
            check=False,
        )
        if database_name is not None and initial_database_identity is not None:
            database = sql_identifier(database_name)
            dojo_run(
                "dojo",
                "db",
                "--set=ON_ERROR_STOP=1",
                input=(
                    f"ALTER DATABASE {database} CONNECTION LIMIT "
                    f"{initial_database_identity['connection_limit']};"
                    f"COMMENT ON DATABASE {database} IS "
                    f"{sql_literal(initial_database_identity['comment'])};"
                    f"ALTER DATABASE {database} "
                    f"RESET {sql_identifier(metadata_setting)};"
                ),
                check=False,
            )
            dojo_run(
                "dojo",
                "db",
                "--set=ON_ERROR_STOP=1",
                input=f"DROP ROLE IF EXISTS {sql_identifier(metadata_role)};",
                check=False,
            )
        if postgres_scs_modified:
            postgres_sql(
                "ALTER DATABASE postgres RESET standard_conforming_strings;",
                check=False,
            )
            if postgres_scs_setting in {"on", "off"}:
                postgres_sql(
                    "ALTER DATABASE postgres SET standard_conforming_strings TO "
                    f"{postgres_scs_setting};",
                    check=False,
                )
        if max_prepared_transactions_modified:
            postgres_sql(
                "ALTER SYSTEM RESET max_prepared_transactions;",
                check=False,
            )
            dojo_run("docker", "restart", "db", check=False)
            wait_for_postgres()
        postgres_sql(
            f"DROP DATABASE IF EXISTS {sql_identifier(wrong_database_name)};",
            check=False,
        )
        if backup_paths:
            dojo_run("rm", "--force", *backup_paths, check=False)
        if backup_directories:
            dojo_run("rmdir", *backup_directories, check=False)
        dojo_run("rm", "--recursive", "--force", failed_dump_directory, check=False)
        dojo_run("rm", "--force", legacy_rollback_path, check=False)
        if helper_target is not None:
            dojo_run("ln", "--symbolic", helper_target, helper_link, check=False)
        restore_service_snapshot(initial_services)
        if initial_services["ctfd"]["running"]:
            wait_for_http()


@pytest.mark.timeout(900)
def test_external_database_target_backup_restore_and_rollback():
    suffix = uuid.uuid4().hex
    external_container = f"restore-external-{suffix}"
    external_database = f"restore_external_{suffix}"
    external_user = f"restore_user_{suffix}"
    external_password = f"restore_password_{suffix}"
    restricted_user = f"restore_restricted_{suffix}"
    restricted_password = f"restore_restricted_password_{suffix}"
    sentinel_schema = f"restore_endpoint_{suffix}"
    external_state = f"/data/.dojo-restore-external-{suffix}"
    original_config = dojo_run("cat", "/data/config.env").stdout
    config_changed = False
    backup_paths = []

    def external_sql_result(sql):
        return dojo_run(
            "docker",
            "exec",
            "--env",
            f"PGPASSWORD={external_password}",
            "--env",
            "PGCONNECT_TIMEOUT=5",
            external_container,
            "psql",
            "--host=127.0.0.1",
            "--port=5432",
            f"--username={external_user}",
            f"--dbname={external_database}",
            "--no-psqlrc",
            "--tuples-only",
            "--no-align",
            "--set=ON_ERROR_STOP=1",
            "--command",
            sql,
            check=False,
        )

    def external_sql(sql):
        result = external_sql_result(sql)
        assert result.returncode == 0, (
            f"external PostgreSQL command exited {result.returncode}"
            f"\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        return result.stdout.strip()

    try:
        postgres_sql(
            f"CREATE ROLE {sql_identifier(external_user)} LOGIN SUPERUSER "
            f"PASSWORD {sql_literal(external_password)};"
        )
        postgres_sql(
            f"CREATE DATABASE {sql_identifier(external_database)} "
            f"OWNER {sql_identifier(external_user)};"
        )
        direct_database_sql(
            external_database,
            f"CREATE SCHEMA {sentinel_schema};"
            f"CREATE TABLE {sentinel_schema}.sentinel (value text NOT NULL);"
            f"INSERT INTO {sentinel_schema}.sentinel VALUES ('local-decoy');",
        )

        database_container = container_info("db")
        database_image = database_container["Config"]["Image"]
        database_network = next(iter(database_container["NetworkSettings"]["Networks"]))
        dojo_run(
            "docker",
            "run",
            "--detach",
            "--name",
            external_container,
            "--network",
            database_network,
            "--env",
            f"POSTGRES_USER={external_user}",
            "--env",
            f"POSTGRES_PASSWORD={external_password}",
            "--env",
            f"POSTGRES_DB={external_database}",
            database_image,
        )
        deadline = time.monotonic() + 90
        while True:
            ready = external_sql_result("SELECT 1;")
            if ready.returncode == 0 and ready.stdout.strip() == "1":
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "external PostgreSQL did not accept an authenticated query "
                    f"for the configured database\nstdout:\n{ready.stdout}"
                    f"\nstderr:\n{ready.stderr}"
                )
            time.sleep(1)

        external_config = configured_database_config(
            original_config,
            DB_HOST=external_container,
            DB_PORT="5432",
            DB_NAME=external_database,
            DB_USER=external_user,
            DB_PASS=external_password,
        )
        write_config(external_config)
        config_changed = True
        external_sql(
            f"CREATE SCHEMA {sentinel_schema};"
            f"CREATE TABLE {sentinel_schema}.sentinel (value text NOT NULL);"
            f"INSERT INTO {sentinel_schema}.sentinel VALUES ('external-backup');"
        )

        external_backup = create_backup()
        backup_paths.append(f"/data/backups/{external_backup}")
        assert external_user != external_database
        external_sql(
            f"UPDATE {sentinel_schema}.sentinel SET value = 'external-live';"
        )
        direct_database_sql(
            external_database,
            f"UPDATE {sentinel_schema}.sentinel SET value = 'local-decoy-live';",
        )
        external_sql(
            f"CREATE ROLE {sql_identifier(restricted_user)} LOGIN NOSUPERUSER "
            f"NOCREATEDB NOCREATEROLE PASSWORD {sql_literal(restricted_password)};"
            f"GRANT pg_monitor TO {sql_identifier(restricted_user)};"
            f"ALTER DATABASE {sql_identifier(external_database)} "
            f"OWNER TO {sql_identifier(restricted_user)};"
        )
        restricted_config = configured_database_config(
            external_config,
            DB_USER=restricted_user,
            DB_PASS=restricted_password,
        )
        write_config(restricted_config)
        services_before_restricted_restore = service_snapshot()
        external_oid_before_restricted_restore = external_sql(
            "SELECT oid::bigint FROM pg_database "
            f"WHERE datname = {sql_literal(external_database)};"
        )
        restricted_restore = dojo_run(
            "dojo",
            "restore",
            external_backup,
            check=False,
        )
        assert restricted_restore.returncode != 0
        assert "maintenance role to be a superuser" in restricted_restore.stderr
        assert service_snapshot() == services_before_restricted_restore
        assert external_sql(
            "SELECT oid::bigint FROM pg_database "
            f"WHERE datname = {sql_literal(external_database)};"
        ) == external_oid_before_restricted_restore
        assert external_sql(
            f"SELECT value FROM {sentinel_schema}.sentinel;"
        ) == "external-live"
        assert restore_phase() is None
        write_config(external_config)
        maintenance_program = f"""
import importlib.machinery
import importlib.util
import pathlib
import shutil

path = pathlib.Path({RESTORE_HELPER!r})
loader = importlib.machinery.SourceFileLoader("external_restore", str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
module.STATE_DIRECTORY = pathlib.Path({external_state!r})
shutil.rmtree(module.STATE_DIRECTORY, ignore_errors=True)

class Services:
    ready_timeout = 30

    def verify_clients_stopped(self):
        pass

runner = module.CommandRunner()
target = module.DatabaseTarget.from_environment()
services = Services()

def target_sql(sql):
    result = database.target.run_client(
        runner,
        "psql",
        (
            "--no-psqlrc",
            "--tuples-only",
            "--no-align",
            "--set=ON_ERROR_STOP=1",
            "--command",
            sql,
        ),
        database=database.target.name,
        connect=True,
        application_name=database.restore_application_name,
        capture_output=True,
    )
    return result.stdout.decode().strip()

with module.RestoreState() as state:
    database = module.DatabaseRestore(runner, state, services, target)
    metadata = database.capture_metadata()
    application_role = database.verify_application_role()
    journal = {{
        "version": 5,
        "phase": "snapshotting",
        "services": {{
            service: {{
                "id": f"external-{{service}}",
                "restart_policy": "no",
                "restart_retries": 0,
                "running": False,
                "status": "exited",
            }}
            for service in module.SNAPSHOT_SERVICES
        }},
        "database": metadata,
        "target": database.capture_target(),
        "installation_id": state.installation_id,
        "application_role": application_role,
        "maintenance": "activating",
    }}
    state.write_journal(journal)
    database.activate_maintenance_role()
    state.set_maintenance(journal, "active")
    database.establish_fence(metadata, application_role)
    with module.open_archive({external_backup!r}) as archive:
        database.restore_archive(archive, metadata)
    value = target_sql("SELECT value FROM {sentinel_schema}.sentinel;")
    if value != "external-backup":
        raise RuntimeError(f"configured restore used the wrong database: {{value}}")
    target_sql(
        "UPDATE {sentinel_schema}.sentinel SET value = 'external-acknowledged';"
    )
    restored_metadata = metadata
    state.set_phase(journal, "ready")
    database.create_rollback()
    target_sql("UPDATE {sentinel_schema}.sentinel SET value = 'destructive';")
    database.restore_rollback()
    database.release_fence(restored_metadata, application_role)
    module.deactivate_maintenance_before_exposure(state, journal, database)
    state.cleanup()
shutil.rmtree(module.STATE_DIRECTORY, ignore_errors=True)
"""
        maintenance = dojo_run(
            "sh",
            "-c",
            (
                ". /data/config.env; "
                "DB_PORT=${DB_PORT:-5432}; "
                "export DB_HOST DB_PORT DB_NAME DB_USER DB_PASS; "
                "exec python3 -c \"$1\""
            ),
            "external-maintenance",
            maintenance_program,
            check=False,
        )
        assert maintenance.returncode == 0, maintenance.stderr
        assert external_sql(
            f"SELECT value FROM {sentinel_schema}.sentinel;"
        ) == "external-acknowledged"
        assert direct_database_sql(
            external_database,
            f"SELECT value FROM {sentinel_schema}.sentinel;",
        ) == "local-decoy-live"
    finally:
        if config_changed:
            write_config(original_config)
            config_changed = False
        dojo_run("rm", "--recursive", "--force", external_state, check=False)
        dojo_run("docker", "rm", "--force", external_container, check=False)
        postgres_sql(
            f"DROP DATABASE IF EXISTS {sql_identifier(external_database)};",
            check=False,
        )
        postgres_sql(
            f"DROP ROLE IF EXISTS {sql_identifier(external_user)};",
            check=False,
        )
        if backup_paths:
            dojo_run("rm", "--force", *backup_paths, check=False)
