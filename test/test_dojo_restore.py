import contextlib
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time

import pytest

from restore_test_utils import (
    docker_network_ip_owners,
    is_transient_docker_ip_allocation_error,
)


def load_restore_module():
    path = pathlib.Path(__file__).parents[1] / "dojo" / "dojo-restore"
    loader = importlib.machinery.SourceFileLoader("dojo_restore", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


RESTORE_MODULE = load_restore_module()
TEST_INSTALLATION_ID = "1" * RESTORE_MODULE.INSTALLATION_ID_LENGTH


def test_docker_network_ip_owners_matches_exact_ipv4_address():
    inspection = [
        {
            "Containers": {
                "first-id": {
                    "Name": "ctfd",
                    "IPv4Address": "172.19.0.12/16",
                },
                "second-id": {
                    "Name": "cache",
                    "IPv4Address": "172.19.0.2/16",
                },
                "third-id": {
                    "Name": "",
                    "IPv4Address": "172.19.0.12/16",
                },
            }
        }
    ]

    assert docker_network_ip_owners(inspection, "172.19.0.12") == [
        "ctfd",
        "third-id",
    ]
    assert docker_network_ip_owners(inspection, "172.19.0.1") == []
    with pytest.raises(ValueError, match="exactly one network"):
        docker_network_ip_owners([], "172.19.0.12")


def test_transient_docker_ip_allocation_error_is_narrow():
    assert is_transient_docker_ip_allocation_error(
        "failed to create endpoint: Address already in use"
    )
    assert is_transient_docker_ip_allocation_error(
        "requested IP address is already allocated"
    )
    assert not is_transient_docker_ip_allocation_error("pull access denied")
    assert not is_transient_docker_ip_allocation_error(
        "no configured subnet contains the IP address"
    )


def test_first_state_and_backup_directories_are_parent_anchored(monkeypatch, tmp_path):
    state_directory = tmp_path / "restore-state"
    backup_directory = tmp_path / "backups"
    monkeypatch.setattr(RESTORE_MODULE, "STATE_DIRECTORY", state_directory)
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_DIRECTORY", backup_directory)
    monkeypatch.setattr(RESTORE_MODULE, "STATE_OWNER_UID", os.getuid())
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_OWNER_UID", os.getuid())
    real_fsync = RESTORE_MODULE.os.fsync
    synced_inodes = []

    def record_fsync(descriptor):
        synced_inodes.append(os.fstat(descriptor).st_ino)
        real_fsync(descriptor)

    monkeypatch.setattr(RESTORE_MODULE.os, "fsync", record_fsync)
    parent_inode = tmp_path.stat().st_ino

    with RESTORE_MODULE.RestoreState() as state:
        installation_id = state.installation_id
        maintenance_secret = state.maintenance_secret
        assert state_directory.stat().st_mode & 0o777 == 0o700
        assert parent_inode in synced_inodes

    backup_descriptor = RESTORE_MODULE.open_backup_directory(create=True)
    os.close(backup_descriptor)

    assert synced_inodes.count(parent_inode) >= 2
    with RESTORE_MODULE.RestoreState() as reopened:
        assert reopened.installation_id == installation_id
        assert reopened.maintenance_secret == maintenance_secret


def test_command_timeout_kills_the_blocking_process_group(tmp_path):
    child_pid_path = tmp_path / "child-pid"
    program = (
        "import pathlib,subprocess,time;"
        "child=subprocess.Popen(['sleep','30']);"
        f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid));"
        "time.sleep(30)"
    )
    runner = RESTORE_MODULE.CommandRunner()

    with pytest.raises(RESTORE_MODULE.RestoreError, match="command timed out"):
        runner.run([sys.executable, "-c", program], timeout=0.2)

    child_pid = int(child_pid_path.read_text())
    deadline = time.monotonic() + 2
    process_stat = pathlib.Path(f"/proc/{child_pid}/stat")
    while process_stat.exists() and time.monotonic() < deadline:
        if process_stat.read_text().rsplit(")", 1)[1].strip().split()[0] == "Z":
            break
        time.sleep(0.01)
    assert not process_stat.exists() or (
        process_stat.read_text().rsplit(")", 1)[1].strip().split()[0] == "Z"
    )


class FakeClock:
    def __init__(self):
        self.current = 0

    def monotonic(self):
        return self.current

    def sleep(self, seconds):
        self.current += seconds

    def reset(self):
        self.current = 0


class UnreadyRunner:
    def run(self, arguments, **_options):
        if "FLUSHDB" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b"OK\n", b"")
        if arguments[1:2] == ["logs"]:
            return subprocess.CompletedProcess(arguments, 0, b"", b"")
        return subprocess.CompletedProcess(arguments, 1, b"", b"not ready")


def database_metadata():
    escaped_value = "metadata\\'; SELECT pg_sleep(10); --"
    return {
        "oid": 20000,
        "owner": "ctfd",
        "encoding": "UTF8",
        "locale_provider": "libc",
        "collate": "C.UTF-8",
        "ctype": "C.UTF-8",
        "locale": None,
        "icu_rules": None,
        "collation_version": "2.39",
        "tablespace": "pg_default",
        "allow_connections": True,
        "is_template": False,
        "connection_limit": -1,
        "acl_default": False,
        "acl": [
            {
                "grantor": "ctfd",
                "grantee": None,
                "privilege": "CONNECT",
                "grantable": False,
            },
            {
                "grantor": "ctfd",
                "grantee": "ctfd",
                "privilege": "CONNECT",
                "grantable": True,
            },
        ],
        "comment": escaped_value,
        "security_labels": [{"provider": "selinux", "label": escaped_value}],
        "settings": [
            {"role": None, "name": "application_name", "value": escaped_value},
            {
                "role": "reader",
                "name": "statement_timeout",
                "value": "5s",
            },
        ],
    }


def database_target():
    return RESTORE_MODULE.DatabaseTarget("db", 5432, "ctfd", "ctfd", "secret")


def test_exported_database_snapshot_stays_open_until_consumer_finishes():
    invocations = []

    class Target:
        name = "ctfd"

        def client_invocation(self, program, arguments, **options):
            invocations.append((program, arguments, options))
            return (
                [
                    "sh",
                    "-c",
                    "read first; read second; "
                    "printf '%s\\n' 00000003-0000001B-1; "
                    "read rollback; read quit",
                ],
                os.environ.copy(),
                2,
            )

    with RESTORE_MODULE.exported_database_snapshot(
        Target(),
        TEST_INSTALLATION_ID,
        2,
    ) as snapshot:
        assert snapshot == "00000003-0000001B-1"

    assert invocations[0][0] == "psql"
    assert invocations[0][2]["input_stream"] is True
    assert invocations[0][2]["application_name"].startswith("dojo-backup:")


def server_identity():
    return {
        "system_identifier": "7487293819472938472",
        "server_version_num": 170005,
    }


def backup_dependencies():
    def role(name, *, superuser=False, login=False):
        return {
            "name": name,
            "superuser": superuser,
            "inherit": True,
            "create_db": superuser,
            "create_role": superuser,
            "login": login,
            "replication": False,
            "bypass_rls": False,
            "connection_limit": -1,
            "valid_until": None,
            "config": [],
        }

    return {
        "roles": [
            role("ctfd", superuser=True, login=True),
            role("reader"),
        ],
        "memberships": [],
        "default_acls": [],
        "tablespaces": [],
    }


def backup_source():
    return {
        "server": server_identity(),
        "database": {"name": "ctfd", "metadata": database_metadata()},
        "pg_dump_major": RESTORE_MODULE.SUPPORTED_POSTGRES_MAJOR,
        "dependencies": backup_dependencies(),
    }


def journal_target():
    return database_target().journal_target(server_identity())


def service_snapshot(*, legacy=False):
    services = (
        RESTORE_MODULE.LEGACY_SNAPSHOT_SERVICES
        if legacy
        else RESTORE_MODULE.SNAPSHOT_SERVICES
    )
    return {
        service: {
            "id": f"{service}-id",
            "restart_policy": "always",
            "restart_retries": 0,
            "running": True,
            "status": "running",
        }
        for service in services
    }


def restore_journal(phase, *, legacy=False, version=None):
    version = version or (1 if legacy else 5)
    journal = {
        "version": version,
        "phase": phase,
        "services": service_snapshot(legacy=legacy),
        "database": database_metadata(),
    }
    if version in {2, 3, 4, 5}:
        journal["target"] = journal_target()
    if version in {3, 4, 5}:
        journal["installation_id"] = TEST_INSTALLATION_ID
    if version in {4, 5}:
        journal["application_role"] = {"name": "ctfd", "login": True}
    if version == 5:
        journal["maintenance"] = "active"
    return journal


class RecordingState:
    def __init__(self, journal, events):
        self.journal = journal
        self.events = events
        self.installation_id = TEST_INSTALLATION_ID

    def load_journal(self):
        return self.journal

    def write_journal(self, journal):
        RESTORE_MODULE.RestoreState()._validate_journal(journal)
        self.journal = journal
        self.events.append(
            (
                "write_journal",
                journal.get("phase"),
                set(journal["services"]),
                journal.get("maintenance"),
            )
        )

    def set_phase(self, journal, phase):
        journal["phase"] = phase
        self.events.append(("set_phase", phase))

    def set_maintenance(self, journal, maintenance):
        journal["maintenance"] = maintenance
        self.events.append(("set_maintenance", maintenance))

    def cleanup(self):
        self.events.append(("cleanup",))


class RecordingServices:
    def __init__(
        self,
        events,
        *,
        pgbouncer_running,
        database_available=True,
        database_present=True,
    ):
        self.events = events
        self.pgbouncer_running = pgbouncer_running
        self.database_available = database_available
        self.database_present = database_present

    def snapshot_service(self, service):
        self.events.append(("snapshot_service", service))
        return service_snapshot()[service]

    def require_supported_snapshot(self, snapshot):
        self.events.append(("require_supported_snapshot", set(snapshot)))

    def database_client_available(self):
        self.events.append(("database_client_available",))
        return self.database_available

    def snapshot_database_for_startup(self):
        self.events.append(("snapshot_database_for_startup",))
        return {
            "present": self.database_present,
            "running": self.database_available,
            "id": "db-id" if self.database_present else None,
        }

    def snapshot_for_startup(self):
        self.events.append(("snapshot_for_startup",))
        return service_snapshot()

    def ensure_database_client(self):
        self.events.append(("ensure_database_client",))

    def verify_startup_database_identity(self, expected):
        self.events.append(("verify_startup_database_identity", expected["id"]))

    def bind_startup_database_identity(self, expected):
        self.events.append(("bind_startup_database_identity", expected["id"]))
        return {"present": True, "running": True, "id": "db-id"}

    def inspect(self, service):
        self.events.append(("inspect", service))
        return {"running": self.pgbouncer_running}

    def verify_identities(self, snapshot):
        self.events.append(("verify_identities", set(snapshot)))

    def cleanup_private_validation(self):
        self.events.append(("cleanup_private_validation",))

    def gate_restarts(self, snapshot):
        self.events.append(("gate_restarts", set(snapshot)))

    def stop_clients(self, snapshot):
        self.events.append(("stop_clients", set(snapshot)))

    def warm_cache(self):
        self.events.append(("warm_cache",))

    def validate_application(self):
        self.events.append(("validate_application",))

    def restore_snapshot(self, snapshot):
        self.events.append(("restore_snapshot", set(snapshot)))

    def wait_external_http(self):
        self.events.append(("wait_external_http",))


class RecordingDatabase:
    def __init__(self, events):
        self.events = events
        self.maintenance_target = "maintenance-target"
        self.application_target = database_target()

    def terminate_maintenance_backends(self):
        self.events.append(("terminate_maintenance_backends",))

    def use_maintenance_target(self):
        self.events.append(("use_maintenance_target",))

    def use_application_target(self):
        self.events.append(("use_application_target",))

    def wait_ready(self):
        self.events.append(("wait_ready",))

    def verify_application_role(self):
        self.events.append(("verify_application_role",))
        return {"name": "ctfd", "login": True}

    def verify_maintenance_role_reusable(self):
        self.events.append(("verify_maintenance_role_reusable",))
        return None

    def verify_maintenance_role_deactivatable(self):
        return None

    def capture_maintenance_role(self, *, target=None):
        self.events.append(("capture_maintenance_role", target))
        return {"login": True}

    def verify_maintenance_role(self, _role, *, login):
        self.events.append(("verify_maintenance_role", login))

    def capture_application_role(self):
        self.events.append(("capture_application_role",))
        return {"name": "ctfd", "login": True}

    def activate_maintenance_role(self):
        self.events.append(("activate_maintenance_role",))

    def establish_fence(self, _metadata, _application_role):
        self.events.append(("establish_fence",))

    def release_fence(self, _metadata, _application_role):
        self.events.append(("release_fence",))

    def deactivate_maintenance_role(self):
        self.events.append(("deactivate_maintenance_role",))

    def verify_journal_identity(self, journal):
        self.events.append(("verify_journal_identity", journal["phase"]))

    def verify_configured_target(self, _target):
        self.events.append(("verify_configured_target",))

    def verify_configured_startup_target(self, _target):
        self.events.append(("verify_configured_startup_target",))

    def verify_recreation_privileges(self):
        self.events.append(("verify_recreation_privileges",))

    def restore_rollback(self):
        self.events.append(("restore_rollback",))

    def verify_fence_integrity(self):
        pass


def test_version_one_legacy_service_snapshot_remains_loadable():
    RESTORE_MODULE.RestoreState()._validate_journal(
        restore_journal("restoring", legacy=True)
    )


def test_version_two_journal_binds_database_target_and_server():
    journal = restore_journal("restoring", version=2)
    RESTORE_MODULE.RestoreState()._validate_journal(journal)
    assert journal["target"] == journal_target()

    journal["target"]["server"]["system_identifier"] = "invalid"
    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="system identifier",
    ):
        RESTORE_MODULE.RestoreState()._validate_journal(journal)


@pytest.mark.parametrize(
    "database",
    [
        {"present": False, "running": False},
        {"present": False, "running": False, "id": "db-id"},
        {"present": False, "running": False, "id": ""},
        {"present": True, "running": False, "id": None},
        {"present": True, "running": False, "id": 1},
        {"present": False, "running": True, "id": None},
    ],
)
def test_startup_journal_requires_consistent_stopped_database_identity(database):
    journal = {
        "version": 6,
        "kind": "startup",
        "services": service_snapshot(),
        "installation_id": TEST_INSTALLATION_ID,
        "database": database,
        "target": database_target().configuration(),
    }

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="invalid startup database state",
    ):
        RESTORE_MODULE.RestoreState()._validate_journal(journal)


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize(
    "phase",
    ["snapshotting", "restoring", "rolling_back", "committed"],
)
def test_legacy_no_nginx_journals_fail_before_docker_or_database_actions(
    version,
    phase,
):
    journal = restore_journal(phase, legacy=True, version=version)

    class State:
        installation_id = TEST_INSTALLATION_ID
        maintenance_secret = "2" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

        def load_journal(self):
            RESTORE_MODULE.RestoreState()._validate_journal(journal)
            return journal

    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            raise AssertionError("legacy journal reached an external command")

    runner = Runner()
    state = State()
    services = RESTORE_MODULE.DockerServices(runner, database_target())
    database = RESTORE_MODULE.DatabaseRestore(
        runner,
        state,
        services,
        database_target(),
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="unsupported legacy service snapshot",
    ):
        RESTORE_MODULE.recover_restore(state, database, services)

    assert runner.calls == []


@pytest.mark.parametrize(
    "method_name",
    ["gate_restarts", "stop_clients", "restore_snapshot"],
)
def test_docker_services_reject_legacy_snapshots_before_commands(method_name):
    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            raise AssertionError("unsupported snapshot reached Docker")

    runner = Runner()
    services = RESTORE_MODULE.DockerServices(runner, database_target())

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="unsupported service snapshot",
    ):
        getattr(services, method_name)(service_snapshot(legacy=True))

    assert runner.calls == []


def test_startup_snapshot_handles_database_outage_and_defers_partial_deployment(
    monkeypatch,
):
    services = RESTORE_MODULE.DockerServices(UnreadyRunner(), database_target())

    def running_state(service):
        return {
            "id": f"{service}-id",
            "running": True,
            "status": "running",
            "paused": False,
            "restarting": False,
            "started_at": "now",
            "health": "unhealthy",
            "restart_policy": "always",
            "restart_retries": 0,
        }

    monkeypatch.setattr(services, "inspect", running_state)
    snapshot = services.snapshot_for_startup()
    assert set(snapshot) == set(RESTORE_MODULE.SNAPSHOT_SERVICES)
    assert all(service["running"] for service in snapshot.values())

    monkeypatch.setattr(
        services,
        "inspect",
        lambda service: None if service == "nginx" else running_state(service),
    )
    assert services.snapshot_for_startup() is None


def test_startup_database_snapshot_distinguishes_absent_and_stopped(monkeypatch):
    services = RESTORE_MODULE.DockerServices(UnreadyRunner(), database_target())
    monkeypatch.setattr(services, "inspect", lambda _service: None)
    assert services.snapshot_database_for_startup() == {
        "present": False,
        "running": False,
        "id": None,
    }
    monkeypatch.setattr(
        services,
        "inspect",
        lambda _service: {
            "id": "db-id",
            "running": False,
            "status": "exited",
            "paused": False,
            "restarting": False,
        },
    )
    assert services.snapshot_database_for_startup() == {
        "present": True,
        "running": False,
        "id": "db-id",
    }


def test_startup_database_identity_rejects_replacement_but_allows_clean_create(
    monkeypatch,
):
    services = RESTORE_MODULE.DockerServices(UnreadyRunner(), database_target())
    current = {
        "id": "original-db-id",
        "running": True,
        "status": "running",
        "paused": False,
        "restarting": False,
    }
    monkeypatch.setattr(services, "inspect", lambda _service: current)
    services.verify_startup_database_identity(
        {"present": True, "running": False, "id": "original-db-id"}
    )

    current["id"] = "replacement-db-id"
    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="database container changed during startup recovery",
    ):
        services.verify_startup_database_identity(
            {"present": True, "running": False, "id": "original-db-id"}
        )

    services.verify_startup_database_identity(
        {"present": False, "running": False, "id": None}
    )


def test_recovery_rejects_target_change_before_service_or_database_mutation():
    events = []
    state = RecordingState(restore_journal("restoring"), events)
    services = RecordingServices(events, pgbouncer_running=False)

    class ChangedDatabase(RecordingDatabase):
        def verify_configured_target(self, _target):
            self.events.append(("verify_configured_target",))
            raise RESTORE_MODULE.RestoreError("configured database target changed")

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="database target changed",
    ):
        RESTORE_MODULE.recover_restore(
            state,
            ChangedDatabase(events),
            services,
        )

    assert events == [("verify_configured_target",)]


def test_clean_startup_without_database_container_skips_psql(monkeypatch):
    events = []

    class MissingDatabaseRunner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            return subprocess.CompletedProcess(
                arguments,
                1,
                b"",
                b"Error: No such container: db\n",
            )

    class EmptyState:
        locked = True

        def __enter__(self):
            events.append("lock")
            return self

        def __exit__(self, *_arguments):
            events.append("unlock")

        def load_journal(self):
            events.append("journal")
            return None

        def _unlink_trusted(self, name):
            events.append(("unlink", name))
            raise FileNotFoundError

    runner = MissingDatabaseRunner()
    monkeypatch.setattr(RESTORE_MODULE, "CommandRunner", lambda: runner)
    monkeypatch.setattr(RESTORE_MODULE, "RestoreState", EmptyState)
    monkeypatch.setattr(
        RESTORE_MODULE.DatabaseTarget,
        "from_environment",
        classmethod(lambda _cls: database_target()),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "install_interrupt_handlers",
        lambda _runner, _operation: events.append("handlers"),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "cleanup_backup_partials",
        lambda _state: events.append("partial-cleanup"),
    )

    RESTORE_MODULE.restore()

    assert [call[0] for call in runner.calls] == [
        ["docker", "inspect", "--type=container", "db"]
    ]
    assert runner.calls[0][1]["check"] is False
    assert events == [
        "handlers",
        "lock",
        "journal",
        ("unlink", "rollback.dump"),
        "partial-cleanup",
        "unlock",
    ]


def test_no_journal_recovery_deactivates_owned_role_after_database_start():
    events = []

    class EmptyState:
        def load_journal(self):
            events.append(("load_journal",))
            return None

        def _unlink_trusted(self, name):
            events.append(("unlink", name))
            raise FileNotFoundError

        def _fsync_directory(self):
            events.append(("fsync",))

    services = RecordingServices(
        events,
        pgbouncer_running=False,
        database_available=True,
    )
    database = RecordingDatabase(events)

    RESTORE_MODULE.recover_restore(EmptyState(), database, services)

    assert events == [
        ("load_journal",),
        ("database_client_available",),
        ("use_application_target",),
        ("wait_ready",),
        ("terminate_maintenance_backends",),
        ("deactivate_maintenance_role",),
        ("terminate_maintenance_backends",),
        ("unlink", "rollback.dump"),
    ]


def test_prepare_without_database_writes_startup_gate_before_client_mutation():
    events = []
    state = RecordingState(None, events)
    services = RecordingServices(
        events,
        pgbouncer_running=True,
        database_available=False,
        database_present=False,
    )

    RESTORE_MODULE.prepare_restore_recovery(
        state,
        RecordingDatabase(events),
        services,
    )

    assert state.journal == {
        "version": 6,
        "kind": "startup",
        "services": service_snapshot(),
        "installation_id": TEST_INSTALLATION_ID,
        "database": {"present": False, "running": False, "id": None},
        "target": database_target().configuration(),
    }
    write_index = next(
        index for index, event in enumerate(events) if event[0] == "write_journal"
    )
    gate_index = events.index(
        ("gate_restarts", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    stop_index = events.index(
        ("stop_clients", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    assert write_index < gate_index < stop_index
    assert ("ensure_database_client",) not in events


def test_startup_gate_recovery_deactivates_before_exact_service_restore(monkeypatch):
    events = []
    monkeypatch.setattr(
        RESTORE_MODULE,
        "pause_for_test",
        lambda point: events.append(("pause", point)),
    )
    state = RecordingState(
        {
            "version": 6,
            "kind": "startup",
            "services": service_snapshot(),
            "installation_id": TEST_INSTALLATION_ID,
            "database": {"present": False, "running": False, "id": None},
            "target": database_target().configuration(),
        },
        events,
    )
    services = RecordingServices(events, pgbouncer_running=False)

    RESTORE_MODULE.recover_restore(
        state,
        RecordingDatabase(events),
        services,
    )

    stop_index = events.index(
        ("stop_clients", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    database_index = events.index(("ensure_database_client",))
    bind_index = events.index(("bind_startup_database_identity", None))
    deactivate_index = events.index(("deactivate_maintenance_role",))
    pause_index = events.index(
        ("pause", "startup-maintenance-role-deactivated")
    )
    restore_index = events.index(
        ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    cleanup_index = events.index(("cleanup",))
    assert (
        stop_index
        < database_index
        < bind_index
        < deactivate_index
        < pause_index
        < restore_index
        < cleanup_index
    )
    assert state.journal["database"] == {
        "present": True,
        "running": True,
        "id": "db-id",
    }


def test_startup_gate_rejects_database_replacement_before_database_actions():
    events = []
    state = RecordingState(
        {
            "version": 6,
            "kind": "startup",
            "services": service_snapshot(),
            "installation_id": TEST_INSTALLATION_ID,
            "database": {
                "present": True,
                "running": False,
                "id": "original-db-id",
            },
            "target": database_target().configuration(),
        },
        events,
    )

    class ReplacedDatabaseServices(RecordingServices):
        def verify_startup_database_identity(self, expected):
            super().verify_startup_database_identity(expected)
            raise RESTORE_MODULE.RestoreError(
                "database container changed during startup recovery"
            )

    services = ReplacedDatabaseServices(events, pgbouncer_running=False)

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="database container changed during startup recovery",
    ):
        RESTORE_MODULE.recover_restore(
            state,
            RecordingDatabase(events),
            services,
        )

    assert ("ensure_database_client",) not in events
    assert ("deactivate_maintenance_role",) not in events
    assert not any(event[0] == "restore_snapshot" for event in events)


def test_prepare_clean_startup_with_no_tracked_containers_needs_no_marker():
    events = []
    state = RecordingState(None, events)

    class EmptyServices(RecordingServices):
        def snapshot_for_startup(self):
            self.events.append(("snapshot_for_startup",))
            return None

    services = EmptyServices(
        events,
        pgbouncer_running=False,
        database_available=False,
        database_present=False,
    )

    RESTORE_MODULE.prepare_restore_recovery(
        state,
        RecordingDatabase(events),
        services,
    )

    assert state.journal is None
    assert events == [
        ("snapshot_database_for_startup",),
        ("snapshot_for_startup",),
    ]


def test_prepare_with_running_database_deactivates_before_service_actions():
    events = []
    state = RecordingState(None, events)
    services = RecordingServices(events, pgbouncer_running=True)

    RESTORE_MODULE.prepare_restore_recovery(
        state,
        RecordingDatabase(events),
        services,
    )

    assert state.journal is None
    assert events == [
        ("snapshot_database_for_startup",),
        ("use_application_target",),
        ("wait_ready",),
        ("terminate_maintenance_backends",),
        ("deactivate_maintenance_role",),
        ("terminate_maintenance_backends",),
    ]


def test_startup_gate_never_overwrites_pending_restore_journal():
    events = []
    pending = restore_journal("restoring")
    state = RecordingState(pending, events)
    services = RecordingServices(
        events,
        pgbouncer_running=False,
        database_available=False,
        database_present=False,
    )

    RESTORE_MODULE.prepare_restore_recovery(
        state,
        RecordingDatabase(events),
        services,
    )

    assert state.journal is pending
    assert not any(event[0] == "write_journal" for event in events)
    assert ("snapshot_database_for_startup",) not in events


def test_ready_recovery_restores_services_without_recreating_database():
    events = []
    state = RecordingState(restore_journal("ready"), events)
    services = RecordingServices(events, pgbouncer_running=False)
    database = RecordingDatabase(events)

    RESTORE_MODULE.recover_restore(state, database, services)

    assert ("restore_rollback",) not in events
    assert ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES)) in events
    assert ("wait_external_http",) in events
    deactivate_index = events.index(("deactivate_maintenance_role",))
    inactive_index = events.index(("set_maintenance", "inactive"))
    restore_index = events.index(
        ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    assert deactivate_index < inactive_index < restore_index
    assert events[-2:] == [("wait_external_http",), ("cleanup",)]
    assert events.count(("terminate_maintenance_backends",)) == 4
    termination_indices = [
        index
        for index, event in enumerate(events)
        if event == ("terminate_maintenance_backends",)
    ]
    assert termination_indices[0] < events.index(("cleanup_private_validation",))
    assert termination_indices[-1] < events.index(
        ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    assert termination_indices[-2] < deactivate_index < termination_indices[-1]


def test_version_two_recovery_accepts_legacy_login_role_with_clients_stopped():
    events = []
    journal = restore_journal("ready", version=2)
    state = RecordingState(journal, events)
    services = RecordingServices(events, pgbouncer_running=False)
    database = RecordingDatabase(events)

    RESTORE_MODULE.recover_restore(state, database, services)

    assert ("use_application_target",) in events
    assert ("verify_application_role",) in events
    assert ("activate_maintenance_role",) in events
    assert state.journal["version"] == 5
    assert state.journal["installation_id"] == TEST_INSTALLATION_ID
    assert state.journal["application_role"] == {"name": "ctfd", "login": True}
    write_index = next(
        index for index, event in enumerate(events) if event[0] == "write_journal"
    )
    activate_index = events.index(("activate_maintenance_role",))
    active_index = events.index(("set_maintenance", "active"))
    stop_index = events.index(("stop_clients", set(RESTORE_MODULE.SNAPSHOT_SERVICES)))
    assert events[write_index][3] == "activating"
    assert write_index < stop_index < activate_index < active_index


@pytest.mark.parametrize("maintenance", ["activating", "deactivating", "inactive"])
def test_inactive_lifecycle_recovery_uses_application_role_before_exposure(
    maintenance,
    monkeypatch,
):
    events = []
    monkeypatch.setattr(
        RESTORE_MODULE,
        "pause_for_test",
        lambda point: events.append(("pause", point)),
    )
    journal = restore_journal("committed")
    journal["maintenance"] = maintenance
    state = RecordingState(journal, events)
    services = RecordingServices(events, pgbouncer_running=False)
    database = RecordingDatabase(events)

    RESTORE_MODULE.recover_restore(state, database, services)

    assert ("use_maintenance_target",) not in events
    assert ("activate_maintenance_role",) not in events
    deactivate_index = events.index(("deactivate_maintenance_role",))
    pause_index = events.index(
        ("pause", "journal-maintenance-role-deactivated")
    )
    restore_index = events.index(
        ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    cleanup_index = events.index(("cleanup",))
    assert deactivate_index < pause_index < restore_index < cleanup_index
    if maintenance != "inactive":
        inactive_index = events.index(("set_maintenance", "inactive"))
        assert pause_index < inactive_index < restore_index


def test_exposure_deactivation_pause_has_durable_marker_and_inactive_role(
    monkeypatch,
):
    events = []
    journal = restore_journal("committed")
    state = RecordingState(journal, events)
    database = RecordingDatabase(events)
    monkeypatch.setattr(
        RESTORE_MODULE,
        "pause_for_test",
        lambda point: events.append(("pause", point)),
    )

    RESTORE_MODULE.deactivate_maintenance_before_exposure(
        state,
        journal,
        database,
    )

    deactivating_index = events.index(("set_maintenance", "deactivating"))
    role_index = events.index(("deactivate_maintenance_role",))
    pause_index = events.index(
        ("pause", "journal-maintenance-role-deactivated")
    )
    inactive_index = events.index(("set_maintenance", "inactive"))
    assert deactivating_index < role_index < pause_index < inactive_index


def test_deactivation_failure_keeps_durable_marker_and_services_stopped():
    events = []
    journal = restore_journal("snapshotting")
    state = RecordingState(journal, events)
    services = RecordingServices(events, pgbouncer_running=False)

    class FailingDatabase(RecordingDatabase):
        def deactivate_maintenance_role(self):
            self.events.append(("deactivate_maintenance_role",))
            raise RESTORE_MODULE.RestoreError("injected deactivation failure")

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="injected deactivation failure",
    ):
        RESTORE_MODULE.recover_restore(state, FailingDatabase(events), services)

    assert state.journal["maintenance"] == "deactivating"
    assert ("cleanup",) not in events
    assert (
        "restore_snapshot",
        set(RESTORE_MODULE.SNAPSHOT_SERVICES),
    ) not in events


def test_prepare_recovery_is_idempotent_without_a_database_client():
    events = []
    state = RecordingState(restore_journal("restoring"), events)
    services = RecordingServices(events, pgbouncer_running=False)
    database = RecordingDatabase(events)

    RESTORE_MODULE.prepare_restore_recovery(state, database, services)
    RESTORE_MODULE.prepare_restore_recovery(state, database, services)

    expected = [
        ("verify_configured_target",),
        ("require_supported_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES)),
        ("verify_identities", set(RESTORE_MODULE.SNAPSHOT_SERVICES)),
        ("gate_restarts", set(RESTORE_MODULE.SNAPSHOT_SERVICES)),
        ("stop_clients", set(RESTORE_MODULE.SNAPSHOT_SERVICES)),
    ]
    assert events == expected * 2
    assert ("ensure_database_client",) not in events
    assert ("wait_ready",) not in events


def test_prepare_recovery_missing_snapshot_container_fails_before_mutation():
    events = []
    state = RecordingState(restore_journal("restoring"), events)

    class MissingServices(RecordingServices):
        def verify_identities(self, snapshot):
            self.events.append(("verify_identities", set(snapshot)))
            raise RESTORE_MODULE.RestoreError(
                "container changed during restore: nginx"
            )

    services = MissingServices(events, pgbouncer_running=False)

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="container changed during restore: nginx",
    ):
        RESTORE_MODULE.prepare_restore_recovery(
            state,
            RecordingDatabase(events),
            services,
        )

    assert events == [
        ("verify_configured_target",),
        ("require_supported_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES)),
        ("verify_identities", set(RESTORE_MODULE.SNAPSHOT_SERVICES)),
    ]


def test_provenance_failure_retries_without_exposure_or_journal_cleanup():
    events = []
    state = RecordingState(restore_journal("committed"), events)
    services = RecordingServices(events, pgbouncer_running=False)

    class UnownedDatabase(RecordingDatabase):
        def verify_maintenance_role(self, _role, *, login):
            self.events.append(("verify_maintenance_role", login))
            raise RESTORE_MODULE.RestoreError(
                "existing PostgreSQL maintenance role is not owned by this installation"
            )

    database = UnownedDatabase(events)
    for _attempt in range(2):
        RESTORE_MODULE.prepare_restore_recovery(state, database, services)
        with pytest.raises(
            RESTORE_MODULE.RestoreError,
            match="not owned by this installation",
        ):
            RESTORE_MODULE.recover_restore(state, database, services)

    assert state.journal["maintenance"] == "active"
    assert events.count(
        ("gate_restarts", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    ) == 2
    assert events.count(
        ("stop_clients", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    ) == 2
    assert ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES)) not in events
    assert ("cleanup",) not in events


def test_database_start_failure_leaves_journal_for_successful_retry():
    events = []
    state = RecordingState(restore_journal("snapshotting"), events)

    class UnavailableDatabaseServices(RecordingServices):
        def ensure_database_client(self):
            self.events.append(("ensure_database_client",))
            raise RESTORE_MODULE.RestoreError(
                "required database client container is missing: db"
            )

    unavailable = UnavailableDatabaseServices(events, pgbouncer_running=False)
    database = RecordingDatabase(events)

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="database client container is missing",
    ):
        RESTORE_MODULE.recover_restore(state, database, unavailable)

    assert state.journal["maintenance"] == "active"
    assert ("cleanup",) not in events
    available = RecordingServices(events, pgbouncer_running=False)
    RESTORE_MODULE.recover_restore(state, database, available)

    assert state.journal["maintenance"] == "inactive"
    assert events[-2:] == [("wait_external_http",), ("cleanup",)]


def test_version_two_recovery_rejects_disabled_application_role_before_upgrade():
    events = []
    journal = restore_journal("ready", version=2)
    state = RecordingState(journal, events)
    services = RecordingServices(events, pgbouncer_running=False)

    class DisabledApplicationRoleDatabase(RecordingDatabase):
        def verify_application_role(self):
            self.events.append(("verify_application_role",))
            raise RESTORE_MODULE.RestoreError(
                "database restore requires the configured PostgreSQL application "
                "role to be a login superuser"
            )

    with pytest.raises(RESTORE_MODULE.RestoreError, match="login superuser"):
        RESTORE_MODULE.recover_restore(
            state,
            DisabledApplicationRoleDatabase(events),
            services,
        )

    assert state.journal["version"] == 2
    assert events == [
        ("verify_configured_target",),
        ("require_supported_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES)),
        ("ensure_database_client",),
        ("use_application_target",),
        ("wait_ready",),
        ("verify_journal_identity", "ready"),
        ("verify_recreation_privileges",),
        ("verify_application_role",),
    ]


@pytest.mark.parametrize("version", [3, 4])
def test_pre_provenance_recovery_rejects_before_actions(version):
    events = []
    state = RecordingState(restore_journal("ready", version=version), events)
    services = RecordingServices(events, pgbouncer_running=False)
    database = RecordingDatabase(events)

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="predates maintenance-role provenance",
    ):
        RESTORE_MODULE.recover_restore(state, database, services)

    assert events == []


def test_terminal_recovery_refences_before_validation_and_release():
    events = []
    state = RecordingState(restore_journal("committed"), events)
    services = RecordingServices(events, pgbouncer_running=False)
    database = RecordingDatabase(events)

    RESTORE_MODULE.recover_restore(state, database, services)

    establish_index = events.index(("establish_fence",))
    warm_index = events.index(("warm_cache",))
    release_index = events.index(("release_fence",))
    deactivate_index = events.index(("deactivate_maintenance_role",))
    inactive_index = events.index(("set_maintenance", "inactive"))
    restore_index = events.index(
        ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    assert establish_index < warm_index < release_index
    assert release_index < deactivate_index < inactive_index < restore_index
    assert events[-2:] == [("set_phase", "committed_exposed"), ("cleanup",)]


def test_incomplete_cache_warmup_keeps_terminal_recovery_retryable():
    events = []
    state = RecordingState(restore_journal("committed"), events)

    class FailOnceServices(RecordingServices):
        def __init__(self):
            super().__init__(events, pgbouncer_running=False)
            self.fail = True

        def warm_cache(self):
            super().warm_cache()
            if self.fail:
                self.fail = False
                raise RESTORE_MODULE.RestoreError(
                    "injected required cache family failure"
                )

    services = FailOnceServices()
    database = RecordingDatabase(events)

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="required cache family failure",
    ):
        RESTORE_MODULE.recover_restore(state, database, services)

    assert state.journal["phase"] == "committed"
    assert ("release_fence",) not in events
    assert ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES)) not in events
    assert ("cleanup",) not in events

    RESTORE_MODULE.recover_restore(state, database, services)

    assert events.count(("warm_cache",)) == 2
    assert state.journal["phase"] == "committed_exposed"
    assert events[-2:] == [("set_phase", "committed_exposed"), ("cleanup",)]


def test_snapshotting_recovery_releases_without_completing_the_fence():
    events = []
    state = RecordingState(restore_journal("snapshotting"), events)
    services = RecordingServices(events, pgbouncer_running=False)
    database = RecordingDatabase(events)

    RESTORE_MODULE.recover_restore(state, database, services)

    assert ("establish_fence",) not in events
    assert ("release_fence",) in events
    assert ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES)) in events
    deactivate_index = events.index(("deactivate_maintenance_role",))
    inactive_index = events.index(("set_maintenance", "inactive"))
    restore_index = events.index(
        ("restore_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES))
    )
    assert deactivate_index < inactive_index < restore_index
    assert events[-2:] == [("wait_external_http",), ("cleanup",)]


def test_database_identity_rejects_replacement_and_unexpected_absence(monkeypatch):
    database = maintenance_role_database()
    journal = restore_journal("ready")
    monkeypatch.setattr(
        database,
        "capture_database_oid",
        lambda name=None: 20001 if name in {None, "ctfd"} else None,
    )
    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="database identity does not match",
    ):
        database.verify_database_identity(journal)

    monkeypatch.setattr(database, "capture_database_oid", lambda _name=None: None)
    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="unexpectedly missing",
    ):
        database.verify_database_identity(journal)


@pytest.mark.parametrize("phase", ["restoring", "rolling_back"])
def test_database_identity_allows_only_legitimate_missing_recreation_phase(
    monkeypatch,
    phase,
):
    class Services:
        ready_timeout = 2

    database = RESTORE_MODULE.DatabaseRestore(
        None, None, Services(), database_target()
    )
    monkeypatch.setattr(database, "capture_database_oid", lambda _name=None: None)

    database.verify_database_identity(restore_journal(phase))


def test_recreation_privilege_requires_superuser_maintenance_role(monkeypatch):
    class Services:
        ready_timeout = 2

    database = RESTORE_MODULE.DatabaseRestore(
        None, None, Services(), database_target()
    )
    result = subprocess.CompletedProcess(
        [],
        0,
        json.dumps({"superuser": False}).encode(),
        b"",
    )
    monkeypatch.setattr(database, "psql", lambda _sql: result)

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="maintenance role to be a superuser",
    ):
        database.verify_recreation_privileges()


def test_application_role_is_disabled_and_restored_idempotently(monkeypatch):
    class State:
        installation_id = "c" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "d" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    database = RESTORE_MODULE.DatabaseRestore(
        None,
        State(),
        services,
        database_target(),
    )
    role_states = iter((True, False, False, True))
    statements = []

    def psql(sql, **_options):
        statements.append(sql)
        if "json_build_object" in sql:
            state = next(role_states)
            return subprocess.CompletedProcess(
                [],
                0,
                json.dumps(
                    {"name": "ctfd", "superuser": True, "login": state}
                ).encode(),
                b"",
            )
        if "SELECT count(*) FROM pg_stat_activity" in sql:
            return subprocess.CompletedProcess([], 0, b"0\n", b"")
        return subprocess.CompletedProcess([], 0, b"", b"")

    monkeypatch.setattr(database, "psql", psql)
    role = {"name": "ctfd", "login": True}

    database.disable_application_role(role)
    database.restore_application_role(role)

    disable_statement = next(
        statement for statement in statements if 'ALTER ROLE "ctfd" NOLOGIN;' in statement
    )
    assert "pg_terminate_backend" in disable_statement
    assert "datname" not in disable_statement
    assert 'ALTER ROLE "ctfd" LOGIN;' in statements


def test_application_role_snapshot_requires_configured_login_superuser(monkeypatch):
    class Services:
        ready_timeout = 2

    database = RESTORE_MODULE.DatabaseRestore(
        None, None, Services(), database_target()
    )
    result = subprocess.CompletedProcess(
        [],
        0,
        json.dumps(
            {"name": "ctfd", "superuser": True, "login": False}
        ).encode(),
        b"",
    )
    monkeypatch.setattr(database, "psql", lambda _sql, **_options: result)

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="login superuser",
    ):
        database.verify_application_role()


def test_recovery_rejects_insufficient_privilege_before_service_mutation():
    events = []
    state = RecordingState(restore_journal("ready"), events)
    services = RecordingServices(events, pgbouncer_running=False)

    class RestrictedDatabase(RecordingDatabase):
        def verify_recreation_privileges(self):
            self.events.append(("verify_recreation_privileges",))
            raise RESTORE_MODULE.RestoreError(
                "maintenance role must be a superuser"
            )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="maintenance role must be a superuser",
    ):
        RESTORE_MODULE.recover_restore(
            state,
            RestrictedDatabase(events),
            services,
        )

    assert events == [
        ("verify_configured_target",),
        ("require_supported_snapshot", set(RESTORE_MODULE.SNAPSHOT_SERVICES)),
        ("ensure_database_client",),
        ("use_maintenance_target",),
        ("capture_maintenance_role", "maintenance-target"),
        ("verify_maintenance_role", True),
        ("wait_ready",),
        ("verify_journal_identity", "ready"),
        ("verify_recreation_privileges",),
    ]


@pytest.mark.parametrize("phase", sorted(RESTORE_MODULE.JOURNAL_PHASES))
@pytest.mark.parametrize("legacy_service_snapshot", [False, True])
def test_version_one_recovery_always_fails_closed_before_actions(
    phase,
    legacy_service_snapshot,
):
    events = []
    state = RecordingState(
        restore_journal(
            phase,
            legacy=legacy_service_snapshot,
            version=1,
        ),
        events,
    )
    services = RecordingServices(
        events,
        pgbouncer_running=False,
    )
    database = RecordingDatabase(events)

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="not bound to a database target",
    ):
        RESTORE_MODULE.recover_restore(state, database, services)

    assert events == []


def test_restore_readiness_deadlines(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(RESTORE_MODULE, "time", clock)
    services = RESTORE_MODULE.DockerServices(UnreadyRunner(), database_target())
    services.ready_timeout = 2
    services.cold_start_timeout = 2
    services.http_timeout = 2
    running = {
        "running": True,
        "status": "running",
        "health": "starting",
        "restarting": False,
        "started_at": "2026-01-01T00:00:00Z",
    }
    monkeypatch.setattr(services, "inspect", lambda _service, **_options: running)

    with pytest.raises(RESTORE_MODULE.RestoreError, match="cache did not answer PING"):
        services.wait_cache()

    clock.reset()
    with pytest.raises(
        RESTORE_MODULE.RestoreError, match="pgbouncer did not accept connections"
    ):
        services.wait_pgbouncer()

    clock.reset()
    with pytest.raises(RESTORE_MODULE.RestoreError, match="ctfd did not become ready"):
        services.wait_service("ctfd")

    running["health"] = "unhealthy"
    with pytest.raises(RESTORE_MODULE.RestoreError, match="ctfd failed during startup"):
        services.wait_service("ctfd")
    running["health"] = "starting"

    class UnavailableResponse:
        status = 503

        def read(self):
            return b""

    class UnavailableConnection:
        def __init__(self, *_arguments, **_options):
            pass

        def request(self, *_arguments, **_options):
            pass

        def getresponse(self):
            return UnavailableResponse()

        def close(self):
            pass

    clock.reset()
    monkeypatch.setattr(
        RESTORE_MODULE.http.client, "HTTPConnection", UnavailableConnection
    )
    with pytest.raises(
        RESTORE_MODULE.RestoreError, match="nginx did not serve the CTFd application"
    ):
        services.wait_external_http()

    clock.reset()
    database = RESTORE_MODULE.DatabaseRestore(
        UnreadyRunner(), None, services, database_target()
    )
    database.drain_timeout = 2
    monkeypatch.setattr(
        database,
        "psql",
        lambda _sql, **_options: subprocess.CompletedProcess([], 0, b"t\n1\n", b""),
    )
    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="database connections could not be drained",
    ):
        database.drain_database()


def test_pending_recovery_starts_the_database_client_with_a_deadline(monkeypatch):
    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, b"db\n", b"")

    runner = Runner()
    services = RESTORE_MODULE.DockerServices(runner, database_target())
    services.ready_timeout = 7
    states = iter(
        (
            {
                "running": False,
                "paused": False,
                "restarting": False,
                "status": "exited",
            },
            {
                "running": True,
                "paused": False,
                "restarting": False,
                "status": "running",
            },
        )
    )
    monkeypatch.setattr(
        services,
        "inspect",
        lambda _service, **_options: next(states),
    )

    services.ensure_database_client()

    arguments, options = runner.calls[0]
    assert arguments == ["docker", "start", "db"]
    assert 0 < options["timeout"] <= services.ready_timeout


def test_loopback_tls_uses_dojo_host_for_verified_sni(monkeypatch):
    calls = []

    class Socket:
        def close(self):
            calls.append(("close",))

    class Context:
        check_hostname = True
        verify_mode = RESTORE_MODULE.ssl.CERT_REQUIRED

        def wrap_socket(self, connection, *, server_hostname):
            calls.append(("wrap", connection, server_hostname))
            return connection

    connection_socket = Socket()
    monkeypatch.setattr(
        RESTORE_MODULE.socket,
        "create_connection",
        lambda address, timeout, source_address: calls.append(
            ("connect", address, timeout, source_address)
        )
        or connection_socket,
    )
    connection = RESTORE_MODULE.LoopbackHTTPSConnection(
        "dojo.example",
        443,
        timeout=3,
        context=Context(),
    )

    connection.connect()

    assert calls[0] == ("connect", ("127.0.0.1", 443), 3, None)
    assert calls[1] == ("wrap", connection_socket, "dojo.example")
    default_context = RESTORE_MODULE.ssl.create_default_context()
    assert default_context.check_hostname is True
    assert default_context.verify_mode == RESTORE_MODULE.ssl.CERT_REQUIRED


def test_loopback_tls_rejects_untrusted_wrong_host_and_expired_certificates(tmp_path):
    ca_key = tmp_path / "ca.key"
    ca_certificate = tmp_path / "ca.crt"
    server_key = tmp_path / "server.key"
    server_request = tmp_path / "server.csr"
    server_certificate = tmp_path / "server.crt"
    expired_certificate = tmp_path / "expired.crt"
    openssl = ["openssl"]
    subprocess.run(
        [
            *openssl,
            "req",
            "-x509",
            "-newkey",
            "ed25519",
            "-noenc",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_certificate),
            "-subj",
            "/CN=Dojo Restore Test CA",
            "-days",
            "2",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            *openssl,
            "req",
            "-newkey",
            "ed25519",
            "-noenc",
            "-keyout",
            str(server_key),
            "-out",
            str(server_request),
            "-subj",
            "/CN=dojo.test",
            "-addext",
            "subjectAltName=DNS:dojo.test",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            *openssl,
            "x509",
            "-req",
            "-in",
            str(server_request),
            "-CA",
            str(ca_certificate),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(server_certificate),
            "-days",
            "1",
            "-copy_extensions",
            "copy",
        ],
        check=True,
        capture_output=True,
    )
    (tmp_path / "index.txt").write_text("")
    (tmp_path / "serial").write_text("1000\n")
    (tmp_path / "newcerts").mkdir()
    openssl_configuration = tmp_path / "openssl.cnf"
    openssl_configuration.write_text(
        "\n".join(
            (
                "[ca]",
                "default_ca=default",
                "[default]",
                f"dir={tmp_path}",
                "database=$dir/index.txt",
                "new_certs_dir=$dir/newcerts",
                "certificate=$dir/ca.crt",
                "private_key=$dir/ca.key",
                "serial=$dir/serial",
                "default_md=sha256",
                "policy=policy",
                "copy_extensions=copy",
                "unique_subject=no",
                "[policy]",
                "commonName=supplied",
            )
        )
        + "\n"
    )
    subprocess.run(
        [
            *openssl,
            "ca",
            "-batch",
            "-notext",
            "-config",
            str(openssl_configuration),
            "-in",
            str(server_request),
            "-out",
            str(expired_certificate),
            "-startdate",
            "20200101000000Z",
            "-enddate",
            "20200102000000Z",
        ],
        check=True,
        capture_output=True,
    )

    def tls_server(certificate):
        listener = RESTORE_MODULE.socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def serve():
            connection, _address = listener.accept()
            context = RESTORE_MODULE.ssl.SSLContext(
                RESTORE_MODULE.ssl.PROTOCOL_TLS_SERVER
            )
            context.load_cert_chain(certificate, server_key)
            try:
                secured = context.wrap_socket(connection, server_side=True)
                secured.close()
            except RESTORE_MODULE.ssl.SSLError:
                connection.close()
            finally:
                listener.close()

        thread = threading.Thread(target=serve)
        thread.start()
        return port, thread

    trusted_context = RESTORE_MODULE.ssl.create_default_context(cafile=ca_certificate)
    port, server = tls_server(server_certificate)
    connection = RESTORE_MODULE.LoopbackHTTPSConnection(
        "dojo.test",
        port,
        timeout=2,
        context=trusted_context,
    )
    connection.connect()
    connection.close()
    server.join(timeout=2)
    assert not server.is_alive()

    for hostname, certificate, context in (
        (
            "wrong.test",
            server_certificate,
            RESTORE_MODULE.ssl.create_default_context(cafile=ca_certificate),
        ),
        (
            "dojo.test",
            server_certificate,
            RESTORE_MODULE.ssl.create_default_context(),
        ),
        (
            "dojo.test",
            expired_certificate,
            RESTORE_MODULE.ssl.create_default_context(cafile=ca_certificate),
        ),
    ):
        port, server = tls_server(certificate)
        connection = RESTORE_MODULE.LoopbackHTTPSConnection(
            hostname,
            port,
            timeout=2,
            context=context,
        )
        with pytest.raises(RESTORE_MODULE.ssl.SSLCertVerificationError):
            connection.connect()
        server.join(timeout=2)
        assert not server.is_alive()


def test_external_http_uses_real_ingress_and_requires_ctfd_response(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(RESTORE_MODULE, "time", clock)
    services = RESTORE_MODULE.DockerServices(UnreadyRunner(), database_target())
    services.http_timeout = 2
    monkeypatch.setattr(
        services,
        "inspect",
        lambda _service: {"running": True},
    )
    connections = []

    class Response:
        def __init__(self, status, body):
            self.status = status
            self.body = body

        def read(self):
            return self.body

    class Connection:
        response = Response(307, b"")

        def __init__(self, host, port, **options):
            connections.append((host, port, options))

        def request(self, method, path, headers):
            connections.append((method, path, headers))

        def getresponse(self):
            return self.response

        def close(self):
            pass

    monkeypatch.setenv("DOJO_ENV", "production")
    monkeypatch.setattr(RESTORE_MODULE, "LoopbackHTTPSConnection", Connection)
    monkeypatch.setattr(
        RESTORE_MODULE.ssl,
        "create_default_context",
        lambda: "local-tls-context",
    )
    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="HTTP 307 without the expected CTFd response",
    ):
        services.wait_external_http()
    assert connections[0] == (
        "localhost.pwn.college",
        443,
        {"timeout": 2, "context": "local-tls-context"},
    )

    clock.reset()
    connections.clear()
    Connection.response = Response(200, b"nginx placeholder")
    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="HTTP 200 without the expected CTFd response",
    ):
        services.wait_external_http()

    clock.reset()
    connections.clear()
    Connection.response = Response(
        200,
        b"<script>'csrfNonce': \"restored\"</script>",
    )
    services.wait_external_http()
    assert connections[1] == (
        "GET",
        "/",
        {"Host": "localhost.pwn.college"},
    )

    clock.reset()
    connections.clear()
    monkeypatch.setenv("DOJO_ENV", "coverage")
    monkeypatch.setattr(RESTORE_MODULE.http.client, "HTTPConnection", Connection)
    services.wait_external_http()
    assert connections[0] == ("127.0.0.1", 80, {"timeout": 2})


def test_cache_warm_uses_only_the_private_validator(monkeypatch):
    class CacheRunner:
        def run(self, arguments, **_options):
            output = b"3\n" if "EXISTS" in arguments else b"OK\n"
            return subprocess.CompletedProcess(arguments, 0, output, b"")

    services = RESTORE_MODULE.DockerServices(CacheRunner(), database_target())
    starts = []
    validations = []
    monkeypatch.setattr(services, "start", starts.append)
    monkeypatch.setattr(services, "wait_cache", lambda: None)
    monkeypatch.setattr(
        services,
        "run_private_validation",
        lambda name, program, timeout: (
            validations.append((name, program, timeout))
            or subprocess.CompletedProcess(
                [],
                0,
                RESTORE_MODULE.CACHE_VALIDATION_MARKER,
                b"",
            )
        ),
    )

    services.warm_cache()

    assert starts == ["cache"]
    assert validations == [
        (
            "cache",
            RESTORE_MODULE.CACHE_VALIDATION_PROGRAM,
            services.cold_start_timeout,
        )
    ]


def test_cache_warm_synchronously_persists_restored_state(monkeypatch):
    class CacheRunner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **_options):
            self.calls.append(arguments)
            if "EXISTS" in arguments:
                output = b"3\n"
            else:
                output = b"OK\n"
            return subprocess.CompletedProcess(arguments, 0, output, b"")

    runner = CacheRunner()
    services = RESTORE_MODULE.DockerServices(runner, database_target())
    monkeypatch.setattr(services, "start", lambda _service: None)
    monkeypatch.setattr(services, "wait_cache", lambda: None)
    monkeypatch.setattr(
        services,
        "run_private_validation",
        lambda *_args: subprocess.CompletedProcess(
            [],
            0,
            RESTORE_MODULE.CACHE_VALIDATION_MARKER,
            b"",
        ),
    )

    services.warm_cache()

    flush_index = next(i for i, call in enumerate(runner.calls) if "FLUSHDB" in call)
    save_index = next(i for i, call in enumerate(runner.calls) if "SAVE" in call)
    exists_index = next(i for i, call in enumerate(runner.calls) if "EXISTS" in call)
    assert flush_index < exists_index < save_index


def test_cache_warm_requires_the_complete_cache_contract_marker(monkeypatch):
    class CacheRunner:
        def run(self, arguments, **_options):
            output = b"3\n" if "EXISTS" in arguments else b"OK\n"
            return subprocess.CompletedProcess(arguments, 0, output, b"")

    services = RESTORE_MODULE.DockerServices(CacheRunner(), database_target())
    monkeypatch.setattr(services, "start", lambda _service: None)
    monkeypatch.setattr(services, "wait_cache", lambda: None)
    monkeypatch.setattr(
        services,
        "run_private_validation",
        lambda *_args: subprocess.CompletedProcess([], 0, b"incomplete", b""),
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="every required cache family",
    ):
        services.warm_cache()


def test_cache_validation_contract_is_strict_for_every_initializer():
    compile(RESTORE_MODULE.CACHE_VALIDATION_PROGRAM, "cache-validation", "exec")
    for family in (
        "dojo-stats",
        "scoreboards",
        "scores",
        "belts",
        "emojis",
        "containers",
        "activity",
    ):
        assert f'"{family}"' in RESTORE_MODULE.CACHE_VALIDATION_PROGRAM
    assert RESTORE_MODULE.CACHE_VALIDATION_PROGRAM.count(
        "fail_on_error=True"
    ) == 7
    assert 'scan_iter(match="stats:*")' in RESTORE_MODULE.CACHE_VALIDATION_PROGRAM
    assert "actual_value != canonical_expected" in RESTORE_MODULE.CACHE_VALIDATION_PROGRAM


def test_application_validation_failure_injection_preserves_real_validation(
    monkeypatch,
):
    services = RESTORE_MODULE.DockerServices(None, database_target())
    validations = []
    monkeypatch.setattr(
        services,
        "run_private_validation",
        lambda name, program, timeout: validations.append((name, program, timeout)),
    )

    services.validate_application()
    services.validate_application(fail_after_validation=True)

    assert validations[0] == (
        "application",
        RESTORE_MODULE.APPLICATION_VALIDATION_PROGRAM,
        services.ready_timeout,
    )
    assert validations[1] == (
        "application",
        RESTORE_MODULE.APPLICATION_VALIDATION_PROGRAM
        + "\nraise RuntimeError('injected application validation failure')\n",
        services.ready_timeout,
    )


def test_private_validator_is_unpublished_labeled_and_secret_free(monkeypatch):
    class ValidationRunner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

    runner = ValidationRunner()
    services = RESTORE_MODULE.DockerServices(runner, database_target())
    lifecycle = []
    database_url = "postgresql+psycopg2://ctfd:private-secret@db:5432/ctfd"
    monkeypatch.setattr(
        services,
        "verify_clients_stopped",
        lambda: lifecycle.append("verify_clients_stopped"),
    )
    monkeypatch.setattr(
        services,
        "cleanup_private_validation",
        lambda: lifecycle.append("cleanup_private_validation"),
    )
    monkeypatch.setattr(services, "direct_database_url", lambda: database_url)
    monkeypatch.setenv(
        RESTORE_MODULE.CACHE_VALIDATION_TEST_ENVIRONMENT,
        "scoreboards",
    )

    services.run_private_validation("application", "validation program", 17)

    arguments, options = runner.calls[0]
    assert arguments[:4] == ["dojo", "compose", "run", "--rm"]
    assert "--no-deps" in arguments
    assert "--service-ports" not in arguments
    assert f"{RESTORE_MODULE.PRIVATE_VALIDATION_LABEL}=1" in arguments
    assert arguments.count("--env") == 2
    assert RESTORE_MODULE.CACHE_VALIDATION_TEST_ENVIRONMENT in arguments
    assert database_url not in arguments
    assert options["environment"]["DATABASE_URL"] == database_url
    assert options["timeout"] == 17
    assert lifecycle == [
        "verify_clients_stopped",
        "cleanup_private_validation",
        "cleanup_private_validation",
        "verify_clients_stopped",
    ]


def test_database_target_uses_verified_endpoint_without_password_in_arguments(
    monkeypatch,
    tmp_path,
):
    class TargetRunner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

    runner = TargetRunner()
    password = "private password';--"
    tls_directory = tmp_path / "postgres-tls"
    tls_directory.mkdir(mode=0o755)
    root_certificate = tls_directory / "root.crt"
    root_certificate.write_bytes(b"trusted root certificate")
    root_certificate.chmod(0o644)
    monkeypatch.setattr(RESTORE_MODULE, "DATABASE_TLS_DIRECTORY", tls_directory)
    monkeypatch.setattr(RESTORE_MODULE, "DATABASE_TLS_OWNER_UID", os.getuid())
    target = RESTORE_MODULE.DatabaseTarget(
        "external-postgres",
        5544,
        "dojo_database",
        "maintenance_user",
        password,
        sslmode="verify-full",
        sslrootcert=str(root_certificate),
        trusted_local=False,
    )
    target.run_client(
        runner,
        "pg_dump",
        ("--format=custom",),
        connect=True,
        application_name=RESTORE_MODULE.BACKUP_APPLICATION_NAME,
        timeout=17,
    )

    arguments, options = runner.calls[0]
    assert "--host=external-postgres" in arguments
    assert "--port=5544" in arguments
    assert "--username=maintenance_user" in arguments
    assert "--dbname=dojo_database" in arguments
    assert password not in arguments
    assert all(password not in argument for argument in arguments)
    assert options["environment"]["PGPASSWORD"] == password
    assert options["environment"]["PGSSLMODE"] == "verify-full"
    assert options["environment"]["PGSSLROOTCERT"] == str(root_certificate)
    assert options["environment"]["PGAPPNAME"] == (
        RESTORE_MODULE.BACKUP_APPLICATION_NAME
    )
    assert options["environment"]["PGCONNECT_TIMEOUT"] == "17"
    assert "statement_timeout=17000" in options["environment"]["PGOPTIONS"]
    assert "lock_timeout=17000" in options["environment"]["PGOPTIONS"]
    assert "17s" in arguments
    assert options["timeout"] == 17 + RESTORE_MODULE.COMMAND_TIMEOUT_GRACE
    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="require an application name",
    ):
        target.run_client(runner, "psql", connect=True)


def test_database_target_rejects_unverified_remote_password_connections():
    for sslmode in ("", "allow", "prefer", "require", "verify-ca"):
        with pytest.raises(RESTORE_MODULE.RestoreError, match="TLS mode"):
            RESTORE_MODULE.DatabaseTarget(
                "database.example",
                5432,
                "ctfd",
                "ctfd",
                "secret",
                sslmode=sslmode,
                trusted_local=False,
            )

    with pytest.raises(RESTORE_MODULE.RestoreError, match="trusted local hosts"):
        RESTORE_MODULE.DatabaseTarget(
            "database.example",
            5432,
            "ctfd",
            "ctfd",
            "secret",
            sslmode="disable",
            trusted_local=True,
        )


def test_database_target_requires_explicit_environment_trust(monkeypatch):
    for field in ("DB_SSLMODE", "DB_SSLROOTCERT", "DB_TRUSTED_LOCAL"):
        monkeypatch.delenv(field, raising=False)

    with pytest.raises(RESTORE_MODULE.RestoreError, match="explicitly"):
        RESTORE_MODULE.DatabaseTarget.from_environment()

    monkeypatch.setenv("DB_SSLMODE", "disable")
    monkeypatch.setenv("DB_TRUSTED_LOCAL", "true")
    target = RESTORE_MODULE.DatabaseTarget.from_environment()
    assert target.configuration()["trusted_local"] is True
    assert target.configuration()["sslmode"] == "disable"


def test_database_tls_identity_is_journaled_and_rechecked_before_password_use(
    monkeypatch,
    tmp_path,
):
    class TargetRunner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

    tls_directory = tmp_path / "postgres-tls"
    tls_directory.mkdir(mode=0o755)
    root_certificate = tls_directory / "root.crt"
    root_certificate.write_bytes(b"expected certificate authority")
    root_certificate.chmod(0o644)
    monkeypatch.setattr(RESTORE_MODULE, "DATABASE_TLS_DIRECTORY", tls_directory)
    monkeypatch.setattr(RESTORE_MODULE, "DATABASE_TLS_OWNER_UID", os.getuid())
    target = RESTORE_MODULE.DatabaseTarget(
        "database.example",
        5432,
        "ctfd",
        "ctfd",
        "secret",
        sslmode="verify-full",
        sslrootcert=str(root_certificate),
        trusted_local=False,
    )
    journal_target = target.journal_target(server_identity())

    assert journal_target["sslmode"] == "verify-full"
    assert journal_target["sslrootcert"] == str(root_certificate)
    assert journal_target["sslrootcert_sha256"] == (
        RESTORE_MODULE.hashlib.sha256(b"expected certificate authority").hexdigest()
    )
    RESTORE_MODULE.validate_database_target(journal_target)

    root_certificate.write_bytes(b"attacker certificate authority")
    runner = TargetRunner()
    with pytest.raises(RESTORE_MODULE.RestoreError, match="identity changed"):
        target.run_client(
            runner,
            "psql",
            connect=True,
            application_name="test",
        )
    assert runner.calls == []


def test_verified_database_target_rejects_non_dns_host_and_untrusted_ca_path(
    monkeypatch,
    tmp_path,
):
    tls_directory = tmp_path / "postgres-tls"
    tls_directory.mkdir(mode=0o755)
    root_certificate = tls_directory / "root.crt"
    root_certificate.write_bytes(b"trusted root certificate")
    root_certificate.chmod(0o644)
    monkeypatch.setattr(RESTORE_MODULE, "DATABASE_TLS_DIRECTORY", tls_directory)
    monkeypatch.setattr(RESTORE_MODULE, "DATABASE_TLS_OWNER_UID", os.getuid())

    for host in ("192.0.2.10", "/var/run/postgresql", "db.example,attacker"):
        with pytest.raises(RESTORE_MODULE.RestoreError, match="certificate hostname"):
            RESTORE_MODULE.DatabaseTarget(
                host,
                5432,
                "ctfd",
                "ctfd",
                "secret",
                sslmode="verify-full",
                sslrootcert=str(root_certificate),
                trusted_local=False,
            )

    outside_certificate = tmp_path / "outside.crt"
    outside_certificate.write_bytes(b"untrusted root certificate")
    outside_certificate.chmod(0o644)
    with pytest.raises(RESTORE_MODULE.RestoreError, match="directly beneath"):
        RESTORE_MODULE.DatabaseTarget(
            "database.example",
            5432,
            "ctfd",
            "ctfd",
            "secret",
            sslmode="verify-full",
            sslrootcert=str(outside_certificate),
            trusted_local=False,
        )


def test_restore_psql_is_tagged_and_termination_covers_every_helper_session():
    class State:
        installation_id = "3" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "4" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    class TargetRunner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, b"0\n", b"")

    runner = TargetRunner()
    services = type("Services", (), {"ready_timeout": 2})()
    database = RESTORE_MODULE.DatabaseRestore(
        runner, State(), services, database_target()
    )

    database.terminate_maintenance_backends()

    arguments, options = runner.calls[0]
    query = arguments[arguments.index("--command") + 1]
    assert "datname" not in query
    assert "pid <> pg_backend_pid()" in query
    for application in database.application_names:
        assert RESTORE_MODULE.sql_literal(application) in query
    applications = ", ".join(
        RESTORE_MODULE.sql_literal(application)
        for application in database.application_names
    )
    application_predicate = (
        f"(usename = {RESTORE_MODULE.sql_literal(database.application_target.user)} "
        f"AND application_name IN ({applications}))"
    )
    maintenance_predicate = (
        f"usename = {RESTORE_MODULE.sql_literal(database.maintenance_target.user)}"
    )
    assert f"WHERE ({application_predicate} OR {maintenance_predicate})" in query
    assert options["environment"]["PGAPPNAME"] == database.restore_application_name


def test_installations_cannot_match_each_others_maintenance_sessions():
    class State:
        maintenance_secret = "3" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH

        def __init__(self, installation_id):
            self.installation_id = installation_id

        @property
        def maintenance_role(self):
            return f"dojo_restore_{self.installation_id}"

    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, b"0\n", b"")

    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    first_runner = Runner()
    second_runner = Runner()
    first = RESTORE_MODULE.DatabaseRestore(
        first_runner,
        State("1" * RESTORE_MODULE.INSTALLATION_ID_LENGTH),
        services,
        database_target(),
    )
    second = RESTORE_MODULE.DatabaseRestore(
        second_runner,
        State("2" * RESTORE_MODULE.INSTALLATION_ID_LENGTH),
        services,
        RESTORE_MODULE.DatabaseTarget("db", 5432, "other", "ctfd", "secret"),
    )

    first.terminate_maintenance_backends()
    second.terminate_maintenance_backends()

    first_query = first_runner.calls[0][0][
        first_runner.calls[0][0].index("--command") + 1
    ]
    second_query = second_runner.calls[0][0][
        second_runner.calls[0][0].index("--command") + 1
    ]
    assert all(name in first_query for name in first.application_names)
    assert all(name not in first_query for name in second.application_names)
    assert all(name in second_query for name in second.application_names)
    assert all(name not in second_query for name in first.application_names)
    assert RESTORE_MODULE.sql_literal(first.maintenance_target.user) in first_query
    assert RESTORE_MODULE.sql_literal(second.maintenance_target.user) not in first_query
    assert RESTORE_MODULE.sql_literal(second.maintenance_target.user) in second_query
    assert RESTORE_MODULE.sql_literal(first.maintenance_target.user) not in second_query
    assert all(len(name.encode()) < 64 for name in first.application_names)


def test_server_fence_survives_database_recreation_until_release(monkeypatch):
    class State:
        installation_id = "4" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "5" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    database = RESTORE_MODULE.DatabaseRestore(
        None,
        State(),
        services,
        database_target(),
    )
    statements = []
    monkeypatch.setattr(
        database,
        "psql",
        lambda sql, **_options: statements.append(sql)
        or subprocess.CompletedProcess([], 0, b"", b""),
    )
    database_oids = iter((20000, None, None, 20000))
    monkeypatch.setattr(
        database,
        "capture_database_oid",
        lambda _name=None: next(database_oids),
    )
    monkeypatch.setattr(
        database,
        "drain_database",
        lambda *_arguments: statements.append("drain"),
    )
    monkeypatch.setattr(
        database,
        "disable_application_role",
        lambda _role: statements.append("disable-application-role"),
    )
    monkeypatch.setattr(
        database,
        "restore_application_role",
        lambda _role: statements.append("restore-application-role"),
    )
    monkeypatch.setattr(database, "verify_fence_integrity", lambda: None)

    metadata = database_metadata()
    metadata["allow_connections"] = False
    role = {"name": "ctfd", "login": True}
    database.establish_fence(metadata, role)
    database.recreate_database(metadata)
    database.release_fence(metadata, role)

    assert statements[0] == 'ALTER DATABASE "ctfd" ALLOW_CONNECTIONS false;'
    assert statements[1:3] == ["drain", "disable-application-role"]
    rename = statements[3]
    assert 'ALTER DATABASE "ctfd" OWNER TO "dojo_restore_' in rename
    assert 'ALTER DATABASE "ctfd" IS_TEMPLATE false;' in rename
    assert f'RENAME TO "{database.fenced_database_name}"' in rename
    assert 'OWNER TO "dojo_restore_' in statements[4]
    assert 'IS_TEMPLATE false' in statements[4]
    create = next(statement for statement in statements if "CREATE DATABASE" in statement)
    assert f'OWNER = "{database.maintenance_target.user}"' in create
    assert "IS_TEMPLATE = false" in create
    assert "ALLOW_CONNECTIONS = true" in create
    release_owner = (
        f'ALTER DATABASE "{database.fenced_database_name}" OWNER TO "ctfd";'
    )
    assert release_owner in statements
    acl = next(statement for statement in statements if "GRANTED BY CURRENT_USER" in statement)
    assert "REVOKE ALL" in acl
    assert "CASCADE" in acl
    assert "SET ROLE \"ctfd\"" in acl
    assert statements[-1] == "restore-application-role"


def test_server_fence_preflights_after_denial_and_drain(monkeypatch):
    class State:
        installation_id = "6" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "7" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    database = RESTORE_MODULE.DatabaseRestore(
        None,
        State(),
        services,
        database_target(),
    )
    events = []
    database_oids = iter((20000, None))
    monkeypatch.setattr(
        database,
        "capture_database_oid",
        lambda _name=None: next(database_oids),
    )
    monkeypatch.setattr(
        database,
        "psql",
        lambda sql, **_options: events.append(sql),
    )
    monkeypatch.setattr(
        database,
        "drain_database",
        lambda *_arguments: events.append("drain"),
    )
    monkeypatch.setattr(
        database,
        "preflight_recreation",
        lambda name=None: events.append(("preflight", name)),
    )
    monkeypatch.setattr(
        database,
        "disable_application_role",
        lambda _role: events.append("disable-application-role"),
    )
    monkeypatch.setattr(database, "verify_fence_integrity", lambda: None)

    database.establish_fence(
        database_metadata(),
        {"name": "ctfd", "login": True},
        preflight=True,
    )

    assert events[:5] == [
        'ALTER DATABASE "ctfd" ALLOW_CONNECTIONS false;',
        "drain",
        ("preflight", "ctfd"),
        "disable-application-role",
        ("preflight", "ctfd"),
    ]
    assert f'RENAME TO "{database.fenced_database_name}"' in events[5]
    assert "IS_TEMPLATE false" in events[5]


def test_release_fence_restores_a_denied_original_database(monkeypatch):
    class State:
        installation_id = "a" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "b" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    database = RESTORE_MODULE.DatabaseRestore(
        None,
        State(),
        services,
        database_target(),
    )
    statements = []
    database_oids = iter((20000, None))
    monkeypatch.setattr(
        database,
        "capture_database_oid",
        lambda _name=None: next(database_oids),
    )
    monkeypatch.setattr(
        database,
        "psql",
        lambda sql, **_options: statements.append(sql),
    )
    monkeypatch.setattr(
        database,
        "restore_application_role",
        lambda _role: statements.append("restore-application-role"),
    )

    metadata = database_metadata()
    metadata["connection_limit"] = 777
    metadata["acl_default"] = True
    metadata["acl"] = []
    database.release_fence(metadata, {"name": "ctfd", "login": True})

    assert statements == [
        'ALTER DATABASE "ctfd" OWNER TO "ctfd";',
        "UPDATE pg_database SET datacl = NULL WHERE datname = E'ctfd';",
        'ALTER DATABASE "ctfd" CONNECTION LIMIT 777;'
        'ALTER DATABASE "ctfd" IS_TEMPLATE false;'
        'ALTER DATABASE "ctfd" ALLOW_CONNECTIONS true;',
        "restore-application-role",
    ]


def test_server_fence_resumes_from_a_disabled_renamed_database(monkeypatch):
    class State:
        installation_id = "8" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "9" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    database = RESTORE_MODULE.DatabaseRestore(
        None,
        State(),
        services,
        database_target(),
    )
    statements = []
    monkeypatch.setattr(
        database,
        "capture_database_oid",
        lambda name=None: (
            None if name in {None, database.database_name} else 20000
        ),
    )
    monkeypatch.setattr(
        database,
        "psql",
        lambda sql, **_options: statements.append(sql),
    )
    monkeypatch.setattr(
        database,
        "drain_database",
        lambda *_arguments: statements.append("drain"),
    )
    monkeypatch.setattr(
        database,
        "disable_application_role",
        lambda _role: statements.append("disable-application-role"),
    )

    monkeypatch.setattr(database, "verify_fence_integrity", lambda: None)

    database.establish_fence(
        database_metadata(), {"name": "ctfd", "login": True}
    )

    assert statements[0] == (
        f'ALTER DATABASE "{database.fenced_database_name}" '
        'ALLOW_CONNECTIONS false;'
    )
    assert statements[1] == "drain"
    assert statements[2] == "disable-application-role"
    assert statements[3].endswith("ALLOW_CONNECTIONS true;")
    assert f'OWNER TO "{database.maintenance_target.user}"' in statements[3]
    assert "IS_TEMPLATE false" in statements[3]


def test_maintenance_role_cannot_equal_application_role():
    class State:
        installation_id = "e" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "f" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    target = RESTORE_MODULE.DatabaseTarget(
        "db",
        5432,
        "ctfd",
        State.maintenance_role,
        "application-secret",
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="maintenance role must differ",
    ):
        RESTORE_MODULE.DatabaseRestore(None, State(), services, target)


def maintenance_role_database():
    class State:
        installation_id = "6" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "7" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    return RESTORE_MODULE.DatabaseRestore(
        None,
        State(),
        services,
        database_target(),
    )


def maintenance_role_record(database, *, login, **overrides):
    role = {
        "name": database.maintenance_target.user,
        "oid": 24680,
        "comment": database.maintenance_provenance,
        "superuser": True,
        "inherit": True,
        "create_db": False,
        "create_role": False,
        "login": login,
        "replication": False,
        "bypass_rls": False,
        "connection_limit": -1,
        "valid_until_null": True,
        "config_null": True,
        "memberships": 0,
    }
    role.update(overrides)
    return role


def cluster_claim_record(role_name, provenance):
    return {
        "name": role_name,
        "comment": provenance,
        "superuser": False,
        "inherit": True,
        "create_db": False,
        "create_role": False,
        "login": False,
        "replication": False,
        "bypass_rls": False,
        "connection_limit": -1,
        "valid_until_null": True,
        "config_null": True,
        "memberships": 0,
    }


def test_cluster_claims_are_atomic_and_installation_owned(monkeypatch):
    database = maintenance_role_database()
    expected = database.cluster_claims(server_identity())
    records = {}
    statements = []
    monkeypatch.setattr(database, "capture_cluster_claim", records.get)

    def create_claims(statement, **_options):
        statements.append(statement)
        records.update(
            {
                name: cluster_claim_record(name, provenance)
                for name, provenance in expected.items()
            }
        )

    monkeypatch.setattr(database, "psql_private", create_claims)
    database.acquire_cluster_claims(server_identity())

    assert len(statements) == 1
    assert statements[0].startswith("BEGIN;")
    assert statements[0].endswith("COMMIT;")
    assert all(name in statements[0] for name in expected)

    other_database = maintenance_role_database()
    wrong_records = {
        name: cluster_claim_record(name, "another installation") for name in expected
    }
    monkeypatch.setattr(other_database, "capture_cluster_claim", wrong_records.get)
    writes = []
    monkeypatch.setattr(other_database, "psql_private", writes.append)
    with pytest.raises(RESTORE_MODULE.RestoreError, match="claimed by another"):
        other_database.acquire_cluster_claims(server_identity())
    assert writes == []


def test_cluster_claim_role_is_shared_across_database_names_for_same_role():
    first = maintenance_role_database()
    second = maintenance_role_database()
    second.database_name = "other"
    first_claims = first.cluster_claims(server_identity())
    second_claims = second.cluster_claims(server_identity())
    role_claim = RESTORE_MODULE.cluster_claim_role_name(
        "role", server_identity(), "ctfd"
    )

    assert role_claim in first_claims
    assert role_claim in second_claims
    assert set(first_claims) != set(second_claims)


def test_fence_integrity_rejects_owner_session_and_privilege_escape(monkeypatch):
    database = maintenance_role_database()
    database.use_fenced_maintenance_target()
    safe = {
        "owner": database.maintenance_target.user,
        "is_template": False,
        "allow_connections": True,
        "connection_limit": 0,
        "application_superuser": True,
        "application_login": False,
        "application_sessions": 0,
        "unexpected_privileged_roles": 0,
    }

    def result(payload):
        return subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(database, "psql", lambda _sql: result(safe))
    database.verify_fence_integrity()

    for field, value in (
        ("owner", "ctfd"),
        ("is_template", True),
        ("allow_connections", False),
        ("connection_limit", -1),
        ("application_superuser", False),
        ("application_login", True),
        ("application_sessions", 1),
        ("unexpected_privileged_roles", 1),
    ):
        monkeypatch.setattr(
            database,
            "psql",
            lambda _sql, field=field, value=value: result({**safe, field: value}),
        )
        with pytest.raises(RESTORE_MODULE.RestoreError, match="integrity was lost"):
            database.verify_fence_integrity()


def test_unrelated_maintenance_role_collision_is_never_mutated(monkeypatch):
    database = maintenance_role_database()
    collision = maintenance_role_record(
        database,
        login=False,
        comment="unrelated role",
        superuser=False,
        inherit=False,
        create_db=True,
        create_role=True,
        connection_limit=7,
        config_null=False,
        memberships=2,
    )
    original = dict(collision)
    statements = []
    monkeypatch.setattr(
        database,
        "capture_maintenance_role",
        lambda **_options: collision,
    )
    monkeypatch.setattr(
        database,
        "psql_private",
        lambda statement, **_options: statements.append(statement),
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="not owned by this installation",
    ):
        database.activate_maintenance_role()

    assert statements == []
    assert collision == original


def test_unrelated_role_collision_is_rejected_before_session_termination(
    monkeypatch,
):
    database = maintenance_role_database()
    collision = maintenance_role_record(
        database,
        login=False,
        comment="unrelated role",
        superuser=False,
        memberships=1,
    )
    terminations = []
    monkeypatch.setattr(
        database,
        "capture_maintenance_role",
        lambda **_options: collision,
    )
    monkeypatch.setattr(database, "wait_ready", lambda: None)
    monkeypatch.setattr(
        database,
        "terminate_maintenance_backends",
        lambda: terminations.append(True),
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="not owned by this installation",
    ):
        RESTORE_MODULE.deactivate_maintenance_with_application(database)

    assert terminations == []


def test_restore_rejects_role_collision_before_mutating_preflight(monkeypatch):
    events = []

    class State:
        locked = True

        def __enter__(self):
            events.append("lock")
            return self

        def __exit__(self, *_arguments):
            events.append("unlock")

    class Services:
        cold_start_timeout = 2

        def __init__(self, _runner, _target):
            pass

        def snapshot(self):
            events.append("snapshot")
            return service_snapshot()

    class Database:
        def __init__(self, _runner, _state, _services, _target):
            pass

        def verify_maintenance_role_reusable(self):
            events.append("verify-maintenance-role")
            raise RESTORE_MODULE.RestoreError(
                "existing PostgreSQL maintenance role is not owned by this installation"
            )

        def preflight_recreation(self):
            events.append("preflight-recreation")

        def verify_application_role(self):
            events.append("verify-application-role")

        def verify_fence_available(self):
            events.append("verify-fence")

    monkeypatch.setattr(RESTORE_MODULE, "RestoreState", State)
    monkeypatch.setattr(RESTORE_MODULE, "DockerServices", Services)
    monkeypatch.setattr(RESTORE_MODULE, "DatabaseRestore", Database)
    monkeypatch.setattr(
        RESTORE_MODULE.DatabaseTarget,
        "from_environment",
        classmethod(lambda _cls: database_target()),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "install_interrupt_handlers",
        lambda _runner, _operation: events.append("handlers"),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "recover_restore",
        lambda _state, _database, _services: events.append("recover"),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "cleanup_backup_partials",
        lambda _state: events.append("cleanup-partials"),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "open_archive",
        lambda _filename: contextlib.nullcontext(object()),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "validate_archive",
        lambda *_arguments, **_options: events.append("validate-archive"),
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="not owned by this installation",
    ):
        RESTORE_MODULE.restore("backup.dump")

    assert events == [
        "handlers",
        "lock",
        "recover",
        "cleanup-partials",
        "verify-maintenance-role",
        "unlock",
    ]


def test_helper_owned_role_with_unsafe_membership_is_never_mutated(monkeypatch):
    database = maintenance_role_database()
    unsafe_role = maintenance_role_record(database, login=False, memberships=1)
    statements = []
    monkeypatch.setattr(
        database,
        "capture_maintenance_role",
        lambda **_options: unsafe_role,
    )
    monkeypatch.setattr(
        database,
        "psql_private",
        lambda statement, **_options: statements.append(statement),
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="unsafe attributes",
    ):
        database.activate_maintenance_role()

    assert statements == []
    assert unsafe_role["memberships"] == 1


def test_only_provenance_bound_inactive_role_is_reused(monkeypatch):
    database = maintenance_role_database()
    inactive = maintenance_role_record(database, login=False)
    active = maintenance_role_record(database, login=True)
    captures = iter((inactive, active))
    statements = []
    monkeypatch.setattr(
        database,
        "capture_maintenance_role",
        lambda **_options: next(captures),
    )
    monkeypatch.setattr(
        database,
        "psql_private",
        lambda statement, **_options: statements.append(statement),
    )
    monkeypatch.setattr(database, "wait_ready", lambda: None)

    database.activate_maintenance_role()

    assert len(statements) == 1
    assert f'ALTER ROLE "{database.maintenance_target.user}"' in statements[0]
    assert "CREATE ROLE" not in statements[0]
    assert "COMMENT ON ROLE" not in statements[0]
    assert inactive["oid"] == active["oid"]
    assert inactive["comment"] == active["comment"]


def test_maintenance_secret_never_enters_process_arguments():
    class State:
        installation_id = "6" * RESTORE_MODULE.INSTALLATION_ID_LENGTH
        maintenance_secret = "7" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH
        maintenance_role = f"dojo_restore_{installation_id}"

    class Runner:
        def __init__(self):
            self.calls = []
            self.role_active = False

        def run(self, arguments, **options):
            self.calls.append((arguments, options))
            joined = " ".join(arguments)
            if "-i" in arguments:
                self.role_active = True
                output = b""
            elif "shobj_description" in joined:
                if self.role_active:
                    output = json.dumps(
                        maintenance_role_record(database, login=True)
                    ).encode()
                else:
                    output = b""
            elif "SELECT 1;" in arguments:
                output = b"1\n"
            else:
                output = b""
            return subprocess.CompletedProcess(arguments, 0, output, b"")

    runner = Runner()
    services = type(
        "Services",
        (),
        {"ready_timeout": 2, "cold_start_timeout": 2, "target": None},
    )()
    database = RESTORE_MODULE.DatabaseRestore(
        runner,
        State(),
        services,
        database_target(),
    )

    database.activate_maintenance_role()

    for arguments, _options in runner.calls:
        assert all(State.maintenance_secret not in argument for argument in arguments)


def test_private_validation_cleanup_refuses_an_unrelated_container():
    class UnrelatedRunner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **_options):
            self.calls.append(arguments)
            payload = json.dumps(
                [{"Config": {"Labels": {"com.docker.compose.service": "ctfd"}}}]
            ).encode()
            return subprocess.CompletedProcess(arguments, 0, payload, b"")

    runner = UnrelatedRunner()
    services = RESTORE_MODULE.DockerServices(runner, database_target())

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="reserved validation container name is occupied",
    ):
        services.cleanup_private_validation()

    assert runner.calls[0] == [
        "docker",
        "inspect",
        "--type=container",
        RESTORE_MODULE.PRIVATE_VALIDATION_CONTAINER,
    ]
    assert all(arguments[1:2] != ["rm"] for arguments in runner.calls)


def test_private_validation_cleanup_removes_its_labeled_orphan():
    class OrphanRunner:
        def __init__(self):
            self.calls = []

        def run(self, arguments, **_options):
            self.calls.append(arguments)
            if arguments[1:2] == ["inspect"]:
                payload = json.dumps(
                    [
                        {
                            "Config": {
                                "Labels": {
                                    RESTORE_MODULE.PRIVATE_VALIDATION_LABEL: "1"
                                }
                            }
                        }
                    ]
                ).encode()
                return subprocess.CompletedProcess(arguments, 0, payload, b"")
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

    runner = OrphanRunner()
    services = RESTORE_MODULE.DockerServices(runner, database_target())

    services.cleanup_private_validation()

    assert ["docker", "rm", "--force", RESTORE_MODULE.PRIVATE_VALIDATION_CONTAINER] in runner.calls


def test_database_recreation_preserves_metadata(monkeypatch):
    metadata = database_metadata()
    metadata["allow_connections"] = False
    database = maintenance_role_database()
    statements = []
    monkeypatch.setattr(database, "drain_database", lambda *_arguments: None)
    monkeypatch.setattr(database, "psql", lambda sql: statements.append(sql))

    database.recreate_database(metadata)
    database.apply_metadata(metadata)

    assert statements[0] == 'DROP DATABASE IF EXISTS "ctfd";'
    assert "CREATE DATABASE \"ctfd\" WITH" in statements[1]
    assert "TEMPLATE = template0" in statements[1]
    assert f'OWNER = "{database.maintenance_target.user}"' in statements[1]
    assert "ALLOW_CONNECTIONS = true" in statements[1]
    assert "OID = 20000" in statements[1]
    assert "COLLATION_VERSION = E'2.39'" in statements[1]
    escaped_value = RESTORE_MODULE.sql_literal(metadata["comment"])
    assert f'COMMENT ON DATABASE "ctfd" IS {escaped_value}' in statements[2]
    assert (
        f'SECURITY LABEL FOR "selinux" ON DATABASE "ctfd" IS {escaped_value}'
        in statements[2]
    )
    assert (
        f'ALTER DATABASE "ctfd" SET "application_name" TO {escaped_value}'
        in statements[2]
    )
    assert (
        'ALTER ROLE "reader" IN DATABASE "ctfd" SET "statement_timeout" TO E\'5s\''
        in statements[2]
    )


def test_database_recreation_interruption_hook_sleeps_between_drop_and_create(
    monkeypatch,
):
    database = maintenance_role_database()
    statements = []
    monkeypatch.setattr(database, "drain_database", lambda *_arguments: None)
    monkeypatch.setattr(database, "psql", statements.append)
    monkeypatch.setenv("DOJO_RESTORE_TEST_SLEEP_AFTER_DATABASE_DROP", "1")

    database.recreate_database(database_metadata())

    assert statements[0] == 'DROP DATABASE IF EXISTS "ctfd";'
    assert statements[1] == "SELECT pg_sleep(300);"
    assert statements[2].startswith('CREATE DATABASE "ctfd" WITH ')


def test_sql_literal_is_setting_independent():
    value = "metadata\\'; SELECT pg_sleep(10); --"
    assert RESTORE_MODULE.sql_literal(value) == (
        "E'metadata\\\\''; SELECT pg_sleep(10); --'"
    )


def test_template_database_metadata_is_rejected_before_recreation(monkeypatch):
    metadata = database_metadata()
    metadata["is_template"] = True
    database = maintenance_role_database()
    mutations = []
    monkeypatch.setattr(database, "drain_database", lambda *_args: mutations.append("drain"))
    monkeypatch.setattr(database, "psql", lambda sql: mutations.append(sql))

    with pytest.raises(RESTORE_MODULE.RestoreError, match="template databases"):
        database.recreate_database(metadata)
    assert mutations == []


def test_database_acl_replay_preserves_delegated_grantors_and_cascade_ordering():
    metadata = database_metadata()
    metadata["acl"] = [
        {
            "grantor": "ctfd",
            "grantee": "reader",
            "privilege": "CONNECT",
            "grantable": True,
        },
        {
            "grantor": "reader",
            "grantee": "student",
            "privilege": "CONNECT",
            "grantable": False,
        },
    ]
    RESTORE_MODULE.validate_database_metadata(metadata)
    database = maintenance_role_database()
    statements = database.database_acl_statements(metadata, '"ctfd"')
    sql = ";".join(statements)

    assert sql.startswith('BEGIN;REVOKE ALL ON DATABASE "ctfd" FROM PUBLIC CASCADE')
    assert 'SET ROLE "ctfd";GRANT CONNECT ON DATABASE "ctfd" TO "reader" ' in sql
    assert "WITH GRANT OPTION GRANTED BY CURRENT_USER" in sql
    assert 'SET ROLE "reader";GRANT CONNECT ON DATABASE "ctfd" TO "student" ' in sql
    assert sql.index('SET ROLE "ctfd"') < sql.index('SET ROLE "reader"')
    assert statements[-1] == "COMMIT"

    metadata["acl"][0]["grantor"] = "unreachable"
    with pytest.raises(RESTORE_MODULE.RestoreError, match="grant chain"):
        RESTORE_MODULE.validate_database_metadata(metadata)


def test_global_dependency_preflight_seeds_every_manifest_role(monkeypatch):
    expected = backup_dependencies()
    role_template = expected["roles"][1]
    expected["roles"].extend(
        {**role_template, "name": name}
        for name in (
            "analyst",
            "default_owner",
            "default_grantor",
            "default_grantee",
            "tablespace_owner",
            "tablespace_grantor",
            "tablespace_grantee",
        )
    )
    expected["memberships"] = [
        {
            "role": "reader",
            "member": "analyst",
            "grantor": "ctfd",
            "admin_option": False,
            "inherit_option": True,
            "set_option": True,
        }
    ]
    expected["default_acls"] = [
        {
            "owner": "default_owner",
            "schema": None,
            "object_type": "r",
            "grantor": "default_grantor",
            "grantee": "default_grantee",
            "privilege": "SELECT",
            "grantable": False,
        }
    ]
    expected["tablespaces"] = [
        {
            "name": "archive_space",
            "owner": "tablespace_owner",
            "location": "/data/postgres-tablespaces/archive-space",
            "options": [],
            "acl_default": False,
            "acl": [
                {
                    "grantor": "tablespace_grantor",
                    "grantee": "tablespace_grantee",
                    "privilege": "CREATE",
                    "grantable": False,
                }
            ],
        }
    ]
    seeds = []

    def capture(
        required_role_names=(),
        required_tablespace_names=(),
        *,
        include_database_dependencies=True,
    ):
        seeds.append(
            (
                set(required_role_names),
                set(required_tablespace_names),
                include_database_dependencies,
            )
        )
        return expected

    database = maintenance_role_database()
    monkeypatch.setattr(database, "capture_backup_dependencies", capture)

    database.verify_global_backup_dependencies(expected)

    assert seeds == [
        (
            {
                "ctfd",
                "reader",
                "analyst",
                "default_owner",
                "default_grantor",
                "default_grantee",
                "tablespace_owner",
                "tablespace_grantor",
                "tablespace_grantee",
            },
            {"archive_space"},
            False,
        )
    ]


def test_pending_recovery_accepts_postgresql_minor_upgrade(monkeypatch):
    database = maintenance_role_database()
    expected = journal_target()
    current = {
        **expected["server"],
        "server_version_num": 170006,
    }
    claims = []
    monkeypatch.setattr(database, "verify_configured_target", lambda _target: None)
    monkeypatch.setattr(database, "capture_server_identity", lambda: current)
    monkeypatch.setattr(database, "acquire_cluster_claims", claims.append)

    database.verify_target(expected)

    assert claims == [expected["server"]]


def test_postgresql_16_is_rejected_before_metadata_or_artifact_work(monkeypatch):
    database = maintenance_role_database()
    identity = {
        "system_identifier": server_identity()["system_identifier"],
        "server_version_num": 160010,
    }
    monkeypatch.setattr(
        database,
        "psql",
        lambda _sql: subprocess.CompletedProcess(
            [], 0, json.dumps(identity).encode(), b""
        ),
    )
    work = []
    monkeypatch.setattr(database, "capture_metadata", lambda: work.append("metadata"))

    with pytest.raises(RESTORE_MODULE.RestoreError, match="PostgreSQL 17 is required"):
        database.capture_server_identity()
    assert work == []


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"other_owned_databases": 1}, "shared by another database"),
        ({"application_memberships": 1}, "must not have role memberships"),
        (
            {
                "other_application_sessions": 1,
                "other_application_session_details": [
                    {
                        "database": "postgres",
                        "application_name": "psql",
                        "client_type": "local",
                        "backend_type": "client backend",
                    }
                ],
            },
            "sessions in another database",
        ),
        ({"privileged_roles": ["other_admin"]}, "exclusive PostgreSQL cluster"),
    ],
)
def test_database_preflight_rejects_nonexclusive_cluster_topology(
    monkeypatch,
    override,
    message,
):
    database = maintenance_role_database()
    topology = {
        "owner": "ctfd",
        "other_owned_databases": 0,
        "privileged_roles": [],
        "application_memberships": 0,
        "other_application_sessions": 0,
        "other_application_session_details": [],
        **override,
    }
    monkeypatch.setattr(
        database,
        "psql",
        lambda _sql: subprocess.CompletedProcess(
            [], 0, json.dumps(topology).encode(), b""
        ),
    )

    if topology["other_application_sessions"]:
        monkeypatch.setattr(
            RESTORE_MODULE,
            "wait_for_retry",
            lambda _deadline, error: (_ for _ in ()).throw(
                RESTORE_MODULE.RestoreError(error)
            ),
        )

    with pytest.raises(RESTORE_MODULE.RestoreError, match=message) as caught:
        database.verify_exclusive_cluster_topology()

    if topology["other_application_sessions"]:
        assert '"application_name":"psql"' in str(caught.value)
        assert '"client_type":"local"' in str(caught.value)


def test_database_preflight_waits_for_transient_foreign_database_session(monkeypatch):
    database = maintenance_role_database()
    occupied = {
        "owner": "ctfd",
        "other_owned_databases": 0,
        "privileged_roles": [],
        "application_memberships": 0,
        "other_application_sessions": 1,
        "other_application_session_details": [
            {
                "database": "postgres",
                "application_name": "psql",
                "client_type": "local",
                "backend_type": "client backend",
            }
        ],
    }
    quiet = {
        **occupied,
        "other_application_sessions": 0,
        "other_application_session_details": [],
    }
    observations = iter((occupied, quiet))
    waits = []
    monkeypatch.setattr(
        database,
        "psql",
        lambda _sql: subprocess.CompletedProcess(
            [],
            0,
            json.dumps(next(observations)).encode(),
            b"",
        ),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "wait_for_retry",
        lambda deadline, error: waits.append((deadline, error)),
    )

    database.verify_exclusive_cluster_topology()

    assert len(waits) == 1
    assert "sessions in another database" in waits[0][1]


@pytest.mark.parametrize(
    "blocker",
    ["prepared_transactions", "logical_slots", "subscriptions"],
)
def test_database_preflight_rejects_drop_blockers(monkeypatch, blocker):
    class Services:
        ready_timeout = 2

    database = RESTORE_MODULE.DatabaseRestore(
        None, None, Services(), database_target()
    )
    blockers = {
        "prepared_transactions": 0,
        "logical_slots": 0,
        "subscriptions": 0,
        "is_template": False,
    }
    blockers[blocker] = 1
    result = subprocess.CompletedProcess(
        [],
        0,
        json.dumps(blockers).encode(),
        b"",
    )
    monkeypatch.setattr(database, "psql", lambda _sql: result)
    monkeypatch.setattr(database, "verify_recreation_privileges", lambda: None)
    monkeypatch.setattr(
        database,
        "verify_exclusive_cluster_topology",
        lambda _database_name=None: None,
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match=blocker.replace("_", " "),
    ):
        database.preflight_recreation()


def test_database_preflight_rejects_template_before_recreation(monkeypatch):
    database = maintenance_role_database()
    blockers = {
        "prepared_transactions": 0,
        "logical_slots": 0,
        "subscriptions": 0,
        "is_template": True,
    }
    monkeypatch.setattr(
        database,
        "psql",
        lambda _sql: subprocess.CompletedProcess(
            [],
            0,
            json.dumps(blockers).encode(),
            b"",
        ),
    )
    monkeypatch.setattr(database, "verify_recreation_privileges", lambda: None)
    monkeypatch.setattr(
        database,
        "verify_exclusive_cluster_topology",
        lambda _database_name=None: None,
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="template databases",
    ):
        database.preflight_recreation()


class ArchiveRunner:
    def __init__(self, contents, decode_error=None):
        self.contents = contents
        self.decode_error = decode_error
        self.calls = []

    def run(self, arguments, **_options):
        self.calls.append(arguments)
        if "--list" in arguments:
            return subprocess.CompletedProcess(arguments, 0, self.contents, b"")
        if self.decode_error is not None:
            raise RESTORE_MODULE.RestoreError(self.decode_error)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")


def temporary_archive():
    archive = tempfile.TemporaryFile()
    archive.write(b"archive")
    archive.seek(0)
    return archive


def test_archive_validation_decodes_high_object_count_archive():
    contents = b"\n".join(
        f"{index}; 1259 {index} TABLE public table_{index} ctfd".encode()
        for index in range(5000)
    )
    runner = ArchiveRunner(contents)
    with temporary_archive() as archive:
        catalog_ids = RESTORE_MODULE.validate_archive(
            runner,
            database_target(),
            archive,
        )
        assert archive.tell() == 0

    assert catalog_ids == {(1259, index) for index in range(1, 5000)}
    assert len(runner.calls) == 2
    assert "--list" in runner.calls[0]
    assert "--create" in runner.calls[0]
    assert "--file=/dev/null" in runner.calls[1]
    assert "--create" not in runner.calls[1]


def test_archive_validation_rejects_subscriptions():
    runner = ArchiveRunner(b"1; 6104 1 SUBSCRIPTION public source ctfd\n")
    with temporary_archive() as archive:
        with pytest.raises(
            RESTORE_MODULE.RestoreError,
            match="subscriptions are unsupported",
        ):
            RESTORE_MODULE.validate_archive(runner, database_target(), archive)

    assert len(runner.calls) == 1


def test_archive_validation_rejects_corrupt_data():
    runner = ArchiveRunner(
        b"1; 1259 1 TABLE public target ctfd\n",
        decode_error="corrupt archive data",
    )
    with temporary_archive() as archive:
        with pytest.raises(RESTORE_MODULE.RestoreError, match="corrupt archive data"):
            RESTORE_MODULE.validate_archive(runner, database_target(), archive)

    assert len(runner.calls) == 2


def test_pg_dump_major_parses_distribution_suffix_and_rejects_other_major():
    class Target:
        def __init__(self, output):
            self.output = output

        def run_client(self, *_args, **_options):
            return subprocess.CompletedProcess([], 0, self.output, b"")

    assert RESTORE_MODULE.capture_pg_dump_major(
        object(),
        Target(b"pg_dump (PostgreSQL) 17.6 (Debian 17.6-1.pgdg120+1)\n"),
        timeout=2,
    ) == 17
    with pytest.raises(RESTORE_MODULE.RestoreError, match="pg_dump 17 is required"):
        RESTORE_MODULE.capture_pg_dump_major(
            object(),
            Target(b"pg_dump (PostgreSQL) 16.10 (Ubuntu 16.10-1)\n"),
            timeout=2,
        )


def test_restore_uses_bounded_transactions(monkeypatch):
    class Services:
        ready_timeout = 2

    runner = ArchiveRunner(b"")
    database = RESTORE_MODULE.DatabaseRestore(
        runner, None, Services(), database_target()
    )
    monkeypatch.setattr(database, "recreate_database", lambda _metadata: None)
    monkeypatch.setattr(database, "apply_metadata", lambda _metadata: None)
    monkeypatch.setattr(database, "enforce_fenced_acl", lambda: None)

    with temporary_archive() as archive:
        database.restore_archive(archive, database_metadata())

    restore_command = runner.calls[0]
    assert (
        f"--transaction-size={RESTORE_MODULE.RESTORE_TRANSACTION_SIZE}"
        in restore_command
    )
    assert "--single-transaction" not in restore_command


class LockedState:
    locked = True
    installation_id = TEST_INSTALLATION_ID
    maintenance_secret = "2" * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH


class SnapshotDatabase:
    snapshot = "00000003-0000001B-1"

    def __init__(self):
        self.captured = []

    @contextlib.contextmanager
    def export_backup_snapshot(self):
        yield self.snapshot

    def capture_backup_dependencies(self, *, snapshot, archive_catalog_ids):
        self.captured.append((snapshot, set(archive_catalog_ids)))
        return backup_dependencies()


def test_backup_is_private_validated_atomic_and_same_second_safe(
    monkeypatch,
    tmp_path,
):
    backup_directory = tmp_path / "backups"
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_DIRECTORY", backup_directory)
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_OWNER_UID", os.getuid())
    real_datetime = RESTORE_MODULE.datetime.datetime

    class FrozenDateTime:
        @classmethod
        def now(cls, timezone):
            return real_datetime(2026, 7, 18, 12, 34, 56, tzinfo=timezone)

    dump_commands = []
    snapshot_databases = [SnapshotDatabase(), SnapshotDatabase()]

    class BackupRunner:
        def run(self, arguments, **options):
            if "pg_dump" in arguments:
                dump_commands.append(arguments)
                os.write(options["stdout"], b"valid archive")
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

    validated = []

    def validate_backup(_runner, _target, archive, **_options):
        archive.seek(archive.payload_offset)
        validated.append(archive.read())
        return {(1259, 24680)}

    monkeypatch.setattr(RESTORE_MODULE.datetime, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        RESTORE_MODULE,
        "validate_archive",
        validate_backup,
    )
    previous_umask = os.umask(0o777)
    try:
        first = RESTORE_MODULE.create_backup(
            BackupRunner(),
            database_target(),
            LockedState(),
            backup_source(),
            snapshot_databases[0],
        )
        second = RESTORE_MODULE.create_backup(
            BackupRunner(),
            database_target(),
            LockedState(),
            backup_source(),
            snapshot_databases[1],
        )
    finally:
        os.umask(previous_umask)

    assert first != second
    assert first.startswith("db-2026-07-18T12:34:56Z-")
    assert second.startswith("db-2026-07-18T12:34:56Z-")
    assert validated == [b"valid archive", b"valid archive"]
    assert all(
        f"--snapshot={SnapshotDatabase.snapshot}" in command
        for command in dump_commands
    )
    assert all(
        database.captured == [(SnapshotDatabase.snapshot, {(1259, 24680)})]
        for database in snapshot_databases
    )
    assert {path.name for path in backup_directory.iterdir()} == {first, second}
    for filename in (first, second):
        assert (backup_directory / filename).stat().st_mode & 0o777 == 0o600
    assert not any(path.name.endswith(".partial") for path in backup_directory.iterdir())


def test_backup_envelope_binds_source_checksum_and_explicit_migration(
    monkeypatch,
    tmp_path,
):
    backup_directory = tmp_path / "backups"
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_DIRECTORY", backup_directory)
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_OWNER_UID", os.getuid())

    class BackupRunner:
        def run(self, arguments, **options):
            if "pg_dump" in arguments:
                flags = fcntl.fcntl(options["stdout"], fcntl.F_GETFL)
                fcntl.fcntl(
                    options["stdout"],
                    fcntl.F_SETFL,
                    flags | os.O_APPEND,
                )
                os.write(options["stdout"], b"complete custom archive")
            return subprocess.CompletedProcess(arguments, 0, b"", b"")

    monkeypatch.setattr(
        RESTORE_MODULE,
        "validate_archive",
        lambda *_args, **_kwargs: {(1259, 24680)},
    )
    state = LockedState()
    filename = RESTORE_MODULE.create_backup(
        BackupRunner(),
        database_target(),
        state,
        backup_source(),
        SnapshotDatabase(),
    )

    with RESTORE_MODULE.open_archive(filename) as archive:
        assert archive.read() == b"complete custom archive"
        RESTORE_MODULE.verify_backup_manifest(
            archive,
            state,
            database_target(),
            server_identity(),
            allow_migration=False,
        )
        foreign_state = type(
            "ForeignState",
            (),
            {
                "installation_id": "f" * RESTORE_MODULE.INSTALLATION_ID_LENGTH,
                "maintenance_secret": "e"
                * RESTORE_MODULE.MAINTENANCE_SECRET_LENGTH,
            },
        )()
        with pytest.raises(RESTORE_MODULE.RestoreError, match="another installation"):
            RESTORE_MODULE.verify_backup_manifest(
                archive,
                foreign_state,
                database_target(),
                server_identity(),
                allow_migration=False,
            )
        RESTORE_MODULE.verify_backup_manifest(
            archive,
            foreign_state,
            database_target(),
            server_identity(),
            allow_migration=True,
        )

    path = backup_directory / filename
    with path.open("r+b") as tampered:
        tampered.seek(RESTORE_MODULE.BACKUP_HEADER_SIZE)
        tampered.write(b"tampered")
    with pytest.raises(RESTORE_MODULE.RestoreError, match="checksum"):
        RESTORE_MODULE.open_archive(filename)


def test_manifest_archive_requires_full_database_toc_entry():
    runner = ArchiveRunner(
        b"1; 0 0 DATABASE PROPERTIES - ctfd ctfd\n"
        b"2; 1259 1 TABLE public target ctfd\n"
    )
    with temporary_archive() as archive:
        archive.manifest = {}
        with pytest.raises(RESTORE_MODULE.RestoreError, match="complete database dump"):
            RESTORE_MODULE.validate_archive(runner, database_target(), archive)


def test_manifest_archive_accepts_database_toc_entry():
    runner = ArchiveRunner(b"1; 1262 16384 DATABASE - ctfd ctfd\n")
    with temporary_archive() as archive:
        archive.manifest = {}
        catalog_ids = RESTORE_MODULE.validate_archive(
            runner,
            database_target(),
            archive,
        )

    assert catalog_ids == {(1262, 16384)}


def test_failed_partial_backup_is_never_published(monkeypatch, tmp_path):
    backup_directory = tmp_path / "backups"
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_DIRECTORY", backup_directory)
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_OWNER_UID", os.getuid())

    class FailedRunner:
        def run(self, arguments, **options):
            assert "pg_dump" in arguments
            os.write(options["stdout"], b"partial archive")
            raise RESTORE_MODULE.RestoreError("pg_dump failed")

    with pytest.raises(RESTORE_MODULE.RestoreError, match="pg_dump failed"):
        RESTORE_MODULE.create_backup(
            FailedRunner(),
            database_target(),
            LockedState(),
            backup_source(),
            SnapshotDatabase(),
        )

    assert list(backup_directory.iterdir()) == []


def test_backup_refuses_pending_restore_before_cleanup_or_dump(monkeypatch):
    events = []

    class PendingState:
        locked = True

        def __enter__(self):
            events.append("lock")
            return self

        def __exit__(self, *_arguments):
            events.append("unlock")

        def load_journal(self):
            events.append("journal")
            return restore_journal("warming")

    monkeypatch.setattr(RESTORE_MODULE, "RestoreState", PendingState)
    monkeypatch.setattr(
        RESTORE_MODULE,
        "install_interrupt_handlers",
        lambda _runner, _operation: events.append("handlers"),
    )
    monkeypatch.setattr(
        RESTORE_MODULE.DatabaseTarget,
        "from_environment",
        classmethod(lambda _cls: database_target()),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "cleanup_backup_partials",
        lambda _state: events.append("cleanup"),
    )
    monkeypatch.setattr(
        RESTORE_MODULE,
        "create_backup",
        lambda _runner, _target, _state: events.append("dump"),
    )

    with pytest.raises(
        RESTORE_MODULE.RestoreError,
        match="restore recovery is pending",
    ):
        RESTORE_MODULE.backup()

    assert events == ["handlers", "lock", "journal", "unlock"]


def test_stale_backup_cleanup_removes_only_trusted_partials(monkeypatch, tmp_path):
    backup_directory = tmp_path / "backups"
    backup_directory.mkdir(mode=0o755)
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_DIRECTORY", backup_directory)
    monkeypatch.setattr(RESTORE_MODULE, "BACKUP_OWNER_UID", os.getuid())
    trusted = backup_directory / (
        ".dojo-backup.0123456789abcdef0123456789abcdef.123.partial"
    )
    legacy_trusted = backup_directory / (
        ".db-2026-07-18T12:34:56Z-3123456789abcdef0123456789abcdef.dump.123.partial"
    )
    untrusted_mode = backup_directory / (
        ".dojo-backup.1123456789abcdef0123456789abcdef.123.partial"
    )
    unrelated = backup_directory / ".unrelated.partial"
    symlink = backup_directory / (
        ".dojo-backup.2123456789abcdef0123456789abcdef.123.partial"
    )
    trusted.write_bytes(b"partial")
    trusted.chmod(0o600)
    legacy_trusted.write_bytes(b"partial")
    legacy_trusted.chmod(0o600)
    untrusted_mode.write_bytes(b"partial")
    untrusted_mode.chmod(0o644)
    unrelated.write_bytes(b"partial")
    symlink.symlink_to(trusted)

    RESTORE_MODULE.cleanup_backup_partials(LockedState())

    assert not trusted.exists()
    assert not legacy_trusted.exists()
    assert untrusted_mode.exists()
    assert unrelated.exists()
    assert symlink.is_symlink()


@pytest.mark.parametrize("value", ["0", "invalid", "604801"])
def test_restore_timeout_configuration_rejects_invalid_values(monkeypatch, value):
    name = "DOJO_RESTORE_READY_TIMEOUT_SECONDS"
    monkeypatch.setenv(name, value)
    with pytest.raises(RESTORE_MODULE.RestoreError, match=name):
        RESTORE_MODULE.DockerServices(UnreadyRunner(), database_target())


def test_restore_timeout_configuration_is_exported_by_shell_entrypoints():
    repository = pathlib.Path(__file__).parents[1]
    for script in (repository / "dojo" / "dojo", repository / "dojo" / "dojo-init"):
        contents = script.read_text()
        assert "export DOJO_ENV DOJO_HOST" in contents
        assert "export DOJO_RESTORE_READY_TIMEOUT_SECONDS" in contents
        assert "export DOJO_RESTORE_COLD_START_TIMEOUT_SECONDS" in contents

    dojo_script = (repository / "dojo" / "dojo").read_text()
    assert "/opt/pwn.college/dojo/dojo-restore --validate-target" in dojo_script

    service = repository / "etc" / "systemd" / "system" / "pwn.college.service"
    service_contents = service.read_text()
    assert "After=docker.service" in service_contents
    assert "Restart=on-failure" in service_contents
    assert "RestartSec=5s" in service_contents
    assert "ExecStop=/usr/local/bin/dojo shutdown" in service_contents

    nginx = (repository / "nginx" / "nginx.conf").read_text()
    assert "zone frontend_upstream 64k;" in nginx
    assert "server frontend:3000 resolve;" in nginx

    compose = (repository / "docker-compose.yml").read_text()
    assert "SERVER_TLS_SSLMODE: ${DB_SSLMODE}" in compose
    assert "SERVER_TLS_CA_FILE: ${DB_SSLROOTCERT:-}" in compose
    assert "PGSSLMODE: ${DB_SSLMODE}" not in compose


def test_backup_timer_waits_for_startup_without_activating_a_stopped_dojo():
    repository = pathlib.Path(__file__).parents[1]
    backup_service = (
        repository / "etc" / "systemd" / "system" / "pwn.college.backup.service"
    ).read_text()
    backup_timer = (
        repository / "etc" / "systemd" / "system" / "pwn.college.backup.timer"
    ).read_text()

    assert "Requisite=pwn.college.service" in backup_service
    assert "After=pwn.college.service" in backup_service
    assert "Requires=pwn.college.service" not in backup_service
    assert "Wants=pwn.college.service" not in backup_service
    assert "Unit=pwn.college.backup.service" in backup_timer


def test_dependency_query_scopes_contract_to_dumped_database_objects():
    database = maintenance_role_database()
    commands = []

    def run_client(_runner, program, arguments, **_options):
        commands.append((program, arguments))
        return subprocess.CompletedProcess(
            [],
            0,
            json.dumps(backup_dependencies()).encode(),
        )

    database.target.run_client = run_client

    database.capture_backup_dependencies(
        required_tablespace_names={"migration_space"},
    )

    query = commands[0][1][commands[0][1].index("--command") + 1]
    assert "target_tablespaces AS (" in query
    assert (
        "SELECT DISTINCT relation.reltablespace AS oid FROM pg_class AS relation "
        "WHERE relation.reltablespace <> 0 AND relation.relpersistence <> 't'"
        in query
    )
    assert "extension_members AS (" in query
    assert "temp_objects(classid, objid) AS (" in query
    assert "extension.classid = dependency.classid" in query
    assert "temporary.classid = dependency.classid" in query
    assert (
        "UNION SELECT oid FROM pg_tablespace WHERE spcname IN (E'migration_space')"
        in query
    )
    assert query.count(
        "JOIN target_tablespaces ON target_tablespaces.oid = tablespace.oid"
    ) == 4
    assert "dattablespace" not in query
    assert "datdba" not in query
    assert "aclexplode(database.datacl)" not in query
    assert "pg_db_role_setting" not in query


def test_dependency_verification_ignores_destination_only_database_graph():
    database = maintenance_role_database()
    commands = []

    def run_client(_runner, _program, arguments, **_options):
        commands.append(arguments)
        return subprocess.CompletedProcess(
            [],
            0,
            json.dumps(backup_dependencies()).encode(),
        )

    database.target.run_client = run_client

    database.capture_backup_dependencies(
        {"ctfd", "reader"},
        {"migration_space"},
        include_database_dependencies=False,
    )

    query = commands[0][commands[0].index("--command") + 1]
    seed_roles = query.split("), seed_roles AS (", 1)[1].split(
        "), role_graph(oid) AS (", 1
    )[0]
    target_tablespaces = query.split("), target_tablespaces AS (", 1)[1].split(
        "), seed_roles AS (", 1
    )[0]
    assert "pg_shdepend" not in seed_roles
    assert "pg_default_acl" not in seed_roles
    assert "pg_class" not in target_tablespaces
    assert "spcname IN (E'migration_space')" in target_tablespaces


def test_dependency_capture_joins_the_exported_dump_snapshot():
    database = maintenance_role_database()
    commands = []
    catalog_inputs = []

    def run_client(_runner, _program, arguments, **_options):
        commands.append(arguments)
        catalog_inputs.append(_options["stdin"].read())
        return subprocess.CompletedProcess(
            [],
            0,
            b"BEGIN\nSET\n" + json.dumps(backup_dependencies()).encode() + b"\nCOMMIT\n",
        )

    database.target.run_client = run_client
    snapshot = "00000003-0000001B-1"

    database.capture_backup_dependencies(
        snapshot=snapshot,
        archive_catalog_ids={(1259, 40001), (2615, 40000)},
    )

    arguments = commands[0]
    query = arguments[arguments.index("--command") + 1]
    assert "--quiet" in arguments
    assert "BEGIN ISOLATION LEVEL REPEATABLE READ" in query
    assert f"SET TRANSACTION SNAPSHOT E'{snapshot}'" in query
    assert "COPY archive_objects (classid, objid) FROM STDIN" in query
    assert "archived_relation.objid = relation.oid" in query
    assert "archived_default.objid = defaults.oid" in query
    assert query.endswith(" COMMIT;")
    assert catalog_inputs == [b"1259\t40001\n2615\t40000\n\\.\n"]


@pytest.mark.parametrize(
    "options",
    [
        {"snapshot": "00000003-0000001B-1"},
        {"archive_catalog_ids": {(1259, 40001)}},
    ],
)
def test_dependency_capture_requires_paired_snapshot_and_archive_identity(options):
    database = maintenance_role_database()

    with pytest.raises(RESTORE_MODULE.RestoreError, match="must be paired"):
        database.capture_backup_dependencies(**options)


@pytest.mark.parametrize(
    ("pending", "compose_action"),
    [(True, "stop"), (False, "down")],
)
def test_shutdown_preserves_container_identities_during_pending_restore(
    monkeypatch,
    pending,
    compose_action,
):
    calls = []

    class State:
        def __enter__(self):
            calls.append("lock")
            return self

        def __exit__(self, *_args):
            calls.append("unlock")

        def load_journal(self):
            return restore_journal("restoring") if pending else None

    class Runner:
        def run(self, arguments, **_options):
            calls.append(arguments)

    monkeypatch.setattr(RESTORE_MODULE, "RestoreState", State)
    monkeypatch.setattr(RESTORE_MODULE, "CommandRunner", Runner)
    monkeypatch.setattr(
        RESTORE_MODULE,
        "install_interrupt_handlers",
        lambda _runner, _operation: None,
    )

    RESTORE_MODULE.shutdown()

    assert calls == ["lock", ["dojo", "compose", compose_action], "unlock"]


def test_dojo_up_recovers_with_only_database_started_before_clients():
    repository = pathlib.Path(__file__).parents[1]
    contents = (repository / "dojo" / "dojo").read_text()
    prepare_index = contents.index(
        "/opt/pwn.college/dojo/dojo-restore --prepare-recovery"
    )
    database_index = contents.index(
        'dojo compose up -d "${build_args[@]}" --no-deps --no-recreate db'
    )
    recover_index = contents.index(
        "/opt/pwn.college/dojo/dojo-restore --recover",
        database_index,
    )
    clients_index = contents.index(
        'dojo compose up -d "${build_args[@]}" --remove-orphans "$@"'
    )

    assert contents.startswith("#!/bin/bash -e")
    assert prepare_index < database_index < recover_index < clients_index
