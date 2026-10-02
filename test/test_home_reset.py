import errno
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import Mock

import docker
from flask import Flask
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
def volume(tmp_path, monkeypatch):
    path = tmp_path / "42"
    home = path / "active"
    home.mkdir(parents=True)
    (home / "saved-file").write_text("saved data")
    monkeypatch.setattr(storage, "backup_source", lambda home, directory: nullcontext(home))
    return path


def backup_contents(path):
    arguments = {"fileobj": path} if hasattr(path, "read") else {"name": path}
    with tarfile.open(mode="r:gz", **arguments) as archive:
        return {member.name: archive.extractfile(member).read()
                for member in archive.getmembers() if member.isfile()}


def test_backup_preserves_home_and_archives_hidden_files_and_links(volume, tmp_path, monkeypatch):
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
        detail = storage.backup_home(volume)
    backup = Path(detail["backup"])
    assert backup_contents(backup) == {
        "home/hacker/.config/nested/settings": b"settings",
        "home/hacker/saved-file": b"saved data",
    }
    with tarfile.open(backup, "r:gz") as archive:
        link = archive.getmember("home/hacker/outside-link")
        assert link.issym() and link.linkname == str(outside)
    assert outside.read_text() == "keep outside"
    assert (home / "saved-file").read_text() == "saved data"
    assert not (home / "home-backup.tar.gz").exists()
    assert backup.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.geteuid() != 0, reason="homefs resets run as root")
def test_reset_backs_up_root_owned_files_and_leaves_an_empty_writable_home(volume):
    home = volume / "active"
    for name in (".emacs.d", ".gunicorn"):
        private = home / name
        private.mkdir(mode=0o700)
        (private / "private-file").write_text("private data")
    os.chown(home, 1000, 1000)
    os.chmod(home, 0)
    detail = storage.backup_home(volume)
    storage.reset_home(volume)
    contents = backup_contents(detail["backup"])
    for name in (".emacs.d", ".gunicorn"):
        assert contents[f"home/hacker/{name}/private-file"] == b"private data"
    assert not list(home.iterdir())
    assert home.stat().st_uid == home.stat().st_gid == 1000
    assert home.stat().st_mode & 0o777 == 0o755


def test_backup_includes_the_10_mb_boundary_and_excludes_larger_files_and_hardlinks(volume):
    home = volume / "active"
    for name, size in (("boundary", 10_000_000), ("large", 10_000_001)):
        with (home / name).open("wb") as stream:
            stream.truncate(size)
    os.link(home / "large", home / "large-link")
    detail = storage.backup_home(volume)
    with tarfile.open(detail["backup"], "r:gz") as archive:
        assert archive.getmember("home/hacker/boundary").size == 10_000_000
        assert "home/hacker/large" not in archive.getnames()
        assert "home/hacker/large-link" not in archive.getnames()
    assert detail["skipped"] == 2
    assert (home / "large").stat().st_size == 10_000_001


def test_backup_failure_preserves_the_home_and_previous_verified_archive(volume, monkeypatch):
    storage.backup_home(volume)
    backup = storage.archive_path(volume)
    previous = backup.read_bytes()
    (volume / "active" / "new-file").write_text("new data")
    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(tarfile.TarFile, "add", fail)
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.backup_home(volume)
    assert failure.value.phase == "backup"
    assert backup.read_bytes() == previous
    assert (volume / "active" / "new-file").read_text() == "new data"
    assert list(backup.parent.iterdir()) == [backup]


def test_verification_failure_does_not_delete_home(volume, monkeypatch):
    monkeypatch.setattr(storage, "verify_backup", Mock(side_effect=EOFError("Truncated archive")))
    with pytest.raises(storage.HomeResetFailure):
        storage.backup_home(volume)
    assert (volume / "active" / "saved-file").read_text() == "saved data"
    assert not list((volume / "home-backups").iterdir())


@pytest.mark.parametrize("compressible", [False, True])
def test_archive_limit_aborts_before_home_deletion(volume, monkeypatch, compressible):
    monkeypatch.setattr(storage, "MAX_ARCHIVE_SIZE", 16 * 1024)
    data = b"x" * 64 * 1024 if compressible else os.urandom(64 * 1024)
    (volume / "active" / "file").write_bytes(data)
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.backup_home(volume)
    assert "archive limit" in str(failure.value)
    assert (volume / "active" / "file").read_bytes() == data
    assert not list((volume / "home-backups").iterdir())


def test_repeated_failed_resets_do_not_accumulate_archives(volume, monkeypatch):
    folder = volume / "active" / "folder"
    folder.mkdir()
    (folder / "data").write_text("data")
    monkeypatch.setattr(storage.shutil, "rmtree", Mock(side_effect=OSError(errno.EIO, "Input/output error")))
    for attempt in range(4):
        storage.backup_home(volume)
        with pytest.raises(storage.HomeResetFailure) as failure:
            storage.reset_home(volume)
        assert failure.value.phase == "reset"
        assert Path(failure.value.backup) == storage.archive_path(volume)
        assert list((volume / "home-backups").iterdir()) == [storage.archive_path(volume)]


def test_abandoned_partial_archive_is_replaced_automatically(volume):
    storage.backup_home(volume)
    partial = storage.archive_path(volume).with_suffix(".partial")
    partial.write_bytes(b"interrupted")
    (volume / "active" / "new-file").write_text("new data")
    storage.backup_home(volume)
    assert not partial.exists()
    assert backup_contents(storage.archive_path(volume))["home/hacker/new-file"] == b"new data"
    assert list((volume / "home-backups").iterdir()) == [storage.archive_path(volume)]


def test_reset_requires_a_verified_backup_before_deleting_anything(volume):
    with pytest.raises(storage.HomeResetFailure):
        storage.reset_home(volume)
    assert (volume / "active" / "saved-file").exists()


@pytest.mark.parametrize("action", ["backup_home", "reset_home", "latest_backup"])
def test_busy_home_prevents_operations(volume, action):
    with (volume / ".active.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(storage.HomeResetFailure) as failure:
            getattr(storage, action)(volume)
    assert failure.value.phase == "lock"
    assert (volume / "active" / "saved-file").read_text() == "saved data"


def test_latest_backup_does_not_create_an_archive(volume):
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.latest_backup(volume)
    assert failure.value.phase == "missing"
    detail = storage.backup_home(volume)
    assert storage.latest_backup(volume)["backup"] == detail["backup"]


def test_latest_backup_remains_available_without_an_active_home(volume):
    detail = storage.backup_home(volume)
    shutil.rmtree(volume / "active")
    assert storage.latest_backup(volume)["backup"] == detail["backup"]


def test_latest_backup_is_missing_for_a_user_without_storage(tmp_path):
    with pytest.raises(storage.HomeResetFailure) as failure:
        storage.latest_backup(tmp_path / "42")
    assert failure.value.phase == "missing"


def test_backup_source_uses_and_removes_a_readonly_btrfs_snapshot(tmp_path, monkeypatch):
    run = Mock()
    monkeypatch.setattr(storage.subprocess, "run", run)
    with pytest.raises(RuntimeError):
        with storage.backup_source(tmp_path / "active", tmp_path) as source:
            assert source == tmp_path / "source"
            raise RuntimeError("archive failed")
    assert run.call_args_list[0].args[0] == [
        "btrfs", "subvolume", "snapshot", "-r", str(tmp_path / "active"), str(tmp_path / "source")
    ]
    assert run.call_args_list[1].args[0] == ["btrfs", "subvolume", "delete", str(tmp_path / "source")]


@pytest.fixture
def clients():
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        data = b"saved data"
        member = tarfile.TarInfo("home/hacker/saved-file")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    compressed = payload.getvalue()
    wrapped = io.BytesIO()
    with tarfile.open(fileobj=wrapped, mode="w") as archive:
        member = tarfile.TarInfo("backup.tar.gz")
        member.size = len(compressed)
        archive.addfile(member, io.BytesIO(compressed))
    container = Mock(status="running")
    homefs = Mock()
    detail = {"event": "complete", "backup": "/storage/42/home-backups/backup.tar.gz", "size": len(compressed), "skipped": 1}
    homefs.exec_run.return_value = (0, (json.dumps(detail).encode(), None))
    homefs.get_archive.return_value = (iter([wrapped.getvalue()[i:i+19] for i in range(0, len(wrapped.getvalue()), 19)]), {})
    client = Mock(api=SimpleNamespace(timeout=60))
    client.containers.get.side_effect = lambda name: {"user_42": container, "homefs": homefs}[name]
    lock = Mock()
    lock.acquire.return_value = True
    return client, container, homefs, lock


def test_reset_stops_under_lock_and_copies_backup_before_deleting_home(clients):
    client, container, homefs, lock = clients
    original = homefs.exec_run.return_value
    def run(command, **kwargs):
        container.stop.assert_called_once_with(timeout=10)
        container.wait.assert_called_once_with(condition="removed", timeout=30)
        lock.release.assert_not_called()
        if command[-1] == "reset":
            homefs.get_archive.assert_called_once()
        assert kwargs["user"] == "0"
        return original
    homefs.exec_run.side_effect = run
    archive = orchestration.manage_home_directory(client, 42, lock)
    assert archive.status == "success"
    assert [call.args[0][-1] for call in homefs.exec_run.call_args_list] == ["backup", "reset"]
    assert backup_contents(archive.file) == {"home/hacker/saved-file": b"saved data"}
    archive.file.close()
    container.start.assert_not_called()
    container.pause.assert_not_called()
    container.unpause.assert_not_called()
    lock.release.assert_called_once()
    assert client.api.timeout == 60


@pytest.mark.parametrize("action", ["backup", "latest"])
def test_non_destructive_download_keeps_workspace_running(clients, action):
    client, container, homefs, lock = clients
    archive = orchestration.manage_home_directory(client, 42, lock, action=action)
    assert backup_contents(archive.file) == {"home/hacker/saved-file": b"saved data"}
    archive.file.close()
    container.stop.assert_not_called()
    container.exec_run.assert_not_called()
    lock.release.assert_called_once()


def test_competing_workspace_operation_prevents_reset(clients):
    client, container, homefs, lock = clients
    lock.acquire.return_value = False
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.manage_home_directory(client, 42, lock)
    assert failure.value.status == 409
    client.containers.get.assert_not_called()
    lock.release.assert_not_called()


@pytest.mark.parametrize("status", ["exited", "paused"])
def test_inactive_workspace_is_not_reset(clients, status):
    client, container, homefs, lock = clients
    container.status = status
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.manage_home_directory(client, 42, lock)
    assert failure.value.status == 409
    container.stop.assert_not_called()
    homefs.exec_run.assert_not_called()
    lock.release.assert_called_once()


@pytest.mark.parametrize("operation", ["stop", "wait"])
def test_stop_failure_does_not_modify_home(clients, operation):
    client, container, homefs, lock = clients
    getattr(container, operation).side_effect = requests.ConnectionError("connection lost")
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.manage_home_directory(client, 42, lock)
    assert failure.value.status == 503
    homefs.exec_run.assert_not_called()
    lock.release.assert_called_once()


@pytest.mark.parametrize("operation", ["stop", "wait"])
def test_automatic_container_removal_race_is_safe(clients, operation):
    client, container, homefs, lock = clients
    getattr(container, operation).side_effect = docker.errors.NotFound("already removed")
    orchestration.manage_home_directory(client, 42, lock).file.close()
    lock.release.assert_called_once()


def test_failed_backup_transfer_prevents_home_deletion(clients):
    client, container, homefs, lock = clients
    homefs.get_archive.side_effect = requests.ConnectionError("connection lost")
    with pytest.raises(orchestration.HomeResetError):
        orchestration.manage_home_directory(client, 42, lock)
    assert [call.args[0][-1] for call in homefs.exec_run.call_args_list] == ["backup"]
    lock.release.assert_called_once()


def test_truncated_backup_transfer_prevents_home_deletion(clients):
    client, container, homefs, lock = clients
    homefs.get_archive.return_value = (iter([b"truncated"]), {})
    with pytest.raises(orchestration.HomeResetError):
        orchestration.manage_home_directory(client, 42, lock)
    assert [call.args[0][-1] for call in homefs.exec_run.call_args_list] == ["backup"]
    lock.release.assert_called_once()


def test_unavailable_storage_does_not_stop_workspace(clients):
    client, container, homefs, lock = clients
    client.containers.get.side_effect = docker.errors.NotFound("homefs")
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.manage_home_directory(client, 42, lock)
    assert failure.value.status == 503
    container.stop.assert_not_called()
    lock.release.assert_called_once()


@pytest.mark.parametrize("uncertain", [False, True])
def test_reset_failure_still_returns_backup_without_admin_intervention(clients, uncertain):
    client, container, homefs, lock = clients
    result = homefs.exec_run.return_value
    def run(command, **kwargs):
        if command[-1] == "reset":
            if uncertain:
                raise requests.ConnectionError("connection lost")
            return 1, (None, b'{"phase":"reset","error":"Input/output error"}')
        return result
    homefs.exec_run.side_effect = run
    archive = orchestration.manage_home_directory(client, 42, lock)
    assert archive.status == ("unknown" if uncertain else "failed")
    assert "administrator" not in archive.message
    assert backup_contents(archive.file) == {"home/hacker/saved-file": b"saved data"}
    archive.file.close()
    assert lock.release.called is not uncertain
    assert client.api.timeout == 60


def test_lost_backup_connection_retains_operation_lock(clients):
    client, container, homefs, lock = clients
    homefs.exec_run.side_effect = requests.ConnectionError("connection lost")
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.manage_home_directory(client, 42, lock)
    assert failure.value.uncertain
    lock.release.assert_not_called()


def test_http_response_is_gzip_attachment_and_closes_temporary_file(clients):
    client, container, homefs, lock = clients
    archive = orchestration.manage_home_directory(client, 42, lock)
    app = Flask(__name__)
    app.add_url_rule("/download", view_func=lambda: orchestration.home_download_response(archive))
    with app.test_client() as browser:
        response = browser.get("/download")
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/gzip"
        assert "attachment" in response.headers["Content-Disposition"]
        assert "home-backup.tar.gz" in response.headers["Content-Disposition"]
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Home-Operation-Status"] == "success"
        assert backup_contents(io.BytesIO(response.data)) == {"home/hacker/saved-file": b"saved data"}
        response.close()
    assert archive.file.closed


@pytest.mark.parametrize("status, code", [("failed", 500), ("unknown", 503)])
def test_failed_reset_response_still_delivers_backup(clients, status, code):
    client, container, homefs, lock = clients
    archive = orchestration.manage_home_directory(client, 42, lock)
    archive.status = status
    app = Flask(__name__)
    app.add_url_rule("/download", view_func=lambda: orchestration.home_download_response(archive))
    with app.test_client() as browser:
        response = browser.get("/download")
        assert response.status_code == code
        assert response.headers["X-Home-Operation-Status"] == status
        assert backup_contents(io.BytesIO(response.data)) == {"home/hacker/saved-file": b"saved data"}
        response.close()
    assert archive.file.closed


def test_rate_limit_is_per_user_and_returns_retry_after():
    cache = Mock()
    cache.eval.return_value = 0
    orchestration.check_home_rate_limit(cache, 42)
    assert cache.eval.call_args.args[2] == "user.42.home.requests"
    cache.eval.return_value = 3599
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.check_home_rate_limit(cache, 42)
    assert failure.value.status == 429 and failure.value.retry_after == 3599


def test_download_retries_have_a_separate_bounded_rate_limit():
    cache = Mock()
    cache.eval.return_value = 0
    orchestration.check_home_rate_limit(cache, 42, downloads_only=True)
    assert cache.eval.call_args.args[2] == "user.42.home.downloads"


def test_rate_limit_service_failure_fails_closed():
    cache = Mock()
    cache.eval.side_effect = redis.exceptions.ConnectionError("redis unavailable")
    with pytest.raises(orchestration.HomeResetError) as failure:
        orchestration.check_home_rate_limit(cache, 42)
    assert failure.value.status == 503


@pytest.mark.parametrize("user_id", ["../42", "/42", "0", "-1", "１２"])
def test_storage_command_rejects_invalid_user_id(user_id, monkeypatch, capsys):
    monkeypatch.setattr(storage.sys, "argv", ["reset_home.py", user_id, "backup"])
    assert storage.main() == 1
    assert json.loads(capsys.readouterr().err)["error"] == "Invalid user ID"


def test_home_management_browser_download_and_error_flows():
    node = shutil.which("node") or os.environ.get("HOME_MANAGEMENT_TEST_NODE")
    if not node:
        pytest.skip("Node.js is unavailable")
    subprocess.run([node, str(ROOT / "test/test_home_management_client.js")], check=True)
