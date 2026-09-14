import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from unittest.mock import Mock, call

import docker
import pytest
from requests import Response
from requests.exceptions import ConnectionError, ReadTimeout

from watchdog import docker_remove_containers as reaper


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def container(container_id, *, hours=0, size=0):
    return {"Id": container_id, "Created": NOW.timestamp() - hours * 3600,
            "SizeRw": size, "Labels": {"dojo.user_id": container_id}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(reaper, "datetime", Mock(now=Mock(return_value=NOW)))
    client = Mock()
    client.api.base_url = "http://node:2375"
    client.api.containers.return_value = []
    return client


def test_age_size_limits_and_removal_once_without_inspect(client):
    client.api.containers.return_value = [
        container("young"),
        container("boundary", hours=6, size=16 * reaper.GiB),
        container("old", hours=7),
        container("large", size=17 * reaper.GiB),
        container("both", hours=8, size=20 * reaper.GiB),
    ]
    assert reaper.collect_containers(client)
    client.api.containers.assert_called_once_with(filters={"label": "dojo.user_id"}, size=True)
    assert client.api.remove_container.call_args_list == [
        call(cid, force=True, v=False) for cid in ["both", "large", "old"]
    ]
    client.containers.list.assert_not_called()
    client.api.inspect_container.assert_not_called()
    client.df.assert_not_called()


@pytest.mark.parametrize("error", [ReadTimeout("stuck"), ConnectionError("disconnected")])
def test_removal_network_failure_does_not_block_other_candidates(client, error, caplog):
    client.api.containers.return_value = [container("stuck", hours=8), container("next", hours=7)]
    client.api.remove_container.side_effect = [error, None]
    assert not reaper.collect_containers(client)
    assert client.api.remove_container.call_args_list == [
        call(cid, force=True, v=False) for cid in ["stuck", "next"]
    ]
    assert "removal not confirmed for stuck" in caplog.text
    assert "Docker may still be processing it" in caplog.text


@pytest.mark.parametrize("status", [404, 409, 500])
def test_removal_api_failure_does_not_block_other_candidates(client, status):
    response = Response()
    response.status_code = status
    error_type = docker.errors.NotFound if status == 404 else docker.errors.APIError
    client.api.containers.return_value = [container("gone", hours=8), container("next", hours=7)]
    client.api.remove_container.side_effect = [error_type("failed", response=response), None]
    assert reaper.collect_containers(client) == (status == 404)
    assert client.api.remove_container.call_count == 2


def test_empty_inventory_removes_nothing(client):
    assert reaper.collect_containers(client)
    client.api.remove_container.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
def test_node_timeout_and_connection_cleanup(client, monkeypatch, failure):
    factory = Mock(return_value=client)
    monkeypatch.setattr(reaper.docker, "DockerClient", factory)
    if failure:
        client.api.containers.side_effect = ReadTimeout("inventory unavailable")
    assert reaper.collect_node("tcp://node:2375") == (not failure)
    factory.assert_called_once_with(base_url="tcp://node:2375", timeout=60)
    client.close.assert_called_once()
    client.api.remove_container.assert_not_called()


@pytest.mark.parametrize("nodes,urls", [
    ({}, ["unix:///var/run/docker.sock"]),
    ({"1": {}, "2": {}}, ["tcp://192.168.42.2:2375", "tcp://192.168.42.3:2375"]),
])
def test_main_sweeps_all_nodes_even_when_one_fails(tmp_path, monkeypatch, nodes, urls):
    monkeypatch.setattr(reaper, "LOCK_PATH", str(tmp_path / "remove.lock"))
    monkeypatch.setattr(reaper.Path, "read_text", lambda _: json.dumps(nodes))
    sweep = Mock(side_effect=lambda url: url != urls[0])
    monkeypatch.setattr(reaper, "collect_node", sweep)
    assert reaper.main() == 1
    assert sorted(sweep.call_args_list) == sorted(call(url) for url in urls)


def test_overlapping_run_skips_and_releases_lock(tmp_path, monkeypatch):
    path = tmp_path / "remove.lock"
    monkeypatch.setattr(reaper, "LOCK_PATH", str(path))
    inventory = Mock(return_value="{}")
    monkeypatch.setattr(reaper.Path, "read_text", inventory)
    sweep = Mock(return_value=True)
    monkeypatch.setattr(reaper, "collect_node", sweep)
    with path.open("a") as lock:
        reaper.fcntl.flock(lock, reaper.fcntl.LOCK_EX | reaper.fcntl.LOCK_NB)
        assert reaper.main() == 0
    inventory.assert_not_called()
    sweep.assert_not_called()
    assert reaper.main() == 0
    assert reaper.main() == 0
    assert sweep.call_count == 2


def test_sdk_read_timeout_continues_to_next_container(client):
    requests = []
    release = Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(("GET", self.path))
            body = json.dumps([container("stuck", hours=8), container("next", hours=7)]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_DELETE(self):
            requests.append(("DELETE", self.path))
            if "/stuck?" in self.path:
                release.wait(5)
                self.close_connection = True
                return
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    sdk = docker.DockerClient(base_url=f"http://127.0.0.1:{server.server_port}", version="1.47", timeout=0.1)
    try:
        assert not reaper.collect_containers(sdk)
        assert [method for method, _ in requests] == ["GET", "DELETE", "DELETE"]
        assert "/containers/next?" in requests[-1][1]
        assert not release.is_set()
    finally:
        release.set()
        sdk.close()
        server.shutdown()
        server.server_close()
        thread.join()
