import errno
import fcntl
import importlib.util
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from flask import Flask
from werkzeug.routing import BaseConverter

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
        output.write(b"".join(storage.backup_home(volume)))
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
    output.write(b"".join(storage.backup_home(volume)))
    output.seek(0)
    with tarfile.open(fileobj=output, mode="r:gz") as archive:
        assert archive.getmember("home/hacker/boundary").size == 10_000_000
        assert "home/hacker/large" not in archive.getnames()
        assert "home/hacker/large-link" not in archive.getnames()
    assert (home / "large").stat().st_size == 10_000_001


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
        b"".join(storage.backup_home(volume))
    assert (volume / "active" / "saved-file").read_text() == "saved data"
    assert set(entry.name for entry in volume.iterdir()) == {"active", ".active.lock"}


@pytest.mark.parametrize("action", ["backup", "reset"])
def test_busy_home_prevents_operations(volume, action):
    with (volume / ".active.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            b"".join(storage.backup_home(volume)) if action == "backup" else storage.reset_home(volume)
    assert (volume / "active" / "saved-file").exists()


@pytest.fixture
def home_api(volume, monkeypatch):
    for name in ("utils", "btrfs_volume", "models"):
        monkeypatch.setitem(sys.modules, name, load_module(f"homefs_{name}", f"homefs/{name}.py"))
    monkeypatch.setitem(sys.modules, "reset_home", storage)
    volume_server = load_module("homefs_volume_server", "homefs/volume_server.py")
    monkeypatch.setattr(volume_server, "STORAGE_ROOT", volume.parent)
    monkeypatch.setattr(volume_server, "backup_home", storage.backup_home)
    monkeypatch.setattr(volume_server, "reset_home", storage.reset_home)
    app = Flask(__name__)
    app.url_map.converters["volume"] = BaseConverter
    app.register_blueprint(volume_server.volume_server, url_prefix="/volume")
    return app.test_client()


def test_homefs_api_streams_backup_and_resets_home(home_api, volume):
    response = home_api.post("/volume/42/backup")
    assert response.status_code == 200
    assert response.mimetype == "application/gzip" and "Content-Length" not in response.headers
    assert backup_contents(io.BytesIO(response.data)) == {"home/hacker/saved-file": b"saved data"}
    response.close()
    assert (volume / "active" / "saved-file").exists()
    response = home_api.post("/volume/42/reset")
    assert response.status_code == 200 and response.json["success"]
    assert not list((volume / "active").iterdir())


@pytest.mark.parametrize("user_id", ["0", "-1", "../42", "42x"])
def test_homefs_api_rejects_invalid_user_id(home_api, user_id):
    assert home_api.post(f"/volume/{user_id}/reset").status_code == 404


@pytest.mark.parametrize("action", ["backup", "reset"])
def test_homefs_api_reports_busy_or_missing_home(home_api, volume, action):
    assert home_api.post(f"/volume/43/{action}").status_code == 404
    with (volume / ".active.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        response = home_api.post(f"/volume/42/{action}")
        assert response.status_code == 409 and response.json["success"] is False
    assert (volume / "active" / "saved-file").exists()


def test_backup_stream_closure_releases_home_lock(volume):
    stream = storage.backup_home(volume)
    assert next(stream)
    with (volume / ".active.lock").open("a+b") as lock:
        with pytest.raises(BlockingIOError):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stream.close()
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.fixture
def clients(monkeypatch):
    payload = b"archive-data"
    response = MagicMock(status_code=200)
    response.__enter__.return_value = response
    response.iter_content.side_effect = lambda **kwargs: iter([payload[:4], payload[4:]])
    response.json.return_value = {"success": True}
    post = Mock(return_value=response)
    monkeypatch.setattr(orchestration.requests, "post", post)
    container, lock = Mock(status="running"), Mock()
    client = Mock()
    client.containers.get.return_value = container
    lock.acquire.return_value = True
    return client, container, response, lock, payload, post


def without_workspace(client):
    client.containers.get.side_effect = docker.errors.NotFound("No workspace")


def test_backup_streams_and_reset_takes_a_separate_lock(clients):
    client, container, response, lock, payload, post = clients
    stream = orchestration.backup_home_directory(client, 42, lock, homefs_url="http://homefs:4201")
    assert next(stream) == payload[:4]
    container.stop.assert_called_once_with(timeout=10)
    container.wait.assert_called_once_with(condition="removed", timeout=30)
    lock.release.assert_not_called()
    assert payload[:4] + b"".join(stream) == payload
    lock.release.assert_called_once()
    without_workspace(client)
    assert orchestration.reset_home_directory(client, 42, lock, homefs_url="http://node:4201") is None
    assert lock.acquire.call_count == lock.release.call_count == 2
    assert [call.args[0] for call in post.call_args_list] == ["http://homefs:4201/volume/42/backup", "http://node:4201/volume/42/reset"]
    response.__exit__.assert_called()
    container.pause.assert_not_called()


@pytest.mark.parametrize("failure, status", [("lock", 409), ("redis", 503), ("workspace", 503), ("stop", 503), ("wait", 503)])
def test_preparation_failure_does_not_archive_or_reset(clients, failure, status):
    client, container, _, lock, _, post = clients
    if failure == "lock":
        lock.acquire.return_value = False
    elif failure == "redis":
        lock.acquire.side_effect = redis.exceptions.ConnectionError("redis unavailable")
    elif failure == "workspace":
        client.containers.get.side_effect = requests.ConnectionError("unavailable")
    else:
        getattr(container, failure).side_effect = requests.ConnectionError("connection lost")
    with pytest.raises(orchestration.HomeResetError) as error:
        list(orchestration.backup_home_directory(client, 42, lock, homefs_url="http://homefs:4201"))
    assert error.value.status == status
    post.assert_not_called()
    assert lock.release.called is (failure not in ("lock", "redis"))


@pytest.mark.parametrize("operation", ["stop", "wait", "missing"])
def test_backup_handles_auto_removal_and_already_stopped_workspaces(clients, operation):
    client, container, _, lock, payload, _ = clients
    if operation == "missing":
        without_workspace(client)
    else:
        getattr(container, operation).side_effect = docker.errors.NotFound("already removed")
    assert b"".join(orchestration.backup_home_directory(client, 42, lock, homefs_url="http://homefs:4201")) == payload
    lock.release.assert_called_once()


@pytest.mark.parametrize("state", ["running", "paused", "exited"])
def test_reset_refuses_an_existing_workspace_instead_of_stopping_and_deleting_it(clients, state):
    client, container, _, lock, _, post = clients
    container.status = state
    with pytest.raises(orchestration.HomeResetError) as error:
        orchestration.reset_home_directory(client, 42, lock, homefs_url="http://homefs:4201")
    assert error.value.status == 409 and "Download a new backup" in str(error.value)
    post.assert_not_called()
    container.stop.assert_not_called()
    lock.release.assert_called_once()


@pytest.mark.parametrize("failure", ["transport", "truncated", "invalid_reset"])
def test_unconfirmed_home_operation_lets_lock_expire(clients, failure):
    client, _, response, lock, _, _ = clients
    without_workspace(client)
    if failure == "invalid_reset":
        response.json.return_value = {"success": False}
    else:
        def chunks(**kwargs):
            yield b"first-chunk"
            error = requests.ConnectionError if failure == "transport" else requests.exceptions.ChunkedEncodingError
            raise error("Incomplete HTTP stream")
        response.iter_content.side_effect = chunks
    with pytest.raises(orchestration.HomeResetError) as error:
        if failure == "invalid_reset":
            orchestration.reset_home_directory(client, 42, lock, homefs_url="http://homefs:4201")
        else:
            list(orchestration.backup_home_directory(client, 42, lock, homefs_url="http://homefs:4201"))
    assert error.value.status == 503 and error.value.uncertain
    lock.release.assert_not_called()
    response.__exit__.assert_called_once()


def test_client_disconnect_closes_http_response_and_lets_lock_expire(clients):
    client, _, response, lock, _, _ = clients
    stream = orchestration.backup_home_directory(client, 42, lock, homefs_url="http://homefs:4201")
    next(stream)
    stream.close()
    response.__exit__.assert_called_once()
    lock.release.assert_not_called()


@pytest.mark.parametrize("operation, status", [(orchestration.backup_home_directory, 413), (orchestration.reset_home_directory, 500), (orchestration.backup_home_directory, 404)])
def test_known_homefs_failure_releases_lock(clients, operation, status):
    client, _, response, lock, _, _ = clients
    without_workspace(client)
    response.status_code = status
    response.json.return_value = {"success": False, "error": "Home operation failed"}
    with pytest.raises(orchestration.HomeResetError) as error:
        result = operation(client, 42, lock, homefs_url="http://homefs:4201")
        if result is not None:
            list(result)
    assert error.value.status == status
    lock.release.assert_called_once()


@pytest.mark.parametrize("outcome", [1, 5, 6, "unavailable"])
def test_per_user_rate_limit_reports_retry_after_or_service_failure(outcome):
    cache = MagicMock()
    counter = cache.pipeline.return_value.__enter__.return_value
    if outcome == "unavailable":
        counter.execute.side_effect = redis.exceptions.ConnectionError("redis unavailable")
    else:
        counter.execute.return_value = [outcome, True, 3599]
    if outcome == "unavailable" or outcome > 5:
        with pytest.raises(orchestration.HomeResetError) as error:
            orchestration.check_home_rate_limit(cache, 42)
        assert error.value.status == (503 if outcome == "unavailable" else 429)
        assert error.value.retry_after == (None if outcome == "unavailable" else 3599)
    else:
        orchestration.check_home_rate_limit(cache, 42)
    counter.incr.assert_called_once_with("user.42.home.requests")


def test_home_management_browser_download_and_error_flows():
    node = shutil.which("node") or os.environ.get("HOME_MANAGEMENT_TEST_NODE")
    if not node:
        pytest.skip("Node.js is unavailable")
    subprocess.run([node, str(ROOT / "test/test_home_management_client.js")], check=True)
