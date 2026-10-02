import errno
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import socket
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

import docker
import pytest
import redis
import requests


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.unit


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


storage = load_module("home_reset_storage", "homefs/reset_home.py")
orchestration = load_module("home_reset_orchestration", "dojo_plugin/utils/home_reset.py")


@pytest.fixture
def volume(tmp_path):
    path = tmp_path / "42"
    home = path / "active"
    home.mkdir(parents=True)
    (home / "saved-file").write_text("saved data")
    return path


def backup_contents(path):
    with tarfile.open(path, "r:gz") as archive:
        return {member.name: archive.extractfile(member).read()
                for member in archive.getmembers() if member.isfile()}


@pytest.mark.skipif(os.geteuid() != 0, reason="homefs resets run as root")
def test_reset_preserves_hidden_files_links_and_socket_backups(volume, tmp_path, monkeypatch):
    home = volume / "active"
    hidden = home / ".config" / "nested"
    hidden.mkdir(parents=True)
    (hidden / "settings").write_text("settings")
    outside = tmp_path / "outside"
    outside.write_text("keep outside")
    (home / "outside-link").symlink_to(outside)
    monkeypatch.chdir(home)
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind("service.sock")
        storage.reset_home(volume)

    backup = home / "home-backup.tar.gz"
    assert list(home.iterdir()) == [backup]
    assert backup_contents(backup) == {
        "home/hacker/.config/nested/settings": b"settings",
        "home/hacker/saved-file": b"saved data",
    }
    with tarfile.open(backup, "r:gz") as archive:
        link = archive.getmember("home/hacker/outside-link")
        assert link.issym() and link.linkname == str(outside)
    assert outside.read_text() == "keep outside"
    assert home.stat().st_uid == 1000 and home.stat().st_mode & 0o777 == 0o755
    assert backup.stat().st_uid == 1000 and backup.stat().st_mode & 0o777 == 0o600
    assert not list((volume / "reset-backups").iterdir())


@pytest.mark.skipif(os.geteuid() != 0, reason="requires root to create root-owned unreadable files")
def test_reset_backs_up_root_owned_private_directories(volume):
    home = volume / "active"
    for name in (".emacs.d", ".gunicorn"):
        private = home / name
        private.mkdir(mode=0o700)
        (private / "private-file").write_text("private data")
    os.chown(home, 1000, 1000)
    os.chmod(home, 0)

    storage.reset_home(volume)

    backup = home / "home-backup.tar.gz"
    contents = backup_contents(backup)
    for name in (".emacs.d", ".gunicorn"):
        assert contents[f"home/hacker/{name}/private-file"] == b"private data"
        with tarfile.open(backup, "r:gz") as archive:
            member = archive.getmember(f"home/hacker/{name}")
            assert member.uid == 0 and member.mode == 0o700


def test_backup_write_failure_does_not_delete_home(volume, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tarfile.TarFile, "add", fail)
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.reset_home(volume)
    assert failure.value.phase == "backup" and failure.value.backup is None
    assert (volume / "active" / "saved-file").read_text() == "saved data"
    assert not list((volume / "reset-backups").iterdir())


def test_backup_verification_failure_does_not_delete_home(volume, monkeypatch):
    def fail(path):
        raise EOFError("Truncated archive")

    monkeypatch.setattr(storage, "verify_backup", fail)
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.reset_home(volume)
    assert failure.value.phase == "backup"
    assert (volume / "active" / "saved-file").read_text() == "saved data"
    assert not list((volume / "reset-backups").iterdir())


def test_delete_failure_preserves_verified_backup_outside_home(volume, monkeypatch):
    folder = volume / "active" / "folder"
    folder.mkdir()
    (folder / "file").write_text("nested data")

    def fail(path):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(storage.shutil, "rmtree", fail)
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.reset_home(volume)
    assert failure.value.phase == "delete"
    assert backup_contents(failure.value.backup) == {
        "home/hacker/saved-file": b"saved data",
        "home/hacker/folder/file": b"nested data",
    }


@pytest.mark.skipif(os.geteuid() != 0, reason="homefs resets run as root")
def test_restore_failure_preserves_verified_backup_outside_home(volume, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError(errno.EDQUOT, "Disk quota exceeded")

    monkeypatch.setattr(storage.shutil, "copyfileobj", fail)
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.reset_home(volume)
    assert failure.value.phase == "restore"
    assert backup_contents(failure.value.backup) == {"home/hacker/saved-file": b"saved data"}
    assert not list((volume / "active").iterdir())


def test_busy_volume_does_not_change_home(volume):
    with (volume / ".active.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(storage.HomeResetFailure) as failure:
            storage.reset_home(volume)
    assert failure.value.phase == "lock"
    assert (volume / "active" / "saved-file").read_text() == "saved data"
    assert not (volume / "reset-backups").exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="homefs resets run as root")
def test_failed_partial_restore_cleanup_does_not_hide_recovery_backup(volume, monkeypatch):
    unlink = Path.unlink

    def fail_copy(*args, **kwargs):
        raise OSError(errno.EDQUOT, "Disk quota exceeded")

    def fail_cleanup(path, *args, **kwargs):
        if path.name.startswith(".home-backup-"):
            raise OSError(errno.EIO, "Input/output error")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(storage.shutil, "copyfileobj", fail_copy)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.reset_home(volume)
    assert failure.value.phase == "restore"
    assert "Disk quota exceeded" in str(failure.value)
    assert backup_contents(failure.value.backup) == {"home/hacker/saved-file": b"saved data"}


def test_missing_active_volume_does_not_create_a_home(tmp_path):
    with pytest.raises(storage.HomeResetFailure):
        storage.reset_home(tmp_path / "42")
    assert not (tmp_path / "42").exists()


@pytest.mark.skipif(os.geteuid() != 0, reason="homefs resets run as root")
def test_repeat_reset_keeps_previous_backup_inside_new_archive(volume):
    storage.reset_home(volume)
    previous = (volume / "active" / "home-backup.tar.gz").read_bytes()
    storage.reset_home(volume)
    assert backup_contents(volume / "active" / "home-backup.tar.gz") == {
        "home/hacker/home-backup.tar.gz": previous,
    }
    assert not list((volume / "reset-backups").iterdir())


@pytest.mark.skipif(os.geteuid() != 0, reason="homefs resets run as root")
def test_cleanup_failure_does_not_report_a_completed_reset_as_failed(volume, monkeypatch, capsys):
    unlink = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.parent.name == "reset-backups":
            raise OSError(errno.EIO, "Input/output error")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    storage.reset_home(volume)
    assert backup_contents(volume / "active" / "home-backup.tar.gz") == {"home/hacker/saved-file": b"saved data"}
    assert json.loads(capsys.readouterr().err)["event"] == "cleanup_failed"


@pytest.fixture
def clients():
    container = Mock(status="running", attrs={"State": {"Paused": False}})
    homefs = Mock()
    homefs.exec_run.return_value = (0, (b'{"event":"complete"}\n', None))
    client = Mock(api=SimpleNamespace(timeout=60))
    client.containers.get.side_effect = lambda name: {"user_42": container, "homefs": homefs}[name]
    lock = Mock()
    lock.acquire.return_value = True
    return client, container, homefs, lock


def test_reset_stops_workspace_under_lock_before_using_storage_tools(clients):
    client, container, homefs, lock = clients

    def stop(*args, **kwargs):
        lock.acquire.assert_called_once_with(blocking=False)
        lock.release.assert_not_called()

    container.stop.side_effect = stop

    def reset(*args, **kwargs):
        container.stop.assert_called_once_with(timeout=10)
        container.wait.assert_called_once_with(condition="removed", timeout=30)
        lock.release.assert_not_called()
        assert kwargs["user"] == "0"
        assert client.api.timeout > orchestration.HOME_RESET_TIMEOUT
        return 0, (b'{"event":"complete"}\n', None)

    homefs.exec_run.side_effect = reset
    orchestration.reset_home_directory(client, 42, lock)
    container.exec_run.assert_not_called()
    container.start.assert_not_called()
    container.pause.assert_not_called()
    container.unpause.assert_not_called()
    lock.release.assert_called_once()
    assert client.api.timeout == 60


def test_competing_workspace_operation_prevents_reset(clients):
    client, container, homefs, lock = clients
    lock.acquire.return_value = False
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.status == 409
    client.containers.get.assert_not_called()
    lock.release.assert_not_called()


def test_missing_workspace_returns_conflict(clients):
    client, container, homefs, lock = clients
    client.containers.get.side_effect = docker.errors.NotFound("missing")
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.status == 409
    container.stop.assert_not_called()
    lock.release.assert_called_once()


def test_stopped_workspace_is_not_reset(clients):
    client, container, homefs, lock = clients
    container.status = "exited"
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.status == 409
    container.stop.assert_not_called()
    homefs.exec_run.assert_not_called()
    lock.release.assert_called_once()


def test_previously_paused_workspace_is_not_reset(clients):
    client, container, homefs, lock = clients
    container.status = "paused"
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.status == 409
    container.stop.assert_not_called()
    container.unpause.assert_not_called()
    homefs.exec_run.assert_not_called()
    lock.release.assert_called_once()


def test_storage_failure_leaves_workspace_stopped_and_reports_backup(clients, caplog):
    client, container, homefs, lock = clients
    detail = {"event": "failed", "phase": "restore", "error": "Disk quota exceeded", "backup": "/42/reset-backups/backup.tar.gz"}
    homefs.exec_run.return_value = (1, (None, json.dumps(detail).encode()))
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.status == 500
    assert "backup was preserved" in str(failure.value)
    assert detail["backup"] not in str(failure.value)
    assert "Disk quota exceeded" in caplog.text
    container.stop.assert_called_once()
    container.start.assert_not_called()
    lock.release.assert_called_once()


def test_lost_storage_connection_keeps_workspace_stopped_and_lock_held(clients):
    client, container, homefs, lock = clients
    homefs.exec_run.side_effect = requests.ConnectionError("connection lost")
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.status == 503 and failure.value.uncertain
    container.stop.assert_called_once()
    container.start.assert_not_called()
    lock.release.assert_not_called()
    assert client.api.timeout == 60


@pytest.mark.parametrize("operation", ["stop", "wait"])
def test_stop_failure_does_not_modify_home(clients, operation):
    client, container, homefs, lock = clients
    getattr(container, operation).side_effect = requests.ConnectionError("connection lost")
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.status == 503
    homefs.exec_run.assert_not_called()
    container.start.assert_not_called()
    lock.release.assert_called_once()


@pytest.mark.parametrize("operation", ["stop", "wait"])
def test_automatically_removed_workspace_can_still_be_reset(clients, operation):
    client, container, homefs, lock = clients
    getattr(container, operation).side_effect = docker.errors.NotFound("already removed")
    orchestration.reset_home_directory(client, 42, lock)
    homefs.exec_run.assert_called_once()
    lock.release.assert_called_once()


def test_storage_timeout_leaves_workspace_stopped_and_reports_recovery_error(clients):
    client, container, homefs, lock = clients
    homefs.exec_run.return_value = (124, (b'{"event":"backup_ready"}\n', None))
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert "timed out" in str(failure.value)
    container.stop.assert_called_once()
    container.start.assert_not_called()
    lock.release.assert_called_once()


def test_unknown_exec_exit_status_keeps_workspace_stopped_and_lock_held(clients):
    client, container, homefs, lock = clients
    homefs.exec_run.return_value = (None, (None, None))
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.uncertain
    container.stop.assert_called_once()
    container.start.assert_not_called()
    lock.release.assert_not_called()


def test_lock_service_failure_does_not_touch_workspace(clients):
    client, container, homefs, lock = clients
    lock.acquire.side_effect = redis.exceptions.ConnectionError("redis unavailable")
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.reset_home_directory(client, 42, lock)
    assert failure.value.status == 503
    client.containers.get.assert_not_called()


@pytest.mark.parametrize("user_id", ["../42", "/42", "0", "-1", "１２"])
def test_storage_command_rejects_invalid_user_id(user_id, monkeypatch, capsys):
    monkeypatch.setattr(storage.sys, "argv", ["reset_home.py", user_id])
    assert storage.main() == 1
    assert json.loads(capsys.readouterr().err)["error"] == "Invalid user ID"
