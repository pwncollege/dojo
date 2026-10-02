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
orchestration = load_module("home_reset_orchestration", "site/dojo/utils/home_reset.py")


@pytest.fixture
def volume(tmp_path):
    path = tmp_path / "42"
    (path / "active").mkdir(parents=True)
    (path / "active" / "saved-file").write_text("saved data")
    return path


def backup_contents(file):
    file.seek(0)
    with tarfile.open(fileobj=file, mode="r:gz") as archive:
        return {member.name: archive.extractfile(member).read() for member in archive if member.isfile()}


@pytest.mark.skipif(os.geteuid() != 0, reason="homefs runs as root")
def test_backup_reads_private_and_hidden_files_without_following_links_or_saving_an_archive(volume, tmp_path, monkeypatch):
    home = volume / "active"
    private = home / ".emacs.d"
    private.mkdir(mode=0o700)
    (private / "settings").write_text("private data")
    outside = tmp_path / "outside"
    outside.write_text("keep outside")
    (home / "link").symlink_to(outside)
    monkeypatch.chdir(home)
    os.chown(home, 1000, 1000)
    os.chmod(home, 0)
    output = io.BytesIO()
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind("service.sock")
        detail = storage.backup_home(volume, output)
    assert detail["size"] == len(output.getvalue())
    assert backup_contents(output) == {"home/hacker/.emacs.d/settings": b"private data", "home/hacker/saved-file": b"saved data"}
    output.seek(0)
    with tarfile.open(fileobj=output, mode="r:gz") as archive:
        assert archive.getmember("home/hacker/.emacs.d").uid == 0
        assert archive.getmember("home/hacker/link").issym()
    assert outside.read_text() == "keep outside"
    assert set(entry.name for entry in volume.iterdir()) == {"active", ".active.lock"}
    assert not list(home.glob("*.tar.gz"))


def test_backup_includes_10_mb_boundary_but_excludes_larger_files_and_hardlinks(volume):
    home = volume / "active"
    for name, size in (("boundary", 10_000_000), ("large", 10_000_001)):
        with (home / name).open("wb") as stream:
            stream.truncate(size)
    os.link(home / "large", home / "large-link")
    output = io.BytesIO()
    detail = storage.backup_home(volume, output)
    output.seek(0)
    with tarfile.open(fileobj=output, mode="r:gz") as archive:
        assert archive.getmember("home/hacker/boundary").size == 10_000_000
        assert "home/hacker/large" not in archive.getnames()
        assert "home/hacker/large-link" not in archive.getnames()
    assert detail["skipped"] == 2 and (home / "large").stat().st_size == 10_000_001


@pytest.mark.skipif(os.geteuid() != 0, reason="homefs runs as root")
def test_reset_removes_nested_files_and_links_and_leaves_an_empty_writable_home(volume, tmp_path):
    home = volume / "active"
    (home / ".config" / "nested").mkdir(parents=True)
    (home / ".config" / "nested" / "settings").write_text("settings")
    outside = tmp_path / "outside"
    outside.write_text("keep outside")
    (home / "link").symlink_to(outside)
    storage.reset_home(volume)
    assert not list(home.iterdir()) and outside.read_text() == "keep outside"
    assert home.stat().st_uid == home.stat().st_gid == 1000
    assert home.stat().st_mode & 0o777 == 0o755
    assert set(entry.name for entry in volume.iterdir()) == {"active", ".active.lock"}


@pytest.mark.parametrize("failure", ["write", "compressible_limit", "incompressible_limit"])
def test_failed_backup_preserves_home_and_does_not_retain_files(volume, monkeypatch, failure):
    if failure == "write":
        monkeypatch.setattr(tarfile.TarFile, "add", Mock(side_effect=OSError(errno.ENOSPC, "No space left")))
    else:
        monkeypatch.setattr(storage, "MAX_ARCHIVE_SIZE", 16 * 1024)
        data = b"x" * 64 * 1024 if failure == "compressible_limit" else os.urandom(64 * 1024)
        (volume / "active" / "large-data").write_bytes(data)
    with pytest.raises(OSError):
        storage.backup_home(volume, io.BytesIO())
    assert (volume / "active" / "saved-file").read_text() == "saved data"
    assert set(entry.name for entry in volume.iterdir()) == {"active", ".active.lock"}


@pytest.mark.parametrize("action", ["backup", "reset"])
def test_busy_home_prevents_operations(volume, action):
    with (volume / ".active.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            storage.backup_home(volume, io.BytesIO()) if action == "backup" else storage.reset_home(volume)
    assert (volume / "active" / "saved-file").exists()


@pytest.mark.parametrize("user_id", ["../42", "/42", "0", "-1", "１２"])
def test_storage_command_rejects_invalid_user_id(user_id, monkeypatch, capsys):
    monkeypatch.setattr(storage.sys, "argv", ["reset_home.py", user_id, "backup"])
    assert storage.main() == 1
    assert json.loads(capsys.readouterr().err)["error"] == "Invalid user ID"


def test_storage_command_streams_gzip_on_stdout_and_metadata_on_stderr(volume, monkeypatch, capsys):
    output = io.BytesIO()
    with monkeypatch.context() as patch:
        patch.setenv("STORAGE_ROOT", str(volume.parent))
        patch.setattr(storage.sys, "argv", ["reset_home.py", "42", "backup"])
        patch.setattr(storage.sys, "stdout", SimpleNamespace(buffer=output))
        assert storage.main() == 0
    detail = json.loads(capsys.readouterr().err)
    assert detail == {"event": "complete", "size": len(output.getvalue()), "skipped": 0}
    assert backup_contents(output) == {"home/hacker/saved-file": b"saved data"}


def command_result(payload=b"", **detail):
    chunks = [(payload[i:i+19], None) for i in range(0, len(payload), 19)]
    chunks.append((None, json.dumps({"event": "complete", **detail}).encode()))
    return None, (chunk for chunk in chunks)


@pytest.fixture
def clients():
    file = io.BytesIO()
    with tarfile.open(fileobj=file, mode="w:gz") as archive:
        member = tarfile.TarInfo("home/hacker/saved-file")
        member.size = len(b"saved data")
        archive.addfile(member, io.BytesIO(b"saved data"))
    payload = file.getvalue()
    container, homefs, lock = Mock(status="running"), Mock(), Mock()
    def run(command, **kwargs):
        return command_result(payload, size=len(payload), skipped=1) if command[-1] == "backup" else command_result()
    homefs.exec_run.side_effect = run
    client = Mock(api=SimpleNamespace(timeout=60))
    client.containers.get.side_effect = lambda name: {"user_42": container, "homefs": homefs}[name]
    lock.acquire.return_value = True
    return client, container, homefs, lock, payload


@pytest.mark.parametrize("action", ["backup", "reset"])
def test_operations_stop_under_lock_and_verify_the_download_before_reset(clients, monkeypatch, action):
    client, container, homefs, lock, payload = clients
    respond = homefs.exec_run.side_effect
    verify = Mock(wraps=orchestration.verify_home_archive)
    monkeypatch.setattr(orchestration, "verify_home_archive", verify)
    def run(command, **kwargs):
        container.stop.assert_called_once_with(timeout=10)
        container.wait.assert_called_once_with(condition="removed", timeout=30)
        lock.release.assert_not_called()
        assert kwargs == {"user": "0", "stream": True, "demux": True}
        if command[-1] == "reset":
            verify.assert_called_once()
        return respond(command)
    homefs.exec_run.side_effect = run
    result = orchestration.manage_home_directory(client, 42, lock, action=action)
    assert result.status == "success" and result.size == len(payload) and result.skipped == 1
    assert backup_contents(result.file) == {"home/hacker/saved-file": b"saved data"}
    assert [call.args[0][-1] for call in homefs.exec_run.call_args_list] == (["backup", "reset"] if action == "reset" else ["backup"])
    result.file.close()
    container.start.assert_not_called()
    container.pause.assert_not_called()
    lock.release.assert_called_once()
    assert client.api.timeout == 60


@pytest.mark.parametrize("failure, status", [("lock", 409), ("storage", 503), ("workspace", 409), ("stop", 503), ("wait", 503), ("inactive", 409)])
def test_preparation_failure_does_not_archive_or_reset(clients, failure, status):
    client, container, homefs, lock, _ = clients
    if failure == "lock":
        lock.acquire.return_value = False
    elif failure == "storage":
        client.containers.get.side_effect = docker.errors.NotFound("homefs")
    elif failure == "workspace":
        client.containers.get.side_effect = [homefs, docker.errors.NotFound("workspace")]
    elif failure == "inactive":
        container.status = "paused"
    else:
        getattr(container, failure).side_effect = requests.ConnectionError("connection lost")
    with pytest.raises(orchestration.HomeResetError) as error:
        orchestration.manage_home_directory(client, 42, lock)
    assert error.value.status == status
    homefs.exec_run.assert_not_called()
    assert lock.release.called is (failure != "lock")


@pytest.mark.parametrize("operation", ["stop", "wait"])
def test_auto_removal_race_is_safe(clients, operation):
    client, container, homefs, lock, _ = clients
    getattr(container, operation).side_effect = docker.errors.NotFound("already removed")
    orchestration.manage_home_directory(client, 42, lock).file.close()
    lock.release.assert_called_once()


@pytest.mark.parametrize("failure", ["transport", "marker", "truncated", "corrupt", "overflow"])
def test_incomplete_or_unverified_backup_prevents_reset_and_closes_temporary_file(clients, monkeypatch, failure):
    client, container, homefs, lock, payload = clients
    file = io.BytesIO()
    monkeypatch.setattr(orchestration.tempfile, "SpooledTemporaryFile", lambda **kwargs: file)
    if failure == "transport":
        homefs.exec_run.side_effect = requests.ConnectionError("connection lost")
    else:
        data = payload[:-5] if failure == "truncated" else b"bad" + payload[3:] if failure == "corrupt" else payload
        event = "invalid" if failure == "marker" else "complete"
        homefs.exec_run.side_effect = lambda *args, **kwargs: command_result(data, size=len(payload), event=event)
        if failure == "overflow":
            monkeypatch.setattr(orchestration, "MAX_ARCHIVE_SIZE", 16)
    with pytest.raises(orchestration.HomeResetError):
        orchestration.manage_home_directory(client, 42, lock)
    assert [call.args[0][-1] for call in homefs.exec_run.call_args_list] == ["backup"]
    assert lock.release.called is (failure in ["truncated", "corrupt"])
    assert file.closed


@pytest.mark.parametrize("uncertain", [False, True])
def test_reset_failure_returns_the_verified_backup_without_admin_intervention(clients, uncertain):
    client, container, homefs, lock, _ = clients
    respond = homefs.exec_run.side_effect
    def run(command, **kwargs):
        if command[-1] == "reset":
            if uncertain:
                raise requests.ConnectionError("connection lost")
            return command_result(event="failed", status=500, error="Input/output error")
        return respond(command)
    homefs.exec_run.side_effect = run
    result = orchestration.manage_home_directory(client, 42, lock)
    assert result.status == ("unknown" if uncertain else "failed")
    assert "administrator" not in result.message
    assert backup_contents(result.file) == {"home/hacker/saved-file": b"saved data"}
    result.file.close()
    assert lock.release.called is not uncertain


@pytest.mark.parametrize("status, code", [("success", 200), ("failed", 500), ("unknown", 503)])
def test_download_response_is_a_gzip_attachment_and_closes_the_temporary_file(clients, status, code):
    client, _, _, lock, payload = clients
    result = orchestration.manage_home_directory(client, 42, lock)
    result.status = status
    app = Flask(__name__)
    app.add_url_rule("/download", view_func=lambda: orchestration.home_download_response(result))
    with app.test_client() as browser:
        response = browser.get("/download")
        assert response.status_code == code and response.data == payload
        assert response.headers["Content-Type"] == "application/gzip"
        assert 'attachment; filename=home-backup.tar.gz' == response.headers["Content-Disposition"]
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Home-Operation-Status"] == status
        response.close()
    assert result.file.closed


@pytest.mark.parametrize("outcome", [0, 3599, "unavailable"])
def test_per_user_rate_limit_reports_retry_after_or_service_failure(outcome):
    cache = Mock()
    if outcome == "unavailable":
        cache.eval.side_effect = redis.exceptions.ConnectionError("redis unavailable")
    else:
        cache.eval.return_value = outcome
    if outcome:
        with pytest.raises(orchestration.HomeResetError) as error:
            orchestration.check_home_rate_limit(cache, 42)
        assert error.value.status == (503 if outcome == "unavailable" else 429)
        assert error.value.retry_after == (None if outcome == "unavailable" else outcome)
    else:
        orchestration.check_home_rate_limit(cache, 42)
    assert cache.eval.call_args.args[2] == "user.42.home.requests"


def test_home_management_browser_download_and_error_flows():
    node = shutil.which("node") or os.environ.get("HOME_MANAGEMENT_TEST_NODE")
    if not node:
        pytest.skip("Node.js is unavailable")
    subprocess.run([node, str(ROOT / "test/test_home_management_client.js")], check=True)
