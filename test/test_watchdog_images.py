from unittest.mock import MagicMock, Mock, call

import docker
import pytest
from requests import Response

from watchdog import docker_prune_images as prune


ID = "sha256:" + "a" * 64
OTHER_ID = "sha256:" + "b" * 64
DIGEST = "sha256:" + "c" * 64


@pytest.mark.parametrize("reference,expected", [
    ("example/course", "docker.io/example/course:latest"),
    ("example/course:latest", "docker.io/example/course:latest"),
    ("index.docker.io/example/course", "docker.io/example/course:latest"),
    ("registry-1.docker.io/example/course", "registry-1.docker.io/example/course:latest"),
    ("ubuntu", "docker.io/library/ubuntu:latest"),
    ("docker.io/ubuntu", "docker.io/library/ubuntu:latest"),
    ("registry.example:5000/course:V2", "registry.example:5000/course:V2"),
    ("example/course:old@" + DIGEST, "docker.io/example/course@" + DIGEST),
    (ID, ID), (ID[7:19], ID[:19]),
])
def test_normalization(reference, expected):
    assert prune.normalize_reference(reference) == expected


def image(tags=None, *, image_id=ID, digests=None, labels=None):
    return {"Id": image_id, "RepoTags": tags or [], "RepoDigests": digests or [], "Labels": labels or {}}


def client_for(item):
    client = Mock()
    client.api.images.return_value = [item]
    client.api.containers.return_value = []
    client.api.inspect_image.return_value = item
    return client


@pytest.mark.parametrize("item,refs,used_ids", [
    (image(["example/course:latest", "example/old:v1"]), {"example/course"}, set()),
    (image(digests=["example/course@" + DIGEST]), {"example/course@" + DIGEST}, set()),
    (image(), {ID[:19]}, set()),
    (image(), set(), {ID}),
    (image(labels={"com.docker.compose.project": "dojo"}), set(), set()),
    (image(labels={"pwn.college.gc.keep": ""}), set(), set()),
])
def test_protection(item, refs, used_ids):
    assert prune.protected(item, {prune.normalize_reference(ref) for ref in refs}, used_ids)


@pytest.mark.parametrize("reference", ["pwncollege/dojo:latest", "ubuntu:24.04", "alpine:3.22", "busybox@" + DIGEST])
def test_base_images_follow_normal_reference_protection(reference):
    item = image([reference])
    assert not prune.protected(item, set(), set())
    assert prune.protected(item, {prune.normalize_reference(reference)}, set())
    assert prune.protected(item, set(), {ID})


def test_db_references_and_default_image():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(None,), ("",), ("example/course",), ("mac:desktop",)]
    assert prune.challenge_references(connection) == {prune.normalize_reference(prune.LEGACY_IMAGE), prune.normalize_reference("example/course")}
    cursor.execute.assert_called_once_with("SELECT DISTINCT data->'image' FROM dojo_challenges")


@pytest.mark.parametrize("rows", [[], [(False,)], [("invalid reference",)]])
def test_invalid_db_inventory_aborts(rows):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = rows
    with pytest.raises(ValueError):
        prune.challenge_references(connection)


@pytest.mark.parametrize("tags", [[], ["example/old:v1"], ["example/old:v1", "example/old:v2"]])
def test_dry_run_and_nonforce_removal(tags):
    client = client_for(image(tags))
    prune.collect_images(client, lambda: set())
    client.api.remove_image.assert_not_called()
    prune.collect_images(client, lambda: set(), apply=True)
    assert client.api.remove_image.call_args_list == [call(target, force=False, noprune=True) for target in tags or [ID]]


def test_stopped_container_preserves_image_and_configured_tag():
    client = client_for(image(["example/old:v1"]))
    client.api.images.return_value.append(image(["example/current:latest"], image_id=OTHER_ID))
    client.api.containers.return_value = [{"ImageID": ID, "Image": "example/current", "State": "exited"}]
    prune.collect_images(client, lambda: set(), apply=True)
    client.api.containers.assert_called_with(all=True)
    client.api.remove_image.assert_not_called()


def test_reference_added_between_alias_removals():
    client = client_for(image(["example/old:v1", "example/old:v2"]))
    refs = Mock(side_effect=[set(), set(), {prune.normalize_reference("example/old:v2")}])
    prune.collect_images(client, refs, apply=True)
    client.api.remove_image.assert_called_once_with("example/old:v1", force=False, noprune=True)


def test_moved_tag_is_skipped():
    client = client_for(image(["example/old:v1"]))
    client.api.inspect_image.return_value = image(["example/old:v1"], image_id=OTHER_ID)
    prune.collect_images(client, lambda: set(), apply=True)
    client.api.remove_image.assert_not_called()


def test_new_container_is_protected():
    client = client_for(image(["example/old:v1"]))
    client.api.containers.side_effect = [[], [{"ImageID": ID, "Image": "example/old:v1"}]]
    prune.collect_images(client, lambda: set(), apply=True)
    client.api.remove_image.assert_not_called()


def test_failed_db_refresh_prevents_deletion():
    client = client_for(image(["example/old:v1"]))
    with pytest.raises(RuntimeError):
        prune.collect_images(client, Mock(side_effect=[set(), RuntimeError("DB unavailable")]), apply=True)
    client.api.remove_image.assert_not_called()


@pytest.mark.parametrize("status", [404, 409, 500])
def test_docker_errors_are_not_retried_or_forced(status):
    client = client_for(image(["example/old:v1"]))
    response = Response()
    response.status_code = status
    client.api.remove_image.side_effect = docker.errors.APIError("failed", response=response)
    if status == 500:
        with pytest.raises(docker.errors.APIError):
            prune.collect_images(client, lambda: set(), apply=True)
    else:
        prune.collect_images(client, lambda: set(), apply=True)
    assert client.api.remove_image.call_count == 1


def test_overlapping_run_does_not_connect(tmp_path, monkeypatch):
    path = tmp_path / "prune.lock"
    monkeypatch.setattr(prune, "LOCK_PATH", str(path))
    monkeypatch.setattr(prune.argparse.ArgumentParser, "parse_args", lambda _: Mock())
    connect = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(prune.psycopg2, "connect", connect)
    with path.open("a") as lock:
        prune.fcntl.flock(lock, prune.fcntl.LOCK_EX | prune.fcntl.LOCK_NB)
        assert prune.main() == 0
    connect.assert_not_called()


@pytest.mark.parametrize("nodes,urls", [
    ('{}', ["unix:///var/run/docker.sock"]),
    ('{"1": {}, "2": {}}', ["tcp://192.168.42.2:2375", "tcp://192.168.42.3:2375"]),
])
def test_main_uses_direct_read_only_db_connection(tmp_path, monkeypatch, nodes, urls):
    monkeypatch.setattr(prune, "LOCK_PATH", str(tmp_path / "prune.lock"))
    monkeypatch.setattr(prune.argparse.ArgumentParser, "parse_args", lambda _: Mock(apply=False))
    monkeypatch.setattr(prune.Path, "read_text", lambda _: nodes)
    connection = Mock()
    connect = Mock(return_value=connection)
    factory = Mock(return_value=Mock())
    collect = Mock()
    monkeypatch.setattr(prune.psycopg2, "connect", connect)
    monkeypatch.setattr(prune.docker, "DockerClient", factory)
    monkeypatch.setattr(prune, "collect_images", collect)
    assert prune.main() == 0
    connect.assert_called_once_with(connect_timeout=10, options="-c default_transaction_read_only=on -c statement_timeout=10000")
    assert connection.autocommit is True
    connection.close.assert_called_once()
    assert factory.call_args_list == [call(base_url=url, timeout=60) for url in urls]
    assert collect.call_count == len(urls)
    assert factory.return_value.close.call_count == len(urls)
