import errno
import fcntl
import importlib.util
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
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
        size = storage.backup_home(volume, output)
    assert size == len(output.getvalue())
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
    size = storage.backup_home(volume, output)
    output.seek(0)
    with tarfile.open(fileobj=output, mode="r:gz") as archive:
        assert archive.getmember("home/hacker/boundary").size == 10_000_000
        assert "home/hacker/large" not in archive.getnames()
        assert "home/hacker/large-link" not in archive.getnames()
    assert size == len(output.getvalue()) and (home / "large").stat().st_size == 10_000_001


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
    assert capsys.readouterr().err.strip() == "Invalid user ID"


def test_storage_command_streams_gzip_on_stdout_and_byte_count_on_stderr(volume, monkeypatch, capsys):
    output = io.BytesIO()
    with monkeypatch.context() as patch:
        patch.setenv("STORAGE_ROOT", str(volume.parent))
        patch.setattr(storage.sys, "argv", ["reset_home.py", "42", "backup"])
        patch.setattr(storage.sys, "stdout", SimpleNamespace(buffer=output))
        assert storage.main() == 0
    assert int(capsys.readouterr().err) == len(output.getvalue())
    assert backup_contents(output) == {"home/hacker/saved-file": b"saved data"}


def command_stream(payload=b"", stderr=b""):
    chunks = [(payload[i:i+19], None) for i in range(0, len(payload), 19)]
    chunks.append((None, stderr))
    return (chunk for chunk in chunks)


@pytest.fixture
def clients():
    file = io.BytesIO()
    with tarfile.open(fileobj=file, mode="w:gz") as archive:
        member = tarfile.TarInfo("home/hacker/saved-file")
        member.size = len(b"saved data")
        archive.addfile(member, io.BytesIO(b"saved data"))
    payload = file.getvalue()
    api = Mock()
    container, homefs, lock = Mock(status="running"), Mock(id="homefs", client=SimpleNamespace(api=api)), Mock()
    api.exec_create.side_effect = lambda homefs_id, command, **kwargs: {"Id": command[-1]}
    api.exec_start.side_effect = lambda action, **kwargs: command_stream(payload, str(len(payload)).encode()) if action == "backup" else command_stream()
    api.exec_inspect.return_value = {"ExitCode": 0}
    client = Mock(api=api)
    api.timeout = 60
    client.containers.get.side_effect = lambda name: {"user_42": container, "homefs": homefs}[name]
    lock.acquire.return_value = True
    return client, container, homefs, lock, payload


def without_workspace(client, homefs):
    def get(name):
        if name == "homefs":
            return homefs
        raise docker.errors.NotFound("No workspace")
    client.containers.get.side_effect = get


def test_backup_streams_before_completion_and_reset_takes_a_separate_lock(clients):
    client, container, homefs, lock, payload = clients
    stream = orchestration.manage_home_directory(client, 42, lock, action="backup")
    assert next(stream) == payload[:19]
    container.stop.assert_called_once_with(timeout=10)
    container.wait.assert_called_once_with(condition="removed", timeout=30)
    lock.release.assert_not_called()
    lock.release.assert_not_called()
    assert payload[:19] + b"".join(stream) == payload
    assert [call.args[1][-1] for call in client.api.exec_create.call_args_list] == ["backup"]
    lock.release.assert_called_once()
    stream.close()
    without_workspace(client, homefs)
    assert list(orchestration.manage_home_directory(client, 42, lock, action="reset")) == []
    assert lock.acquire.call_count == lock.release.call_count == 2
    assert [call.args[1][-1] for call in client.api.exec_create.call_args_list] == ["backup", "reset"]
    container.pause.assert_not_called()
    assert client.api.timeout == 60


@pytest.mark.parametrize("failure, status", [("lock", 409), ("redis", 503), ("storage", 503), ("workspace", 503), ("stop", 503), ("wait", 503)])
def test_preparation_failure_does_not_archive_or_reset(clients, failure, status):
    client, container, homefs, lock, _ = clients
    if failure == "lock":
        lock.acquire.return_value = False
    elif failure == "redis":
        lock.acquire.side_effect = redis.exceptions.ConnectionError("redis unavailable")
    elif failure == "storage":
        client.containers.get.side_effect = docker.errors.NotFound("homefs")
    elif failure == "workspace":
        client.containers.get.side_effect = [homefs, requests.ConnectionError("unavailable")]
    else:
        getattr(container, failure).side_effect = requests.ConnectionError("connection lost")
    with pytest.raises(orchestration.HomeResetError) as error:
        list(orchestration.manage_home_directory(client, 42, lock, action="backup"))
    assert error.value.status == status
    client.api.exec_create.assert_not_called()
    assert lock.release.called is (failure not in ("lock", "redis"))


@pytest.mark.parametrize("operation", ["stop", "wait", "missing"])
def test_backup_handles_auto_removal_and_already_stopped_workspaces(clients, operation):
    client, container, homefs, lock, payload = clients
    if operation == "missing":
        without_workspace(client, homefs)
    else:
        getattr(container, operation).side_effect = docker.errors.NotFound("already removed")
    stream = orchestration.manage_home_directory(client, 42, lock, action="backup")
    assert b"".join(stream) == payload
    stream.close()
    lock.release.assert_called_once()


@pytest.mark.parametrize("state", ["running", "paused", "exited"])
def test_reset_refuses_an_existing_workspace_instead_of_stopping_and_deleting_it(clients, state):
    client, container, homefs, lock, _ = clients
    container.status = state
    with pytest.raises(orchestration.HomeResetError) as error:
        list(orchestration.manage_home_directory(client, 42, lock, action="reset"))
    assert error.value.status == 409 and "Download a new backup" in str(error.value)
    client.api.exec_create.assert_not_called()
    container.stop.assert_not_called()
    lock.release.assert_called_once()


@pytest.mark.parametrize("failure", ["transport", "count", "truncated", "running"])
def test_failed_stream_aborts_without_deleting_home(clients, failure):
    client, _, _, lock, payload = clients
    def chunks():
        yield payload[:19], None
        if failure == "transport":
            raise requests.ConnectionError("connection lost")
        yield payload[19:-5] if failure == "truncated" else payload[19:], None
        yield None, b"invalid" if failure == "count" else str(len(payload)).encode()
    iterator = chunks()
    client.api.exec_start.side_effect = lambda *args, **kwargs: iterator
    if failure == "running":
        client.api.exec_inspect.return_value = {"ExitCode": None}
    stream = orchestration.manage_home_directory(client, 42, lock, action="backup")
    with pytest.raises(orchestration.HomeResetError):
        b"".join(stream)
    stream.close()
    assert iterator.gi_frame is None
    assert [call.args[1][-1] for call in client.api.exec_create.call_args_list] == ["backup"]
    lock.release.assert_not_called()
    assert client.api.timeout == 60


def test_client_disconnect_closes_docker_stream_and_lets_lock_expire(clients):
    client, _, _, lock, payload = clients
    iterator = command_stream(payload, str(len(payload)).encode())
    client.api.exec_start.side_effect = lambda *args, **kwargs: iterator
    stream = orchestration.manage_home_directory(client, 42, lock, action="backup")
    next(stream)
    stream.close()
    assert iterator.gi_frame is None
    assert client.api.timeout == 60
    lock.release.assert_not_called()


@pytest.mark.parametrize("action, code, status", [("backup", errno.EFBIG, 413), ("reset", 1, 500), ("backup", errno.ENOENT, 404)])
def test_known_helper_failure_releases_lock(clients, action, code, status):
    client, _, homefs, lock, _ = clients
    without_workspace(client, homefs)
    client.api.exec_start.side_effect = lambda *args, **kwargs: command_stream(stderr=b"failed")
    client.api.exec_inspect.return_value = {"ExitCode": code}
    with pytest.raises(orchestration.HomeResetError) as error:
        list(orchestration.manage_home_directory(client, 42, lock, action=action))
    assert error.value.status == status
    lock.release.assert_called_once()


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
