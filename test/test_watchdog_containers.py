from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import Mock, call

import docker
import pytest
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


@pytest.mark.parametrize("error,success", [
    (ReadTimeout("stuck"), False),
    (ConnectionError("disconnected"), False),
    (docker.errors.NotFound("gone"), True),
    (docker.errors.APIError("refused"), False),
])
def test_removal_failure_does_not_block_other_candidates(client, error, success):
    client.api.containers.return_value = [container("stuck", hours=8), container("next", hours=7)]
    client.api.remove_container.side_effect = [error, None]
    assert reaper.collect_containers(client) == success
    assert client.api.remove_container.call_args_list == [
        call(cid, force=True, v=False) for cid in ["stuck", "next"]
    ]


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
    sweep.assert_called_once_with("unix:///var/run/docker.sock")


@pytest.mark.parametrize("failed_node", [None, "tcp://192.168.42.3:2375"])
def test_cleanup_sweeps_nodes_concurrently_and_reports_partial_failure(tmp_path, monkeypatch, failed_node):
    monkeypatch.setattr(reaper, "LOCK_PATH", str(tmp_path / "remove.lock"))
    monkeypatch.setattr(reaper.Path, "read_text", lambda _: '{"1": {}, "2": {}}')
    started = Barrier(2, timeout=5)

    def sweep(url):
        started.wait()
        return url != failed_node

    collect = Mock(side_effect=sweep)
    monkeypatch.setattr(reaper, "collect_node", collect)

    assert reaper.main() == (1 if failed_node else 0)
    assert {args.args[0] for args in collect.call_args_list} == {
        "tcp://192.168.42.2:2375", "tcp://192.168.42.3:2375",
    }
